#!/usr/bin/env python3
from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jumpserver_api.jms_bootstrap import ensure_requirements_installed

ensure_requirements_installed()

import argparse

from jumpserver_api.jms_analytics import (
    _apply_common_filters,
    _asset_filter_evidence,
    _exact_first_filter,
    _fetch_terminal_session_records,
    _normalize_time_filters,
    _resolve_asset,
    _resolve_user,
    _server_filters,
    explain_asset_permissions,
    resolve_command_storage_context,
    run_capability,
)
from jumpserver_api.jms_runtime import (
    CLIError,
    create_client,
    create_discovery,
    ensure_selected_org_context,
    org_context_output,
    parse_bool,
    parse_json_arg,
    run_and_print,
)


ASSET_PATH = "/api/v1/assets/assets/"
NODE_PATH = "/api/v1/assets/nodes/"
PLATFORM_PATH = "/api/v1/assets/platforms/"
ACCOUNT_PATH = "/api/v1/accounts/accounts/"
ACCOUNT_TEMPLATE_PATH = "/api/v1/accounts/account-templates/"
USER_PATH = "/api/v1/users/users/"
GROUP_PATH = "/api/v1/users/groups/"
ORG_PATH = "/api/v1/orgs/orgs/"
LABEL_PATH = "/api/v1/labels/labels/"
ZONE_PATH = "/api/v1/assets/zones/"

ASSET_KIND_PATHS = {
    "": ASSET_PATH,
    "generic": ASSET_PATH,
    "host": "/api/v1/assets/hosts/",
    "database": "/api/v1/assets/databases/",
    "device": "/api/v1/assets/devices/",
    "cloud": "/api/v1/assets/clouds/",
    "web": "/api/v1/assets/webs/",
    "website": "/api/v1/assets/webs/",
    "custom": "/api/v1/assets/customs/",
    "customs": "/api/v1/assets/customs/",
    "directory": "/api/v1/assets/directories/",
    "directories": "/api/v1/assets/directories/",
}

OBJECT_RESOURCE_PATHS = {
    "node": NODE_PATH,
    "platform": PLATFORM_PATH,
    "account": ACCOUNT_PATH,
    "account-template": ACCOUNT_TEMPLATE_PATH,
    "user": USER_PATH,
    "user-group": GROUP_PATH,
    "organization": ORG_PATH,
    "label": LABEL_PATH,
    "zone": ZONE_PATH,
}

LOCAL_MATCH_FIELDS = {
    "asset": ("id", "name", "address"),
    "node": ("id", "name", "value", "full_value"),
    "platform": ("id", "name"),
    "account": ("id", "name", "username"),
    "user": ("id", "name", "username", "email"),
    "user-group": ("id", "name"),
    "organization": ("id", "name"),
    "label": ("id", "name"),
    "zone": ("id", "name"),
}

PERMISSION_RESOURCE_PATHS = {
    "asset-permission": "/api/v1/perms/asset-permissions/",
    "connect-method-acl": "/api/v1/acls/connect-method-acls/",
    "data-masking-rule": "/api/v1/acls/data-masking-rules/",
    "login-asset-acl": "/api/v1/acls/login-asset-acls/",
    "login-acl": "/api/v1/acls/login-acls/",
    "command-filter-acl": "/api/v1/acls/command-filter-acls/",
    "command-group": "/api/v1/acls/command-groups/",
    "org-role": "/api/v1/rbac/org-roles/",
    "system-role": "/api/v1/rbac/system-roles/",
    "role-binding": "/api/v1/rbac/role-bindings/",
    "org-role-binding": "/api/v1/rbac/org-role-bindings/",
    "system-role-binding": "/api/v1/rbac/system-role-bindings/",
}

AUDIT_PATHS = {
    "operate": "/api/v1/audits/operate-logs/",
    "login": "/api/v1/audits/login-logs/",
    "session": "/api/v1/audits/user-sessions/",
    "ftp": "/api/v1/audits/ftp-logs/",
    "password_change": "/api/v1/audits/password-change-logs/",
    "jobs": "/api/v1/audits/job-logs/",
    "command": "/api/v1/terminal/commands/",
    "terminal-session": "/api/v1/terminal/sessions/",
}

