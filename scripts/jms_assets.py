#!/usr/bin/env python3
"""JumpServer CRUD for assets, nodes, platforms, accounts, users, and groups."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from jms_bootstrap import bootstrap_runtime

bootstrap_runtime()

import argparse
import difflib
from enum import Enum
import json
import os
import time
from typing import Any

from jms_runtime import (
    build_request_instance,
    create_client,
    ensure_selected_org_context,
    import_string,
    parse_json_arg,
    require_confirmation,
    resolve_effective_org_context,
    run_and_print,
    run_request,
    serialize,
    temporary_org_client,
)
from jms_client.v1.models.request.common import Request
from jms_client.v1.models.request.mixins import WithIDMixin


RESOURCE_MAP: dict[str, dict[str, Any]] = {
    "asset": {
        "list": "jms_client.v1.models.request.assets.assets.DescribeAssetsRequest",
        "detail": "jms_client.v1.models.request.assets.assets.DetailAssetRequest",
        "delete": "jms_client.v1.models.request.assets.assets.DeleteAssetRequest",
        "create": {
            "host": "jms_client.v1.models.request.assets.assets.CreateHostRequest",
            "database": "jms_client.v1.models.request.assets.assets.CreateDatabaseRequest",
            "device": "jms_client.v1.models.request.assets.assets.CreateDeviceRequest",
            "cloud": "jms_client.v1.models.request.assets.assets.CreateCloudRequest",
            "web": "jms_client.v1.models.request.assets.assets.CreateWebRequest",
        },
        "update": {
            "host": "jms_client.v1.models.request.assets.assets.UpdateHostRequest",
            "database": "jms_client.v1.models.request.assets.assets.UpdateDatabaseRequest",
            "device": "jms_client.v1.models.request.assets.assets.UpdateDeviceRequest",
            "cloud": "jms_client.v1.models.request.assets.assets.UpdateCloudRequest",
            "web": "jms_client.v1.models.request.assets.assets.UpdateWebRequest",
        },
    },
    "node": {
        "list": "jms_client.v1.models.request.assets.nodes.DescribeNodesRequest",
        "detail": "jms_client.v1.models.request.assets.nodes.DetailNodeRequest",
        "create": "jms_client.v1.models.request.assets.nodes.CreateNodeRequest",
        "update": "jms_client.v1.models.request.assets.nodes.UpdateNodeRequest",
        "delete": "jms_client.v1.models.request.assets.nodes.DeleteNodeRequest",
    },
    "platform": {
        "list": "jms_client.v1.models.request.assets.platforms.DescribePlatformsRequest",
        "detail": "jms_client.v1.models.request.assets.platforms.DetailPlatformRequest",
        "create": "jms_client.v1.models.request.assets.platforms.CreatePlatformRequest",
        "update": "jms_client.v1.models.request.assets.platforms.UpdatePlatformRequest",
        "delete": "jms_client.v1.models.request.assets.platforms.DeletePlatformRequest",
    },
    "account": {
        "list": "jms_client.v1.models.request.accounts.accounts.DescribeAccountsRequest",
        "detail": "jms_client.v1.models.request.accounts.accounts.DetailAccountRequest",
        "create": "jms_client.v1.models.request.accounts.accounts.CreateAccountRequest",
        "update": "jms_client.v1.models.request.accounts.accounts.UpdateAccountRequest",
        "delete": "jms_client.v1.models.request.accounts.accounts.DeleteAccountRequest",
    },
    "user": {
        "list": "jms_client.v1.models.request.users.users.DescribeUsersRequest",
        "detail": "jms_client.v1.models.request.users.users.DetailUserRequest",
        "create": "jms_client.v1.models.request.users.users.CreateUserRequest",
        "update": "jms_client.v1.models.request.users.users.UpdateUserRequest",
        "delete": "jms_client.v1.models.request.users.users.DeleteUserRequest",
    },
    "user-group": {
        "list": "jms_client.v1.models.request.users.user_groups.DescribeUserGroupsRequest",
        "detail": "jms_client.v1.models.request.users.user_groups.DetailUserGroupRequest",
        "create": "jms_client.v1.models.request.users.user_groups.CreateUserGroupRequest",
        "update": "jms_client.v1.models.request.users.user_groups.UpdateUserGroupRequest",
        "delete": "jms_client.v1.models.request.users.user_groups.DeleteUserGroupRequest",
    },
    "organization": {
        "list": "jms_client.v1.models.request.organizations.organizations.DescribeOrganizationsRequest",
        "detail": "jms_client.v1.models.request.organizations.organizations.DetailOrganizationRequest",
        "create": "jms_client.v1.models.request.organizations.organizations.CreateOrganizationRequest",
        "update": "jms_client.v1.models.request.organizations.organizations.UpdateOrganizationRequest",
        "delete": "jms_client.v1.models.request.organizations.organizations.DeleteOrganizationRequest",
    },
}

ASSET_DETAIL_MAP = {
    "host": "jms_client.v1.models.request.assets.assets.DetailHostRequest",
    "database": "jms_client.v1.models.request.assets.assets.DetailDatabaseRequest",
    "device": "jms_client.v1.models.request.assets.assets.DetailDeviceRequest",
    "cloud": "jms_client.v1.models.request.assets.assets.DetailCloudRequest",
    "web": "jms_client.v1.models.request.assets.assets.DetailWebRequest",
}

ASSET_KIND_ALIASES = {
    "host": "host",
    "database": "database",
    "db": "database",
    "device": "device",
    "cloud": "cloud",
    "web": "web",
    "website": "web",
}

SENSITIVE_FIELDS = {"password", "secret"}
USER_AUTH_STRATEGY_CLASS = "jms_client.v1.models.request.users.users.AuthStrategyParam"
PLATFORM_AUTOMATION_PARAM_CLASS = "jms_client.v1.models.request.assets.platforms.AutomationParam"
PLATFORM_PROTOCOL_PARAM_CLASS = "jms_client.v1.models.request.params.ProtocolParam"
PLATFORM_SU_PARAM_CLASS = "jms_client.v1.models.request.assets.platforms.SuParam"
NODE_API_PATH = "api/v1/assets/nodes/"


class UnblockUserRequest(WithIDMixin, Request):
    URL = "users/users/{id}/unblock/"

    @staticmethod
    def get_method() -> str:
        return "patch"


def resolve_request_target(
    resource: str,
    action: str,
    kind: str | None = None,
) -> str | type[Any]:
    resource_info = RESOURCE_MAP[resource]
    request_target = resource_info[action]
    if isinstance(request_target, dict):
        if not kind:
            raise RuntimeError(f"{resource} {action} requires --kind.")
        if kind not in request_target:
            raise RuntimeError(
                f"Unsupported kind '{kind}'. Supported: {', '.join(sorted(request_target))}"
        )
        request_target = request_target[kind]
    return request_target


def build_request(resource: str, action: str, payload: dict[str, Any], kind: str | None = None) -> Any:
    request_target = resolve_request_target(resource, action, kind=kind)
    request_cls = import_string(request_target) if isinstance(request_target, str) else request_target
    return request_cls(**payload)


def extract_ids(items: Any) -> list[Any]:
    if not isinstance(items, list):
        return []
    result: list[Any] = []
    for item in items:
        if isinstance(item, dict):
            item_id = item.get("id")
            if item_id is None:
                raise RuntimeError("Expected list items with an 'id' field.")
            result.append(item_id)
        else:
            result.append(item)
    return result


def extract_object_id(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("id")
    return value


def extract_choice_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def extract_scalar(
    value: Any,
    preferred_keys: tuple[str, ...] = ("value", "username", "name", "id"),
) -> Any:
    if isinstance(value, dict):
        for key in preferred_keys:
            if key in value and value[key] not in {None, ""}:
                return value[key]
        if len(value) == 1:
            return next(iter(value.values()))
    return value


def extract_scalar_list(
    items: Any,
    preferred_keys: tuple[str, ...] = ("value", "username", "name", "id"),
) -> list[Any]:
    if not isinstance(items, list):
        return []
    return [extract_scalar(item, preferred_keys) for item in items]


def sanitize_preview(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            key: ("<redacted>" if key in SENSITIVE_FIELDS else sanitize_preview(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_preview(item) for item in value]
    return value


def build_diff(current: dict[str, Any], proposed: dict[str, Any]) -> str:
    current_text = json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True)
    proposed_text = json.dumps(proposed, ensure_ascii=False, indent=2, sort_keys=True)
    return "\n".join(
        difflib.unified_diff(
            current_text.splitlines(),
            proposed_text.splitlines(),
            fromfile="current",
            tofile="proposed",
            lineterm="",
        )
    )


def build_target_summary(current: dict[str, Any]) -> dict[str, Any]:
    target = {"id": current.get("id"), "name": current.get("name")}
    if "username" in current:
        target["username"] = current.get("username")
    if "address" in current:
        target["address"] = current.get("address")
    return target


def normalize_asset_kind(value: Any) -> str | None:
    raw = str(extract_choice_value(value) or "").strip().lower().replace("_", "-")
    return ASSET_KIND_ALIASES.get(raw)


def infer_asset_kind(current: dict[str, Any]) -> str | None:
    if "db_name" in current:
        return "database"
    if any(
        key in current
        for key in ("autofill", "username_selector", "password_selector", "submit_selector", "script")
    ):
        return "web"

    for key in ("type", "category"):
        inferred = normalize_asset_kind(current.get(key))
        if inferred:
            return inferred
    return None


def resolve_asset_kind(kind: str | None, current: dict[str, Any]) -> str:
    resolved = normalize_asset_kind(kind) if kind else infer_asset_kind(current)
    if not resolved:
        raise RuntimeError(
            "Asset preview/update requires --kind "
            "(host, database, device, cloud, web)."
        )
    return resolved


def parse_update_payload(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "need_update_password", False) and not getattr(args, "password", None):
        raise RuntimeError("--need-update-password requires --password.")

    payload = parse_json_arg(getattr(args, "payload", None))
    if args.resource == "user":
        if not payload and not getattr(args, "password", None):
            raise RuntimeError("User update requires --payload, --password, or both.")
        return payload

    if not payload:
        raise RuntimeError(f"{args.resource} update requires --payload.")
    return payload


def parse_create_payload(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "need_update_password", False) and not getattr(args, "password", None):
        raise RuntimeError("--need-update-password requires --password.")

    payload = parse_json_arg(getattr(args, "payload", None))
    if args.resource != "user":
        if getattr(args, "password", None) or getattr(args, "need_update_password", False):
            raise RuntimeError("Create password options are only supported for --resource user.")
        return payload

    if {"auth_strategy", "password", "password_strategy", "need_update_password"} & payload.keys():
        raise RuntimeError(
            "User create password fields must use --password/--need-update-password, not --payload."
        )
    return payload


def build_user_create_payload_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "need_update_password", False) and not getattr(args, "password", None):
        raise RuntimeError("--need-update-password requires --password.")

    payload: dict[str, Any] = {
        "name": args.name,
        "username": args.username,
        "email": args.email,
        "is_active": not getattr(args, "inactive", False),
    }

    if getattr(args, "comment", None):
        payload["comment"] = args.comment
    if getattr(args, "system_role_ids", None):
        payload["system_roles"] = list(args.system_role_ids)
    if getattr(args, "org_role_ids", None):
        payload["org_roles"] = list(args.org_role_ids)
    if getattr(args, "group_ids", None):
        payload["groups"] = list(args.group_ids)
    if getattr(args, "mfa_level", None):
        payload["mfa_level"] = args.mfa_level
    if getattr(args, "source", None):
        payload["source"] = args.source
    if getattr(args, "phone", None):
        payload["phone"] = args.phone
    if getattr(args, "wechat", None):
        payload["wechat"] = args.wechat
    if getattr(args, "date_expired", None):
        payload["date_expired"] = args.date_expired
    return payload


def build_user_create_namespace(args: argparse.Namespace) -> argparse.Namespace:
    payload = build_user_create_payload_from_args(args)
    return argparse.Namespace(
        resource="user",
        kind=None,
        payload=json.dumps(payload, ensure_ascii=False),
        password=args.password,
        need_update_password=args.need_update_password,
    )


def build_user_base_payload(current: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": current["name"],
        "username": current["username"],
        "email": current["email"],
        "comment": current.get("comment", ""),
        "is_active": current.get("is_active", True),
        "groups": extract_ids(current.get("groups", [])),
        "system_roles": extract_ids(current.get("system_roles", [])),
        "org_roles": extract_ids(current.get("org_roles", [])),
    }

    date_expired = current.get("date_expired")
    if date_expired:
        payload["date_expired"] = date_expired

    mfa_level = extract_choice_value(current.get("mfa_level"))
    if mfa_level is not None:
        payload["mfa_level"] = str(mfa_level)

    source = extract_choice_value(current.get("source"))
    if source:
        payload["source"] = source

    phone = current.get("phone")
    if phone:
        payload["phone"] = phone

    wechat = current.get("wechat")
    if wechat:
        payload["wechat"] = wechat

    return payload


def build_user_update_payload(
    current: dict[str, Any],
    patch: dict[str, Any],
    password: str | None,
    need_update_password: bool,
) -> dict[str, Any]:
    payload = build_user_base_payload(current)
    payload.update(patch)
    if password:
        payload["password_strategy"] = "custom"
        payload["password"] = password
        payload["need_update_password"] = need_update_password
    return payload


def build_asset_base_payload(current: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": current["name"],
        "address": current["address"],
        "platform": extract_object_id(current.get("platform")) or "",
        "is_active": current.get("is_active", True),
        "comment": current.get("comment", ""),
    }

    domain_id = extract_object_id(current.get("domain"))
    if domain_id:
        payload["domain"] = domain_id
    if "nodes" in current:
        payload["nodes"] = extract_ids(current.get("nodes", []))
    if "protocols" in current:
        payload["protocols"] = current.get("protocols", [])
    if "labels" in current:
        payload["labels"] = extract_scalar_list(current.get("labels", []))
    return payload


def build_database_base_payload(current: dict[str, Any]) -> dict[str, Any]:
    payload = build_asset_base_payload(current)
    spec_info = current.get("spec_info") if isinstance(current.get("spec_info"), dict) else {}

    if "db_name" in current:
        payload["db_name"] = current.get("db_name")
    elif "db_name" in spec_info:
        payload["db_name"] = spec_info.get("db_name")
    else:
        raise RuntimeError("Database detail does not include 'db_name'.")

    for key in ("use_ssl", "allow_invalid_cert"):
        if key in current:
            payload[key] = bool(current.get(key, False))
        elif key in spec_info:
            payload[key] = bool(spec_info.get(key, False))

    for key in ("ca_cert", "client_cert", "client_key"):
        if current.get(key):
            payload[key] = current[key]
        elif spec_info.get(key):
            payload[key] = spec_info[key]

    pg_ssl_mode = extract_choice_value(current.get("pg_ssl_mode"))
    if pg_ssl_mode in {None, ""} and "pg_ssl_mode" in spec_info:
        pg_ssl_mode = extract_choice_value(spec_info.get("pg_ssl_mode"))
    if pg_ssl_mode not in {None, ""}:
        payload["pg_ssl_mode"] = pg_ssl_mode
    return payload


def build_web_base_payload(current: dict[str, Any]) -> dict[str, Any]:
    payload = build_asset_base_payload(current)
    payload["autofill"] = current.get("autofill", "basic")
    payload["username_selector"] = current.get("username_selector", "name=username")
    payload["password_selector"] = current.get("password_selector", "name=password")
    payload["submit_selector"] = current.get("submit_selector", "id=login_button")
    if "script" in current:
        payload["script"] = current.get("script", [])
    return payload


def build_platform_base_payload(current: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": current["name"],
        "type": extract_choice_value(current.get("type")),
        "category": extract_choice_value(current.get("category")),
        "comment": current.get("comment", ""),
        "domain_enabled": current.get("domain_enabled", True),
    }

    charset = extract_choice_value(current.get("charset"))
    if charset is not None:
        payload["charset"] = charset
    if "protocols" in current:
        payload["protocols"] = normalize_platform_protocols(current.get("protocols", []))
    if "automation" in current:
        payload["automation"] = normalize_platform_automation(current.get("automation", {}))
    su_method = extract_choice_value(current.get("su_method"))
    if su_method not in {None, ""}:
        payload["su_enabled"] = bool(current.get("su_enabled", False))
        payload["su_method"] = su_method
    return payload


def build_account_base_payload(current: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "username": current["username"],
        "asset": extract_object_id(current.get("asset")),
        "name": current["name"],
        "is_active": current.get("is_active", True),
        "privileged": current.get("privileged", False),
        "comment": current.get("comment", ""),
    }

    secret_type = extract_choice_value(current.get("secret_type"))
    if secret_type:
        payload["secret_type"] = secret_type
    su_from = extract_object_id(current.get("su_from"))
    if su_from:
        payload["su_from"] = su_from
    if "params" in current:
        payload["params"] = current.get("params", {})
    if "push_now" in current:
        payload["push_now"] = bool(current.get("push_now", False))
    return payload


def build_node_base_payload(current: dict[str, Any]) -> dict[str, Any]:
    return {"value": current.get("value", "")}


def build_user_group_base_payload(current: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "name": current["name"],
        "comment": current.get("comment", ""),
    }
    if "users" in current:
        payload["users"] = extract_ids(current.get("users", []))
    return payload


def build_organization_base_payload(current: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": current["name"],
        "comment": current.get("comment", ""),
    }


def build_update_base_payload(
    resource: str,
    current: dict[str, Any],
    kind: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    if resource == "asset":
        resolved_kind = resolve_asset_kind(kind, current)
        builder = {
            "host": build_asset_base_payload,
            "database": build_database_base_payload,
            "device": build_asset_base_payload,
            "cloud": build_asset_base_payload,
            "web": build_web_base_payload,
        }[resolved_kind]
        return builder(current), resolved_kind
    if resource == "user":
        return build_user_base_payload(current), None
    if resource == "platform":
        return build_platform_base_payload(current), None
    if resource == "account":
        return build_account_base_payload(current), None
    if resource == "node":
        return build_node_base_payload(current), None
    if resource == "user-group":
        return build_user_group_base_payload(current), None
    if resource == "organization":
        return build_organization_base_payload(current), None
    raise RuntimeError(f"Unsupported resource '{resource}'.")


def format_change_line(field: str, before: Any, after: Any) -> str:
    return f"{field}: {before!r} -> {after!r}"


def _node_api_request(
    method: str,
    *,
    node_id: str | None = None,
    params: dict[str, Any] | None = None,
    org_id: str | None = None,
) -> Any:
    def execute_request() -> Any:
        client = create_client()
        path = NODE_API_PATH if node_id is None else f"{NODE_API_PATH}{node_id}/"
        response = client.client.request(path, method, params=params)
        if response.status_code >= 400:
            try:
                error = response.json()
            except ValueError:
                error = response.text.strip() or f"HTTP {response.status_code}"
            raise RuntimeError(str(error))
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"Node API returned invalid JSON for '{path}'.") from exc

    if org_id:
        with temporary_org_client(org_id):
            return execute_request()
    return execute_request()


def _normalize_node_query(payload: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None or value == "":
            continue
        params["id" if key == "id_" else key] = value
    return params


def _extract_node_org_context(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    normalized_payload = _normalize_node_query(payload)
    org_id = str(normalized_payload.pop("org_id", "") or "").strip() or None
    return org_id, normalized_payload


def normalize_node_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("Node API did not return an object.")
    node = serialize(value)
    if not node.get("name") and node.get("value"):
        node["name"] = node["value"]
    return node


def list_node_objects(payload: dict[str, Any]) -> list[dict[str, Any]]:
    org_id, normalized_payload = _extract_node_org_context(payload)
    if "limit" in normalized_payload or "offset" in normalized_payload:
        result = _node_api_request("get", params=normalized_payload, org_id=org_id)
        if isinstance(result, dict) and "results" in result:
            results = result.get("results", [])
            if not isinstance(results, list):
                raise RuntimeError("Node list API results field is not a list.")
            return [normalize_node_object(item) for item in results]
        if isinstance(result, list):
            return [normalize_node_object(item) for item in result]
        raise RuntimeError("Node list API did not return a list.")

    page_size = 200
    page_offset = 0
    combined: list[dict[str, Any]] = []
    while True:
        page_payload = dict(normalized_payload)
        page_payload["limit"] = page_size
        page_payload["offset"] = page_offset
        result = _node_api_request("get", params=page_payload, org_id=org_id)
        if isinstance(result, dict) and "results" in result:
            results = result.get("results", [])
            if not isinstance(results, list):
                raise RuntimeError("Node list API results field is not a list.")
            batch = [normalize_node_object(item) for item in results]
        elif isinstance(result, list):
            batch = [normalize_node_object(item) for item in result]
        else:
            raise RuntimeError("Node list API did not return a list.")
        combined.extend(batch)
        if len(batch) < page_size:
            break
        page_offset += len(batch)
    return combined


def get_node_object(node_id: str, *, org_id: str | None = None) -> dict[str, Any]:
    result = _node_api_request("get", node_id=node_id, org_id=org_id)
    return normalize_node_object(result)


def normalize_platform_protocol(protocol: Any) -> dict[str, Any]:
    if not isinstance(protocol, dict):
        raise RuntimeError("Platform protocols must be objects.")
    normalized = {
        "name": protocol["name"],
        "port": protocol["port"],
    }
    for key in ("default", "required", "public", "secret_types", "setting", "xpack"):
        if key in protocol:
            normalized[key] = protocol[key]
    if "port_from_attr" in protocol:
        normalized["port_from_attr"] = protocol["port_from_attr"]
    elif "port_from_addr" in protocol:
        normalized["port_from_attr"] = protocol["port_from_addr"]
    return normalized


def normalize_platform_protocols(protocols: Any) -> list[dict[str, Any]]:
    if not isinstance(protocols, list):
        return []
    return [normalize_platform_protocol(protocol) for protocol in protocols]


def normalize_platform_automation(automation: Any) -> dict[str, Any]:
    if not isinstance(automation, dict):
        return {}
    normalized = dict(automation)
    normalized.pop("id", None)
    return normalized


def build_platform_protocol_param(type_value: str, protocols: Any) -> Any | None:
    normalized = normalize_platform_protocols(protocols)
    if not normalized:
        return None
    protocol_param_cls = import_string(PLATFORM_PROTOCOL_PARAM_CLASS)
    protocol_param = protocol_param_cls(type_value)
    protocol_param._pre_check = False
    protocol_param._protocols = normalized
    return protocol_param


def build_platform_automation_param(type_value: str, automation: Any) -> Any | None:
    normalized = normalize_platform_automation(automation)
    if not normalized:
        return None
    automation_param_cls = import_string(PLATFORM_AUTOMATION_PARAM_CLASS)
    automation_param = automation_param_cls(type_value)
    automation_param._automation = normalized
    return automation_param


def build_platform_su_param(type_value: str, payload: dict[str, Any]) -> Any | None:
    if "su_enabled" not in payload and "su_method" not in payload:
        return None
    su_enabled = bool(payload.get("su_enabled", False))
    su_method = str(extract_choice_value(payload.get("su_method")) or "").strip()
    if not su_enabled and not su_method:
        return None
    if su_enabled and not su_method:
        raise RuntimeError("Platform request with su_enabled=true requires a non-empty 'su_method'.")
    su_param_cls = import_string(PLATFORM_SU_PARAM_CLASS)
    su_param = su_param_cls(type_value)
    su_param._su_info = {
        "su_enabled": su_enabled,
        "su_method": su_method,
    }
    return su_param


def build_platform_request_payload(
    payload: dict[str, Any],
    object_id: str | None = None,
) -> dict[str, Any]:
    type_value = str(extract_choice_value(payload.get("type")) or "").strip()
    if not type_value:
        raise RuntimeError("Platform request requires a non-empty 'type'.")

    request_payload: dict[str, Any] = {
        "name": payload["name"],
        "type": type_value,
        "charset": extract_choice_value(payload.get("charset")) or "utf-8",
        "domain_enabled": bool(payload.get("domain_enabled", True)),
        "comment": payload.get("comment", ""),
    }
    if object_id:
        request_payload["id_"] = object_id

    protocols = build_platform_protocol_param(type_value, payload.get("protocols"))
    if protocols is not None:
        request_payload["protocols"] = protocols

    automation = build_platform_automation_param(type_value, payload.get("automation"))
    if automation is not None:
        request_payload["automation"] = automation

    su = build_platform_su_param(type_value, payload)
    if su is not None:
        request_payload["su"] = su

    return request_payload


def lookup_created_node(payload: dict[str, Any], create_result: Any) -> dict[str, Any]:
    full_value = str(payload.get("full_value") or "").strip()
    org_id = str(payload.get("org_id") or "").strip() or None
    lookup_value = ""
    if isinstance(create_result, str) and create_result:
        lookup_value = create_result
    elif payload.get("value"):
        lookup_value = str(payload["value"]).strip()
    elif full_value:
        lookup_value = full_value.strip("/").rsplit("/", 1)[-1]

    if not lookup_value:
        raise RuntimeError("Node create succeeded but could not derive a lookup value.")

    expected_suffix = ""
    if full_value:
        expected_suffix = full_value if full_value.startswith("/") else f"/{full_value}"

    last_error = ""
    for _ in range(5):
        matches = list_node_objects({"value": lookup_value, "org_id": org_id})
        if expected_suffix:
            exact = [
                item for item in matches if str(item.get("full_value", "")).endswith(expected_suffix)
            ]
            if exact:
                matches = exact
        if len(matches) == 1:
            return matches[0]
        last_error = f"Expected one node for value '{lookup_value}', got {len(matches)}."
        time.sleep(0.1)

    raise RuntimeError(last_error)


def normalize_lookup_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload = parse_json_arg(args.filters)
    if args.id:
        payload["id_"] = args.id
    if args.name and args.resource not in {"node", "account"}:
        payload["name"] = args.name
    if args.resource == "account" and args.name:
        payload["username"] = args.name
    if args.resource == "node" and args.name:
        payload["value"] = args.name
    if args.resource == "user-group" and args.name:
        payload["name"] = args.name
    return payload


def run_paginated_list_request(resource: str, payload: dict[str, Any]) -> list[Any]:
    if "limit" in payload or "offset" in payload:
        result = run_request(build_request(resource, "list", payload), with_model=True)
        if not isinstance(result, list):
            raise RuntimeError(f"{resource} list API did not return a list.")
        return [serialize(item) for item in result]

    page_size = 200
    page_offset = 0
    combined: list[Any] = []
    while True:
        page_payload = dict(payload)
        page_payload["limit"] = page_size
        page_payload["offset"] = page_offset
        result = run_request(build_request(resource, "list", page_payload), with_model=True)
        if not isinstance(result, list):
            raise RuntimeError(f"{resource} list API did not return a list.")
        batch = [serialize(item) for item in result]
        combined.extend(batch)
        if len(batch) < page_size:
            break
        page_offset += len(batch)
    return combined


def list_objects(args: argparse.Namespace) -> Any:
    payload = normalize_lookup_payload(args)
    if args.resource == "node":
        return list_node_objects(payload)
    return run_paginated_list_request(args.resource, payload)


def list_platform_objects(payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return run_paginated_list_request("platform", payload or {})


def _summarize_platform_candidate(item: dict[str, Any]) -> dict[str, Any]:
    platform_type = item.get("type")
    type_value = extract_choice_value(platform_type)
    if isinstance(platform_type, dict):
        type_label = platform_type.get("label")
    elif platform_type is None:
        type_label = None
    else:
        type_label = str(platform_type)
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "type": {
            "value": type_value,
            "label": type_label,
        },
    }


def _format_platform_type(candidate: dict[str, Any]) -> str:
    platform_type = candidate.get("type")
    if isinstance(platform_type, dict):
        label = str(platform_type.get("label") or "").strip()
        value = str(platform_type.get("value") or "").strip()
        if label:
            return label
        if value:
            return value
    elif platform_type is not None:
        text = str(platform_type).strip()
        if text:
            return text
    return "-"


def _format_platform_candidates(candidates: list[dict[str, Any]]) -> str:
    return ", ".join(
        f"{item.get('id')}:{item.get('name')} [type={_format_platform_type(item)}]"
        for item in candidates
    )


def _collect_platform_type_matches(
    platforms: list[dict[str, Any]],
    folded: str,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    for item in platforms:
        platform_type = item.get("type")
        candidates = [extract_choice_value(platform_type)]
        if isinstance(platform_type, dict):
            candidates.append(platform_type.get("label"))
        elif platform_type is not None:
            candidates.append(platform_type)
        if not any(str(candidate).strip().casefold() == folded for candidate in candidates if candidate is not None):
            continue
        item_id = item.get("id")
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        matches.append(_summarize_platform_candidate(item))
    return matches


def resolve_platform_reference(value: Any) -> dict[str, Any]:
    raw = extract_scalar(value, preferred_keys=("id", "value", "name", "label"))
    if raw is None or raw == "":
        return {
            "input": raw,
            "status": "not_found",
            "match_mode": "none",
            "resolved_id": None,
            "resolved": None,
            "exact_name_matches": [],
            "type_matches": [],
            "message": "Platform value is empty. Pass a platform ID or an exact platform name.",
        }
    if isinstance(raw, int):
        return {
            "input": raw,
            "status": "resolved",
            "match_mode": "id",
            "resolved_id": raw,
            "resolved": {"id": raw},
            "exact_name_matches": [],
            "type_matches": [],
            "message": f"Platform input '{raw}' was treated as platform ID {raw}.",
        }
    text = str(raw).strip()
    if not text:
        return {
            "input": text,
            "status": "not_found",
            "match_mode": "none",
            "resolved_id": None,
            "resolved": None,
            "exact_name_matches": [],
            "type_matches": [],
            "message": "Platform value is empty. Pass a platform ID or an exact platform name.",
        }
    if text.isdigit():
        resolved_id = int(text)
        return {
            "input": text,
            "status": "resolved",
            "match_mode": "id",
            "resolved_id": resolved_id,
            "resolved": {"id": resolved_id},
            "exact_name_matches": [],
            "type_matches": [],
            "message": f"Platform input '{text}' was treated as platform ID {resolved_id}.",
        }

    platforms = list_platform_objects()
    folded = text.casefold()
    exact_name_matches = [
        _summarize_platform_candidate(item)
        for item in platforms
        if str(item.get("name") or "").strip().casefold() == folded
    ]
    if len(exact_name_matches) == 1:
        resolved = exact_name_matches[0]
        return {
            "input": text,
            "status": "resolved",
            "match_mode": "exact_name",
            "resolved_id": resolved.get("id"),
            "resolved": resolved,
            "exact_name_matches": exact_name_matches,
            "type_matches": [],
            "message": f"Platform name '{text}' resolved to {resolved.get('id')}:{resolved.get('name')}.",
        }
    if len(exact_name_matches) > 1:
        return {
            "input": text,
            "status": "ambiguous",
            "match_mode": "exact_name",
            "resolved_id": None,
            "resolved": None,
            "exact_name_matches": exact_name_matches,
            "type_matches": [],
            "message": (
                f"Platform name '{text}' matched multiple platforms. "
                f"Please choose one by ID or exact platform name: "
                f"{_format_platform_candidates(exact_name_matches)}"
            ),
        }

    type_matches = _collect_platform_type_matches(platforms, folded)
    if type_matches:
        return {
            "input": text,
            "status": "ambiguous",
            "match_mode": "type_hint",
            "resolved_id": None,
            "resolved": None,
            "exact_name_matches": [],
            "type_matches": type_matches,
            "message": (
                f"Platform '{text}' did not match a unique platform name. "
                f"It matched platform type '{text}'. "
                f"Please choose one platform by ID or exact platform name: "
                f"{_format_platform_candidates(type_matches)}"
            ),
        }

    return {
        "input": text,
        "status": "not_found",
        "match_mode": "none",
        "resolved_id": None,
        "resolved": None,
        "exact_name_matches": [],
        "type_matches": [],
        "message": (
            f"Platform '{text}' was not found. "
            "Please pass a platform ID or an existing exact platform name."
        ),
    }


def resolve_platform_id(value: Any) -> Any:
    raw = extract_scalar(value, preferred_keys=("id", "value", "name", "label"))
    if raw is None or raw == "":
        return raw
    result = resolve_platform_reference(raw)
    if result["status"] == "resolved":
        return result["resolved_id"]
    raise RuntimeError(result["message"])


def normalize_asset_payload_for_request(payload: dict[str, Any]) -> dict[str, Any]:
    request_payload = dict(payload)
    if "platform" in request_payload:
        request_payload["platform"] = resolve_platform_id(request_payload.get("platform"))
    return request_payload


def get_object(args: argparse.Namespace) -> Any:
    payload: dict[str, Any] = {}
    if not args.id:
        raise RuntimeError("Detail lookup requires --id.")
    payload["id_"] = args.id
    if args.resource == "node":
        return get_node_object(args.id)
    request = build_request(args.resource, "detail", payload)
    return run_request(request, with_model=True)


def build_create_request(
    resource: str,
    payload: dict[str, Any],
    kind: str | None = None,
    password: str | None = None,
    need_update_password: bool = False,
) -> Any:
    request_payload = dict(payload)
    if resource == "asset":
        request_payload = normalize_asset_payload_for_request(request_payload)
    if resource == "user" and password:
        auth_strategy_cls = import_string(USER_AUTH_STRATEGY_CLASS)
        auth_strategy = auth_strategy_cls()
        auth_strategy.set_password(password, need_update=need_update_password)
        request_payload["auth_strategy"] = auth_strategy
    request_target = resolve_request_target(resource, "create", kind=kind)
    if resource == "platform":
        return build_request_instance(request_target, build_platform_request_payload(request_payload))
    return build_request_instance(request_target, request_payload)


def build_create_preview_body(request: Any, fallback: dict[str, Any]) -> Any:
    body = getattr(request, "_body", None)
    if isinstance(body, dict):
        return sanitize_preview(body)
    return sanitize_preview(fallback)


def resolve_target_org() -> dict[str, Any]:
    context = resolve_effective_org_context()
    effective_org = context.get("effective_org")
    if not isinstance(effective_org, dict):
        return {"id": "", "name": "", "source": "unselected"}
    return {
        "id": effective_org.get("id", ""),
        "name": effective_org.get("name", ""),
        "source": effective_org.get("source", "selected"),
    }


def prepare_create_context(args: argparse.Namespace) -> tuple[Any, Any, str | None]:
    payload = parse_create_payload(args)
    request = build_create_request(
        args.resource,
        payload,
        kind=getattr(args, "kind", None),
        password=getattr(args, "password", None),
        need_update_password=getattr(args, "need_update_password", False),
    )
    return request, build_create_preview_body(request, payload), getattr(args, "kind", None)


def preview_create(args: argparse.Namespace) -> Any:
    _, proposed, resolved_kind = prepare_create_context(args)
    result: dict[str, Any] = {
        "kind": resolved_kind,
        "proposed": proposed,
    }
    if args.resource == "user":
        result["target_org"] = resolve_target_org()
    return result


def create_object(args: argparse.Namespace) -> Any:
    request, _, _ = prepare_create_context(args)
    result = run_request(request, with_model=True)
    if args.resource == "node":
        return lookup_created_node(parse_create_payload(args), serialize(result))
    return result


def preview_create_user(args: argparse.Namespace) -> Any:
    return preview_create(build_user_create_namespace(args))


def create_user(args: argparse.Namespace) -> Any:
    return create_object(build_user_create_namespace(args))


def fetch_current(resource: str, object_id: str, kind: str | None = None) -> Any:
    if resource == "node":
        return get_node_object(object_id)
    if resource == "asset" and kind:
        request = build_request_instance(ASSET_DETAIL_MAP[kind], {"id_": object_id})
    else:
        request = build_request(resource, "detail", {"id_": object_id})
    return run_request(request, with_model=True)


def prepare_update_context(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str | None]:
    if not args.id:
        raise RuntimeError("Update preview requires --id.")
    patch = parse_update_payload(args)
    current = serialize(fetch_current(args.resource, args.id))
    if args.resource == "asset":
        resolved_kind = resolve_asset_kind(getattr(args, "kind", None), current)
        if resolved_kind == "database" or getattr(args, "kind", None) != resolved_kind:
            current = serialize(fetch_current(args.resource, args.id, kind=resolved_kind))
        current_payload, resolved_kind = build_update_base_payload(
            args.resource,
            current,
            resolved_kind,
        )
    else:
        current_payload, resolved_kind = build_update_base_payload(
            args.resource,
            current,
            getattr(args, "kind", None),
        )

    proposed_payload = dict(current_payload)
    proposed_payload.update(patch)
    if args.resource == "user" and args.password:
        proposed_payload = build_user_update_payload(
            current,
            patch,
            args.password,
            args.need_update_password,
        )
    elif args.resource == "asset":
        proposed_payload = normalize_asset_payload_for_request(proposed_payload)

    return current, current_payload, proposed_payload, resolved_kind


def preview_update(args: argparse.Namespace) -> Any:
    current, current_payload, proposed_payload, resolved_kind = prepare_update_context(args)
    current_preview = sanitize_preview(current_payload)
    proposed_preview = sanitize_preview(proposed_payload)
    return {
        "target": build_target_summary(current),
        "kind": resolved_kind,
        "current": current_preview,
        "proposed": proposed_preview,
        "diff": build_diff(current_preview, proposed_preview),
    }


def build_update_request(
    resource: str,
    object_id: str,
    payload: dict[str, Any],
    kind: str | None = None,
) -> Any:
    if resource == "platform":
        request_cls = RESOURCE_MAP[resource]["update"]
        return build_request_instance(request_cls, build_platform_request_payload(payload, object_id))
    request_payload = dict(payload)
    body_payload = dict(payload)
    if resource == "asset":
        request_payload = normalize_asset_payload_for_request(request_payload)
        body_payload = normalize_asset_payload_for_request(body_payload)
    request_payload["id_"] = object_id
    request_cls = RESOURCE_MAP[resource]["update"]
    if isinstance(request_cls, dict):
        if not kind:
            raise RuntimeError(f"{resource} update requires --kind.")
        request_cls = request_cls[kind]
    return build_request_instance(request_cls, request_payload, body_override=body_payload)


def update_object(args: argparse.Namespace) -> Any:
    require_confirmation(args)
    if not args.id:
        raise RuntimeError("Update requires --id.")
    _, _, payload, resolved_kind = prepare_update_context(args)
    request = build_update_request(args.resource, args.id, payload, resolved_kind)
    return run_request(request, with_model=True)


def preview_delete(args: argparse.Namespace) -> Any:
    if not args.id:
        raise RuntimeError("Delete preview requires --id.")
    current = serialize(fetch_current(args.resource, args.id))
    return {"target": current, "message": "Review the object before deleting it."}


def delete_object(args: argparse.Namespace) -> Any:
    require_confirmation(args)
    if not args.id:
        raise RuntimeError("Delete requires --id.")
    request = build_request(args.resource, "delete", {"id_": args.id})
    return run_request(request, with_model=True)


def preview_unblock_user(args: argparse.Namespace) -> Any:
    if args.resource != "user":
        raise RuntimeError("Unblock is only supported for --resource user.")
    current = serialize(fetch_current(args.resource, args.id))
    return {
        "target": {
            "id": current.get("id"),
            "name": current.get("name"),
            "username": current.get("username"),
        },
        "changes": [
            format_change_line(
                "login_blocked",
                bool(current.get("login_blocked", False)),
                False,
            )
        ],
    }


def unblock_user(args: argparse.Namespace) -> Any:
    require_confirmation(args)
    if args.resource != "user":
        raise RuntimeError("Unblock is only supported for --resource user.")
    before = serialize(fetch_current(args.resource, args.id))
    if not before.get("login_blocked", False):
        return {
            "changed": False,
            "target": {
                "id": before.get("id"),
                "name": before.get("name"),
                "username": before.get("username"),
            },
            "before": {
                "login_blocked": before.get("login_blocked", False),
            },
            "after": {
                "login_blocked": before.get("login_blocked", False),
            },
            "message": "User is already unblocked.",
        }

    run_request(UnblockUserRequest(id_=args.id), with_model=True)
    after = serialize(fetch_current(args.resource, args.id))
    return {
        "changed": before.get("login_blocked") != after.get("login_blocked"),
        "target": {
            "id": after.get("id"),
            "name": after.get("name"),
            "username": after.get("username"),
        },
        "before": {
            "login_blocked": before.get("login_blocked", False),
        },
        "after": {
            "login_blocked": after.get("login_blocked", False),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    resources = sorted(RESOURCE_MAP)

    def add_resource(p: argparse.ArgumentParser) -> None:
        p.add_argument("--resource", required=True, choices=resources)

    def add_create_args(p: argparse.ArgumentParser) -> None:
        add_resource(p)
        p.add_argument("--kind", help="Required for asset create")
        p.add_argument("--payload", required=True, help="JSON create payload")
        p.add_argument("--password", help="Password to set for user creates")
        p.add_argument(
            "--need-update-password",
            action="store_true",
            help="Require the user to change the password on next login",
        )

    def add_user_create_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--name", required=True)
        p.add_argument("--username", required=True)
        p.add_argument("--email", required=True)
        p.add_argument("--password", required=True, help="Password to set for the new user")
        p.add_argument(
            "--system-role-id",
            dest="system_role_ids",
            action="append",
            help="System role ID to attach during user creation; repeat for multiple roles",
        )
        p.add_argument(
            "--org-role-id",
            dest="org_role_ids",
            action="append",
            help="Organization role ID to attach during user creation; repeat for multiple roles",
        )
        p.add_argument(
            "--group-id",
            dest="group_ids",
            action="append",
            help="User group ID to attach during user creation; repeat for multiple groups",
        )
        p.add_argument("--comment")
        p.add_argument(
            "--need-update-password",
            action="store_true",
            help="Require the user to change the password on next login",
        )
        p.add_argument(
            "--inactive",
            action="store_true",
            help="Create the user in an inactive state",
        )
        p.add_argument("--mfa-level")
        p.add_argument("--source")
        p.add_argument("--phone")
        p.add_argument("--wechat")
        p.add_argument("--date-expired")

    list_parser = subparsers.add_parser("list")
    add_resource(list_parser)
    list_parser.add_argument("--id")
    list_parser.add_argument("--name")
    list_parser.add_argument("--filters", help="JSON filter object")
    list_parser.set_defaults(func=list_objects)

    get_parser = subparsers.add_parser("get")
    add_resource(get_parser)
    get_parser.add_argument("--id", required=True)
    get_parser.set_defaults(func=get_object)

    preview_create_parser = subparsers.add_parser("preview-create")
    add_create_args(preview_create_parser)
    preview_create_parser.set_defaults(func=preview_create)

    create_parser = subparsers.add_parser("create")
    add_create_args(create_parser)
    create_parser.set_defaults(func=create_object)

    preview_create_user_parser = subparsers.add_parser("preview-create-user")
    add_user_create_args(preview_create_user_parser)
    preview_create_user_parser.set_defaults(func=preview_create_user)

    create_user_parser = subparsers.add_parser("create-user")
    add_user_create_args(create_user_parser)
    create_user_parser.set_defaults(func=create_user)

    preview_update_parser = subparsers.add_parser("preview-update")
    add_resource(preview_update_parser)
    preview_update_parser.add_argument("--id", required=True)
    preview_update_parser.add_argument(
        "--kind",
        help="Required for asset preview/update when kind cannot be inferred",
    )
    preview_update_parser.add_argument("--payload", help="JSON patch payload")
    preview_update_parser.add_argument("--password", help="Password to set for user updates")
    preview_update_parser.add_argument(
        "--need-update-password",
        action="store_true",
        help="Require the user to change the password on next login",
    )
    preview_update_parser.set_defaults(func=preview_update)

    update_parser = subparsers.add_parser("update")
    add_resource(update_parser)
    update_parser.add_argument("--id", required=True)
    update_parser.add_argument("--kind", help="Required for asset update")
    update_parser.add_argument("--payload", help="JSON update payload")
    update_parser.add_argument("--password", help="Password to set for user updates")
    update_parser.add_argument(
        "--need-update-password",
        action="store_true",
        help="Require the user to change the password on next login",
    )
    update_parser.add_argument("--confirm", action="store_true")
    update_parser.set_defaults(func=update_object)

    preview_unblock_parser = subparsers.add_parser("preview-unblock")
    add_resource(preview_unblock_parser)
    preview_unblock_parser.add_argument("--id", required=True)
    preview_unblock_parser.set_defaults(func=preview_unblock_user)

    unblock_parser = subparsers.add_parser("unblock")
    add_resource(unblock_parser)
    unblock_parser.add_argument("--id", required=True)
    unblock_parser.add_argument("--confirm", action="store_true")
    unblock_parser.set_defaults(func=unblock_user)

    preview_delete_parser = subparsers.add_parser("preview-delete")
    add_resource(preview_delete_parser)
    preview_delete_parser.add_argument("--id", required=True)
    preview_delete_parser.set_defaults(func=preview_delete)

    delete_parser = subparsers.add_parser("delete")
    add_resource(delete_parser)
    delete_parser.add_argument("--id", required=True)
    delete_parser.add_argument("--confirm", action="store_true")
    delete_parser.set_defaults(func=delete_object)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    original = args.func

    def guarded(ns: argparse.Namespace, _func=original):
        ensure_selected_org_context()
        return _func(ns)

    args.func = guarded
    return run_and_print(args.func, args)


if __name__ == "__main__":
    raise SystemExit(main())
