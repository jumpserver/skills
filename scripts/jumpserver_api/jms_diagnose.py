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
    _extract_account,
    _extract_asset,
    _extract_datetime,
    _extract_duration,
    _extract_protocol,
    _extract_source_ip,
    _extract_status,
    _extract_user,
    _fetch_command_records,
    _fetch_session_records,
    _login_records,
    _normalize_time_filters,
    _server_filters,
    run_capability,
)
from jumpserver_api.jms_capabilities import CAPABILITIES
from jumpserver_api.jms_runtime import (
    build_org_selection_required_payload,
    CLIError,
    DEFAULT_PAGE_SIZE,
    ORG_SELECTION_NEXT_STEP,
    create_client,
    create_discovery,
    current_runtime_values,
    ensure_selected_org_context,
    get_config_status,
    list_accessible_orgs,
    org_context_output,
    parse_json_arg,
    persist_selected_org,
    require_confirmation,
    resolve_effective_org_context,
    resolve_platform_reference,
    run_and_print,
    user_profile,
    write_local_env_config,
)


def _config_status(_: argparse.Namespace):
    return get_config_status()


def _config_write(args: argparse.Namespace):
    require_confirmation(args)
    payload = parse_json_arg(args.payload)
    return write_local_env_config(payload)


def _ping(_: argparse.Namespace):
    client = create_client()
    health = client.health_check()
    profile = user_profile(client)
    org_context = resolve_effective_org_context()
    current = client.get("/api/v1/orgs/orgs/current/")
    config_status = get_config_status()
    return {
        "health": health,
        "profile": profile,
        "candidate_orgs": org_context.get("candidate_orgs"),
        "current_org": current,
        "auth_mode": config_status.get("auth_mode"),
        "config_status": config_status,
        **org_context_output(org_context),
    }


def _select_org(args: argparse.Namespace):
    candidates = list_accessible_orgs()
    current_context = resolve_effective_org_context(auto_select=False)
    if not args.org_id:
        if current_context.get("selection_required"):
            return build_org_selection_required_payload(current_context)
        return {
            "selection_required": False,
            "candidate_orgs": candidates,
            "next_step": ORG_SELECTION_NEXT_STEP,
            **org_context_output(current_context),
        }
    selected = next((item for item in candidates if str(item.get("id")) == args.org_id), None)
    if selected is None:
        raise CLIError("Organization %s is not accessible in the current environment." % args.org_id)
    preview_scope = "%s (%s)" % (
        str(selected.get("name") or "").strip() or "Unknown",
        str(selected.get("id") or "").strip() or "<unknown-org-id>",
    )
    preview_context = {
        **current_context,
        "effective_org": {**selected, "source": "user_selected"},
        "switchable_orgs": [item for item in candidates if str(item.get("id") or "") != str(args.org_id)],
        "switchable_org_count": len([item for item in candidates if str(item.get("id") or "") != str(args.org_id)]),
        "org_context_hint": (
            "当前预览的查询范围将切换为组织 %s；确认写入后才能按该组织继续查询。"
            % preview_scope
        ),
    }
    if not args.confirm:
        return {
            "selection_required": False,
            "next_step": "python3 scripts/jumpserver_api/jms_diagnose.py select-org --org-id %s --confirm" % args.org_id,
            **org_context_output(preview_context),
        }
    require_confirmation(args)
    persisted = persist_selected_org(args.org_id)
    confirmed_context = {
        **preview_context,
        "org_context_hint": (
            "当前查询范围固定为组织 %s；如需切换查询范围，请先切换组织。"
            % preview_scope
            if preview_context["switchable_org_count"]
            else None
        ),
    }
    return {
        "selection_required": False,
        "current_nonsecret": persisted["current_nonsecret"],
        "env_file_path": persisted["env_file_path"],
        **org_context_output(confirmed_context),
    }