TERMINAL_SESSION_PRESETS = {
    "online": {"is_finished": 0, "order": "is_finished,-date_end"},
    "history": {"is_finished": 1, "order": "is_finished,-date_end"},
}

COMMAND_AUDIT_CAPABILITIES = {
    "command-record-query",
    "high-risk-command-audit",
}


def _asset_list_path(kind: str | None) -> str:
    kind_value = str(kind or "").strip().lower()
    if kind_value not in ASSET_KIND_PATHS:
        raise CLIError("Unsupported asset kind: %s" % kind)
    return ASSET_KIND_PATHS[kind_value]


def _object_list_path(resource: str, kind: str | None) -> str:
    if resource == "asset":
        return _asset_list_path(kind)
    if kind:
        raise CLIError("--kind is only supported when --resource asset.")
    return OBJECT_RESOURCE_PATHS[resource]


def _object_get_path(resource: str) -> str:
    if resource == "asset":
        return ASSET_PATH
    return OBJECT_RESOURCE_PATHS[resource]


def _without_pagination(filters: dict) -> dict:
    payload = dict(filters)
    payload.pop("limit", None)
    payload.pop("offset", None)
    return payload


def _apply_requested_page(records, filters: dict):
    if not isinstance(records, list):
        return records
    if filters.get("limit") in {None, ""} and filters.get("offset") in {None, ""}:
        return records
    try:
        offset = max(int(filters.get("offset") or 0), 0)
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(filters.get("limit")) if filters.get("limit") not in {None, ""} else None
    except (TypeError, ValueError):
        limit = None
    if limit is not None and limit < 0:
        limit = None
    end = offset + limit if limit is not None else None
    return records[offset:end]


def _merge_match_strategy(current: str, addition: str) -> str:
    parts = [item for item in str(current or "").split("+") if item]
    if addition not in parts:
        parts.append(addition)
    return "+".join(parts) if parts else addition


def _candidate_brief(resource: str, item: dict) -> dict:
    if resource == "asset":
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "address": item.get("address"),
            "platform": (item.get("platform") or {}).get("name") if isinstance(item.get("platform"), dict) else item.get("platform"),
            "nodes_display": item.get("nodes_display"),
        }
    if resource == "node":
        return {
            "id": item.get("id"),
            "name": item.get("name") or item.get("value"),
            "full_value": item.get("full_value"),
            "org_name": item.get("org_name"),
        }
    return {"id": item.get("id"), "name": item.get("name")}


def _ambiguity_hint(resource: str, matched_fields: list[str]) -> str | None:
    if resource == "asset" and "address" in matched_fields:
        return "Address 可能对应多个资产，请改用 id、name 或 platform 继续确认。"
    if resource == "node" and "full_value" in matched_fields:
        return "full_value 应唯一命中；若仍多条，请改用 id。"
    if matched_fields:
        return "当前条件仍命中多个对象，请改用 id 或更精确字段继续缩小范围。"
    return None


def _apply_local_exact_filters(client, *, path: str, resource: str, filters: dict, records):
    if not isinstance(records, list):
        return records, "server", []
    current = [item for item in records if isinstance(item, dict)]
    match_strategy = "server"
    matched_fields = []
    for field in LOCAL_MATCH_FIELDS.get(resource, ()):
        value = filters.get(field)
        if value in {None, ""}:
            continue
        matched_fields.append(field)
        narrowed = _exact_first_filter(current, value, field)
        if narrowed:
            if narrowed != current:
                match_strategy = "local_exact_first"
            current = narrowed
            continue
        broader_filters = _without_pagination(filters)
        broader_filters.pop(field, None)
        broader = client.list_paginated(path, params=broader_filters)
        broader = [item for item in broader if isinstance(item, dict)] if isinstance(broader, list) else []
        current = _exact_first_filter(broader, value, field)
        match_strategy = "local_exact_first_broad_fetch"
    return current, match_strategy, matched_fields


