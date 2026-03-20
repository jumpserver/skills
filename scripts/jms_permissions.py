#!/usr/bin/env python3
"""JumpServer permission and authorization operations."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from jms_bootstrap import bootstrap_runtime

bootstrap_runtime()

import argparse
import difflib
import json
import re
from typing import Any

from jms_assets import build_request, get_node_object, list_node_objects, run_paginated_list_request
from jms_runtime import (
    ORG_SELECTION_NEXT_STEP,
    StructuredActionError,
    build_request_instance,
    ensure_selected_org_context,
    import_string,
    parse_json_arg,
    require_confirmation,
    resolve_effective_org_context,
    run_and_print,
    run_request,
    run_request_in_org,
    serialize,
    temporary_org_client,
)


RELATION_APPEND = {
    "users": "jms_client.v1.models.request.permissions.permissions.AppendUsersToPermissionRequest",
    "user-groups": "jms_client.v1.models.request.permissions.permissions.AppendUserGroupsToPermissionRequest",
    "assets": "jms_client.v1.models.request.permissions.permissions.AppendAssetsToPermissionRequest",
    "nodes": "jms_client.v1.models.request.permissions.permissions.AppendNodesToPermissionRequest",
}

RELATION_REMOVE = {
    "user": "jms_client.v1.models.request.permissions.permissions.RemoveUserFromPermissionRequest",
    "user-group": "jms_client.v1.models.request.permissions.permissions.RemoveUserGroupFromPermissionRequest",
    "asset": "jms_client.v1.models.request.permissions.permissions.RemoveAssetFromPermissionRequest",
    "node": "jms_client.v1.models.request.permissions.permissions.RemoveNodeFromPermissionRequest",
}

RELATION_PREVIEW = {
    "user": {"payload_key": "user_id", "field": "users"},
    "user-group": {"payload_key": "user_group_id", "field": "user_groups"},
    "asset": {"payload_key": "asset_id", "field": "assets"},
    "node": {"payload_key": "node_id", "field": "nodes"},
}
RELATION_APPEND_FIELDS = {
    "users": "users",
    "user-groups": "user_groups",
    "assets": "assets",
    "nodes": "nodes",
}

VALID_ACTIONS = {
    "connect",
    "upload",
    "download",
    "copy",
    "paste",
    "delete",
    "share",
}

ACCOUNT_TOKENS = {"@ALL", "@INPUT", "@SPEC", "@ANON", "@USER"}
ACCOUNT_INPUT_ALIASES = {
    "手动账号": "@INPUT",
    "同名账号": "@USER",
    "匿名账号": "@ANON",
    "所有账号": "@ALL",
}
ACCOUNT_DISPLAY_ALIASES = {
    "@INPUT": "手动账号",
    "@USER": "同名账号",
    "@ANON": "匿名账号",
    "@ALL": "所有账号",
    "@SPEC": "指定账号",
}
ACCOUNT_ALL_ALLOWED_TOKENS = {"@ALL", "@INPUT", "@USER", "@ANON"}
CREATE_RELATION_FIELDS = ("users", "assets", "nodes", "user_groups")
CREATE_BODY_OVERRIDE_FIELDS = ("accounts", "actions", "protocols")
UUID_LIKE_RE = re.compile(
    r"^[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)
REFERENCE_FIELD_LABELS = {
    "users": "用户",
    "assets": "资产",
    "nodes": "节点",
    "user_groups": "用户组",
}
REFERENCE_FIELD_RESOURCES = {
    "users": "user",
    "assets": "asset",
    "nodes": "node",
    "user_groups": "user-group",
}


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


def fetch_permission_detail(permission_id: str, *, org_id: str | None = None) -> dict[str, Any]:
    request_cls = import_string(
        "jms_client.v1.models.request.permissions.permissions.DetailPermissionRequest"
    )
    request = request_cls(id_=permission_id)
    if org_id:
        return serialize(run_request_in_org(org_id, request, with_model=True))
    return serialize(run_request(request, with_model=True))


def normalize_reference_list(field: str, value: Any) -> list[Any]:
    items = value if isinstance(value, list) else [value]
    result: list[Any] = []
    for item in items:
        if isinstance(item, dict):
            item_id = item.get("id")
            if item_id in {None, ""}:
                raise RuntimeError(
                    f"Field '{field}' objects must include a non-empty 'id'."
                )
            result.append(item_id)
            continue
        if isinstance(item, list) or item in {None, ""}:
            raise RuntimeError(
                f"Field '{field}' items must be an id value or object with 'id'."
            )
        result.append(item)
    return result


def normalize_string_list(field: str, value: Any) -> list[str]:
    if not isinstance(value, list):
        raise RuntimeError(f"Field '{field}' must be a JSON array.")
    if not value:
        raise RuntimeError(f"Field '{field}' must not be empty.")

    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RuntimeError(f"Field '{field}' must contain non-empty strings.")
        result.append(item.strip())
    return result


def normalize_account_alias(item: str) -> str:
    if item == "指定账号":
        raise RuntimeError(
            "Field 'accounts' does not support input alias '指定账号'. "
            "Use '@SPEC' with account username."
        )
    if item in {"排除账号", "无"}:
        raise RuntimeError(
            f"Field 'accounts' does not support input alias '{item}'."
        )
    return ACCOUNT_INPUT_ALIASES.get(item, item)


def normalize_accounts(value: Any, *, allow_empty: bool = False) -> list[str]:
    if allow_empty and value == []:
        return []

    accounts = [normalize_account_alias(item) for item in normalize_string_list("accounts", value)]
    tokens = {item for item in accounts if item.startswith("@")}
    invalid_tokens = sorted(token for token in tokens if token not in ACCOUNT_TOKENS)
    if invalid_tokens:
        raise RuntimeError(
            "Field 'accounts' contains unsupported special values: "
            f"{', '.join(invalid_tokens)}. Supported: {', '.join(sorted(ACCOUNT_TOKENS))}."
        )
    account_usernames = [item for item in accounts if not item.startswith("@")]
    if "@SPEC" in tokens and not account_usernames:
        raise RuntimeError(
            "Field 'accounts' using '@SPEC' must include at least one account username."
        )
    if "@ALL" in tokens:
        disallowed_tokens = sorted(token for token in tokens if token not in ACCOUNT_ALL_ALLOWED_TOKENS)
        if disallowed_tokens:
            raise RuntimeError(
                "Field 'accounts' using '@ALL' may only combine with "
                "'@INPUT', '@USER', or '@ANON'."
            )
        if account_usernames:
            raise RuntimeError(
                "Field 'accounts' using '@ALL' cannot include explicit account usernames."
            )
    uuid_like = sorted(item for item in account_usernames if UUID_LIKE_RE.fullmatch(item))
    if uuid_like:
        raise RuntimeError(
            "Field 'accounts' must use account username, not account id: "
            f"{', '.join(uuid_like)}."
        )
    return accounts


def display_accounts(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    result: list[Any] = []
    for item in value:
        if isinstance(item, str):
            result.append(ACCOUNT_DISPLAY_ALIASES.get(item, item))
        else:
            result.append(item)
    return result


def _display_permission_result(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "accounts":
                result[key] = display_accounts(item)
            else:
                result[key] = _display_permission_result(item)
        return result
    if isinstance(value, list):
        return [_display_permission_result(item) for item in value]
    return value


def display_permission_result(value: Any) -> Any:
    return _display_permission_result(serialize(value))


def normalize_actions(value: Any) -> list[str]:
    actions = normalize_string_list("actions", value)
    invalid = sorted(action for action in actions if action not in VALID_ACTIONS)
    if invalid:
        raise RuntimeError(
            "Field 'actions' contains unsupported values: "
            f"{', '.join(invalid)}. Supported: {', '.join(sorted(VALID_ACTIONS))}."
        )
    return actions


def normalize_protocols(value: Any) -> list[str]:
    return normalize_string_list("protocols", value)


def _is_uuid_like(value: Any) -> bool:
    return isinstance(value, str) and bool(UUID_LIKE_RE.fullmatch(value))


def _org_summary(org: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(org, dict):
        return {"id": "", "name": ""}
    summary = {
        "id": str(org.get("id") or ""),
        "name": str(org.get("name") or ""),
    }
    for key in ("is_default", "is_root", "internal", "source"):
        if key in org:
            summary[key] = org.get(key)
    return summary


def _org_display(org: dict[str, Any]) -> str:
    name = str(org.get("name") or "").strip()
    org_id = str(org.get("id") or "").strip()
    if name and org_id:
        return f"{name} ({org_id})"
    if org_id:
        return org_id
    return name or "-"


def _dedupe_org_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for item in items:
        org_id = str(item.get("id") or "")
        if not org_id:
            continue
        current = seen.get(org_id)
        if current is None:
            seen[org_id] = _org_summary(item)
            continue
        if not current.get("name") and item.get("name"):
            current["name"] = item["name"]
    return list(seen.values())


def _build_org_guard_status(status: str, reason: str, message: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "message": message,
    }


def _raise_org_guard(
    message: str,
    *,
    effective_org: dict[str, Any],
    reason: str,
    candidate_orgs: list[dict[str, Any]] | None = None,
    referenced_object_orgs: list[dict[str, Any]] | None = None,
    cross_org_block_reason: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "effective_org": _org_summary(effective_org),
        "org_source": effective_org.get("source"),
        "org_guard_status": _build_org_guard_status("blocked", reason, message),
    }
    if candidate_orgs:
        payload["candidate_orgs"] = [_org_summary(item) for item in candidate_orgs]
    if referenced_object_orgs:
        payload["referenced_object_orgs"] = referenced_object_orgs
    if cross_org_block_reason:
        payload["cross_org_block_reason"] = cross_org_block_reason
    raise StructuredActionError(message, payload=payload)


def _build_ready_org_guard(
    *,
    effective_org: dict[str, Any],
    message: str = "All referenced objects belong to the current processing organization.",
    reason: str = "current_org_verified",
) -> dict[str, Any]:
    return {
        "effective_org": _org_summary(effective_org),
        "org_source": effective_org.get("source"),
        "org_guard_status": _build_org_guard_status("ready", reason, message),
    }


def _extract_reference_value(item: Any) -> str:
    if isinstance(item, dict):
        raw = extract_scalar(item)
    else:
        raw = item
    if raw in {None, ""}:
        raise RuntimeError("Reference items must not be empty.")
    return str(raw).strip()


def _annotate_object_org(item: dict[str, Any], org: dict[str, Any]) -> dict[str, Any]:
    annotated = serialize(item)
    if not isinstance(annotated, dict):
        raise RuntimeError("Resolved object must be a JSON object.")
    if not annotated.get("org_id"):
        annotated["org_id"] = org.get("id", "")
    if not annotated.get("org_name") and org.get("name"):
        annotated["org_name"] = org.get("name")
    return annotated


def _object_display_name(field: str, item: dict[str, Any]) -> str:
    if field == "users":
        return str(item.get("username") or item.get("name") or item.get("id") or "")
    if field == "nodes":
        return str(item.get("full_value") or item.get("value") or item.get("name") or item.get("id") or "")
    return str(item.get("name") or item.get("username") or item.get("value") or item.get("id") or "")


def _reference_summary(field: str, reference: str, item: dict[str, Any]) -> dict[str, Any]:
    org = {
        "id": str(item.get("org_id") or ""),
        "name": str(item.get("org_name") or ""),
    }
    return {
        "field": field,
        "reference": reference,
        "resolved_object": {
            "id": item.get("id"),
            "name": _object_display_name(field, item),
        },
        "org": org,
    }


def _permission_org_summary(permission: dict[str, Any], effective_org: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(permission.get("org_id") or effective_org.get("id") or ""),
        "name": str(permission.get("org_name") or effective_org.get("name") or ""),
    }


def _resolve_permission_guard_context(*, require_explicit_org_for_write: bool) -> dict[str, Any]:
    context = resolve_effective_org_context()
    effective_org = context["effective_org"]
    if not isinstance(effective_org, dict):
        message = "当前尚未选择组织；权限操作必须先选择组织后再执行。"
        _raise_org_guard(
            message,
            effective_org={},
            reason="org_selection_required",
            candidate_orgs=context.get("candidate_orgs", []),
        )
    if not context.get("selected_org_accessible", True):
        message = "当前配置的组织已不在当前账号可访问组织中；请先重新选择组织。"
        _raise_org_guard(
            message,
            effective_org=effective_org,
            reason="selected_org_inaccessible",
            candidate_orgs=context.get("candidate_orgs", []),
        )
    return context


def _detail_reference_in_effective_org(field: str, reference: str, effective_org: dict[str, Any]) -> dict[str, Any] | None:
    try:
        if field == "nodes":
            with temporary_org_client(str(effective_org.get("id") or "")):
                return _annotate_object_org(get_node_object(reference), effective_org)
        resource = REFERENCE_FIELD_RESOURCES[field]
        return _annotate_object_org(
            serialize(
                run_request_in_org(
                    effective_org["id"],
                    build_request(resource, "detail", {"id_": reference}),
                    with_model=True,
                )
            ),
            effective_org,
        )
    except Exception:  # noqa: BLE001
        return None


def _list_reference_matches_in_effective_org(
    field: str,
    reference: str,
    effective_org: dict[str, Any],
) -> list[dict[str, Any]]:
    with temporary_org_client(str(effective_org.get("id") or "")):
        if field == "users":
            result = run_paginated_list_request("user", {"username": reference})
            if not result:
                result = run_paginated_list_request("user", {"name": reference})
        elif field == "assets":
            result = run_paginated_list_request("asset", {"search": reference})
        elif field == "nodes":
            result = list_node_objects({"value": reference})
        elif field == "user_groups":
            result = run_paginated_list_request("user-group", {"name": reference})
        else:
            result = []

    if not isinstance(result, list):
        return []

    exact: list[dict[str, Any]] = []
    folded = reference.casefold()
    seen_ids: set[str] = set()
    for raw in result:
        item = _annotate_object_org(serialize(raw), effective_org)
        if field == "users":
            options = [item.get("username"), item.get("name")]
        elif field == "assets":
            options = [item.get("name")]
        elif field == "nodes":
            options = [item.get("value"), item.get("name"), item.get("full_value")]
        else:
            options = [item.get("name")]
        if not any(str(option or "").strip().casefold() == folded for option in options):
            continue
        item_id = str(item.get("id") or "")
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        exact.append(item)
    return exact


def _scan_reference_other_orgs(
    field: str,
    reference: str,
    guard_context: dict[str, Any],
) -> list[dict[str, Any]]:
    current_org_id = str(guard_context["effective_org"].get("id") or "")
    matches: list[dict[str, Any]] = []
    for org in guard_context.get("accessible_orgs", []):
        if str(org.get("id") or "") == current_org_id:
            continue
        if _is_uuid_like(reference):
            resolved = _detail_reference_in_effective_org(field, reference, org)
            if resolved is not None:
                matches.append(resolved)
            continue
        matches.extend(_list_reference_matches_in_effective_org(field, reference, org))
    return matches


def _resolve_reference_in_current_org_or_block(
    field: str,
    reference: str,
    guard_context: dict[str, Any],
) -> dict[str, Any]:
    effective_org = guard_context["effective_org"]
    if _is_uuid_like(reference):
        current = _detail_reference_in_effective_org(field, reference, effective_org)
        if current is not None:
            return current
    else:
        current_matches = _list_reference_matches_in_effective_org(field, reference, effective_org)
        if len(current_matches) == 1:
            return current_matches[0]
        if len(current_matches) > 1:
            raise RuntimeError(
                f"{REFERENCE_FIELD_LABELS[field]}引用 {reference!r} 在当前处理组织 "
                f"{_org_display(effective_org)} 中匹配到多个对象，请改用 ID。"
            )

    other_matches = _scan_reference_other_orgs(field, reference, guard_context)
    if other_matches:
        candidate_orgs = _dedupe_org_candidates(
            [
                {"id": item.get("org_id"), "name": item.get("org_name")}
                for item in other_matches
            ]
        )
        referenced_object_orgs = [
            _reference_summary(field, reference, item)
            for item in other_matches
        ]
        if len(candidate_orgs) == 1:
            target_org = candidate_orgs[0]
            message = (
                f"当前处理组织={_org_display(effective_org)}，"
                f"目标对象组织={_org_display(target_org)}，"
                "跨组织授权已禁止；请先明确组织后重试。"
            )
            _raise_org_guard(
                message,
                effective_org=effective_org,
                reason="cross_org_reference_forbidden",
                candidate_orgs=candidate_orgs,
                referenced_object_orgs=referenced_object_orgs,
                cross_org_block_reason=(
                    f"{REFERENCE_FIELD_LABELS[field]} 引用 {reference!r} 不在当前处理组织 "
                    f"{_org_display(effective_org)} 中，而是在 {_org_display(target_org)} 中。"
                ),
            )
        _raise_org_guard(
            f"{REFERENCE_FIELD_LABELS[field]}引用 {reference!r} 在多个组织中命中；请先明确组织后重试。",
            effective_org=effective_org,
            reason="reference_org_ambiguous",
            candidate_orgs=candidate_orgs,
            referenced_object_orgs=referenced_object_orgs,
        )

    raise RuntimeError(
        f"{REFERENCE_FIELD_LABELS[field]}引用 {reference!r} 在当前处理组织 "
        f"{_org_display(effective_org)} 中不存在。"
    )


def _resolve_reference_field_values(
    field: str,
    value: Any,
    guard_context: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    items = value if isinstance(value, list) else [value]
    resolved_ids: list[str] = []
    summaries: list[dict[str, Any]] = []
    for item in items:
        reference = _extract_reference_value(item)
        resolved = _resolve_reference_in_current_org_or_block(field, reference, guard_context)
        resolved_id = str(resolved.get("id") or "")
        if not resolved_id:
            raise RuntimeError(
                f"{REFERENCE_FIELD_LABELS[field]}引用 {reference!r} 缺少可用的对象 ID。"
            )
        resolved_ids.append(resolved_id)
        summaries.append(_reference_summary(field, reference, resolved))
    return resolved_ids, summaries


def _guard_permission_reference_payload(
    payload: dict[str, Any],
    guard_context: dict[str, Any],
    *,
    fields: tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized = dict(payload)
    summaries: list[dict[str, Any]] = []
    target_fields = fields or tuple(field for field in CREATE_RELATION_FIELDS if field in normalized)
    for field in target_fields:
        if field not in normalized:
            continue
        resolved_ids, field_summaries = _resolve_reference_field_values(
            field,
            normalized[field],
            guard_context,
        )
        normalized[field] = resolved_ids
        summaries.extend(field_summaries)
    return normalized, summaries


def _fetch_permission_detail_in_org(permission_id: str, org: dict[str, Any]) -> dict[str, Any] | None:
    try:
        detail = fetch_permission_detail(permission_id, org_id=str(org.get("id") or ""))
    except Exception:  # noqa: BLE001
        return None
    if not detail.get("org_id"):
        detail["org_id"] = org.get("id", "")
    if not detail.get("org_name") and org.get("name"):
        detail["org_name"] = org.get("name")
    return detail


def _fetch_permission_detail_guarded(permission_id: str, guard_context: dict[str, Any]) -> dict[str, Any]:
    effective_org = guard_context["effective_org"]
    current = _fetch_permission_detail_in_org(permission_id, effective_org)
    if current is not None:
        current_org_id = str(current.get("org_id") or effective_org.get("id") or "")
        if current_org_id and current_org_id != str(effective_org.get("id") or ""):
            message = (
                f"当前处理组织={_org_display(effective_org)}，"
                f"目标授权组织={_org_display(_permission_org_summary(current, effective_org))}，"
                "跨组织授权已禁止；请先明确组织后重试。"
            )
            _raise_org_guard(
                message,
                effective_org=effective_org,
                reason="permission_org_mismatch",
                candidate_orgs=[_permission_org_summary(current, effective_org)],
                cross_org_block_reason=message,
            )
        return current

    other_matches = [
        detail
        for org in guard_context.get("accessible_orgs", [])
        if str(org.get("id") or "") != str(effective_org.get("id") or "")
        for detail in [_fetch_permission_detail_in_org(permission_id, org)]
        if detail is not None
    ]
    if other_matches:
        candidate_orgs = _dedupe_org_candidates(
            [_permission_org_summary(item, effective_org) for item in other_matches]
        )
        if len(candidate_orgs) == 1:
            target_org = candidate_orgs[0]
            message = (
                f"当前处理组织={_org_display(effective_org)}，"
                f"目标授权组织={_org_display(target_org)}，"
                "跨组织授权已禁止；请先明确组织后重试。"
            )
            _raise_org_guard(
                message,
                effective_org=effective_org,
                reason="permission_org_mismatch",
                candidate_orgs=candidate_orgs,
                cross_org_block_reason=message,
            )
        _raise_org_guard(
            f"授权 {permission_id!r} 在多个组织中可见；请先明确组织后重试。",
            effective_org=effective_org,
            reason="permission_org_ambiguous",
            candidate_orgs=candidate_orgs,
        )

    raise RuntimeError(
        f"授权 {permission_id!r} 在当前处理组织 {_org_display(effective_org)} 中不存在。"
    )


def prepare_create_request(
    raw_payload: dict[str, Any],
    *,
    guard_context: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    request_cls = import_string(
        "jms_client.v1.models.request.permissions.permissions.CreatePermissionRequest"
    )
    native_payload = dict(raw_payload)
    referenced_object_orgs: list[dict[str, Any]] = []
    if guard_context is not None:
        native_payload, referenced_object_orgs = _guard_permission_reference_payload(
            native_payload,
            guard_context,
        )
    else:
        for field in CREATE_RELATION_FIELDS:
            if field in native_payload:
                native_payload[field] = normalize_reference_list(field, native_payload[field])

    body_patch: dict[str, Any] = {}
    normalizers = {
        "accounts": normalize_accounts,
        "actions": normalize_actions,
        "protocols": normalize_protocols,
    }
    for field in CREATE_BODY_OVERRIDE_FIELDS:
        if field in native_payload:
            body_patch[field] = normalizers[field](native_payload.pop(field))

    request = request_cls(**native_payload)
    if body_patch:
        request._body.update(body_patch)
    return request, serialize(request.get_data()), referenced_object_orgs


def build_permission_update_payload(
    current: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": current["name"],
        "date_start": current.get("date_start", ""),
        "date_expired": current.get("date_expired", ""),
        "is_active": current.get("is_active", True),
        "comment": current.get("comment", ""),
        "accounts": extract_scalar_list(current.get("accounts", [])),
        "actions": extract_scalar_list(current.get("actions", []), ("value", "name")),
        "protocols": extract_scalar_list(current.get("protocols", []), ("value", "name")),
    }
    for field in ("users", "assets", "nodes", "user_groups"):
        if field in current:
            payload[field] = extract_ids(current.get(field, []))
    payload.update(patch)
    if "accounts" in patch or payload["accounts"]:
        payload["accounts"] = normalize_accounts(payload["accounts"])
    else:
        payload["accounts"] = normalize_accounts(payload["accounts"], allow_empty=True)
    return payload


def run_paginated_permission_list(payload: dict[str, Any], *, org_id: str | None = None):
    request_cls = import_string(
        "jms_client.v1.models.request.permissions.permissions.DescribePermissionsRequest"
    )
    if "limit" in payload or "offset" in payload:
        request = request_cls(**payload)
        if org_id:
            return run_request_in_org(org_id, request, with_model=True)
        return run_request(request, with_model=True)

    page_size = 200
    page_offset = 0
    combined: list[Any] = []
    while True:
        page_payload = dict(payload)
        page_payload["limit"] = page_size
        page_payload["offset"] = page_offset
        request = request_cls(**page_payload)
        if org_id:
            result = run_request_in_org(org_id, request, with_model=True)
        else:
            result = run_request(request, with_model=True)
        if not isinstance(result, list):
            raise RuntimeError("Permission list API did not return a list.")
        combined.extend(result)
        if len(result) < page_size:
            break
        page_offset += len(result)
    return combined


def list_permissions(args: argparse.Namespace):
    guard_context = resolve_effective_org_context()
    return display_permission_result(
        run_paginated_permission_list(
            parse_json_arg(args.filters),
            org_id=str(guard_context["effective_org"].get("id") or ""),
        )
    )


def get_permission(args: argparse.Namespace):
    guard_context = resolve_effective_org_context()
    return display_permission_result(
        fetch_permission_detail(
            args.id,
            org_id=str(guard_context["effective_org"].get("id") or ""),
        )
    )


def create_permission(args: argparse.Namespace):
    guard_context = _resolve_permission_guard_context(require_explicit_org_for_write=True)
    request, _, _ = prepare_create_request(
        parse_json_arg(args.payload),
        guard_context=guard_context,
    )
    return display_permission_result(
        run_request_in_org(
            str(guard_context["effective_org"].get("id") or ""),
            request,
            with_model=True,
        )
    )


def preview_create(args: argparse.Namespace):
    guard_context = _resolve_permission_guard_context(require_explicit_org_for_write=True)
    _, payload, referenced_object_orgs = prepare_create_request(
        parse_json_arg(args.payload),
        guard_context=guard_context,
    )
    result = {
        "target": {"name": payload.get("name")},
        "proposed": display_permission_result(payload),
        "referenced_object_orgs": referenced_object_orgs,
        "message": "Review the normalized payload before running create.",
    }
    result.update(_build_ready_org_guard(effective_org=guard_context["effective_org"]))
    return result


def preview_update(args: argparse.Namespace):
    guard_context = _resolve_permission_guard_context(require_explicit_org_for_write=True)
    current = _fetch_permission_detail_guarded(args.id, guard_context)
    patch = parse_json_arg(args.payload)
    current_payload = build_permission_update_payload(current, {})
    proposed_payload = build_permission_update_payload(current, patch)
    relation_fields = tuple(field for field in CREATE_RELATION_FIELDS if field in patch)
    proposed_payload, referenced_object_orgs = _guard_permission_reference_payload(
        proposed_payload,
        guard_context,
        fields=relation_fields,
    )
    current_display = display_permission_result(current_payload)
    proposed_display = display_permission_result(proposed_payload)
    result = {
        "target": {"id": current.get("id"), "name": current.get("name")},
        "permission_org": _permission_org_summary(current, guard_context["effective_org"]),
        "current": current_display,
        "proposed": proposed_display,
        "referenced_object_orgs": referenced_object_orgs,
        "diff": build_diff(current_display, proposed_display),
    }
    result.update(_build_ready_org_guard(effective_org=guard_context["effective_org"]))
    return result


def update_permission(args: argparse.Namespace):
    require_confirmation(args)
    guard_context = _resolve_permission_guard_context(require_explicit_org_for_write=True)
    current = _fetch_permission_detail_guarded(args.id, guard_context)
    patch = parse_json_arg(args.payload)
    payload = build_permission_update_payload(current, patch)
    relation_fields = tuple(field for field in CREATE_RELATION_FIELDS if field in patch)
    payload, _ = _guard_permission_reference_payload(
        payload,
        guard_context,
        fields=relation_fields,
    )
    request_cls = (
        "jms_client.v1.models.request.permissions.permissions.UpdatePermissionRequest"
    )
    request = build_request_instance(
        request_cls,
        {**payload, "id_": args.id},
        body_override=payload,
    )
    return display_permission_result(
        run_request_in_org(
            str(guard_context["effective_org"].get("id") or ""),
            request,
            with_model=True,
        )
    )


def preview_relation(args: argparse.Namespace):
    guard_context = _resolve_permission_guard_context(require_explicit_org_for_write=True)
    payload = parse_json_arg(args.payload)
    meta = RELATION_PREVIEW[args.relation]
    target_id = payload.get(meta["payload_key"])
    if not target_id:
        raise RuntimeError(
            f"preview-remove for relation '{args.relation}' requires "
            f"'{meta['payload_key']}' in --payload."
        )

    current = _fetch_permission_detail_guarded(args.permission_id, guard_context)
    items = current.get(meta["field"])
    if not isinstance(items, list):
        raise RuntimeError(
            f"Permission detail does not include relation list '{meta['field']}'."
        )

    matches = [serialize(item) for item in items if extract_scalar(item, ("id",)) == target_id]
    if not matches:
        raise RuntimeError(
            f"No relation '{args.relation}' with id '{target_id}' is currently attached "
            f"to permission '{args.permission_id}'."
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"Relation '{args.relation}' with id '{target_id}' matched multiple objects."
        )

    result = {
        "target_permission": {
            "id": current.get("id"),
            "name": current.get("name"),
        },
        "permission_org": _permission_org_summary(current, guard_context["effective_org"]),
        "relation": args.relation,
        "matched": matches[0],
        "payload": {meta["payload_key"]: target_id},
        "current_count": len(items),
        "remaining_count": len(items) - 1,
        "message": "Review the scope before rerunning with --confirm for destructive changes.",
    }
    result.update(_build_ready_org_guard(effective_org=guard_context["effective_org"]))
    return result


def append_relation(args: argparse.Namespace):
    guard_context = _resolve_permission_guard_context(require_explicit_org_for_write=True)
    _fetch_permission_detail_guarded(args.permission_id, guard_context)
    payload = parse_json_arg(args.payload)
    relation_field = RELATION_APPEND_FIELDS[args.relation]
    payload, _ = _guard_permission_reference_payload(
        payload,
        guard_context,
        fields=(relation_field,),
    )
    payload["permission_id"] = args.permission_id
    request_cls = import_string(RELATION_APPEND[args.relation])
    return run_request_in_org(
        str(guard_context["effective_org"].get("id") or ""),
        request_cls(**payload),
        with_model=True,
    )


def remove_relation(args: argparse.Namespace):
    require_confirmation(args)
    guard_context = _resolve_permission_guard_context(require_explicit_org_for_write=True)
    _fetch_permission_detail_guarded(args.permission_id, guard_context)
    payload = parse_json_arg(args.payload)
    payload["permission_id"] = args.permission_id
    request_cls = import_string(RELATION_REMOVE[args.relation])
    return run_request_in_org(
        str(guard_context["effective_org"].get("id") or ""),
        request_cls(**payload),
        with_model=True,
    )


def delete_permission(args: argparse.Namespace):
    require_confirmation(args)
    guard_context = _resolve_permission_guard_context(require_explicit_org_for_write=True)
    _fetch_permission_detail_guarded(args.id, guard_context)
    request_cls = import_string(
        "jms_client.v1.models.request.permissions.permissions.DeletePermissionRequest"
    )
    return run_request_in_org(
        str(guard_context["effective_org"].get("id") or ""),
        request_cls(id_=args.id),
        with_model=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--filters", help="JSON filter object")
    list_parser.set_defaults(func=list_permissions)

    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("--id", required=True)
    get_parser.set_defaults(func=get_permission)

    preview_create_parser = subparsers.add_parser("preview-create")
    preview_create_parser.add_argument("--payload", required=True, help="JSON create payload")
    preview_create_parser.set_defaults(func=preview_create)

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--payload", required=True, help="JSON create payload")
    create_parser.set_defaults(func=create_permission)

    preview_update_parser = subparsers.add_parser("preview-update")
    preview_update_parser.add_argument("--id", required=True)
    preview_update_parser.add_argument("--payload", required=True)
    preview_update_parser.set_defaults(func=preview_update)

    update_parser = subparsers.add_parser("update")
    update_parser.add_argument("--id", required=True)
    update_parser.add_argument("--payload", required=True)
    update_parser.add_argument("--confirm", action="store_true")
    update_parser.set_defaults(func=update_permission)

    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--permission-id", required=True)
    append_parser.add_argument("--relation", required=True, choices=sorted(RELATION_APPEND))
    append_parser.add_argument("--payload", required=True)
    append_parser.set_defaults(func=append_relation)

    preview_remove_parser = subparsers.add_parser("preview-remove")
    preview_remove_parser.add_argument("--permission-id", required=True)
    preview_remove_parser.add_argument("--relation", required=True, choices=sorted(RELATION_REMOVE))
    preview_remove_parser.add_argument("--payload", required=True)
    preview_remove_parser.set_defaults(func=preview_relation)

    remove_parser = subparsers.add_parser("remove")
    remove_parser.add_argument("--permission-id", required=True)
    remove_parser.add_argument("--relation", required=True, choices=sorted(RELATION_REMOVE))
    remove_parser.add_argument("--payload", required=True)
    remove_parser.add_argument("--confirm", action="store_true")
    remove_parser.set_defaults(func=remove_relation)

    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("--id", required=True)
    delete_parser.add_argument("--confirm", action="store_true")
    delete_parser.set_defaults(func=delete_permission)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    original = args.func

    def guarded(ns: argparse.Namespace, _func=original):
        ensure_selected_org_context(next_step=ORG_SELECTION_NEXT_STEP)
        return _func(ns)

    args.func = guarded
    return run_and_print(args.func, args)


if __name__ == "__main__":
    raise SystemExit(main())