def _resolve(args: argparse.Namespace):
    ensure_selected_org_context()
    client = create_client()
    discovery = create_discovery()
    filters = parse_json_arg(args.filters)
    if args.resource == "asset":
        items = discovery.list_assets()
        field_names = ("id", "name", "address")
    elif args.resource == "node":
        items = discovery.list_nodes()
        field_names = ("id", "name", "value", "full_value")
    elif args.resource == "user":
        items = discovery.list_users()
        field_names = ("id", "name", "username", "email")
    elif args.resource == "user-group":
        items = discovery.list_user_groups()
        field_names = ("id", "name")
    elif args.resource == "organization":
        items = client.list_paginated("/api/v1/orgs/orgs/")
        field_names = ("id", "name")
    elif args.resource == "account":
        items = client.list_paginated("/api/v1/accounts/accounts/")
        field_names = ("id", "name", "username")
    elif args.resource == "platform":
        items = [item.to_dict() for item in discovery.list_platforms()]
        field_names = ("id", "name", "slug", "category")
    elif args.resource == "permission":
        items = client.list_paginated("/api/v1/perms/asset-permissions/")
        field_names = ("id", "name")
    else:
        raise CLIError("Unsupported resolve resource: %s" % args.resource)

    if args.id:
        matches = [item for item in items if str(item.get("id")) == args.id]
    else:
        wanted = str(args.name or filters.get("name") or "").strip()
        matches = _exact_first_filter([item for item in items if isinstance(item, dict)], wanted, *field_names)
    return {"resource": args.resource, "matches": matches[: int(filters.get("limit") or 50)]}


def _resolve_platform(args: argparse.Namespace):
    ensure_selected_org_context()
    return resolve_platform_reference(args.value)


def _require_exactly_one_selector(*, values: dict[str, str | None], message: str) -> None:
    provided = [name for name, value in values.items() if str(value or "").strip()]
    if len(provided) != 1:
        raise CLIError(message, payload={"provided": provided})


def _validate_user_selector(args: argparse.Namespace) -> None:
    _require_exactly_one_selector(
        values={"user_id": args.user_id, "username": args.username},
        message="Provide exactly one of --user-id or --username.",
    )


def _validate_asset_selector(args: argparse.Namespace) -> None:
    _require_exactly_one_selector(
        values={"asset_id": args.asset_id, "asset_name": args.asset_name},
        message="Provide exactly one of --asset-id or --asset-name.",
    )


def _normalize_effective_access_payload(payload, *, resource: str):
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
        return records, len(records)
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        records = [item for item in (payload.get("results") or []) if isinstance(item, dict)]
        try:
            total = int(payload.get("count"))
        except (TypeError, ValueError):
            total = len(records)
        return records, max(total, len(records))
    raise CLIError(
        "Effective %s API returned an unexpected payload." % resource,
        payload={"resource": resource, "payload_type": type(payload).__name__},
    )


def _append_unique_effective_records(target, new_records, *, seen_ids):
    for item in new_records:
        record_id = str(item.get("id") or "").strip() if isinstance(item, dict) else ""
        if record_id:
            if record_id in seen_ids:
                continue
            seen_ids.add(record_id)
        target.append(item)


def _fetch_effective_access_records(client, path: str, *, resource: str, params=None):
    payload = client.get(path, params=params)
    records, reported_total = _normalize_effective_access_payload(payload, resource=resource)
    collected = []
    seen_ids = set()
    _append_unique_effective_records(collected, records, seen_ids=seen_ids)
    warnings = []
    next_ref = payload.get("next") if isinstance(payload, dict) else None
    while next_ref:
        page_payload = client.get(next_ref)
        page_records, _ = _normalize_effective_access_payload(page_payload, resource=resource)
        if not page_records:
            break
        _append_unique_effective_records(collected, page_records, seen_ids=seen_ids)
        next_ref = page_payload.get("next") if isinstance(page_payload, dict) else None
    return collected, len(collected), reported_total, warnings