def _permission_detail_matches_user(detail: dict, *, resolved_user: dict) -> bool:
    user_id = str(resolved_user.get("id") or "").strip()
    user_name = str(resolved_user.get("name") or "").strip().lower()
    user_username = str(resolved_user.get("username") or "").strip().lower()
    user_group_ids = {
        str(item.get("id", item)).strip()
        for item in (resolved_user.get("groups") or [])
        if str(item.get("id", item) if isinstance(item, dict) else item).strip()
    }
    expected_values = {value for value in {user_id, user_name, user_username} if value}

    for item in detail.get("users", []) or []:
        if isinstance(item, dict):
            item_id = str(item.get("id") or "").strip()
            item_name = str(item.get("name") or "").strip().lower()
            item_username = str(item.get("username") or "").strip().lower()
            if user_id and item_id == user_id:
                return True
            if user_username and item_username == user_username:
                return True
            if user_name and item_name == user_name:
                return True
            continue
        item_text = str(item or "").strip()
        if item_text and (item_text == user_id or item_text.lower() in expected_values):
            return True

    detail_group_ids = {
        str(item.get("id", item)).strip()
        for item in (detail.get("user_groups") or [])
        if str(item.get("id", item) if isinstance(item, dict) else item).strip()
    }
    return bool(detail_group_ids & user_group_ids)


def _filter_asset_permission_records_by_user(client, records, user_filter, *, discovery=None):
    resolved_user = _resolve_user(str(user_filter or "").strip(), discovery=discovery)
    filtered_records = []
    for item in records:
        permission_id = str(item.get("id") or "").strip() if isinstance(item, dict) else ""
        if not permission_id:
            continue
        detail = client.get("%s%s/" % (_permission_resource_path("asset-permission"), permission_id))
        if _permission_detail_matches_user(detail, resolved_user=resolved_user):
            filtered_records.append(item)
    return filtered_records, resolved_user


def _object_list(args: argparse.Namespace):
    context = ensure_selected_org_context()
    client = create_client()
    filters = parse_json_arg(args.filters)
    path = _object_list_path(args.resource, args.kind)
    records = client.list_paginated(path, params=filters)
    records, match_strategy, matched_fields = _apply_local_exact_filters(
        client,
        path=path,
        resource=args.resource,
        filters=filters,
        records=records,
    )
    ambiguous = isinstance(records, list) and bool(matched_fields) and len(records) > 1
    return {
        "resource": args.resource,
        "kind": args.kind if args.resource == "asset" else None,
        "match_strategy": match_strategy,
        "summary": {
            "total": len(records) if isinstance(records, list) else None,
            "filters": filters,
            "matched_fields": matched_fields,
            "ambiguous": ambiguous,
            "ambiguity_hint": _ambiguity_hint(args.resource, matched_fields) if ambiguous else None,
            "candidates": [_candidate_brief(args.resource, item) for item in records[:10]] if ambiguous else [],
        },
        "records": records,
        **org_context_output(context),
    }


def _object_get(args: argparse.Namespace):
    context = ensure_selected_org_context()
    client = create_client()
    record = client.get("%s%s/" % (_object_get_path(args.resource), args.id))
    return {
        "resource": args.resource,
        "record": record,
        **org_context_output(context),
    }


def _permission_resource_path(resource: str) -> str:
    return PERMISSION_RESOURCE_PATHS[resource]


def _permission_brief(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "is_expired": item.get("is_expired"),
        "from_ticket": item.get("from_ticket"),
        "date_start": item.get("date_start"),
        "date_expired": item.get("date_expired"),
    }


