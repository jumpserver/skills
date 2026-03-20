#!/usr/bin/env python3
"""Environment initialization and read-only diagnostics for JumpServer."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from jms_bootstrap import bootstrap_runtime

bootstrap_runtime()

import argparse

from jms_runtime import (
    ORG_SELECTION_NEXT_STEP,
    ensure_selected_org_context,
    get_accessible_orgs,
    get_config_status,
    get_user_profile,
    import_string,
    parse_json_arg,
    persist_selected_org,
    require_confirmation,
    resolve_effective_org_context,
    run_and_print,
    run_request,
    serialize,
    write_local_env_config,
)

from jms_assets import build_request, get_node_object, list_node_objects, resolve_platform_reference
from jms_audit import AUDIT_TYPES, normalize_audit_payload
from jms_client.v1.models.request.assets.assets import DescribeUserPermAssetsRequest
from jms_client.v1.models.request.common import Request
from jms_client.v1.models.request.mixins import WithIDMixin


class UserPermNodesRequest(WithIDMixin, Request):
    URL = "perms/users/{id}/nodes/"


class UserPermAssetAccessRequest(Request):
    URL = "perms/users/{user_id}/assets/{asset_id}/"

    def __init__(self, user_id: str, asset_id: str):
        if not user_id:
            raise ValueError("Param [user_id] is required")
        if not asset_id:
            raise ValueError("Param [asset_id] is required")
        self.user_id = user_id
        self.asset_id = asset_id
        super().__init__()

    def get_url(self):
        return f"{self.url_prefix}{self.URL.format(user_id=self.user_id, asset_id=self.asset_id)}"


def ping(_: argparse.Namespace):
    profile = get_user_profile()
    accessible_orgs = get_accessible_orgs(profile=profile)
    context = resolve_effective_org_context(accessible_orgs=accessible_orgs)
    effective_org = context.get("effective_org")
    result = dict(profile)
    result["derived_accessible_orgs"] = context["accessible_orgs"]
    result["effective_org"] = effective_org
    result["org_source"] = effective_org.get("source") if isinstance(effective_org, dict) else None
    result["multiple_accessible_orgs"] = context["multiple_accessible_orgs"]
    result["selection_required"] = context["selection_required"]
    result["candidate_orgs"] = context["candidate_orgs"]
    result["reserved_org_auto_select_eligible"] = context["reserved_org_auto_select_eligible"]
    result["selected_org_accessible"] = context["selected_org_accessible"]
    return result


def config_status(_: argparse.Namespace):
    return get_config_status()


def config_write(args: argparse.Namespace):
    require_confirmation(args)
    return write_local_env_config(parse_json_arg(args.payload))


def select_org(args: argparse.Namespace):
    accessible_orgs = get_accessible_orgs()
    if not accessible_orgs:
        raise RuntimeError("Current account cannot enumerate any accessible organizations.")

    if not args.org_id:
        return {
            "selection_required": True,
            "candidate_orgs": accessible_orgs,
            "next_step": ORG_SELECTION_NEXT_STEP,
            "reserved_org_auto_select_eligible": (
                resolve_effective_org_context(accessible_orgs=accessible_orgs)[
                    "reserved_org_auto_select_eligible"
                ]
            ),
            "message": "Choose one organization, then rerun with --confirm to persist JMS_ORG_ID.",
        }

    selected = next(
        (item for item in accessible_orgs if str(item.get("id") or "") == args.org_id),
        None,
    )
    if not isinstance(selected, dict):
        raise RuntimeError(f"Organization {args.org_id!r} is not accessible in the current environment.")

    effective_org = dict(selected)
    effective_org["source"] = "user_selected"
    if not args.confirm:
        return {
            "selection_required": False,
            "effective_org": effective_org,
            "org_source": effective_org["source"],
            "candidate_orgs": accessible_orgs,
            "next_step": f"python3 scripts/jms_diagnose.py select-org --org-id {args.org_id} --confirm",
            "message": "Review the selected organization, then rerun with --confirm to persist JMS_ORG_ID.",
        }

    require_confirmation(args)
    persisted = persist_selected_org(args.org_id)
    return {
        "selection_required": False,
        "effective_org": effective_org,
        "org_source": effective_org["source"],
        "current_nonsecret": persisted.get("current_nonsecret", {}),
        "env_file_path": persisted.get("env_file_path"),
        "message": "Selected organization has been written to .env.local and reloaded.",
    }


def resolve_object(args: argparse.Namespace):
    payload = parse_json_arg(args.filters)
    if args.resource == "node":
        node_org_id = str(payload.get("org_id") or "").strip() or None
        if args.id:
            return get_node_object(args.id, org_id=node_org_id)
        if args.name:
            payload["value"] = args.name
        return list_node_objects(payload)

    if args.id:
        request = build_request(args.resource, "detail", {"id_": args.id})
    else:
        if args.name:
            if args.resource == "account":
                payload["username"] = args.name
            else:
                payload["name"] = args.name
        request = build_request(args.resource, "list", payload)
    return run_request(request, with_model=True)


def resolve_platform(args: argparse.Namespace):
    return resolve_platform_reference(args.value)


def recent_audit(args: argparse.Namespace):
    payload = normalize_audit_payload(args.audit_type, parse_json_arg(args.filters))
    request_cls = import_string(AUDIT_TYPES[args.audit_type]["list"])
    return run_request(request_cls(**payload), with_model=True)


def _validate_pagination_args(args: argparse.Namespace) -> dict[str, int | None]:
    if args.limit is not None and args.limit <= 0:
        raise RuntimeError("--limit must be greater than 0.")
    if args.offset < 0:
        raise RuntimeError("--offset must be greater than or equal to 0.")
    return {"limit": args.limit, "offset": args.offset}


def _run_paginated_request(request_factory, *, limit: int | None, offset: int):
    if limit is not None:
        return run_request(request_factory(limit, offset), with_model=False)

    page_size = 200
    page_offset = offset
    combined = []
    while True:
        batch = run_request(request_factory(page_size, page_offset), with_model=False)
        if not isinstance(batch, list):
            raise RuntimeError("Expected paginated request to return a list result.")
        combined.extend(batch)
        if len(batch) < page_size:
            break
        page_offset += len(batch)
    return combined


def _resolve_target_reference_id(
    *,
    resource: str,
    id_value: str | None,
    name_value: str | None,
    id_flag: str,
    name_flag: str,
    name_field: str,
    label: str,
) -> str:
    if bool(id_value) == bool(name_value):
        raise RuntimeError(f"Provide exactly one of {id_flag} or {name_flag}.")
    if id_value:
        return id_value

    request = build_request(resource, "list", {name_field: name_value})
    result = serialize(run_request(request, with_model=True))
    if not isinstance(result, list):
        raise RuntimeError(f"Expected {label} lookup to return a list result.")
    if not result:
        raise RuntimeError(f"No {label} found for {name_field} '{name_value}'.")
    if len(result) > 1:
        raise RuntimeError(
            f"Multiple {label}s found for {name_field} '{name_value}'. Use {id_flag}."
        )
    resolved_id = result[0].get("id")
    if not resolved_id:
        raise RuntimeError(f"Resolved {label} is missing an 'id' field.")
    return str(resolved_id)


def _resolve_target_user_id(args: argparse.Namespace) -> str:
    return _resolve_target_reference_id(
        resource="user",
        id_value=args.user_id,
        name_value=args.username,
        id_flag="--user-id",
        name_flag="--username",
        name_field="username",
        label="user",
    )


def _resolve_target_asset_id(args: argparse.Namespace) -> str:
    return _resolve_target_reference_id(
        resource="asset",
        id_value=args.asset_id,
        name_value=args.asset_name,
        id_flag="--asset-id",
        name_flag="--asset-name",
        name_field="name",
        label="asset",
    )


def _describe_user_scope(
    args: argparse.Namespace,
    request_cls: type[Request],
):
    pagination = _validate_pagination_args(args)
    user_id = _resolve_target_user_id(args)
    return _run_paginated_request(
        lambda limit, offset: request_cls(id_=user_id, limit=limit, offset=offset),
        limit=pagination["limit"],
        offset=pagination["offset"],
    )


def describe_user_assets(args: argparse.Namespace):
    pagination = _validate_pagination_args(args)
    user_id = _resolve_target_user_id(args)
    return _run_paginated_request(
        lambda limit, offset: DescribeUserPermAssetsRequest(
            user_id=user_id,
            limit=limit,
            offset=offset,
        ),
        limit=pagination["limit"],
        offset=pagination["offset"],
    )


def describe_user_nodes(args: argparse.Namespace):
    return _describe_user_scope(args, UserPermNodesRequest)


def describe_user_asset_access(args: argparse.Namespace):
    user_id = _resolve_target_user_id(args)
    asset_id = _resolve_target_asset_id(args)
    return run_request(
        UserPermAssetAccessRequest(user_id=user_id, asset_id=asset_id),
        with_model=False,
    )


def _add_target_user_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--user-id")
    parser.add_argument("--username")


def _add_target_asset_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--asset-id")
    parser.add_argument("--asset-name")


def _add_pagination_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum items to return. Omit to auto-paginate and fetch all results.",
    )
    parser.add_argument("--offset", type=int, default=0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_status_parser = subparsers.add_parser("config-status")
    config_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Accepted for explicitness. Output is always JSON.",
    )
    config_status_parser.set_defaults(func=config_status)

    config_write_parser = subparsers.add_parser("config-write")
    config_write_parser.add_argument("--payload", required=True, help="JSON config object")
    config_write_parser.add_argument("--confirm", action="store_true")
    config_write_parser.set_defaults(func=config_write)

    ping_parser = subparsers.add_parser("ping")
    ping_parser.set_defaults(func=ping)

    select_org_parser = subparsers.add_parser("select-org")
    select_org_parser.add_argument("--org-id")
    select_org_parser.add_argument("--confirm", action="store_true")
    select_org_parser.set_defaults(func=select_org)

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument(
        "--resource",
        required=True,
        choices=["asset", "node", "platform", "account", "user", "user-group", "organization"],
    )
    resolve_parser.add_argument("--id")
    resolve_parser.add_argument("--name")
    resolve_parser.add_argument("--filters", help="JSON filter object")
    resolve_parser.set_defaults(func=resolve_object)

    resolve_platform_parser = subparsers.add_parser("resolve-platform")
    resolve_platform_parser.add_argument("--value", required=True)
    resolve_platform_parser.set_defaults(func=resolve_platform)

    user_assets_parser = subparsers.add_parser("user-assets")
    _add_target_user_arguments(user_assets_parser)
    _add_pagination_arguments(user_assets_parser)
    user_assets_parser.set_defaults(func=describe_user_assets)

    user_nodes_parser = subparsers.add_parser("user-nodes")
    _add_target_user_arguments(user_nodes_parser)
    _add_pagination_arguments(user_nodes_parser)
    user_nodes_parser.set_defaults(func=describe_user_nodes)

    user_asset_access_parser = subparsers.add_parser("user-asset-access")
    _add_target_user_arguments(user_asset_access_parser)
    _add_target_asset_arguments(user_asset_access_parser)
    user_asset_access_parser.set_defaults(func=describe_user_asset_access)

    audit_parser = subparsers.add_parser("recent-audit")
    audit_parser.add_argument("--audit-type", required=True, choices=sorted(AUDIT_TYPES))
    audit_parser.add_argument("--filters", help="JSON filter object")
    audit_parser.set_defaults(func=recent_audit)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command not in {"config-status", "config-write", "ping", "select-org"}:
        original = args.func

        def guarded(ns: argparse.Namespace, _func=original):
            ensure_selected_org_context()
            return _func(ns)

        args.func = guarded
    return run_and_print(args.func, args)


if __name__ == "__main__":
    raise SystemExit(main())