def _effective_user_access(user):
    client = create_client()
    user_id = str(user.get("id") or "")
    assets_path = "/api/v1/perms/users/%s/assets/" % user_id
    nodes_path = "/api/v1/perms/users/%s/nodes/" % user_id
    asset_params = {"all": 1, "asset": "", "node": "", "offset": 0, "limit": DEFAULT_PAGE_SIZE, "display": 1, "draw": 1}
    node_params = {"all": 1}
    assets, asset_count, reported_asset_count, asset_warnings = _fetch_effective_access_records(
        client,
        assets_path,
        resource="assets",
        params=asset_params,
    )
    nodes, node_count, reported_node_count, node_warnings = _fetch_effective_access_records(
        client,
        nodes_path,
        resource="nodes",
        params=node_params,
    )
    warnings = [*asset_warnings, *node_warnings]
    return {
        "asset_count": asset_count,
        "node_count": node_count,
        "assets": assets,
        "nodes": nodes,
        "matched_permissions": [],
        "data_source": {
            "assets_endpoint": assets_path,
            "assets_params": asset_params,
            "nodes_endpoint": nodes_path,
            "nodes_params": node_params,
        },
        "warnings": warnings,
    }


def _user_assets(args: argparse.Namespace):
    _validate_user_selector(args)
    ensure_selected_org_context()
    from jumpserver_api.jms_analytics import _resolve_user

    user = _resolve_user(args.user_id, args.username)
    return {"user": user, **_effective_user_access(user)}


def _user_nodes(args: argparse.Namespace):
    _validate_user_selector(args)
    result = _user_assets(args)
    return {
        "user": result["user"],
        "node_count": result["node_count"],
        "nodes": result["nodes"],
        "matched_permissions": result["matched_permissions"],
        "data_source": result["data_source"],
        "warnings": result["warnings"],
    }


def _node_full_value(node_lookup, node_id: str, *, fallback_name: str | None = None) -> str:
    node = node_lookup.get(node_id) or {}
    full_value = str(node.get("full_value") or "").strip()
    if full_value:
        return full_value
    name = str(node.get("value") or node.get("name") or fallback_name or "").strip()
    return "/%s" % name if name else ""


def _permission_matches_asset(*, permission, asset, node_lookup) -> bool:
    asset_id = str(asset.get("id") or "")
    asset_ids = {str(obj.get("id", obj)) for obj in permission.get("assets", [])}
    if asset_id and asset_id in asset_ids:
        return True

    asset_label_ids = {str(obj.get("id", obj)) for obj in asset.get("labels", [])}
    permission_label_ids = {str(obj.get("id", obj)) for obj in permission.get("labels", [])}
    if asset_label_ids and permission_label_ids and (asset_label_ids & permission_label_ids):
        return True

    asset_paths = set()
    for node in asset.get("nodes", []):
        if isinstance(node, dict):
            node_id = str(node.get("id") or "")
            full_value = _node_full_value(
                node_lookup,
                node_id,
                fallback_name=str(node.get("name") or node.get("value") or ""),
            )
            if full_value:
                asset_paths.add(full_value)
    for display in asset.get("nodes_display", []) or []:
        display_text = str(display or "").strip()
        if display_text:
            asset_paths.add(display_text)

    permission_paths = set()
    for node in permission.get("nodes", []):
        if isinstance(node, dict):
            node_id = str(node.get("id") or "")
            full_value = _node_full_value(
                node_lookup,
                node_id,
                fallback_name=str(node.get("name") or node.get("value") or ""),
            )
        else:
            full_value = _node_full_value(node_lookup, str(node))
        if full_value:
            permission_paths.add(full_value)

    for asset_path in asset_paths:
        for permission_path in permission_paths:
            prefix = permission_path.rstrip("/") + "/"
            if asset_path == permission_path or asset_path.startswith(prefix):
                return True
    return False