def _permission_list(args: argparse.Namespace):
    context = ensure_selected_org_context()
    client = create_client()
    filters = parse_json_arg(args.filters)
    path = _permission_resource_path(args.resource)
    records = client.list_paginated(path, params=filters)
    filtered_records = [item for item in records if isinstance(item, dict)] if isinstance(records, list) else records
    match_strategy = "server"
    summary = {
        "filters": filters,
        "total": len(filtered_records) if isinstance(filtered_records, list) else None,
    }

    if isinstance(filtered_records, list) and args.resource == "asset-permission" and filters.get("name"):
        filtered = _exact_first_filter(filtered_records, filters.get("name"), "name")
        if filtered:
            if filtered != filtered_records:
                match_strategy = "local_exact_first"
            filtered_records = filtered
        else:
            fallback_filters = dict(filters)
            fallback_filters.pop("name", None)
            fallback_filters.pop("search", None)
            broader_records = client.list_paginated(path, params=fallback_filters)
            broader_records = [item for item in broader_records if isinstance(item, dict)] if isinstance(broader_records, list) else []
            filtered_records = _exact_first_filter(broader_records, filters.get("name"), "name")
            match_strategy = "local_exact_first_broad_fetch"
        summary["matched_name"] = filters.get("name")

    if isinstance(filtered_records, list) and args.resource == "asset-permission":
        requested_user_filter = next(
            ((field, filters.get(field)) for field in ("users", "user") if filters.get(field) not in {None, ""}),
            None,
        )
        if requested_user_filter is not None:
            field_name, field_value = requested_user_filter
            discovery = create_discovery()
            broader_filters = _without_pagination({key: value for key, value in filters.items() if key not in {"user", "users"}})
            broader_records = client.list_paginated(path, params=broader_filters)
            broader_records = [item for item in broader_records if isinstance(item, dict)] if isinstance(broader_records, list) else []
            locally_filtered_records, resolved_user = _filter_asset_permission_records_by_user(
                client,
                broader_records,
                field_value,
                discovery=discovery,
            )
            filtered_records = _apply_requested_page(locally_filtered_records, filters)
            match_strategy = _merge_match_strategy(match_strategy, "local_detail_user_filter")
            summary["requested_user_filter"] = {"field": field_name, "value": field_value}
            summary["matched_user"] = {
                "id": resolved_user.get("id"),
                "name": resolved_user.get("name"),
                "username": resolved_user.get("username"),
                "email": resolved_user.get("email"),
            }
            summary["local_detail_user_filter_candidate_count"] = len(broader_records)
            summary["local_detail_user_filter_total_before_pagination"] = len(locally_filtered_records)
            if not filtered_records and not summary.get("empty_reason_hint"):
                summary["empty_reason_hint"] = "当前组织下实时可见的 asset-permission 中未发现匹配该用户或其用户组的规则。"

    if isinstance(filtered_records, list) and args.resource == "asset-permission":
        visible_sample = filtered_records
        if filters.get("name") and not filtered_records:
            visible_sample = client.list_paginated(path, params={k: v for k, v in filters.items() if k not in {"name", "search"}})
            visible_sample = [item for item in visible_sample if isinstance(item, dict)] if isinstance(visible_sample, list) else []
            summary["current_visible_total_without_name_filter"] = len(visible_sample)
            if not visible_sample:
                summary["empty_reason_hint"] = "名称链路已尝试服务端过滤与本地 broad fetch，当前组织下仍未发现该规则；若历史工件曾出现该对象，可能已删除、跨组织，或当前账号不可见。"
            else:
                summary["current_visible_candidates"] = [_permission_brief(item) for item in visible_sample[:10]]

        if filters.get("is_expired") is not None:
            wanted = parse_bool(filters.get("is_expired"))
            active_sample = client.list_paginated(path, params={k: v for k, v in filters.items() if k != "is_expired"})
            active_sample = [item for item in active_sample if isinstance(item, dict)] if isinstance(active_sample, list) else []
            summary["requested_is_expired"] = wanted
            summary["returned_expired_count"] = sum(1 for item in filtered_records if parse_bool(item.get("is_expired")))
            summary["returned_active_count"] = sum(1 for item in filtered_records if not parse_bool(item.get("is_expired")))
            summary["current_visible_total_without_is_expired_filter"] = len(active_sample)
            summary["current_visible_expired_count_without_filter"] = sum(1 for item in active_sample if parse_bool(item.get("is_expired")))
            summary["current_visible_active_count_without_filter"] = sum(1 for item in active_sample if not parse_bool(item.get("is_expired")))
            if wanted and not filtered_records:
                summary["empty_reason_hint"] = "当前组织下实时可见的 asset-permission 中没有 is_expired=true 记录；若历史工件曾出现该对象，可能已删除、跨组织，或当前账号不可见。"
                summary["current_visible_candidates"] = [_permission_brief(item) for item in active_sample[:10]]

    summary["total"] = len(filtered_records) if isinstance(filtered_records, list) else summary.get("total")
    return {
        "resource": args.resource,
        "match_strategy": match_strategy,
        "summary": summary,
        "records": filtered_records,
        **org_context_output(context),
    }


