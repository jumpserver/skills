#!/usr/bin/env python3
"""Common helpers for JumpServer V4 ops scripts."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import importlib
import inspect
import json
import os
from pathlib import Path
import sys
import threading
from typing import Any, Callable, Iterator
import warnings

# Suppress the LibreSSL/OpenSSL runtime warning and HTTPS certificate warnings.
warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+",
    module=r"urllib3(\..*)?",
)
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from jms_client.const import DEFAULT_ORG as CANONICAL_DEFAULT_ORG_ID
except Exception:  # noqa: BLE001
    CANONICAL_DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000002"

RESERVED_INTERNAL_ORG_ID = "00000000-0000-0000-0000-000000000004"
RESERVED_AUTO_SELECT_ORG_SETS = frozenset(
    {
        frozenset({CANONICAL_DEFAULT_ORG_ID}),
        frozenset({CANONICAL_DEFAULT_ORG_ID, RESERVED_INTERNAL_ORG_ID}),
    }
)
ORG_SELECTION_NEXT_STEP = "python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm"

SKILL_DIR = Path(__file__).resolve().parent.parent
LOCAL_ENV_FILE = SKILL_DIR / ".env.local"
RUNTIME_ENV_KEYS = (
    "JMS_API_URL",
    "JMS_WEB_URL",
    "JMS_VERSION",
    "JMS_ACCESS_KEY_ID",
    "JMS_ACCESS_KEY_SECRET",
    "JMS_USERNAME",
    "JMS_PASSWORD",
    "JMS_ORG_ID",
    "JMS_TIMEOUT",
    "JMS_SDK_MODULE",
    "JMS_SDK_GET_CLIENT",
)
NONSECRET_ENV_KEYS = (
    "JMS_API_URL",
    "JMS_WEB_URL",
    "JMS_VERSION",
    "JMS_ORG_ID",
    "JMS_TIMEOUT",
    "JMS_SDK_MODULE",
    "JMS_SDK_GET_CLIENT",
)
ADDRESS_ENV_KEYS = ("JMS_API_URL", "JMS_WEB_URL")
ACCESS_KEY_ENV_KEYS = ("JMS_ACCESS_KEY_ID", "JMS_ACCESS_KEY_SECRET")
BASIC_AUTH_ENV_KEYS = ("JMS_USERNAME", "JMS_PASSWORD")
WRITABLE_ENV_KEYS = frozenset(RUNTIME_ENV_KEYS)
CLIENT_ERROR_KEYWORDS = (
    "401",
    "403",
    "auth",
    "authorization",
    "certificate",
    "connect",
    "connection",
    "forbidden",
    "refused",
    "ssl",
    "timeout",
    "token",
    "unauthorized",
)

_CLIENT_POOL: dict[tuple[Any, ...], Any] = {}
_CLIENT_POOL_LOCK = threading.Lock()
_ACTIVE_CLIENT: ContextVar[Any | None] = ContextVar("jumpserver_active_client", default=None)
_ACTION_METADATA: ContextVar[dict[str, Any]] = ContextVar("jumpserver_action_metadata", default={})


class StructuredActionError(RuntimeError):
    def __init__(self, message: str, *, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.payload = dict(payload or {})


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def set_action_metadata(values: dict[str, Any] | None) -> None:
    if not isinstance(values, dict) or not values:
        return
    current = dict(_ACTION_METADATA.get() or {})
    current.update(serialize(values))
    _ACTION_METADATA.set(current)


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


@lru_cache(maxsize=1)
def read_local_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not LOCAL_ENV_FILE.exists():
        return values

    for raw_line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _strip_wrapping_quotes(value.strip())
    return values


def load_local_env() -> None:
    if getattr(load_local_env, "_loaded", False):
        return

    for key, value in read_local_env().items():
        if key not in os.environ or os.environ.get(key, "") == "":
            os.environ[key] = value

    load_local_env._loaded = True


def reset_local_env_state() -> None:
    read_local_env.cache_clear()
    load_local_env._loaded = False


def invalidate_all_clients() -> None:
    with _CLIENT_POOL_LOCK:
        _CLIENT_POOL.clear()


def _value_is_set(value: Any) -> bool:
    return value is not None and str(value) != ""


def _effective_runtime_values() -> dict[str, str]:
    values = dict(read_local_env())
    for key in RUNTIME_ENV_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def _build_nonsecret_view(values: dict[str, str]) -> dict[str, str]:
    return {
        key: str(values[key])
        for key in NONSECRET_ENV_KEYS
        if key in values
    }


def _auth_status(values: dict[str, str]) -> tuple[str | None, bool]:
    has_access_key = any(_value_is_set(values.get(key)) for key in ACCESS_KEY_ENV_KEYS)
    access_key_complete = all(_value_is_set(values.get(key)) for key in ACCESS_KEY_ENV_KEYS)
    has_basic_auth = any(_value_is_set(values.get(key)) for key in BASIC_AUTH_ENV_KEYS)
    basic_auth_complete = all(_value_is_set(values.get(key)) for key in BASIC_AUTH_ENV_KEYS)

    if has_access_key and has_basic_auth:
        return "conflict", True
    if has_access_key:
        return "aksk", not access_key_complete
    if has_basic_auth:
        return "basic", not basic_auth_complete
    return None, True


def get_config_status() -> dict[str, Any]:
    values = _effective_runtime_values()
    missing_address = not any(_value_is_set(values.get(key)) for key in ADDRESS_ENV_KEYS)
    auth_mode, missing_auth = _auth_status(values)
    complete = not missing_address and not missing_auth and auth_mode in {"aksk", "basic"}

    return {
        "env_file_path": str(LOCAL_ENV_FILE),
        "exists": LOCAL_ENV_FILE.exists(),
        "complete": complete,
        "missing_address": missing_address,
        "missing_auth": missing_auth,
        "auth_mode": auth_mode,
        "current_nonsecret": _build_nonsecret_view(values),
    }


def _normalize_config_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _merge_config_values(payload: dict[str, Any]) -> dict[str, str]:
    unknown_keys = sorted(set(payload) - WRITABLE_ENV_KEYS)
    if unknown_keys:
        unknown = ", ".join(unknown_keys)
        raise RuntimeError(f"Unsupported config keys: {unknown}")

    merged = dict(read_local_env())
    for key, raw_value in payload.items():
        value = _normalize_config_value(raw_value)
        if not _value_is_set(value):
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _resolve_address_values(values: dict[str, str]) -> dict[str, str]:
    api_url = values.get("JMS_API_URL")
    web_url = values.get("JMS_WEB_URL")
    if _value_is_set(api_url):
        return {"JMS_API_URL": str(api_url)}
    if _value_is_set(web_url):
        return {"JMS_WEB_URL": str(web_url)}
    raise RuntimeError(
        "JMS_API_URL or JMS_WEB_URL is required in --payload or the current .env.local."
    )


def _resolve_auth_values(
    payload: dict[str, Any],
    merged: dict[str, str],
) -> tuple[str, dict[str, str]]:
    payload_has_access_key = any(key in payload for key in ACCESS_KEY_ENV_KEYS)
    payload_has_basic_auth = any(key in payload for key in BASIC_AUTH_ENV_KEYS)
    if payload_has_access_key and payload_has_basic_auth:
        raise RuntimeError(
            "Provide only one auth mode in --payload: AK/SK or username/password."
        )

    if payload_has_access_key:
        missing = [key for key in ACCESS_KEY_ENV_KEYS if not _value_is_set(merged.get(key))]
        if missing:
            missing_text = ", ".join(missing)
            raise RuntimeError(f"AK/SK auth is incomplete. Missing: {missing_text}")
        return "aksk", {key: str(merged[key]) for key in ACCESS_KEY_ENV_KEYS}

    if payload_has_basic_auth:
        missing = [key for key in BASIC_AUTH_ENV_KEYS if not _value_is_set(merged.get(key))]
        if missing:
            missing_text = ", ".join(missing)
            raise RuntimeError(f"Username/password auth is incomplete. Missing: {missing_text}")
        return "basic", {key: str(merged[key]) for key in BASIC_AUTH_ENV_KEYS}

    auth_mode, missing_auth = _auth_status(merged)
    if auth_mode == "conflict":
        raise RuntimeError(
            "Current configuration contains both AK/SK and username/password. "
            "Provide one complete auth mode in --payload to replace it."
        )
    if missing_auth or auth_mode is None:
        raise RuntimeError(
            "Provide either JMS_ACCESS_KEY_ID/JMS_ACCESS_KEY_SECRET or "
            "JMS_USERNAME/JMS_PASSWORD in --payload."
        )
    if auth_mode == "aksk":
        return auth_mode, {key: str(merged[key]) for key in ACCESS_KEY_ENV_KEYS}
    return auth_mode, {key: str(merged[key]) for key in BASIC_AUTH_ENV_KEYS}


def _format_env_assignment(key: str, value: str) -> str:
    return f"{key}={json.dumps(str(value), ensure_ascii=False)}"


def write_local_env_config(payload: dict[str, Any]) -> dict[str, Any]:
    merged = _merge_config_values(payload)
    address_values = _resolve_address_values(merged)
    auth_mode, auth_values = _resolve_auth_values(payload, merged)

    final_values: dict[str, str] = {}
    final_values.update(address_values)
    final_values["JMS_VERSION"] = str(merged.get("JMS_VERSION") or "4")
    final_values["JMS_ORG_ID"] = str(merged.get("JMS_ORG_ID", ""))
    final_values.update(auth_values)

    timeout = merged.get("JMS_TIMEOUT")
    if _value_is_set(timeout):
        final_values["JMS_TIMEOUT"] = str(timeout)

    module_name = merged.get("JMS_SDK_MODULE")
    if _value_is_set(module_name):
        final_values["JMS_SDK_MODULE"] = str(module_name)

    attr_name = merged.get("JMS_SDK_GET_CLIENT")
    if _value_is_set(attr_name):
        final_values["JMS_SDK_GET_CLIENT"] = str(attr_name)

    lines = [
        "# Generated by scripts/jms_diagnose.py config-write",
        "# Keep this file local. It may contain secrets.",
        "",
    ]
    for key in (
        "JMS_API_URL",
        "JMS_WEB_URL",
        "JMS_VERSION",
        "JMS_ORG_ID",
        "JMS_ACCESS_KEY_ID",
        "JMS_ACCESS_KEY_SECRET",
        "JMS_USERNAME",
        "JMS_PASSWORD",
        "JMS_TIMEOUT",
        "JMS_SDK_MODULE",
        "JMS_SDK_GET_CLIENT",
    ):
        if key in final_values:
            lines.append(_format_env_assignment(key, final_values[key]))

    LOCAL_ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        LOCAL_ENV_FILE.chmod(0o600)
    reset_local_env_state()

    return {
        "env_file_path": str(LOCAL_ENV_FILE),
        "exists": True,
        "complete": True,
        "auth_mode": auth_mode,
        "current_nonsecret": _build_nonsecret_view(final_values),
    }


def parse_json_arg(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("JSON payload must be an object.")
    return parsed


def require_confirmation(args: argparse.Namespace) -> None:
    if not getattr(args, "confirm", False):
        raise RuntimeError(
            "This action requires --confirm after the change preview is reviewed."
        )


@lru_cache(maxsize=None)
def import_string(path: str) -> Any:
    module_name, attr_name = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def load_get_client() -> Callable[..., Any]:
    load_local_env()
    module_name = os.getenv("JMS_SDK_MODULE", "jms_client.client")
    attr_name = os.getenv("JMS_SDK_GET_CLIENT", "get_client")
    return import_string(f"{module_name}.{attr_name}")


def build_request_instance(
    request_target: str | type[Any],
    payload: dict[str, Any],
    body_override: dict[str, Any] | None = None,
) -> Any:
    request_cls = import_string(request_target) if isinstance(request_target, str) else request_target
    signature = inspect.signature(request_cls)
    params = {
        name: param
        for name, param in signature.parameters.items()
        if name != "self" and param.kind != inspect.Parameter.VAR_KEYWORD
    }
    init_payload: dict[str, Any] = {}
    for key, value in payload.items():
        init_key = "type_" if key == "type" else key
        param = params.get(init_key)
        if param is not None:
            annotation = param.annotation
            if (
                inspect.isclass(annotation)
                and annotation.__module__.startswith("jms_client.")
                and value is not None
                and not isinstance(value, annotation)
            ):
                continue
        init_payload[init_key] = value

    try:
        request = request_cls(**init_payload)
    except TypeError as exc:
        raise RuntimeError(
            f"Failed to construct {request_cls.__name__}: {exc}"
        ) from exc

    if body_override is not None:
        if not hasattr(request, "_body"):
            raise RuntimeError(f"{request_cls.__name__} does not support request bodies.")
        request._body = dict(body_override)
    return request


def _current_client() -> Any | None:
    return _ACTIVE_CLIENT.get()


def _client_pool_key() -> tuple[Any, ...]:
    load_local_env()

    version = os.getenv("JMS_VERSION", "4")
    web_url = os.getenv("JMS_API_URL") or os.getenv("JMS_WEB_URL")
    if not web_url:
        raise RuntimeError(
            "JMS_API_URL or JMS_WEB_URL is required. Set it in the environment "
            f"or in {LOCAL_ENV_FILE}."
        )

    org_id = os.getenv("JMS_ORG_ID", "")
    timeout = os.getenv("JMS_TIMEOUT", "")
    module_name = os.getenv("JMS_SDK_MODULE", "jms_client.client")
    attr_name = os.getenv("JMS_SDK_GET_CLIENT", "get_client")

    access_key = os.getenv("JMS_ACCESS_KEY_ID")
    secret_key = os.getenv("JMS_ACCESS_KEY_SECRET")
    username = os.getenv("JMS_USERNAME")
    password = os.getenv("JMS_PASSWORD")

    if access_key and secret_key:
        auth_key = ("ak", access_key, secret_key)
    elif username and password:
        auth_key = ("basic", username, password)
    else:
        raise RuntimeError(
            "Provide either JMS_ACCESS_KEY_ID/JMS_ACCESS_KEY_SECRET or "
            "JMS_USERNAME/JMS_PASSWORD in the environment or .env.local."
        )

    return (
        module_name,
        attr_name,
        version,
        web_url,
        org_id,
        timeout,
        *auth_key,
    )


def _build_client() -> Any:
    get_client = load_get_client()
    version = os.getenv("JMS_VERSION", "4")
    web_url = os.getenv("JMS_API_URL") or os.getenv("JMS_WEB_URL")
    kwargs: dict[str, Any] = {
        "version": version,
        "web_url": web_url,
        "verify": False,
    }

    access_key = os.getenv("JMS_ACCESS_KEY_ID")
    secret_key = os.getenv("JMS_ACCESS_KEY_SECRET")
    username = os.getenv("JMS_USERNAME")
    password = os.getenv("JMS_PASSWORD")

    if access_key and secret_key:
        kwargs["access_key"] = access_key
        kwargs["secret_key"] = secret_key
    elif username and password:
        kwargs["username"] = username
        kwargs["password"] = password

    timeout = os.getenv("JMS_TIMEOUT")
    if timeout:
        kwargs["timeout"] = int(timeout)

    client = get_client(**kwargs)
    org_id = os.getenv("JMS_ORG_ID")
    if org_id:
        client.set_org(org_id)
    return client


def invalidate_client(*, key: tuple[Any, ...] | None = None, client: Any | None = None) -> None:
    with _CLIENT_POOL_LOCK:
        if key is not None:
            _CLIENT_POOL.pop(key, None)
            return
        if client is None:
            return
        stale_keys = [pool_key for pool_key, value in _CLIENT_POOL.items() if value is client]
        for pool_key in stale_keys:
            _CLIENT_POOL.pop(pool_key, None)


def create_client(*, allow_active: bool = True, use_pool: bool = True) -> Any:
    if allow_active:
        active = _current_client()
        if active is not None:
            return active

    key = _client_pool_key()
    if use_pool:
        with _CLIENT_POOL_LOCK:
            pooled = _CLIENT_POOL.get(key)
            if pooled is not None:
                return pooled

    client = _build_client()
    if use_pool:
        with _CLIENT_POOL_LOCK:
            existing = _CLIENT_POOL.get(key)
            if existing is not None:
                return existing
            _CLIENT_POOL[key] = client
    return client


def _looks_like_client_failure(error: Any) -> bool:
    message = str(error).lower()
    return any(keyword in message for keyword in CLIENT_ERROR_KEYWORDS)


def run_request(
    request_instance: Any,
    with_model: bool = False,
    client: Any | None = None,
) -> Any:
    used_client = client or create_client()
    try:
        response = used_client.do(request_instance, with_model=with_model)
    except Exception as exc:  # noqa: BLE001
        if _looks_like_client_failure(exc):
            invalidate_client(client=used_client)
        raise

    if not response.is_request_ok() or not response.is_success():
        error = str(response.get_err_msg())
        if _looks_like_client_failure(error):
            invalidate_client(client=used_client)
        raise RuntimeError(error)
    return response.get_data()


@contextmanager
def request_client(client: Any | None = None) -> Iterator[Any]:
    active_client = client or create_client(allow_active=False)
    token = _ACTIVE_CLIENT.set(active_client)
    try:
        yield active_client
    finally:
        _ACTIVE_CLIENT.reset(token)


@contextmanager
def temporary_runtime_env(values: dict[str, Any] | None) -> Iterator[None]:
    if not values:
        yield
        return

    sentinel = object()
    previous: dict[str, Any] = {}
    for key, value in values.items():
        previous[key] = os.environ.get(key, sentinel)
        if value in {None, ""}:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)

    try:
        yield
    finally:
        for key, value in previous.items():
            if value is sentinel:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)


def _normalize_org_candidate(value: Any) -> dict[str, Any] | None:
    payload = serialize(value)
    if not isinstance(payload, dict):
        return None

    org_id = payload.get("id") or payload.get("org")
    if org_id in {None, ""}:
        return None

    return {
        "id": str(org_id),
        "name": str(payload.get("name") or payload.get("org_name") or ""),
        "is_default": bool(payload.get("is_default", False)),
        "is_root": bool(payload.get("is_root", False)),
        "internal": bool(payload.get("internal", False)),
    }


def _merge_org_candidate(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key in ("name",):
        if not merged.get(key) and incoming.get(key):
            merged[key] = incoming[key]
    for key in ("is_default", "is_root", "internal"):
        merged[key] = bool(merged.get(key) or incoming.get(key))
    return merged


def _sort_org_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("name") or ""),
            str(item.get("id") or ""),
        ),
    )


def _org_id_set(items: list[dict[str, Any]]) -> frozenset[str]:
    return frozenset(
        str(item.get("id") or "").strip()
        for item in items
        if str(item.get("id") or "").strip()
    )


def _reserved_org_auto_select_eligible(accessible_orgs: list[dict[str, Any]]) -> bool:
    return _org_id_set(accessible_orgs) in RESERVED_AUTO_SELECT_ORG_SETS


def _org_output_summary(org: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(org, dict):
        return None
    summary = {
        "id": str(org.get("id") or ""),
        "name": str(org.get("name") or ""),
    }
    for key in ("is_default", "is_root", "internal", "source"):
        if key in org:
            summary[key] = org.get(key)
    return summary


def _build_org_selection_payload(
    *,
    accessible_orgs: list[dict[str, Any]],
    effective_org: dict[str, Any] | None = None,
    selection_required: bool,
    next_step: str = ORG_SELECTION_NEXT_STEP,
    org_source: str | None = None,
    org_auto_selected: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "selection_required": selection_required,
        "candidate_orgs": [_org_output_summary(item) for item in accessible_orgs],
        "next_step": next_step,
    }
    if effective_org is not None:
        payload["effective_org"] = _org_output_summary(effective_org)
    if org_source:
        payload["org_source"] = org_source
    if org_auto_selected:
        payload["org_auto_selected"] = True
    return payload


def get_user_profile(*, client: Any | None = None) -> dict[str, Any]:
    request_cls = import_string("jms_client.v1.models.request.users.users.UserProfileRequest")
    return serialize(run_request(request_cls(), with_model=True, client=client))


def _profile_accessible_orgs(profile: dict[str, Any]) -> list[dict[str, Any]]:
    orgs_by_id: dict[str, dict[str, Any]] = {}
    for key in ("console_orgs", "workbench_orgs", "audit_orgs"):
        values = profile.get(key, [])
        if not isinstance(values, list):
            continue
        for item in values:
            normalized = _normalize_org_candidate(item)
            if normalized is None:
                continue
            current = orgs_by_id.get(normalized["id"])
            if current is None:
                orgs_by_id[normalized["id"]] = normalized
            else:
                orgs_by_id[normalized["id"]] = _merge_org_candidate(current, normalized)
    return _sort_org_candidates(list(orgs_by_id.values()))


def _list_organization_candidates(*, client: Any | None = None) -> list[dict[str, Any]]:
    request_cls = import_string(
        "jms_client.v1.models.request.organizations.organizations.DescribeOrganizationsRequest"
    )
    page_size = 200
    page_offset = 0
    orgs_by_id: dict[str, dict[str, Any]] = {}
    try:
        while True:
            result = serialize(
                run_request(
                    request_cls(limit=page_size, offset=page_offset),
                    with_model=True,
                    client=client,
                )
            )
            if isinstance(result, dict) and "results" in result:
                batch = result.get("results", [])
            else:
                batch = result
            if not isinstance(batch, list):
                return []
            for item in batch:
                normalized = _normalize_org_candidate(item)
                if normalized is None:
                    continue
                current = orgs_by_id.get(normalized["id"])
                if current is None:
                    orgs_by_id[normalized["id"]] = normalized
                else:
                    orgs_by_id[normalized["id"]] = _merge_org_candidate(current, normalized)
            if len(batch) < page_size:
                break
            page_offset += len(batch)
    except Exception:  # noqa: BLE001
        return []
    return _sort_org_candidates(list(orgs_by_id.values()))


def get_accessible_orgs(
    *,
    client: Any | None = None,
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    current_profile = profile if isinstance(profile, dict) else get_user_profile(client=client)
    accessible_orgs = _profile_accessible_orgs(current_profile)
    if accessible_orgs:
        return accessible_orgs
    # Some JumpServer deployments return empty profile org arrays even when the account
    # can enumerate organizations. Fall back to a read-only org list for guard decisions.
    return _list_organization_candidates(client=client)


@contextmanager
def temporary_org_client(org_id: str | None) -> Iterator[Any]:
    with temporary_runtime_env({"JMS_ORG_ID": org_id or ""}):
        client = create_client(allow_active=False, use_pool=True)
        with request_client(client):
            yield client


def run_request_in_org(
    org_id: str | None,
    request_instance: Any,
    *,
    with_model: bool = False,
) -> Any:
    with temporary_org_client(org_id) as client:
        return run_request(request_instance, with_model=with_model, client=client)


def get_organization_detail(
    org_id: str,
    *,
    org_context_id: str | None = None,
) -> dict[str, Any] | None:
    if not org_id:
        return None
    request_cls = import_string(
        "jms_client.v1.models.request.organizations.organizations.DetailOrganizationRequest"
    )
    try:
        return serialize(
            run_request_in_org(
                org_context_id or org_id,
                request_cls(id_=org_id),
                with_model=True,
            )
        )
    except Exception:  # noqa: BLE001
        return None


def _resolve_org_metadata(
    org_id: str,
    accessible_orgs: list[dict[str, Any]],
) -> dict[str, Any]:
    for item in accessible_orgs:
        if item.get("id") == org_id:
            return dict(item)

    detail = get_organization_detail(org_id)
    normalized = _normalize_org_candidate(detail)
    if normalized is not None:
        return normalized

    return {
        "id": str(org_id),
        "name": "",
        "is_default": org_id == CANONICAL_DEFAULT_ORG_ID,
        "is_root": False,
        "internal": False,
    }


def resolve_effective_org_context(
    preferred_org_id: str | None = None,
    *,
    accessible_orgs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if accessible_orgs is None:
        accessible_orgs = get_accessible_orgs()
    explicit_org_id = os.getenv("JMS_ORG_ID") or None
    accessible_org_ids = _org_id_set(accessible_orgs)
    selection_required = False
    selected_org_accessible = True
    source: str | None = None
    effective_org: dict[str, Any] | None = None

    if preferred_org_id:
        source = "user_selected"
        effective_org = _resolve_org_metadata(str(preferred_org_id), accessible_orgs)
        if accessible_org_ids:
            selected_org_accessible = str(preferred_org_id) in accessible_org_ids
    elif explicit_org_id:
        source = "explicit_env"
        effective_org = _resolve_org_metadata(str(explicit_org_id), accessible_orgs)
        if accessible_org_ids:
            selected_org_accessible = str(explicit_org_id) in accessible_org_ids
            selection_required = not selected_org_accessible
    else:
        selection_required = True

    if effective_org is not None and source is not None:
        effective_org["source"] = source

    return {
        "effective_org": effective_org,
        "accessible_orgs": accessible_orgs,
        "candidate_orgs": accessible_orgs,
        "has_explicit_org": bool(preferred_org_id or explicit_org_id),
        "explicit_org_id": explicit_org_id,
        "multiple_accessible_orgs": len(accessible_orgs) > 1,
        "selection_required": selection_required,
        "selected_org_accessible": selected_org_accessible,
        "reserved_org_auto_select_eligible": (
            not bool(preferred_org_id or explicit_org_id)
            and _reserved_org_auto_select_eligible(accessible_orgs)
        ),
    }


def persist_selected_org(org_id: str) -> dict[str, Any]:
    if not org_id:
        raise RuntimeError("Organization id is required.")
    payload = _effective_runtime_values()
    payload["JMS_ORG_ID"] = str(org_id)
    result = write_local_env_config(payload)
    os.environ["JMS_ORG_ID"] = str(org_id)
    reset_local_env_state()
    load_local_env()
    invalidate_all_clients()
    return result


def ensure_selected_org_context(
    *,
    next_step: str = ORG_SELECTION_NEXT_STEP,
    accessible_orgs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if accessible_orgs is None:
        accessible_orgs = get_accessible_orgs()
    context = resolve_effective_org_context(accessible_orgs=accessible_orgs)
    effective_org = context.get("effective_org")

    if context["has_explicit_org"] and not context["selected_org_accessible"]:
        selected = _org_output_summary(effective_org)
        selected_text = (
            f"{selected.get('name')} ({selected.get('id')})"
            if isinstance(selected, dict) and selected.get("name") and selected.get("id")
            else str((selected or {}).get("id") or context.get("explicit_org_id") or "-")
        )
        payload = _build_org_selection_payload(
            accessible_orgs=accessible_orgs,
            effective_org=effective_org,
            selection_required=True,
            next_step=next_step,
            org_source=effective_org.get("source") if isinstance(effective_org, dict) else None,
        )
        raise StructuredActionError(
            f"当前配置的组织 {selected_text} 已不在当前账号可访问组织中，请先重新选择组织。",
            payload=payload,
        )

    if context["selection_required"]:
        if context["reserved_org_auto_select_eligible"]:
            persist_selected_org(CANONICAL_DEFAULT_ORG_ID)
            effective_org = _resolve_org_metadata(CANONICAL_DEFAULT_ORG_ID, accessible_orgs)
            effective_org["source"] = "reserved_org_auto_selected"
            context = dict(context)
            context["effective_org"] = effective_org
            context["selection_required"] = False
            context["has_explicit_org"] = True
            context["explicit_org_id"] = CANONICAL_DEFAULT_ORG_ID
            context["selected_org_accessible"] = True
            context["org_auto_selected"] = True
            set_action_metadata(
                {
                    "effective_org": _org_output_summary(effective_org),
                    "org_source": effective_org.get("source"),
                    "selection_required": False,
                    "org_auto_selected": True,
                }
            )
            return context

        payload = _build_org_selection_payload(
            accessible_orgs=accessible_orgs,
            selection_required=True,
            next_step=next_step,
        )
        raise StructuredActionError(
            "当前尚未选择组织。请先从当前环境可访问组织中选择 1 个组织，并写入 JMS_ORG_ID 后再继续执行业务命令。",
            payload=payload,
        )

    if isinstance(effective_org, dict):
        set_action_metadata(
            {
                "effective_org": _org_output_summary(effective_org),
                "org_source": effective_org.get("source"),
                "selection_required": False,
            }
        )
    return context


def serialize(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize(item) for key, item in value.items()}
    if hasattr(value, "value") and not isinstance(value, type):
        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, (str, int, float, bool)) or enum_value is None:
            return enum_value
    if hasattr(value, "__dict__"):
        return {
            key: serialize(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return repr(value)


def print_json(value: Any) -> None:
    json.dump(serialize(value), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def execute_action(func: Callable[[argparse.Namespace], Any], args: argparse.Namespace) -> dict[str, Any]:
    token = _ACTION_METADATA.set({})
    try:
        result = func(args)
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": str(exc)}
        details = getattr(exc, "payload", None)
        if isinstance(details, dict):
            for key, value in serialize(details).items():
                if key not in {"ok", "error"}:
                    payload[key] = value
    else:
        payload = {"ok": True, "result": result}
    finally:
        metadata = dict(_ACTION_METADATA.get() or {})
        _ACTION_METADATA.reset(token)

    for key, value in metadata.items():
        if key not in {"ok", "error", "result"} and key not in payload:
            payload[key] = value
    return payload


def run_and_print(func: Callable[[argparse.Namespace], Any], args: argparse.Namespace) -> int:
    payload = execute_action(func, args)
    print_json(payload)
    return 0 if payload.get("ok") else 1