def _user_asset_access(args: argparse.Namespace):
    _validate_user_selector(args)
    _validate_asset_selector(args)
    ensure_selected_org_context()
    from jumpserver_api.jms_analytics import _list_permissions, _resolve_asset, _resolve_user

    client = create_client()
    user = _resolve_user(args.user_id, args.username)
    user_group_ids = {str(item.get("id", item)) for item in user.get("groups", [])}
    asset = _resolve_asset(args.asset_id, args.asset_name)
    node_lookup = {str(item.get("id") or ""): item for item in _effective_user_access(user).get("nodes", []) if isinstance(item, dict)}
    permed_accounts = set()
    permed_protocols = set()
    matched_permissions = []
    for item in _list_permissions():
        permission_id = str(item.get("id") or "").strip()
        if not permission_id:
            continue
        detail = client.get("/api/v1/perms/asset-permissions/%s/" % permission_id)
        user_ids = {str(obj.get("id", obj)) for obj in detail.get("users", [])}
        group_ids = {str(obj.get("id", obj)) for obj in detail.get("user_groups", [])}
        if str(user.get("id")) not in user_ids and not (group_ids & user_group_ids):
            continue
        if not _permission_matches_asset(permission=detail, asset=asset, node_lookup=node_lookup):
            continue
        matched_permissions.append({"id": detail.get("id"), "name": detail.get("name")})
        for account in detail.get("accounts", []):
            if isinstance(account, dict):
                permed_accounts.add(str(account.get("name") or account.get("username") or account.get("id")))
            else:
                permed_accounts.add(str(account))
        for protocol in detail.get("protocols", []):
            if isinstance(protocol, dict):
                permed_protocols.add(str(protocol.get("name") or protocol.get("value") or protocol.get("label")))
            else:
                permed_protocols.add(str(protocol))
    return {
        "user": user,
        "asset": asset,
        "permed_accounts": sorted(permed_accounts),
        "permed_protocols": sorted(permed_protocols),
        "matched_permissions": matched_permissions,
    }


def _format_recent_audit_record(audit_type: str, item: dict, *, filters: dict | None = None) -> dict:
    active_filters = dict(filters or {})
    asset_filter = active_filters.get("asset")
    record = {
        "id": item.get("id"),
        "user": _extract_user(item) or None,
        "asset": _extract_asset(item) or None,
        "account": _extract_account(item) or None,
        "protocol": _extract_protocol(item) or None,
        "source_ip": _extract_source_ip(item) or None,
        "status": _extract_status(item) or None,
        "timestamp": _extract_datetime(item),
        "duration_seconds": _extract_duration(item),
        "data_source": item.get("_data_source") or None,
        "filter_strategy": item.get("_filter_strategy") or None,
        "asset_evidence": _asset_filter_evidence(item, expected=asset_filter),
        "raw": item,
    }
    if audit_type == "command":
        record["command"] = str(item.get("input") or item.get("command") or "").strip() or None
    elif audit_type == "login":
        record["reason"] = str(item.get("reason") or item.get("detail") or "").strip() or None
    elif audit_type == "operate":
        record["action"] = str(item.get("operate") or item.get("action") or item.get("type") or "").strip() or None
    return record



def _recent_audit(args: argparse.Namespace):
    context = ensure_selected_org_context()
    filters = _normalize_time_filters(parse_json_arg(args.filters), default_days=7)
    handlers = {
        "login": _login_records,
        "session": _fetch_session_records,
        "command": _fetch_command_records,
    }
    if args.audit_type == "operate":
        client = create_client()
        server_filters = _server_filters(filters)
        result = client.list_paginated("/api/v1/audits/operate-logs/", params=server_filters)
        records = _apply_common_filters([item for item in result if isinstance(item, dict)], filters)
    else:
        records = handlers[args.audit_type](filters)
    limit = int(filters.get("limit") or 20)
    formatted = [_format_recent_audit_record(args.audit_type, item, filters=filters) for item in records[:limit]]
    result = {
        "audit_type": args.audit_type,
        "summary": {
            "total": len(records),
            "returned": len(formatted),
            "filters": {key: value for key, value in filters.items() if not str(key).startswith("_")},
            "data_sources": sorted({item.get("_data_source") for item in records if isinstance(item, dict) and item.get("_data_source")}),
            "filter_strategies": sorted({item.get("_filter_strategy") for item in records if isinstance(item, dict) and item.get("_filter_strategy")}),
        },
        "records": formatted,
        **org_context_output(context),
    }
    if args.audit_type == "command":
        from jumpserver_api.jms_analytics import resolve_command_storage_context

        result.update(resolve_command_storage_context(filters))
    return result