def _permission_get(args: argparse.Namespace):
    context = ensure_selected_org_context()
    client = create_client()
    record_id = str(args.id or args.permission_id or "").strip()
    if not record_id:
        raise CLIError("Provide --id. --permission-id is kept only for backward compatibility.")
    record = client.get("%s%s/" % (_permission_resource_path(args.resource), record_id))
    return {
        "resource": args.resource,
        "record": record,
        **org_context_output(context),
    }


def _asset_perm_users(args: argparse.Namespace):
    context = ensure_selected_org_context()
    client = create_client()
    discovery = create_discovery()
    filters = parse_json_arg(args.filters)
    records = client.list_paginated("/api/v1/assets/assets/%s/perm-users/" % args.asset_id, params=filters)
    result = {
        "resource": "asset-perm-users",
        "asset_id": args.asset_id,
        "records": records,
        **org_context_output(context),
    }
    if isinstance(records, list) and not records:
        asset = _resolve_asset(args.asset_id, discovery=discovery)
        explanation = explain_asset_permissions(asset, client=client, discovery=discovery)
        if explanation.get("matched_permission_count"):
            result.update(
                {
                    "service_view_mismatch": True,
                    "warning": "Asset permission users API returned no records, but matching asset-permissions were found for this asset.",
                    "permission_explain_summary": {
                        "matched_permission_count": explanation.get("matched_permission_count"),
                        "matched_permissions": [
                            {
                                "id": item.get("id"),
                                "name": item.get("name"),
                                "match_source": item.get("match_source"),
                            }
                            for item in explanation.get("matched_permissions", [])
                        ],
                    },
                }
            )
    return result


def _audit_list(args: argparse.Namespace):
    context = ensure_selected_org_context()
    client = create_client()
    filters = _normalize_time_filters(parse_json_arg(args.filters), default_days=7)
    filter_strategy = "server"
    if args.audit_type == "terminal-session":
        result, meta = _fetch_terminal_session_records(filters)
        filter_strategy = meta.get("filter_strategy") or filter_strategy
    else:
        result = client.list_paginated(AUDIT_PATHS[args.audit_type], params=_server_filters(filters))
        if isinstance(result, list):
            filtered = _apply_common_filters([item for item in result if isinstance(item, dict)], filters)
            if len(filtered) != len(result):
                filter_strategy = "server+local_common_filters"
            result = filtered
    return {
        "audit_type": args.audit_type,
        "filter_strategy": filter_strategy,
        "records": result,
        **org_context_output(context),
    }


def _audit_get(args: argparse.Namespace):
    context = ensure_selected_org_context()
    client = create_client()
    result = client.get("%s%s/" % (AUDIT_PATHS[args.audit_type], args.id))
    return {"audit_type": args.audit_type, "record": result, **org_context_output(context)}


def _terminal_sessions(args: argparse.Namespace):
    context = ensure_selected_org_context()
    filters = _normalize_time_filters(parse_json_arg(args.filters), default_days=7)
    preset = TERMINAL_SESSION_PRESETS.get(args.view or "")
    if preset:
        for key, value in preset.items():
            filters.setdefault(key, value)

    filtered, meta = _fetch_terminal_session_records(filters)
    return {
        "audit_type": "terminal-session",
        "view": args.view or "all",
        "summary": {
            "total": len(filtered),
            "filters": {key: value for key, value in filters.items() if not str(key).startswith("_")},
            "filter_strategy": meta.get("filter_strategy"),
            "resolved_asset": meta.get("resolved_asset"),
        },
        "records": [
            {
                **item,
                "asset_evidence": _asset_filter_evidence(item, expected=filters.get("asset")),
            }
            for item in filtered
        ],
        **org_context_output(context),
    }


def _command_storage_hint(args: argparse.Namespace):
    context = ensure_selected_org_context()
    filters = parse_json_arg(args.filters)
    return _command_storage_hint_payload(filters, context=context)


def _command_storage_hint_payload(filters: dict, *, context: dict | None = None):
    storage_context = resolve_command_storage_context(filters)
    return {
        "storage_count": storage_context["available_command_storage_count"],
        "default_storage_count": storage_context["default_storage_count"],
        "storages": storage_context["available_command_storages"],
        "warning": storage_context["command_storage_hint"],
        **storage_context,
        **org_context_output(context or ensure_selected_org_context()),
    }


