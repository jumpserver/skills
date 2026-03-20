#!/usr/bin/env python3
"""JumpServer audit queries."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from jms_bootstrap import bootstrap_runtime

bootstrap_runtime()

import argparse
from datetime import datetime, timedelta
from typing import Any

from jms_runtime import (
    ensure_selected_org_context,
    import_string,
    parse_json_arg,
    run_and_print,
    run_request,
)


AUDIT_TYPES: dict[str, dict[str, Any]] = {
    "operate": {
        "list": "jms_client.v1.models.request.audits.operate_logs.DescribeOperateLogsRequest",
        "detail": "jms_client.v1.models.request.audits.operate_logs.DetailOperateLogRequest",
    },
    "login": {
        "list": "jms_client.v1.models.request.audits.login_logs.DescribeLoginLogsRequest",
        "detail": "jms_client.v1.models.request.audits.login_logs.DetailLoginLogRequest",
    },
    "session": {
        "list": "jms_client.v1.models.request.audits.sessions.DescribeSessionsRequest",
        "detail": "jms_client.v1.models.request.audits.sessions.DetailSessionRequest",
    },
    "command": {
        "list": "jms_client.v1.models.request.audits.commands.DescribeCommandsRequest",
        "detail": "jms_client.v1.models.request.audits.commands.DetailCommandRequest",
    },
}

AUDIT_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_AUDIT_WINDOW_DAYS = 7


def validate_audit_payload(audit_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if audit_type == "command" and not payload.get("command_storage_id"):
        raise RuntimeError(
            "audit-type=command requires --filters "
            '\'{"command_storage_id":"<command-storage-id>"}\'.'
        )
    return payload


def _parse_audit_datetime(value: Any, *, field: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, AUDIT_DATETIME_FORMAT)
    except ValueError as exc:
        raise RuntimeError(
            f"{field} must use format '{AUDIT_DATETIME_FORMAT}'."
        ) from exc


def normalize_audit_payload(audit_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_audit_payload(audit_type, dict(payload))
    start = _parse_audit_datetime(normalized.get("date_from"), field="date_from")
    end = _parse_audit_datetime(normalized.get("date_to"), field="date_to")
    now = datetime.now()

    if start is None and end is None:
        end = now
        start = end - timedelta(days=DEFAULT_AUDIT_WINDOW_DAYS)
    elif start is None:
        start = end - timedelta(days=DEFAULT_AUDIT_WINDOW_DAYS)
    elif end is None:
        end = now

    if start > end:
        raise RuntimeError("date_from must be earlier than or equal to date_to.")

    normalized["date_from"] = start.strftime(AUDIT_DATETIME_FORMAT)
    normalized["date_to"] = end.strftime(AUDIT_DATETIME_FORMAT)
    return normalized


def run_paginated_audit_list(request_cls, payload: dict[str, Any]):
    if "limit" in payload or "offset" in payload:
        return run_request(request_cls(**payload), with_model=True)

    page_size = 200
    page_offset = 0
    combined: list[Any] = []
    while True:
        page_payload = dict(payload)
        page_payload["limit"] = page_size
        page_payload["offset"] = page_offset
        result = run_request(request_cls(**page_payload), with_model=True)
        if not isinstance(result, list):
            raise RuntimeError("Audit list API did not return a list.")
        combined.extend(result)
        if len(result) < page_size:
            break
        page_offset += len(result)
    return combined


def list_events(args: argparse.Namespace):
    payload = normalize_audit_payload(args.audit_type, parse_json_arg(args.filters))
    request_cls = import_string(AUDIT_TYPES[args.audit_type]["list"])
    return run_paginated_audit_list(request_cls, payload)


def get_event(args: argparse.Namespace):
    payload = normalize_audit_payload(args.audit_type, parse_json_arg(args.filters))
    payload["id_"] = args.id
    request_cls = import_string(AUDIT_TYPES[args.audit_type]["detail"])
    return run_request(request_cls(**payload), with_model=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit_types = sorted(AUDIT_TYPES)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--audit-type", required=True, choices=audit_types)
    list_parser.add_argument("--filters", help="JSON filter object")
    list_parser.set_defaults(func=list_events)

    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("--audit-type", required=True, choices=audit_types)
    get_parser.add_argument("--id", required=True)
    get_parser.add_argument(
        "--filters",
        help="Extra JSON payload; command audits require command_storage_id",
    )
    get_parser.set_defaults(func=get_event)

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