def _settings_category(args: argparse.Namespace):
    ensure_selected_org_context()
    filters = parse_json_arg(args.filters, default={"category": args.category})
    filters.setdefault("category", args.category)
    return run_capability("setting-category-query", filters)


def _license_detail(_: argparse.Namespace):
    ensure_selected_org_context()
    return run_capability("license-detail-query", {})


def _tickets(args: argparse.Namespace):
    ensure_selected_org_context()
    filters = parse_json_arg(args.filters)
    return run_capability("ticket-list-query", filters)


def _command_storages(args: argparse.Namespace):
    ensure_selected_org_context()
    filters = parse_json_arg(args.filters)
    return run_capability("command-storage-query", filters)


def _replay_storages(args: argparse.Namespace):
    ensure_selected_org_context()
    filters = parse_json_arg(args.filters)
    return run_capability("replay-storage-query", filters)


def _terminals(args: argparse.Namespace):
    ensure_selected_org_context()
    filters = parse_json_arg(args.filters)
    return run_capability("terminal-component-query", filters)


def _reports(args: argparse.Namespace):
    ensure_selected_org_context()
    filters = parse_json_arg(args.filters, default={"report_type": args.report_type})
    filters.setdefault("report_type", args.report_type)
    if args.days is not None and filters.get("days") in {None, ""}:
        filters["days"] = args.days
    return run_capability("report-query", filters)


def _account_automations(args: argparse.Namespace):
    ensure_selected_org_context()
    filters = parse_json_arg(args.filters)
    return run_capability("account-automation-overview", filters)


def _endpoint_inventory(args: argparse.Namespace):
    ensure_selected_org_context()
    discovery = create_discovery()
    return discovery.core_inventory_payload(refresh=args.refresh)


def _endpoint_verify(args: argparse.Namespace):
    ensure_selected_org_context()
    client = create_client()
    filters = parse_json_arg(args.filters)
    path = str(args.path or filters.get("path") or "").strip()
    if not path:
        raise CLIError("Provide --path or filters.path.")
    method = str(args.method or filters.get("method") or "GET").strip().upper()
    params = filters.get("params") if isinstance(filters.get("params"), dict) else None
    if method == "OPTIONS":
        payload = client.options(path, params=params)
    elif method == "GET":
        payload = client.get(path, params=params)
    else:
        raise CLIError("Unsupported verification method: %s" % method)
    return {"method": method, "path": path, "payload": payload}


def _inspect(args: argparse.Namespace):
    filters = parse_json_arg(args.filters)
    return run_capability(args.capability, filters)


