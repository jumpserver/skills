#!/usr/bin/env python3
"""JumpServer read-only permission queries."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from jms_bootstrap import bootstrap_runtime

bootstrap_runtime()

import argparse
from typing import Any

from jms_runtime import (
    ensure_selected_org_context,
    import_string,
    parse_json_arg,
    run_and_print,
    run_request_in_org,
    serialize,
)


ACCOUNT_DISPLAY_ALIASES = {
    "@INPUT": "手动账号",
    "@USER": "同名账号",
    "@ANON": "匿名账号",
    "@ALL": "所有账号",
    "@SPEC": "指定账号",
}


def _display_permission_result(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "accounts":
                result[key] = _display_permission_result_accounts(item)
            else:
                result[key] = _display_permission_result(item)
        return result
    if isinstance(value, list):
        return [_display_permission_result(item) for item in value]
    return value


def _display_permission_result_accounts(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    result: list[Any] = []
    for item in value:
        if isinstance(item, str):
            result.append(ACCOUNT_DISPLAY_ALIASES.get(item, item))
        else:
            result.append(item)
    return result


def display_permission_result(value: Any) -> Any:
    return _display_permission_result(serialize(value))


def _current_org_id() -> str:
    context = ensure_selected_org_context()
    effective_org = context.get("effective_org")
    if not isinstance(effective_org, dict) or not effective_org.get("id"):
        raise RuntimeError(
            "A selected JMS_ORG_ID is required for permission queries."
        )
    return str(effective_org["id"])


def fetch_permission_detail(permission_id: str, *, org_id: str) -> dict[str, Any]:
    request_cls = import_string(
        "jms_client.v1.models.request.permissions.permissions.DetailPermissionRequest"
    )
    request = request_cls(id_=permission_id)
    return serialize(run_request_in_org(org_id, request, with_model=True))


def run_paginated_permission_list(payload: dict[str, Any], *, org_id: str) -> list[Any]:
    request_cls = import_string(
        "jms_client.v1.models.request.permissions.permissions.DescribePermissionsRequest"
    )
    if "limit" in payload or "offset" in payload:
        result = run_request_in_org(org_id, request_cls(**payload), with_model=True)
        if not isinstance(result, list):
            raise RuntimeError("Permission list API did not return a list.")
        return list(result)

    page_size = 200
    page_offset = 0
    combined: list[Any] = []
    while True:
        page_payload = dict(payload)
        page_payload["limit"] = page_size
        page_payload["offset"] = page_offset
        result = run_request_in_org(org_id, request_cls(**page_payload), with_model=True)
        if not isinstance(result, list):
            raise RuntimeError("Permission list API did not return a list.")
        combined.extend(result)
        if len(result) < page_size:
            break
        page_offset += len(result)
    return combined


def list_permissions(args: argparse.Namespace):
    return display_permission_result(
        run_paginated_permission_list(
            parse_json_arg(args.filters),
            org_id=_current_org_id(),
        )
    )


def get_permission(args: argparse.Namespace):
    return display_permission_result(
        fetch_permission_detail(
            args.id,
            org_id=_current_org_id(),
        )
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
