from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .jms_types import JumpServerAPIError, JumpServerConfig, PlatformSpec

if TYPE_CHECKING:
    from .jms_api_client import JumpServerClient
    from .jms_discovery import JumpServerDiscovery


SKILL_DIR = Path(__file__).resolve().parents[2]
LOCAL_ENV_FILE = SKILL_DIR / ".env"
GLOBAL_ORG_ID = "00000000-0000-0000-0000-000000000000"
DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000002"
DEFAULT_PAGE_SIZE = 100
RESERVED_INTERNAL_ORG_ID = "00000000-0000-0000-0000-000000000004"
RESERVED_AUTO_SELECT_ORG_SETS = frozenset(
    {
        frozenset({DEFAULT_ORG_ID}),
        frozenset({DEFAULT_ORG_ID, RESERVED_INTERNAL_ORG_ID}),
    }
)
UUID_LIKE_RE = re.compile(
    r"^[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)
ENV_KEYS = (
    "JMS_API_URL",
    "JMS_ACCESS_KEY_ID",
    "JMS_ACCESS_KEY_SECRET",
    "JMS_USERNAME",
    "JMS_PASSWORD",
    "JMS_ORG_ID",
    "JMS_TIMEOUT",
    "JMS_VERIFY_TLS",
)
WRITEABLE_ENV_KEYS = frozenset(ENV_KEYS)
NONSECRET_ENV_KEYS = (
    "JMS_API_URL",
    "JMS_USERNAME",
    "JMS_ORG_ID",
    "JMS_TIMEOUT",
    "JMS_VERIFY_TLS",
)
ORG_LIST_PATH = "/api/v1/orgs/orgs/"
ORG_CURRENT_PATH = "/api/v1/orgs/orgs/current/"
USER_PROFILE_PATH = "/api/v1/users/profile/"
ORG_SELECTION_NEXT_STEP = (
    "python3 scripts/jumpserver_api/jms_diagnose.py select-org --org-id <org-id> --confirm"
)
ORG_SELECTION_REQUIRED_REASON_CODE = "organization_selection_required"
ORG_SELECTION_POLICY = "required_before_query_when_multiple_accessible_orgs"
DEFAULT_TIMEOUT = 30
_GLOBAL_ORG_PROBE_ATTEMPTED = False
_GLOBAL_ORG_PROBE_RESULT: dict[str, Any] | None = None


class CLIError(RuntimeError):
    def __init__(self, message: str, *, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.payload = dict(payload or {})


def is_uuid_like(value: Any) -> bool:
    return bool(UUID_LIKE_RE.fullmatch(str(value or "").strip()))


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def mask_secret(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return "%s***%s" % (text[:4], text[-2:])


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_local_env(path: Path | None = None) -> dict[str, str]:
    env_path = Path(path or LOCAL_ENV_FILE)
    if not env_path.exists():
        return {}
    payload: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            payload[key] = _strip_wrapping_quotes(value.strip())
    return payload


def load_local_env(path: Path | None = None) -> None:
    env_path = Path(path or LOCAL_ENV_FILE)
    for key, value in read_local_env(env_path).items():
        if not os.getenv(key):
            os.environ[key] = value


def current_runtime_values(path: Path | None = None) -> dict[str, str]:
    values = read_local_env(path)
    for key in ENV_KEYS:
        if key in os.environ and os.environ[key] != "":
            values[key] = os.environ[key]
    return values


def write_local_env_config(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    env_path = Path(path or LOCAL_ENV_FILE)
    final: dict[str, str] = {}
    current = read_local_env(env_path)
    final.update({key: value for key, value in current.items() if key not in WRITEABLE_ENV_KEYS})

    for key in WRITEABLE_ENV_KEYS:
        value = payload.get(key)
        if value is None:
            if key in current:
                final[key] = current[key]
            continue
        final[key] = str(value)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key in sorted(final):
        value = final[key]
        if value is None:
            continue
        lines.append('%s="%s"' % (key, str(value).replace('"', '\\"')))
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    for key in WRITEABLE_ENV_KEYS:
        if key in final:
            os.environ[key] = str(final[key])
    return {
        "env_file_path": str(env_path),
        "current_nonsecret": current_nonsecret_view(current_runtime_values(env_path)),
    }


def current_nonsecret_view(values: dict[str, str] | None = None) -> dict[str, str]:
    payload = dict(values or current_runtime_values())
    return {key: payload[key] for key in NONSECRET_ENV_KEYS if key in payload and payload[key] != ""}


def get_config_status(path: Path | None = None) -> dict[str, Any]:
    values = current_runtime_values(path)
    missing = []
    invalid_fields = []
    partial_auth_fields = []
    has_url = bool(values.get("JMS_API_URL"))
    has_ak = bool(values.get("JMS_ACCESS_KEY_ID"))
    has_sk = bool(values.get("JMS_ACCESS_KEY_SECRET"))
    has_username = bool(values.get("JMS_USERNAME"))
    has_password = bool(values.get("JMS_PASSWORD"))
    has_aksk = has_ak and has_sk
    has_password_auth = has_username and has_password

    api_url = str(values.get("JMS_API_URL") or "").strip()
    if not api_url:
        missing.append("JMS_API_URL")
    else:
        parsed_url = urlparse(api_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            invalid_fields.append("JMS_API_URL")
    if has_ak != has_sk:
        if not has_ak:
            partial_auth_fields.append("JMS_ACCESS_KEY_ID")
        if not has_sk:
            partial_auth_fields.append("JMS_ACCESS_KEY_SECRET")
    if has_username != has_password:
        if not has_username:
            partial_auth_fields.append("JMS_USERNAME")
        if not has_password:
            partial_auth_fields.append("JMS_PASSWORD")
    if not has_aksk and not has_password_auth:
        if partial_auth_fields:
            missing.extend(partial_auth_fields)
        else:
            missing.append("JMS_ACCESS_KEY_ID/JMS_ACCESS_KEY_SECRET or JMS_USERNAME/JMS_PASSWORD")

    auth_mode = "none"
    if has_aksk:
        auth_mode = "aksk"
    elif has_password_auth:
        auth_mode = "password"

    timeout_value = str(values.get("JMS_TIMEOUT") or "").strip()
    if timeout_value:
        try:
            if int(timeout_value) <= 0:
                invalid_fields.append("JMS_TIMEOUT")
        except ValueError:
            invalid_fields.append("JMS_TIMEOUT")

    return {
        "env_file_path": str(Path(path or LOCAL_ENV_FILE)),
        "exists": Path(path or LOCAL_ENV_FILE).exists(),
        "complete": not missing and not invalid_fields,
        "missing_fields": missing,
        "invalid_fields": invalid_fields,
        "auth_mode": auth_mode,
        "current_nonsecret": current_nonsecret_view(values),
    }


def parse_json_arg(value: str | None, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if value in {None, ""}:
        return dict(default or {})
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CLIError("Invalid JSON payload: %s" % exc.msg) from exc
    if not isinstance(payload, dict):
        raise CLIError("JSON payload must be an object.")
    return payload


def require_confirmation(args: argparse.Namespace) -> None:
    if not getattr(args, "confirm", False):
        raise CLIError(
            "This action requires --confirm after the change preview is reviewed."
        )


def build_config(*, org_id: str | None = None) -> JumpServerConfig:
    load_local_env()
    values = current_runtime_values()
    base_url = values.get("JMS_API_URL")
    config_status = get_config_status()
    if not config_status.get("complete"):
        raise CLIError(
            "Runtime configuration validation failed.",
            payload={"config_status": config_status},
        )

    if not base_url:
        raise CLIError(
            "JMS_API_URL is required.",
            payload={"config_status": config_status},
        )

    access_key = values.get("JMS_ACCESS_KEY_ID") or ""
    secret_key = values.get("JMS_ACCESS_KEY_SECRET") or ""
    username = values.get("JMS_USERNAME") or ""
    password = values.get("JMS_PASSWORD") or ""

    has_aksk = bool(access_key and secret_key)
    has_password_auth = bool(username and password)
    if not has_aksk and not has_password_auth:
        raise CLIError(
            "Provide JMS_ACCESS_KEY_ID/JMS_ACCESS_KEY_SECRET or JMS_USERNAME/JMS_PASSWORD before running business commands.",
            payload={"config_status": get_config_status()},
        )

    if has_aksk:
        username = ""
        password = ""

    return JumpServerConfig(
        base_url=base_url,
        access_key=access_key,
        secret_key=secret_key,
        username=username,
        password=password,
        org_id=org_id if org_id is not None else values.get("JMS_ORG_ID", ""),
        verify_tls=parse_bool(values.get("JMS_VERIFY_TLS"), default=False),
    ).validate(require_org_id=False)


def create_client(*, org_id: str | None = None) -> JumpServerClient:
    from .jms_api_client import JumpServerClient

    config = build_config(org_id=org_id)
    timeout = current_runtime_values().get("JMS_TIMEOUT")
    return JumpServerClient(
        config=config,
        timeout=int(timeout or DEFAULT_TIMEOUT),
    )


def create_discovery(*, org_id: str | None = None) -> JumpServerDiscovery:
    from .jms_discovery import JumpServerDiscovery

    return JumpServerDiscovery(create_client(org_id=org_id))


def _global_org_probe_error(exc: JumpServerAPIError) -> bool:
    if exc.status_code in {403, 404}:
        return True
    text = " ".join(
        [
            str(exc.message or ""),
            str(exc.details or ""),
        ]
    ).lower()
    return any(
        keyword in text
        for keyword in (
            "forbidden",
            "denied",
            "permission",
            "not accessible",
            "not found",
            "无权限",
            "拒绝",
            "不可访问",
            "不存在",
        )
    )


def _global_org_candidate() -> dict[str, Any] | None:
    global _GLOBAL_ORG_PROBE_ATTEMPTED, _GLOBAL_ORG_PROBE_RESULT
    if _GLOBAL_ORG_PROBE_ATTEMPTED:
        return dict(_GLOBAL_ORG_PROBE_RESULT) if _GLOBAL_ORG_PROBE_RESULT else None

    _GLOBAL_ORG_PROBE_ATTEMPTED = True
    try:
        payload = create_client(org_id=GLOBAL_ORG_ID).get(ORG_CURRENT_PATH)
    except JumpServerAPIError as exc:
        if _global_org_probe_error(exc):
            _GLOBAL_ORG_PROBE_RESULT = None
            return None
        raise

    if isinstance(payload, dict):
        candidate = dict(payload)
        reported_id = str(candidate.get("id") or "").strip()
        if reported_id and reported_id != GLOBAL_ORG_ID:
            _GLOBAL_ORG_PROBE_RESULT = None
            return None
        if not reported_id:
            candidate["id"] = GLOBAL_ORG_ID
            candidate["name"] = str(candidate.get("name") or "").strip() or "Global"
    else:
        candidate = {"id": GLOBAL_ORG_ID, "name": "Global"}

    candidate["source"] = str(candidate.get("source") or "").strip() or "global_org_probe"
    _GLOBAL_ORG_PROBE_RESULT = candidate
    return dict(candidate)


def list_accessible_orgs(*, include_global_probe: bool = True) -> list[dict[str, Any]]:
    client = create_client(org_id="")
    result = client.list_paginated(ORG_LIST_PATH)
    if not isinstance(result, list):
        raise CLIError("Organization list API did not return a list.")
    accessible_orgs = [dict(item) for item in result if isinstance(item, dict)]
    if not include_global_probe:
        return accessible_orgs

    known_ids = {
        str(item.get("id") or "").strip()
        for item in accessible_orgs
        if isinstance(item, dict)
    }
    if GLOBAL_ORG_ID not in known_ids:
        global_candidate = _global_org_candidate()
        if global_candidate:
            accessible_orgs.append(global_candidate)
    return accessible_orgs


def _switchable_orgs(accessible_orgs: list[dict[str, Any]], effective_org: dict[str, Any] | None) -> list[dict[str, Any]]:
    effective_org_id = str((effective_org or {}).get("id") or "").strip()
    if not effective_org_id:
        return []
    return [
        item
        for item in accessible_orgs
        if isinstance(item, dict) and str(item.get("id") or "").strip() and str(item.get("id") or "").strip() != effective_org_id
    ]


def _org_scope_label(effective_org: dict[str, Any] | None) -> str:
    payload = dict(effective_org or {})
    org_id = str(payload.get("id") or "").strip() or "<unknown-org-id>"
    org_name = str(payload.get("name") or "").strip() or "Unknown"
    return "%s (%s)" % (org_name, org_id)


def _org_context_hint(effective_org: dict[str, Any] | None, switchable_orgs: list[dict[str, Any]]) -> str | None:
    if not effective_org or not switchable_orgs:
        return None
    org_scope = _org_scope_label(effective_org)
    source = str(effective_org.get("source") or "").strip()
    if source == "env":
        return "当前查询范围固定为组织 %s；如需改查其他组织，请先切换组织。" % org_scope
    if source == "reserved_auto_select":
        return "当前查询范围按保留组织规则固定为组织 %s；如需改查其他组织，请先切换组织。" % org_scope
    return "当前查询范围固定为组织 %s；如需切换查询范围，请先切换组织。" % org_scope


def build_org_selection_required_payload(context: dict[str, Any]) -> dict[str, Any]:
    candidate_orgs = context.get("candidate_orgs")
    if not isinstance(candidate_orgs, list):
        candidate_orgs = []
    return {
        "selection_required": True,
        "candidate_orgs": candidate_orgs,
        "candidate_org_count": len(candidate_orgs),
        "next_step": ORG_SELECTION_NEXT_STEP,
        "reserved_org_auto_select_eligible": bool(context.get("reserved_org_auto_select_eligible")),
        "reason_code": ORG_SELECTION_REQUIRED_REASON_CODE,
        "user_message": "检测到多个可访问组织，继续前必须先选择一个组织。",
        "action_hint": (
            "请从 candidate_orgs 中选择 1 个 org_id，然后执行 %s。"
            % ORG_SELECTION_NEXT_STEP
        ),
        "org_selection_policy": ORG_SELECTION_POLICY,
        **org_context_output(context),
    }


def org_context_output(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "effective_org": context.get("effective_org"),
        "switchable_orgs": context.get("switchable_orgs") or [],
        "switchable_org_count": int(context.get("switchable_org_count") or 0),
        "org_context_hint": context.get("org_context_hint"),
    }


def current_org(client: JumpServerClient | None = None) -> dict[str, Any]:
    active_client = client or create_client()
    result = active_client.get(ORG_CURRENT_PATH)
    if isinstance(result, dict):
        return result
    return {}


def user_profile(client: JumpServerClient | None = None) -> dict[str, Any]:
    active_client = client or create_client()
    result = active_client.get(USER_PROFILE_PATH)
    if isinstance(result, dict):
        return result
    return {}


def persist_selected_org(org_id: str) -> dict[str, Any]:
    values = current_runtime_values()
    values["JMS_ORG_ID"] = org_id
    return write_local_env_config(values)


def resolve_effective_org_context(*, auto_select: bool = True) -> dict[str, Any]:
    values = current_runtime_values()
    selected_org_id = str(values.get("JMS_ORG_ID") or "").strip()
    accessible_orgs = list_accessible_orgs()
    by_id = {str(item.get("id") or ""): item for item in accessible_orgs if isinstance(item, dict)}
    accessible_ids = frozenset([key for key in by_id if key])
    selected_org = by_id.get(selected_org_id) if selected_org_id else None
    reserved_auto_select_eligible = accessible_ids in RESERVED_AUTO_SELECT_ORG_SETS

    if selected_org:
        effective_org = dict(selected_org)
        effective_org["source"] = "env"
        switchable_orgs = _switchable_orgs(accessible_orgs, effective_org)
        return {
            "accessible_orgs": accessible_orgs,
            "candidate_orgs": accessible_orgs,
            "effective_org": effective_org,
            "multiple_accessible_orgs": len(accessible_orgs) > 1,
            "selection_required": False,
            "reserved_org_auto_select_eligible": reserved_auto_select_eligible,
            "selected_org_accessible": True,
            "switchable_orgs": switchable_orgs,
            "switchable_org_count": len(switchable_orgs),
            "org_context_hint": _org_context_hint(effective_org, switchable_orgs),
        }

    if reserved_auto_select_eligible and auto_select:
        persist_selected_org(DEFAULT_ORG_ID)
        auto_selected = dict(by_id.get(DEFAULT_ORG_ID) or {"id": DEFAULT_ORG_ID, "name": "Default"})
        auto_selected["source"] = "reserved_auto_select"
        switchable_orgs = _switchable_orgs(accessible_orgs, auto_selected)
        return {
            "accessible_orgs": accessible_orgs,
            "candidate_orgs": accessible_orgs,
            "effective_org": auto_selected,
            "multiple_accessible_orgs": len(accessible_orgs) > 1,
            "selection_required": False,
            "reserved_org_auto_select_eligible": True,
            "selected_org_accessible": True,
            "switchable_orgs": switchable_orgs,
            "switchable_org_count": len(switchable_orgs),
            "org_context_hint": _org_context_hint(auto_selected, switchable_orgs),
        }

    return {
        "accessible_orgs": accessible_orgs,
        "candidate_orgs": accessible_orgs,
        "effective_org": None,
        "multiple_accessible_orgs": len(accessible_orgs) > 1,
        "selection_required": True,
        "reserved_org_auto_select_eligible": reserved_auto_select_eligible,
        "selected_org_accessible": False,
        "switchable_orgs": [],
        "switchable_org_count": 0,
        "org_context_hint": None,
    }


def ensure_selected_org_context() -> dict[str, Any]:
    context = resolve_effective_org_context()
    if context["selection_required"]:
        raise CLIError(
            "Organization selection is required: multiple accessible organizations were detected.",
            payload=build_org_selection_required_payload(context),
        )
    return context


def resolve_platform_reference(value: str, *, discovery: JumpServerDiscovery | None = None) -> dict[str, Any]:
    active_discovery = discovery or create_discovery()
    wanted = str(value or "").strip().lower()
    exact = []
    category_matches = []
    for item in active_discovery.list_platforms():
        payload = item.to_dict()
        names = {str(payload.get("name", "")).lower(), str(payload.get("slug", "")).lower()}
        if wanted in names:
            exact.append(payload)
            continue
        if wanted and wanted == str(payload.get("category", "")).lower():
            category_matches.append(payload)
    if len(exact) == 1:
        return {"status": "resolved", "resolved": exact[0], "candidates": exact}
    if len(exact) > 1:
        return {"status": "ambiguous", "resolved": None, "candidates": exact}
    return {"status": "candidate_only", "resolved": None, "candidates": category_matches}


def serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, PlatformSpec):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, tuple):
        return [serialize(item) for item in value]
    return value


def print_json(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def run_and_print(func, args: argparse.Namespace | None = None) -> int:
    try:
        result = func(args) if args is not None else func()
        print_json({"ok": True, "result": serialize(result)})
        return 0
    except CLIError as exc:
        payload = {"ok": False, "error": str(exc)}
        if exc.payload:
            payload["details"] = serialize(exc.payload)
        print_json(payload)
        return 1
    except JumpServerAPIError as exc:
        payload = {
            "ok": False,
            "error": exc.message,
            "details": serialize(
                {
                    "status_code": exc.status_code,
                    "method": exc.method,
                    "path": exc.path,
                    "details": exc.details,
                }
            ),
        }
        print_json(payload)
        return 1
    except Exception as exc:  # noqa: BLE001
        print_json({"ok": False, "error": str(exc)})
        return 1