def _capabilities(_: argparse.Namespace):
    return [
        {
            "id": item.capability_id,
            "name": item.name,
            "category": item.category,
            "priority": item.priority,
            "entrypoint": item.entrypoint,
        }
        for item in CAPABILITIES
        if item.entrypoint.startswith("jms_diagnose.py")
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JumpServer diagnostics, inventory and settings inspection.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_status_parser = subparsers.add_parser("config-status")
    config_status_parser.add_argument("--json", action="store_true")
    config_status_parser.set_defaults(func=_config_status)

    config_write_parser = subparsers.add_parser("config-write")
    config_write_parser.add_argument("--payload", required=True)
    config_write_parser.add_argument("--confirm", action="store_true")
    config_write_parser.set_defaults(func=_config_write)

    ping_parser = subparsers.add_parser("ping")
    ping_parser.set_defaults(func=_ping)

    select_org_parser = subparsers.add_parser("select-org")
    select_org_parser.add_argument("--org-id")
    select_org_parser.add_argument("--confirm", action="store_true")
    select_org_parser.set_defaults(func=_select_org)

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("--resource", required=True, choices=["asset", "node", "user", "user-group", "organization", "account", "platform", "permission"])
    resolve_parser.add_argument("--id")
    resolve_parser.add_argument("--name")
    resolve_parser.add_argument("--filters")
    resolve_parser.set_defaults(func=_resolve)

    resolve_platform_parser = subparsers.add_parser("resolve-platform")
    resolve_platform_parser.add_argument("--value", required=True)
    resolve_platform_parser.set_defaults(func=_resolve_platform)

    user_assets_parser = subparsers.add_parser("user-assets")
    user_assets_parser.add_argument("--user-id")
    user_assets_parser.add_argument("--username", "--user-name", dest="username")
    user_assets_parser.set_defaults(func=_user_assets)

    user_nodes_parser = subparsers.add_parser("user-nodes")
    user_nodes_parser.add_argument("--user-id")
    user_nodes_parser.add_argument("--username", "--user-name", dest="username")
    user_nodes_parser.set_defaults(func=_user_nodes)

    user_asset_access_parser = subparsers.add_parser("user-asset-access")
    user_asset_access_parser.add_argument("--user-id")
    user_asset_access_parser.add_argument("--username", "--user-name", dest="username")
    user_asset_access_parser.add_argument("--asset-id")
    user_asset_access_parser.add_argument("--asset-name")
    user_asset_access_parser.set_defaults(func=_user_asset_access)

    recent_audit_parser = subparsers.add_parser("recent-audit")
    recent_audit_parser.add_argument("--audit-type", required=True, choices=["operate", "login", "session", "command"])
    recent_audit_parser.add_argument("--filters")
    recent_audit_parser.set_defaults(func=_recent_audit)

    settings_category_parser = subparsers.add_parser("settings-category")
    settings_category_parser.add_argument("--category", required=True)
    settings_category_parser.add_argument("--filters")
    settings_category_parser.set_defaults(func=_settings_category)

    license_parser = subparsers.add_parser("license-detail")
    license_parser.set_defaults(func=_license_detail)

    tickets_parser = subparsers.add_parser("tickets")
    tickets_parser.add_argument("--filters")
    tickets_parser.set_defaults(func=_tickets)

    command_storages_parser = subparsers.add_parser("command-storages")
    command_storages_parser.add_argument("--filters")
    command_storages_parser.set_defaults(func=_command_storages)

    replay_storages_parser = subparsers.add_parser("replay-storages")
    replay_storages_parser.add_argument("--filters")
    replay_storages_parser.set_defaults(func=_replay_storages)

    terminals_parser = subparsers.add_parser("terminals")
    terminals_parser.add_argument("--filters")
    terminals_parser.set_defaults(func=_terminals)

    reports_parser = subparsers.add_parser("reports")
    reports_parser.add_argument(
        "--report-type",
        required=True,
        choices=[
            "account-statistic",
            "account-automation",
            "asset-statistic",
            "asset-activity",
            "users",
            "user-change-password",
            "pam-dashboard",
            "change-secret-dashboard",
        ],
    )
    reports_parser.add_argument("--days", type=int)
    reports_parser.add_argument("--filters")
    reports_parser.set_defaults(func=_reports)

    account_automations_parser = subparsers.add_parser("account-automations")
    account_automations_parser.add_argument("--filters")
    account_automations_parser.set_defaults(func=_account_automations)

    endpoint_inventory_parser = subparsers.add_parser("endpoint-inventory")
    endpoint_inventory_parser.add_argument("--refresh", action="store_true")
    endpoint_inventory_parser.set_defaults(func=_endpoint_inventory)

    endpoint_verify_parser = subparsers.add_parser("endpoint-verify")
    endpoint_verify_parser.add_argument("--path")
    endpoint_verify_parser.add_argument("--method", choices=["GET", "OPTIONS"], default="GET")
    endpoint_verify_parser.add_argument("--filters")
    endpoint_verify_parser.set_defaults(func=_endpoint_verify)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--capability", required=True)
    inspect_parser.add_argument("--filters")
    inspect_parser.set_defaults(func=_inspect)

    capabilities_parser = subparsers.add_parser("capabilities")
    capabilities_parser.set_defaults(func=_capabilities)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_and_print(args.func, args)


if __name__ == "__main__":
    raise SystemExit(main())