def _audit_analyze(args: argparse.Namespace):
    context = ensure_selected_org_context()
    filters = parse_json_arg(args.filters)
    effective_filters = dict(filters)
    storage_context = None
    if args.capability in COMMAND_AUDIT_CAPABILITIES:
        storage_context = resolve_command_storage_context(filters)
        if not filters.get("command_storage_id"):
            if storage_context.get("selection_required"):
                return {
                    "blocked": True,
                    "block_reason": "Multiple command storages detected and no default storage is available. Select one command_storage_id before querying command audit capabilities.",
                    "capability": args.capability,
                    **_command_storage_hint_payload(filters, context=context),
                }
            selected_command_storage_id = storage_context.get("selected_command_storage_id")
            if selected_command_storage_id:
                effective_filters = {**filters, "command_storage_id": selected_command_storage_id}
    result = run_capability(args.capability, effective_filters)
    if args.capability in COMMAND_AUDIT_CAPABILITIES and storage_context is not None:
        result.update(storage_context)
    if "effective_org" not in result:
        result.update(org_context_output(context))
    return result


def _audit_capabilities(_: argparse.Namespace):
    from jumpserver_api.jms_capabilities import CAPABILITIES

    return [
        {
            "id": item.capability_id,
            "name": item.name,
            "category": item.category,
            "priority": item.priority,
            "entrypoint": item.entrypoint,
        }
        for item in CAPABILITIES
        if item.entrypoint.startswith("jms_query.py audit-analyze")
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JumpServer unified read-only query entry point.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    object_resources = [
        "asset",
        "node",
        "platform",
        "account",
        "account-template",
        "user",
        "user-group",
        "organization",
        "label",
        "zone",
    ]
    permission_resources = sorted(PERMISSION_RESOURCE_PATHS)

    object_list = subparsers.add_parser("object-list")
    object_list.add_argument("--resource", required=True, choices=object_resources)
    object_list.add_argument("--kind")
    object_list.add_argument("--filters")
    object_list.set_defaults(func=_object_list)

    object_get = subparsers.add_parser("object-get")
    object_get.add_argument("--resource", required=True, choices=object_resources)
    object_get.add_argument("--id", required=True)
    object_get.set_defaults(func=_object_get)

    permission_list = subparsers.add_parser("permission-list")
    permission_list.add_argument("--resource", choices=permission_resources, default="asset-permission")
    permission_list.add_argument("--filters")
    permission_list.set_defaults(func=_permission_list)

    permission_get = subparsers.add_parser("permission-get")
    permission_get.add_argument("--resource", choices=permission_resources, default="asset-permission")
    permission_get.add_argument("--id")
    permission_get.add_argument("--permission-id")
    permission_get.set_defaults(func=_permission_get)

    asset_perm_users = subparsers.add_parser("asset-perm-users")
    asset_perm_users.add_argument("--asset-id", required=True)
    asset_perm_users.add_argument("--filters")
    asset_perm_users.set_defaults(func=_asset_perm_users)

    audit_list = subparsers.add_parser("audit-list")
    audit_list.add_argument("--audit-type", required=True, choices=sorted(AUDIT_PATHS))
    audit_list.add_argument("--filters")
    audit_list.set_defaults(func=_audit_list)

    audit_get = subparsers.add_parser("audit-get")
    audit_get.add_argument("--audit-type", required=True, choices=sorted(AUDIT_PATHS))
    audit_get.add_argument("--id", required=True)
    audit_get.set_defaults(func=_audit_get)

    terminal_sessions = subparsers.add_parser("terminal-sessions")
    terminal_sessions.add_argument("--view", choices=["online", "history"])
    terminal_sessions.add_argument("--filters")
    terminal_sessions.set_defaults(func=_terminal_sessions)

    command_storage_hint = subparsers.add_parser("command-storage-hint")
    command_storage_hint.add_argument("--filters")
    command_storage_hint.set_defaults(func=_command_storage_hint)

    audit_analyze = subparsers.add_parser("audit-analyze")
    audit_analyze.add_argument("--capability", required=True)
    audit_analyze.add_argument("--filters")
    audit_analyze.set_defaults(func=_audit_analyze)

    audit_capabilities = subparsers.add_parser("capabilities")
    audit_capabilities.set_defaults(func=_audit_capabilities)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_and_print(args.func, args)


if __name__ == "__main__":
    raise SystemExit(main())
