from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone, tzinfo
import json
import re
from typing import Any

from .jms_capabilities import CAPABILITY_BY_ID
from .jms_runtime import (
    CLIError,
    create_client,
    create_discovery,
    ensure_selected_org_context,
    is_uuid_like,
    org_context_output,
    parse_bool,
)


PERMISSION_PATH = "/api/v1/perms/asset-permissions/"
ACCOUNT_TEMPLATE_PATH = "/api/v1/accounts/account-templates/"
TERMINAL_COMMANDS_PATH = "/api/v1/terminal/commands/"
TERMINAL_SESSIONS_PATH = "/api/v1/terminal/sessions/"
TERMINAL_STATUS_PATH = "/api/v1/terminal/status/"
TERMINALS_PATH = "/api/v1/terminal/terminals/"
REPLAY_STORAGES_PATH = "/api/v1/terminal/replay-storages/"
COMMAND_STORAGES_PATH = "/api/v1/terminal/command-storages/"
ENDPOINT_RULES_PATH = "/api/v1/terminal/endpoint-rules/"
ROLE_BINDINGS_PATH = "/api/v1/rbac/role-bindings/"
ORG_ROLE_BINDINGS_PATH = "/api/v1/rbac/org-role-bindings/"
SYSTEM_ROLE_BINDINGS_PATH = "/api/v1/rbac/system-role-bindings/"
ROLES_PATH = "/api/v1/rbac/roles/"
CANONICAL_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_INPUT_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
)
DATETIME_INPUT_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y/%m/%d %H:%M:%S %z",
)
BASIC_NAIVE_DATETIME_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2}$")


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def parse_date_value(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    for fmt in DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime_value(value: Any, *, naive_tz: tzinfo | None = timezone.utc) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None and naive_tz is not None:
            return value.replace(tzinfo=naive_tz)
        return value
    if isinstance(value, date):
        parsed = datetime.combine(value, time())
        if naive_tz is not None:
            parsed = parsed.replace(tzinfo=naive_tz)
        return parsed
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)

    text = str(value).strip()
    if not text:
        return None

    for fmt in DATETIME_INPUT_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None and naive_tz is not None:
            parsed = parsed.replace(tzinfo=naive_tz)
        return parsed
    return None


def normalize_basic_datetime_text(value: Any, *, naive_tz: tzinfo | None = timezone.utc) -> str | None:
    text = str(value or "").strip()
    if not BASIC_NAIVE_DATETIME_RE.fullmatch(text):
        return None
    parsed = parse_datetime_value(text, naive_tz=naive_tz)
    if parsed is None:
        return None
    return parsed.strftime(CANONICAL_DATETIME_FORMAT)


def _is_empty_like(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _coalesce(*values: Any) -> Any:
    for value in values:
        if _is_empty_like(value):
            continue
        return value
    return None


def _value_from_path(item: dict[str, Any], path: str) -> Any:
    current: Any = item
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _string_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(
            _coalesce(
                value.get("label"),
                value.get("value"),
                value.get("name"),
                value.get("username"),
                value.get("id"),
            )
            or ""
        )
    return str(value or "")


def _simplify_display_name(value: Any) -> str:
    text = _string_value(value).strip()
    if "(" in text and text.endswith(")"):
        prefix, suffix = text.rsplit("(", 1)
        prefix = prefix.strip()
        inner = suffix[:-1].strip()
        if prefix:
            return prefix
        if inner:
            return inner
    return text


def _first_field(item: dict[str, Any], *candidates: str) -> Any:
    for path in candidates:
        value = _value_from_path(item, path)
        if not _is_empty_like(value):
            return value
    return None


def _extract_identifier(item: dict[str, Any], *candidates: str) -> str:
    value = _first_field(item, *candidates)
    return _string_value(value).strip()


def _extract_user(item: dict[str, Any]) -> str:
    return _extract_identifier(
        item,
        "user",
        "user_display",
        "user.username",
        "user.name",
        "username",
        "created_by",
    )


def _extract_asset(item: dict[str, Any]) -> str:
    return _simplify_display_name(
        _extract_identifier(
            item,
            "asset",
            "asset_display",
            "asset.name",
            "asset.address",
            "name",
            "hostname",
            "target",
        )
    )


def _extract_asset_id(item: dict[str, Any]) -> str:
    return _extract_identifier(item, "asset_id", "asset.id")


def _append_unique_text(target: list[str], seen: set[str], value: Any, *, simplify: bool = False) -> None:
    text = _string_value(value).strip()
    if not text:
        return
    candidates = [text]
    if simplify:
        simplified = _simplify_display_name(text)
        if simplified and simplified != text:
            candidates.append(simplified)
    for candidate in candidates:
        key = _lower(candidate)
        if not candidate or key in seen:
            continue
        seen.add(key)
        target.append(candidate)


def _asset_candidate_values(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for path in ("asset", "asset_display", "asset.name", "asset.address", "name", "hostname", "target"):
        raw = _value_from_path(item, path)
        if isinstance(raw, dict):
            for key in ("name", "address", "label", "value", "id"):
                _append_unique_text(values, seen, raw.get(key), simplify=(key != "id"))
            _append_unique_text(values, seen, raw, simplify=True)
            continue
        _append_unique_text(values, seen, raw, simplify=True)
    _append_unique_text(values, seen, _extract_asset_id(item))
    return values


def _text_candidate_values(item: dict[str, Any], *paths: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for path in paths:
        raw = _value_from_path(item, path)
        if isinstance(raw, list):
            for entry in raw:
                _append_unique_text(values, seen, entry, simplify=True)
            continue
        if isinstance(raw, dict):
            for key in ("title", "name", "label", "value", "username", "serial_num", "id"):
                _append_unique_text(values, seen, raw.get(key), simplify=(key not in {"id", "serial_num"}))
            _append_unique_text(values, seen, raw, simplify=True)
            continue
        _append_unique_text(values, seen, raw, simplify=True)
    return values


def _exact_first_filter(items: list[dict[str, Any]], expected: Any, *paths: str) -> list[dict[str, Any]]:
    expected_text = str(expected or "").strip()
    expected_key = _lower(expected_text)
    if not expected_key:
        return list(items)
    exact: list[dict[str, Any]] = []
    fuzzy: list[dict[str, Any]] = []
    for item in items:
        candidates = _text_candidate_values(item, *paths)
        if any(_lower(value) == expected_key for value in candidates):
            exact.append(item)
            continue
        if any(expected_key in _lower(value) for value in candidates):
            fuzzy.append(item)
    return exact or fuzzy


def _asset_filter_evidence(item: dict[str, Any], expected: Any = None) -> dict[str, Any]:
    expected_text = str(expected or "").strip()
    candidates = _asset_candidate_values(item)
    matched_values = [value for value in candidates if expected_text and _lower(expected_text) in _lower(value)]
    return {
        "asset": _extract_asset(item) or None,
        "asset_id": _extract_asset_id(item) or None,
        "candidate_values": candidates,
        "matched_filter": expected_text or None,
        "matched_values": matched_values,
        "is_match": bool(matched_values) if expected_text else None,
    }


def _extract_account(item: dict[str, Any]) -> str:
    return _simplify_display_name(
        _extract_identifier(
            item,
            "account",
            "account_display",
            "account.username",
            "account.name",
            "username",
            "name",
        )
    )


def _extract_protocol(item: dict[str, Any]) -> str:
    return _extract_identifier(
        item,
        "protocol",
        "protocol_display",
        "connect_method",
        "terminal_type",
        "terminal_display",
        "type",
    )


def _extract_source_ip(item: dict[str, Any]) -> str:
    return _extract_identifier(
        item,
        "remote_addr",
        "remote_address",
        "src_ip",
        "source_ip",
        "ip",
        "client_ip",
    )


def _extract_status(item: dict[str, Any]) -> str:
    return _extract_identifier(
        item,
        "status",
        "status_display",
        "result",
        "reason",
        "type",
    )


def _extract_direction(item: dict[str, Any]) -> str:
    return _extract_identifier(item, "operate", "direction", "type", "action")


def _extract_datetime(item: dict[str, Any]) -> datetime | None:
    value = _first_field(
        item,
        "date_from",
        "date_to",
        "timestamp_display",
        "date_start",
        "date_end",
        "date_finished",
        "date_created",
        "date_expired",
        "datetime",
        "timestamp",
    )
    return parse_datetime_value(value, naive_tz=timezone.utc)


def _parse_datetime_value(value: Any) -> datetime | None:
    return parse_datetime_value(value, naive_tz=timezone.utc)


def _extract_duration(item: dict[str, Any]) -> float | None:
    raw = _first_field(item, "duration", "duration_display")
    if raw not in {None, ""}:
        try:
            return float(raw)
        except (TypeError, ValueError):
            text = str(raw).strip()
            if ":" in text:
                parts = text.split(":")
                try:
                    values = [float(part) for part in parts]
                except ValueError:
                    values = []
                if len(values) == 3:
                    return values[0] * 3600 + values[1] * 60 + values[2]
                if len(values) == 2:
                    return values[0] * 60 + values[1]
    start = _extract_datetime(item)
    end = _first_field(item, "date_end", "date_finished")
    if start and end:
        end_dt = _extract_datetime({"date_end": end})
        if end_dt:
            return max((end_dt - start).total_seconds(), 0.0)
    return None


def _match_text(value: str, expected: Any) -> bool:
    expected_text = _lower(expected)
    return not expected_text or expected_text in _lower(value)


def _match_time(record_time: datetime | None, filters: dict[str, Any]) -> bool:
    if record_time is None:
        return True
    if filters.get("_date_from") and record_time < filters["_date_from"]:
        return False
    if filters.get("_date_to") and record_time > filters["_date_to"]:
        return False
    return True


def _normalize_time_filters(filters: dict[str, Any], *, default_days: int = 7) -> dict[str, Any]:
    payload = dict(filters)
    now = datetime.now(timezone.utc)
    date_from = payload.get("date_from")
    date_to = payload.get("date_to")
    days = payload.get("days")
    if days not in {None, ""} and not date_from and not date_to:
        date_from = (now - timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
        date_to = now.strftime("%Y-%m-%d %H:%M:%S")
    if not date_from and not date_to:
        date_from = (now - timedelta(days=default_days)).strftime("%Y-%m-%d %H:%M:%S")
        date_to = now.strftime("%Y-%m-%d %H:%M:%S")
    if date_from not in {None, ""}:
        payload["date_from"] = normalize_basic_datetime_text(date_from, naive_tz=timezone.utc) or date_from
    if date_to not in {None, ""}:
        payload["date_to"] = normalize_basic_datetime_text(date_to, naive_tz=timezone.utc) or date_to
    payload["_date_from"] = _parse_datetime_value(payload.get("date_from"))
    payload["_date_to"] = _parse_datetime_value(payload.get("date_to")) or now
    return payload


def _server_filters(filters: dict[str, Any]) -> dict[str, Any]:
    payload = {}
    for key in (
        "date_from",
        "date_to",
        "limit",
        "offset",
        "search",
        "keyword",
        "status",
        "type",
        "user_id",
        "asset_id",
        "command_storage_id",
        "order",
        "is_finished",
        "users",
        "resource_type",
        "category",
        "days",
        "id",
        "node",
        "node_id",
        "asset",
        "display",
        "draw",
        "all",
    ):
        if filters.get(key) not in {None, ""}:
            payload[key] = filters[key]
    return payload


def _top(counter: Counter, *, limit: int = 10) -> list[dict[str, Any]]:
    items = []
    for key, count in counter.most_common(limit):
        items.append({"name": key, "count": count})
    return items


def _percentage(items: list[dict[str, Any]], total: int) -> list[dict[str, Any]]:
    final = []
    for item in items:
        payload = dict(item)
        payload["ratio"] = round((float(item["count"]) / total) * 100, 2) if total else 0.0
        final.append(payload)
    return final


def _match_asset_filter(item: dict[str, Any], expected: Any) -> bool:
    expected_text = _lower(expected)
    if not expected_text:
        return True
    return any(expected_text in _lower(value) for value in _asset_candidate_values(item))



def _apply_common_filters(items: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    final = []
    for item in items:
        timestamp = _extract_datetime(item)
        if not _match_time(timestamp, filters):
            continue
        if filters.get("user") and not _match_text(_extract_user(item), filters["user"]):
            continue
        if filters.get("asset") and not _match_asset_filter(item, filters["asset"]):
            continue
        if filters.get("account") and not _match_text(_extract_account(item), filters["account"]):
            continue
        if filters.get("protocol") and not _match_text(_extract_protocol(item), filters["protocol"]):
            continue
        if filters.get("source_ip") and not _match_text(_extract_source_ip(item), filters["source_ip"]):
            continue
        keyword = filters.get("keyword")
        if keyword:
            haystack = " ".join(
                [
                    _string_value(_first_field(item, "input", "output", "comment", "detail")),
                    _extract_user(item),
                    " ".join(_asset_candidate_values(item)),
                    _extract_account(item),
                    _extract_protocol(item),
                ]
            )
            if not _match_text(haystack, keyword):
                continue
        final.append(item)
    return final


def _sample(items: list[dict[str, Any]], *, size: int = 10) -> list[dict[str, Any]]:
    return items[:size]


def _empty_result(message: str, filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": {"message": message, "total": 0, "filters": {key: value for key, value in filters.items() if not str(key).startswith("_")}},
        "records": [],
    }


def _with_org_context(result: dict[str, Any]) -> dict[str, Any]:
    context = ensure_selected_org_context()
    payload = dict(result)
    payload.update(org_context_output(context))
    return payload


def _fetch_list(path: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
    client = create_client()
    result = client.list_paginated(path, params=_server_filters(filters))
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def _drop_local_time_only_filters(payload: dict[str, Any]) -> dict[str, Any]:
    server_payload = dict(payload)
    server_payload.pop("days", None)
    return server_payload


def _account_inventory_filters(payload: dict[str, Any]) -> dict[str, Any]:
    server_payload = dict(payload)
    for key in (
        "days",
        "date_from",
        "date_to",
        "_date_from",
        "_date_to",
        "limit",
        "offset",
        "top",
        "account",
        "asset",
        "privileged",
        "is_active",
    ):
        server_payload.pop(key, None)
    return server_payload


def _default_command_storage_id(filters: dict[str, Any]) -> str:
    if filters.get("command_storage_id") not in {None, ""}:
        return str(filters["command_storage_id"])
    storages = _fetch_list(COMMAND_STORAGES_PATH, filters)
    for item in storages:
        if isinstance(item, dict) and item.get("is_default") and item.get("id"):
            return str(item["id"])
    if len(storages) == 1 and isinstance(storages[0], dict) and storages[0].get("id"):
        return str(storages[0]["id"])
    return ""


def _command_storage_scope(filters: dict[str, Any]) -> str:
    return _lower(filters.get("command_storage_scope"))


def _use_all_command_storages(filters: dict[str, Any]) -> bool:
    return filters.get("command_storage_id") in {None, ""} and _command_storage_scope(filters) == "all"


def resolve_command_storage_context(filters: dict[str, Any]) -> dict[str, Any]:
    rows = _fetch_list(COMMAND_STORAGES_PATH, filters)
    storages = [item for item in rows if isinstance(item, dict)]
    explicit_storage_id = str(filters.get("command_storage_id") or "").strip()
    use_all_storages = _use_all_command_storages(filters)
    selected_storage = None
    selection_mode = "unresolved"
    if explicit_storage_id:
        selected_storage = next((item for item in storages if str(item.get("id") or "") == explicit_storage_id), None)
        if selected_storage is None and explicit_storage_id:
            selected_storage = {"id": explicit_storage_id}
        selection_mode = "explicit"
    elif use_all_storages:
        selection_mode = "all"
    else:
        for item in storages:
            if item.get("is_default") and item.get("id"):
                selected_storage = item
                selection_mode = "default"
                break
        if selected_storage is None and len(storages) == 1 and storages[0].get("id"):
            selected_storage = storages[0]
            selection_mode = "single_auto"
    selected_storage_id = str((selected_storage or {}).get("id") or "").strip() or None
    storage_ids = [str(item.get("id") or "").strip() for item in storages if str(item.get("id") or "").strip()]
    if selection_mode == "all":
        switchable_storages = list(storages)
    else:
        switchable_storages = [
            item for item in storages if str(item.get("id") or "").strip() and str(item.get("id") or "").strip() != str(selected_storage_id or "")
        ]
    hint = None
    if selection_mode == "all":
        if storages:
            hint = "当前已汇总全部 command storage 查询结果；如需限定范围，可在 filters.command_storage_id 中指定单个 storage。"
        else:
            hint = "当前请求要求汇总全部 command storage，但当前环境未返回可用 storage 列表。"
    elif selection_mode == "default" and switchable_storages:
        hint = "当前已按默认 command storage 查询；如需切换，可在 filters.command_storage_id 中指定其他 storage。"
    elif selection_mode == "single_auto":
        hint = "当前环境仅发现一个 command storage，已自动使用该 storage 查询。"
    elif selection_mode == "explicit" and switchable_storages:
        hint = "当前已按指定 command storage 查询；如需切换，可改用其他 storage 的 command_storage_id。"
    elif selection_mode == "unresolved" and len(storages) > 1:
        hint = "当前存在多个 command storage，且没有默认 storage；请显式指定 command_storage_id。"
    queried_storage_ids = storage_ids if selection_mode == "all" else ([selected_storage_id] if selected_storage_id else [])
    return {
        "selected_command_storage": selected_storage,
        "selected_command_storage_id": selected_storage_id,
        "selection_mode": selection_mode,
        "command_storage_scope": "all" if selection_mode == "all" else None,
        "queried_command_storage_ids": queried_storage_ids,
        "queried_command_storage_count": len(queried_storage_ids),
        "available_command_storages": storages,
        "available_command_storage_count": len(storages),
        "switchable_command_storages": switchable_storages,
        "selection_required": selection_mode == "unresolved" and len(storages) > 1,
        "command_storage_hint": hint,
        "default_storage_count": sum(1 for item in storages if parse_bool(item.get("is_default"))),
    }


def _with_command_storage_context(result: dict[str, Any], filters: dict[str, Any]) -> dict[str, Any]:
    payload = _with_org_context(result)
    payload.update(resolve_command_storage_context(filters))
    return payload


def _command_record_identity(item: dict[str, Any]) -> str:
    record_id = str(item.get("id") or "").strip()
    if record_id:
        return "id:%s" % record_id
    stable_payload = {key: value for key, value in item.items() if key not in {"_command_storage_id"}}
    return "json:%s" % json.dumps(stable_payload, sort_keys=True, ensure_ascii=False, default=str)


def _fetch_command_records_for_storage(payload: dict[str, Any], *, command_storage_id: str | None = None) -> list[dict[str, Any]]:
    server_payload = _drop_local_time_only_filters(dict(payload))
    if command_storage_id not in {None, ""}:
        server_payload["command_storage_id"] = command_storage_id
    elif server_payload.get("command_storage_id") in {None, ""}:
        server_payload.pop("command_storage_id", None)
    records = _apply_common_filters(_fetch_list(TERMINAL_COMMANDS_PATH, server_payload), payload)
    final: list[dict[str, Any]] = []
    for item in records:
        cloned = dict(item)
        if command_storage_id not in {None, ""}:
            cloned.setdefault("_command_storage_id", str(command_storage_id))
        final.append(cloned)
    return final


def _fetch_command_records(filters: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _normalize_time_filters(filters)
    if _use_all_command_storages(payload):
        storages = _fetch_list(COMMAND_STORAGES_PATH, payload)
        records = []
        seen_record_ids: set[str] = set()
        for storage in storages:
            storage_id = str((storage or {}).get("id") or "").strip()
            if not storage_id:
                continue
            for record in _fetch_command_records_for_storage(payload, command_storage_id=storage_id):
                record_identity = _command_record_identity(record)
                if record_identity in seen_record_ids:
                    continue
                seen_record_ids.add(record_identity)
                records.append(record)
    else:
        effective_storage_id = str(payload.get("command_storage_id") or "").strip()
        if not effective_storage_id:
            default_storage_id = _default_command_storage_id(payload)
            if default_storage_id:
                effective_storage_id = default_storage_id
                payload["command_storage_id"] = default_storage_id
        records = _fetch_command_records_for_storage(payload, command_storage_id=effective_storage_id or None)
    if payload.get("risk_level") not in {None, ""}:
        threshold = int(payload["risk_level"])
        records = [item for item in records if int(_first_field(item, "risk_level.value", "risk_level") or 0) >= threshold]
    records.sort(key=lambda item: _extract_datetime(item) or datetime.fromtimestamp(0, tz=timezone.utc), reverse=True)
    return records


def _fetch_terminal_session_records(filters: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = _normalize_time_filters(filters)
    query_payload = dict(payload)
    resolved_asset = None
    if query_payload.get("asset") and not query_payload.get("asset_id"):
        try:
            resolved_asset = _resolve_asset(name=str(query_payload.get("asset") or "").strip())
        except CLIError:
            resolved_asset = None
        if resolved_asset and resolved_asset.get("id"):
            query_payload["asset_id"] = resolved_asset.get("id")

    server_payload = _drop_local_time_only_filters(query_payload)
    if server_payload.get("asset_id"):
        server_payload.pop("asset", None)
    records = _fetch_list(TERMINAL_SESSIONS_PATH, server_payload)
    filtered = _apply_common_filters(records, payload)
    filter_strategy = "server"

    if payload.get("asset") and not filtered:
        fallback_payload = _drop_sampling_filters(dict(server_payload))
        fallback_payload.pop("asset", None)
        fallback_payload.pop("asset_id", None)
        records = _fetch_list(TERMINAL_SESSIONS_PATH, fallback_payload)
        filtered = _apply_common_filters(records, payload)
        filter_strategy = "local_asset_fallback"

    for item in filtered:
        if isinstance(item, dict):
            item.setdefault("_filter_strategy", filter_strategy)
            item.setdefault("_data_source", TERMINAL_SESSIONS_PATH)
    filtered.sort(key=lambda item: _extract_datetime(item) or datetime.fromtimestamp(0, tz=timezone.utc), reverse=True)
    return filtered, {"filter_strategy": filter_strategy, "resolved_asset": resolved_asset}



def _fetch_session_records(filters: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _normalize_time_filters(filters)
    records, _ = _fetch_terminal_session_records(payload)
    if not records:
        audit_payload = _drop_local_time_only_filters(dict(payload))
        filter_strategy = "audit_user_sessions_fallback"
        if payload.get("asset"):
            audit_payload = _drop_sampling_filters(audit_payload)
            audit_payload.pop("asset", None)
            audit_payload.pop("asset_id", None)
            filter_strategy = "audit_user_sessions_local_asset_fallback"
        records = _apply_common_filters(_fetch_list("/api/v1/audits/user-sessions/", audit_payload), payload)
        for item in records:
            if isinstance(item, dict):
                item.setdefault("_filter_strategy", filter_strategy)
                item.setdefault("_data_source", "/api/v1/audits/user-sessions/")
    if payload.get("status"):
        records = [item for item in records if _match_text(_extract_status(item), payload["status"])]
    records.sort(key=lambda item: _extract_datetime(item) or datetime.fromtimestamp(0, tz=timezone.utc), reverse=True)
    return records


def _fetch_file_transfer_records(filters: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _normalize_time_filters(filters)
    records = _apply_common_filters(_fetch_list("/api/v1/audits/ftp-logs/", payload), payload)
    direction = payload.get("direction")
    if direction:
        records = [item for item in records if _match_text(_extract_direction(item), direction)]
    records.sort(key=lambda item: _extract_datetime(item) or datetime.fromtimestamp(0, tz=timezone.utc), reverse=True)
    return records


def _fetch_detail(path: str, item_id: str) -> dict[str, Any]:
    client = create_client()
    result = client.get("%s%s/" % (path, item_id))
    if isinstance(result, dict):
        return result
    return {}


def _list_permissions(*, client=None) -> list[dict[str, Any]]:
    try:
        if client is not None:
            return client.list_paginated(PERMISSION_PATH)
        return _fetch_list(PERMISSION_PATH, {})
    except Exception as exc:  # noqa: BLE001
        raise CLIError(
            "Asset permission API is unavailable or not yet confirmed in the current environment.",
            payload={"path": PERMISSION_PATH, "reason": str(exc)},
        ) from exc


def _resolve_user(
    target: str | None = None,
    username: str | None = None,
    *,
    discovery=None,
) -> dict[str, Any]:
    active_discovery = discovery or create_discovery()
    users = active_discovery.list_users()
    if target and is_uuid_like(target):
        for item in users:
            if str(item.get("id")) == target:
                return item
    wanted = _lower(username or target)
    matches = [item for item in users if wanted and wanted in {_lower(item.get("username")), _lower(item.get("name"))}]
    if not matches:
        raise CLIError("Unable to resolve user from the provided identifier.", payload={"user": username or target})
    if len(matches) > 1:
        raise CLIError("Multiple users matched the provided identifier.", payload={"candidates": matches[:10]})
    return matches[0]


def _resolve_asset(
    target: str | None = None,
    name: str | None = None,
    *,
    discovery=None,
) -> dict[str, Any]:
    active_discovery = discovery or create_discovery()
    assets = active_discovery.list_assets()
    if target and is_uuid_like(target):
        for item in assets:
            if str(item.get("id")) == target:
                return item
    wanted = _lower(name or target)
    matches = [item for item in assets if wanted and wanted in {_lower(item.get("name")), _lower(item.get("address"))}]
    if not matches:
        raise CLIError("Unable to resolve asset from the provided identifier.", payload={"asset": name or target})
    if len(matches) > 1:
        raise CLIError("Multiple assets matched the provided identifier.", payload={"candidates": matches[:10]})
    return matches[0]


def node_full_value(node_lookup, node_id: str, *, fallback_name: str | None = None) -> str:
    node = node_lookup.get(node_id) or {}
    full_value = str(node.get("full_value") or "").strip()
    if full_value:
        return full_value
    fallback = str(fallback_name or "").strip()
    if fallback.startswith("/"):
        return fallback
    name = str(node.get("value") or node.get("name") or fallback).strip()
    return "/%s" % name if name else ""


def build_node_lookup(*, discovery=None) -> dict[str, dict[str, Any]]:
    active_discovery = discovery or create_discovery()
    return {
        str(item.get("id") or "").strip(): item
        for item in active_discovery.list_nodes()
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }


def _asset_node_paths(asset: dict[str, Any], *, node_lookup) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for node in asset.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        resolved_path = node_full_value(
            node_lookup,
            node_id,
            fallback_name=str(node.get("full_value") or node.get("name") or node.get("value") or ""),
        )
        if not resolved_path or resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)
        paths.append(
            {
                "path": resolved_path,
                "node_id": node_id or None,
                "node_name": str(node.get("name") or node.get("value") or "").strip() or None,
                "source": "asset.nodes",
            }
        )
    for display in asset.get("nodes_display", []) or []:
        display_text = str(display or "").strip()
        if not display_text or display_text in seen_paths:
            continue
        seen_paths.add(display_text)
        paths.append({"path": display_text, "node_id": None, "node_name": None, "source": "asset.nodes_display"})
    return paths


def _permission_node_paths(permission: dict[str, Any], *, node_lookup) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for node in permission.get("nodes", []) or []:
        if isinstance(node, dict):
            node_id = str(node.get("id") or "").strip()
            fallback_name = str(node.get("full_value") or node.get("name") or node.get("value") or "")
            resolved_path = node_full_value(node_lookup, node_id, fallback_name=fallback_name)
            node_name = str(node.get("name") or node.get("value") or "").strip() or None
        else:
            node_id = str(node or "").strip()
            resolved_path = node_full_value(node_lookup, node_id, fallback_name=node_id)
            node_name = None
        if not resolved_path or resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)
        paths.append(
            {
                "path": resolved_path,
                "node_id": node_id or None,
                "node_name": node_name,
                "source": "permission.nodes",
            }
        )
    return paths


def match_permission_to_asset(permission: dict[str, Any], asset: dict[str, Any], *, node_lookup) -> dict[str, Any] | None:
    asset_id = str(asset.get("id") or "").strip()
    permission_asset_ids = {
        str(obj.get("id", obj)).strip()
        for obj in permission.get("assets", []) or []
        if str(obj.get("id", obj) if isinstance(obj, dict) else obj).strip()
    }
    if asset_id and asset_id in permission_asset_ids:
        return {
            "match_source": "direct_asset",
            "match_evidence": {
                "matched_asset_id": asset_id,
                "permission_asset_ids": sorted(permission_asset_ids),
            },
        }

    asset_label_ids = {
        str(obj.get("id", obj)).strip()
        for obj in asset.get("labels", []) or []
        if str(obj.get("id", obj) if isinstance(obj, dict) else obj).strip()
    }
    permission_label_ids = {
        str(obj.get("id", obj)).strip()
        for obj in permission.get("labels", []) or []
        if str(obj.get("id", obj) if isinstance(obj, dict) else obj).strip()
    }
    matched_label_ids = sorted(asset_label_ids & permission_label_ids)
    if matched_label_ids:
        return {
            "match_source": "shared_label",
            "match_evidence": {
                "matched_label_ids": matched_label_ids,
                "asset_label_ids": sorted(asset_label_ids),
                "permission_label_ids": sorted(permission_label_ids),
            },
        }

    asset_paths = _asset_node_paths(asset, node_lookup=node_lookup)
    permission_paths = _permission_node_paths(permission, node_lookup=node_lookup)
    path_matches: list[dict[str, Any]] = []
    for asset_path in asset_paths:
        asset_value = str(asset_path.get("path") or "").strip()
        if not asset_value:
            continue
        for permission_path in permission_paths:
            permission_value = str(permission_path.get("path") or "").strip()
            if not permission_value:
                continue
            prefix = permission_value.rstrip("/") + "/"
            if asset_value == permission_value or asset_value.startswith(prefix):
                depth = len([part for part in permission_value.split("/") if part])
                path_matches.append(
                    {
                        "depth": depth,
                        "asset_path": asset_path,
                        "permission_path": permission_path,
                        "relationship": "exact" if asset_value == permission_value else "ancestor_prefix",
                    }
                )
    if path_matches:
        best_match = sorted(
            path_matches,
            key=lambda item: (
                int(item.get("depth") or 0),
                len(str((item.get("permission_path") or {}).get("path") or "")),
            ),
            reverse=True,
        )[0]
        return {
            "match_source": "node_ancestor",
            "match_evidence": {
                "relationship": best_match["relationship"],
                "matched_asset_path": best_match["asset_path"],
                "matched_permission_path": best_match["permission_path"],
                "asset_node_paths": asset_paths,
                "permission_node_paths": permission_paths,
            },
        }
    return None


def explain_asset_permissions(
    asset: dict[str, Any],
    *,
    client=None,
    discovery=None,
) -> dict[str, Any]:
    active_client = client or create_client()
    active_discovery = discovery or create_discovery()
    node_lookup = build_node_lookup(discovery=active_discovery)
    matched_permissions = []
    for item in _list_permissions(client=active_client):
        permission_id = str(item.get("id") or "").strip()
        if not permission_id:
            continue
        detail = active_client.get("%s%s/" % (PERMISSION_PATH, permission_id))
        if not isinstance(detail, dict):
            continue
        match = match_permission_to_asset(detail, asset, node_lookup=node_lookup)
        if not match:
            continue
        matched_permissions.append(
            {
                "id": detail.get("id"),
                "name": detail.get("name"),
                "match_source": match["match_source"],
                "match_evidence": match["match_evidence"],
            }
        )
    return {
        "asset": asset,
        "matched_permission_count": len(matched_permissions),
        "matched_permissions": matched_permissions,
    }


def command_records(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters)
    records = _fetch_command_records(payload)
    if not records:
        return _with_command_storage_context(_empty_result("No command records matched the current filters.", payload), payload)
    risk_counter = Counter()
    user_counter = Counter()
    asset_counter = Counter()
    for item in records:
        risk_counter[str(_first_field(item, "risk_level", "risk_level_display") or "unknown")] += 1
        user_counter[_extract_user(item) or "unknown"] += 1
        asset_counter[_extract_asset(item) or "unknown"] += 1
    return _with_command_storage_context(
        {
            "summary": {
                "total": len(records),
                "risk_levels": _top(risk_counter),
                "top_users": _top(user_counter),
                "top_assets": _top(asset_counter),
            },
            "records": _sample(records, size=int(payload.get("limit") or 20)),
        },
        payload,
    )


def high_risk_commands(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    payload.setdefault("risk_level", 4)
    return command_records(payload)


def session_records(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters)
    records = _fetch_session_records(payload)
    if not records:
        return _with_org_context(_empty_result("No session records matched the current filters.", payload))
    protocol_counter = Counter()
    asset_counter = Counter()
    user_counter = Counter()
    durations = []
    for item in records:
        protocol_counter[_extract_protocol(item) or "unknown"] += 1
        asset_counter[_extract_asset(item) or "unknown"] += 1
        user_counter[_extract_user(item) or "unknown"] += 1
        duration = _extract_duration(item)
        if duration is not None:
            durations.append(duration)
    return _with_org_context(
        {
            "summary": {
                "total": len(records),
                "top_protocols": _top(protocol_counter),
                "top_assets": _top(asset_counter),
                "top_users": _top(user_counter),
                "average_duration_seconds": round(sum(durations) / len(durations), 2) if durations else None,
            },
            "records": _sample(records, size=int(payload.get("limit") or 20)),
        }
    )


def file_transfer_logs(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters)
    records = _fetch_file_transfer_records(payload)
    if not records:
        return _with_org_context(_empty_result("No file transfer records matched the current filters.", payload))
    direction_counter = Counter()
    user_counter = Counter()
    asset_counter = Counter()
    for item in records:
        direction_counter[_extract_direction(item) or "unknown"] += 1
        user_counter[_extract_user(item) or "unknown"] += 1
        asset_counter[_extract_asset(item) or "unknown"] += 1
    return _with_org_context(
        {
            "summary": {
                "total": len(records),
                "directions": _top(direction_counter),
                "top_users": _top(user_counter),
                "top_assets": _top(asset_counter),
            },
            "records": _sample(records, size=int(payload.get("limit") or 20)),
        }
    )


def file_transfer_risk(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    keyword = payload.get("keyword")
    if not keyword:
        payload["keyword"] = ".sh .sql .pem .key .zip .tar .gz"
    return file_transfer_logs(payload)


def _is_failed_login(item: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            _extract_status(item),
            _string_value(_first_field(item, "reason", "detail", "type")),
        ]
    ).lower()
    return any(token in haystack for token in ("fail", "failed", "auth_err", "error", "denied", "block"))


def _login_records(filters: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _normalize_time_filters(filters)
    records = _apply_common_filters(_fetch_list("/api/v1/audits/login-logs/", payload), payload)
    if filters.get("status"):
        records = [item for item in records if _match_text(_extract_status(item), filters["status"])]
    return records


def abnormal_logins(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters)
    start_hour = int(payload.get("hour_start") or 0)
    end_hour = int(payload.get("hour_end") or 6)
    records = []
    for item in _login_records(payload):
        timestamp = _extract_datetime(item)
        if timestamp is None:
            continue
        hour = timestamp.astimezone(timezone.utc).hour
        if start_hour <= hour < end_hour:
            records.append(item)
    if not records:
        return _with_org_context(_empty_result("No abnormal-hour logins matched the current filters.", payload))
    ip_counter = Counter(_extract_source_ip(item) or "unknown" for item in records)
    user_counter = Counter(_extract_user(item) or "unknown" for item in records)
    return _with_org_context(
        {
            "summary": {
                "total": len(records),
                "top_source_ips": _top(ip_counter),
                "top_users": _top(user_counter),
                "hour_window": {"start": start_hour, "end": end_hour},
            },
            "records": _sample(records, size=int(payload.get("limit") or 20)),
        }
    )


def login_source_ip(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters)
    records = _login_records(payload)
    if payload.get("source_ip"):
        records = [item for item in records if _match_text(_extract_source_ip(item), payload["source_ip"])]
    if not records:
        return _with_org_context(_empty_result("No login records matched the current source IP filters.", payload))
    ip_counter = Counter(_extract_source_ip(item) or "unknown" for item in records)
    success_counter = Counter()
    for item in records:
        label = "failed" if _is_failed_login(item) else "success"
        success_counter[label] += 1
    return _with_org_context(
        {
            "summary": {
                "total": len(records),
                "top_source_ips": _top(ip_counter),
                "status_distribution": _top(success_counter),
            },
            "records": _sample(records, size=int(payload.get("limit") or 20)),
        }
    )


def failed_login_statistics(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters)
    records = [item for item in _login_records(payload) if _is_failed_login(item)]
    if not records:
        return _with_org_context(_empty_result("No failed logins matched the current filters.", payload))
    user_counter = Counter(_extract_user(item) or "unknown" for item in records)
    ip_counter = Counter(_extract_source_ip(item) or "unknown" for item in records)
    asset_counter = Counter(_extract_asset(item) or "unknown" for item in records)
    return _with_org_context(
        {
            "summary": {
                "total": len(records),
                "top_users": _top(user_counter, limit=int(payload.get("top") or 10)),
                "top_source_ips": _top(ip_counter, limit=int(payload.get("top") or 10)),
                "top_assets": _top(asset_counter, limit=int(payload.get("top") or 10)),
            },
            "records": _sample(records, size=int(payload.get("limit") or 20)),
        }
    )


def sensitive_asset_access(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    asset_keyword = payload.get("asset") or payload.get("asset_keywords")
    if not asset_keyword:
        raise CLIError("Sensitive asset access queries require asset or asset_keywords filters, e.g. {\"asset_keywords\":\"10.1.12.32\",\"date_from\":\"2026-03-01 00:00:00\",\"date_to\":\"2026-03-21 23:59:59\"}.")
    return session_records(payload)


def _drop_sampling_filters(payload: dict[str, Any]) -> dict[str, Any]:
    server_payload = dict(payload)
    server_payload.pop("limit", None)
    server_payload.pop("offset", None)
    server_payload.pop("top", None)
    return server_payload


def _normalize_match_key(value: Any) -> str:
    return _lower(_simplify_display_name(value))


def _merge_last_seen(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if candidate is None:
        return current
    if current is None or candidate > current:
        return candidate
    return current


def _is_high_privilege_name(value: Any) -> bool:
    return _normalize_match_key(value) in {"root", "administrator", "dba", "sa"}


def _top_usage_rows(rows: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    return [{"name": item["account"], "count": item["usage_count"]} for item in rows[:limit] if item.get("account")]


def _high_privilege_account_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    final = []
    for item in rows:
        if item.get("privileged"):
            final.append({**item, "privilege_source": "privileged_field"})
            continue
        if _is_high_privilege_name(item.get("account")):
            final.append({**item, "privilege_source": "name_rule"})
    return final


def privileged_account_usage(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=int(filters.get("days") or 30))
    rows = [item for item in _high_privilege_account_rows(_account_activity_rows(payload)) if item["usage_count"] > 0]
    if not rows:
        return _with_org_context(_empty_result("No privileged account activity matched the current filters.", payload))
    total_commands = sum(item["command_count"] for item in rows)
    total_sessions = sum(item["session_count"] for item in rows)
    return _with_org_context(
        {
            "summary": {
                "total": len(rows),
                "total_privileged_accounts_with_activity": len(rows),
                "total_commands": total_commands,
                "total_sessions": total_sessions,
                "top_accounts": _top_usage_rows(rows, limit=int(payload.get("top") or 10)),
            },
            "records": rows[: int(payload.get("limit") or 20)],
        }
    )


def _account_activity_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    rows_by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows_by_account_asset: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in _build_account_rows(payload):
        row = {
            "id": item.get("id"),
            "account": item["name"],
            "username": item.get("username"),
            "asset": item.get("asset"),
            "privileged": item.get("privileged"),
            "is_active": item.get("is_active"),
            "template": item.get("template"),
            "source": item.get("source"),
            "source_id": item.get("source_id"),
            "command_count": 0,
            "session_count": 0,
            "usage_count": 0,
            "last_seen": None,
            "never_seen": True,
        }
        rows.append(row)
        account_keys = {_normalize_match_key(item.get("name")), _normalize_match_key(item.get("username"))}
        asset_key = _normalize_match_key(item.get("asset"))
        for account_key in [value for value in account_keys if value]:
            rows_by_account[account_key].append(row)
            if asset_key:
                rows_by_account_asset[(account_key, asset_key)].append(row)

    activity_payload = _drop_sampling_filters(payload)

    def _resolve_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
        account_key = _normalize_match_key(_extract_account(record))
        if not account_key:
            return []
        asset_key = _normalize_match_key(_extract_asset(record))
        if asset_key:
            exact_matches = rows_by_account_asset.get((account_key, asset_key), [])
            if exact_matches:
                return exact_matches
        name_matches = rows_by_account.get(account_key, [])
        if len(name_matches) == 1:
            return name_matches
        return []

    for item in _fetch_command_records(activity_payload):
        timestamp = _extract_datetime(item)
        for row in _resolve_rows(item):
            row["command_count"] += 1
            row["usage_count"] += 1
            row["last_seen"] = _merge_last_seen(row["last_seen"], timestamp)
            row["never_seen"] = False

    for item in _fetch_session_records(activity_payload):
        timestamp = _extract_datetime(item)
        for row in _resolve_rows(item):
            row["session_count"] += 1
            row["usage_count"] += 1
            row["last_seen"] = _merge_last_seen(row["last_seen"], timestamp)
            row["never_seen"] = False

    rows.sort(
        key=lambda item: (
            item["usage_count"],
            item["last_seen"] or datetime.fromtimestamp(0, tz=timezone.utc),
            item["account"],
        ),
        reverse=True,
    )
    return rows


def account_activity_overview(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=30)
    summary_rows = _account_activity_rows(payload)
    return _with_org_context(
        {
            "summary": {
                "total_accounts": len(summary_rows),
                "active_accounts": sum(1 for item in summary_rows if item["usage_count"] > 0),
                "top_accounts": summary_rows[: int(payload.get("top") or 10)],
            },
            "records": summary_rows[: int(payload.get("limit") or 20)],
        }
    )


def _asset_activity_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    assets = _fetch_list("/api/v1/assets/assets/", payload)
    usage = Counter()
    for item in _fetch_session_records({**payload}) + _fetch_command_records({**payload}):
        usage[_extract_asset(item) or "unknown"] += 1
    rows = []
    for item in assets:
        name = _extract_asset(item)
        if not name:
            continue
        rows.append(
            {
                "asset": name,
                "address": _string_value(_first_field(item, "address")),
                "type": _string_value(_first_field(item, "type", "category.value", "platform.category")),
                "usage_count": usage.get(name, 0),
                "is_active": item.get("is_active"),
            }
        )
    if payload.get("asset"):
        rows = [item for item in rows if _match_text(item["asset"], payload["asset"])]
    rows.sort(key=lambda item: item["usage_count"], reverse=True)
    return rows


def asset_activity_overview(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=30)
    rows = _asset_activity_rows(payload)
    return _with_org_context(
        {
            "summary": {"total_assets": len(rows), "top_assets": rows[: int(payload.get("top") or 10)]},
            "records": rows[: int(payload.get("limit") or 20)],
        }
    )


def asset_type_distribution(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    assets = _fetch_list("/api/v1/assets/assets/", payload)
    counter = Counter()
    for item in assets:
        asset_type = _string_value(_first_field(item, "type", "category.value", "platform.category", "platform.type.value")) or "unknown"
        counter[asset_type] += 1
    rows = _percentage(_top(counter, limit=len(counter) or 10), len(assets))
    return _with_org_context({"summary": {"total_assets": len(assets), "distribution": rows}, "records": rows})


def asset_login_ranking(filters: dict[str, Any]) -> dict[str, Any]:
    return asset_activity_overview(filters)


def account_template_list(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    templates = _fetch_list(ACCOUNT_TEMPLATE_PATH, payload)
    if payload.get("name"):
        templates = [item for item in templates if _match_text(_string_value(_first_field(item, "name")), payload["name"])]
    rows = []
    for item in templates:
        rows.append(
            {
                "id": item.get("id"),
                "name": _string_value(_first_field(item, "name")),
                "type": _string_value(_first_field(item, "type")),
                "is_active": item.get("is_active"),
                "assets": _first_field(item, "assets_amount", "assets_count", "assets") or _first_field(item, "assets"),
                "nodes": _first_field(item, "nodes_amount", "nodes_count", "nodes") or _first_field(item, "nodes"),
            }
        )
    return _with_org_context(
        {"summary": {"total_templates": len(templates)}, "records": rows[: int(payload.get("limit") or 20)]}
    )


def asset_login_trend(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=int(filters.get("days") or 7))
    records = _login_records(payload)
    trend = Counter()
    for item in records:
        timestamp = _extract_datetime(item)
        if timestamp is None:
            continue
        trend[timestamp.strftime("%Y-%m-%d")] += 1
    rows = [{"date": key, "count": trend[key]} for key in sorted(trend)]
    return _with_org_context({"summary": {"total": len(records), "days": len(rows)}, "records": rows})


def recent_active_users_ranking(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=30)
    counter = Counter()
    last_seen = {}
    for item in _fetch_session_records(payload) + _fetch_command_records(payload):
        user = _extract_user(item) or "unknown"
        counter[user] += 1
        ts = _extract_datetime(item)
        if ts and (user not in last_seen or ts > last_seen[user]):
            last_seen[user] = ts
    rows = [{"user": key, "count": count, "last_seen": last_seen.get(key)} for key, count in counter.most_common(int(payload.get("top") or 10))]
    return _with_org_context({"summary": {"total_users": len(counter)}, "records": rows})


def recent_active_assets_ranking(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=30)
    counter = Counter()
    last_seen = {}
    for item in _fetch_session_records(payload) + _fetch_command_records(payload):
        asset = _extract_asset(item) or "unknown"
        counter[asset] += 1
        ts = _extract_datetime(item)
        if ts and (asset not in last_seen or ts > last_seen[asset]):
            last_seen[asset] = ts
    rows = [{"asset": key, "count": count, "last_seen": last_seen.get(key)} for key, count in counter.most_common(int(payload.get("top") or 10))]
    return _with_org_context({"summary": {"total_assets": len(counter)}, "records": rows})


def session_duration_ranking(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=30)
    records = _fetch_session_records(payload)
    rows = []
    for item in records:
        rows.append(
            {
                "id": item.get("id"),
                "user": _extract_user(item),
                "asset": _extract_asset(item),
                "protocol": _extract_protocol(item),
                "duration_seconds": _extract_duration(item),
                "timestamp": _extract_datetime(item),
                "status": _extract_status(item),
            }
        )
    rows = [item for item in rows if item["duration_seconds"] is not None]
    rows.sort(key=lambda item: item["duration_seconds"], reverse=True)
    return _with_org_context({"summary": {"total_sessions": len(rows)}, "records": rows[: int(payload.get("top") or 20)]})


def file_transfer_heavy_entities(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=30)
    records = _fetch_file_transfer_records(payload)
    user_counter = Counter(_extract_user(item) or "unknown" for item in records)
    asset_counter = Counter(_extract_asset(item) or "unknown" for item in records)
    return _with_org_context(
        {
            "summary": {"total_transfers": len(records)},
            "records": [
                {"dimension": "user", "ranking": _top(user_counter, limit=int(payload.get("top") or 10))},
                {"dimension": "asset", "ranking": _top(asset_counter, limit=int(payload.get("top") or 10))},
            ],
        }
    )


def protocol_distribution(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=30)
    records = session_records(payload)["records"]
    counter = Counter(_extract_protocol(item) or "unknown" for item in records)
    rows = _percentage(_top(counter, limit=len(counter) or 10), len(records))
    return _with_org_context({"summary": {"total_sessions": len(records), "distribution": rows}, "records": rows})


def platform_usage_distribution(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=30)
    assets = _fetch_list("/api/v1/assets/assets/", payload)
    platform_by_asset = {}
    for item in assets:
        platform_by_asset[_extract_asset(item)] = _string_value(_first_field(item, "platform.name", "platform", "platform.type.value")) or "unknown"
    counter = Counter()
    for item in _fetch_session_records(payload):
        counter[platform_by_asset.get(_extract_asset(item), "unknown")] += 1
    rows = _percentage(_top(counter, limit=len(counter) or 10), sum(counter.values()))
    return _with_org_context({"summary": {"total_sessions": sum(counter.values())}, "records": rows})


def _build_asset_rows(filters: dict[str, Any]) -> list[dict[str, Any]]:
    payload = dict(filters)
    assets = _fetch_list("/api/v1/assets/assets/", payload)
    assets = _apply_common_filters(assets, _normalize_time_filters({}, default_days=3650))
    rows = []
    for item in assets:
        row = {
            "id": item.get("id"),
            "name": _extract_asset(item),
            "address": _string_value(_first_field(item, "address")),
            "type": _string_value(_first_field(item, "type", "platform.type.value", "category.value")),
            "platform": _string_value(_first_field(item, "platform.name", "platform")),
            "is_active": item.get("is_active"),
            "nodes": _first_field(item, "nodes_display", "nodes"),
        }
        if payload.get("name") and not _match_text(row["name"], payload["name"]):
            continue
        if payload.get("address") and not _match_text(row["address"], payload["address"]):
            continue
        if payload.get("is_active") not in {None, ""}:
            wanted = parse_bool(payload["is_active"])
            if bool(row["is_active"]) != wanted:
                continue
        rows.append(row)
    return rows


def asset_list(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    rows = _build_asset_rows(payload)
    return _with_org_context({"summary": {"total_assets": len(rows)}, "records": rows[: int(payload.get("limit") or 50)]})


def uncategorized_assets(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    rows = [item for item in _build_asset_rows(payload) if _is_empty_like(_first_field(item, "nodes"))]
    return _with_org_context({"summary": {"total_uncategorized_assets": len(rows)}, "records": rows})


def assets_without_valid_template(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    templates = _fetch_list(ACCOUNT_TEMPLATE_PATH, payload)
    template_ids = {str(item.get("id")) for item in templates if item.get("id")}
    assets = _fetch_list("/api/v1/assets/assets/", payload)
    rows = []
    for item in assets:
        linked = _first_field(item, "account_templates", "account_template", "template", "templates")
        linked_ids = set()
        if isinstance(linked, list):
            linked_ids = {str(obj.get("id", obj)) for obj in linked if obj}
        elif linked:
            linked_ids = {str(linked.get("id", linked)) if isinstance(linked, dict) else str(linked)}
        if not linked_ids or not (linked_ids & template_ids):
            rows.append(
                {
                    "id": item.get("id"),
                    "name": _extract_asset(item),
                    "address": _string_value(_first_field(item, "address")),
                    "linked_templates": list(linked_ids),
                }
            )
    return _with_org_context({"summary": {"total_assets": len(rows)}, "records": rows[: int(payload.get("limit") or 50)]})


def duplicate_asset_names(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    rows = _build_asset_rows(payload)
    groups = defaultdict(list)
    for item in rows:
        groups[item["name"]].append(item)
    duplicates = [{"name": key, "count": len(value), "assets": value} for key, value in groups.items() if key and len(value) > 1]
    duplicates.sort(key=lambda item: item["count"], reverse=True)
    return _with_org_context({"summary": {"duplicate_name_count": len(duplicates)}, "records": duplicates[: int(payload.get("limit") or 20)]})


def offline_disabled_assets(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    assets = _build_asset_rows(payload)
    status_rows = _fetch_list(TERMINAL_STATUS_PATH, payload)
    status_by_name = {}
    for item in status_rows:
        status_by_name[_string_value(_first_field(item, "terminal", "name"))] = item
    rows = []
    for item in assets:
        if not item.get("is_active"):
            rows.append({**item, "terminal_status": "disabled"})
            continue
        terminal_status = status_by_name.get(item["name"]) or {}
        if terminal_status:
            rows.append({**item, "terminal_status": _extract_status(terminal_status)})
    return _with_org_context({"summary": {"total": len(rows)}, "records": rows[: int(payload.get("limit") or 50)]})


def unused_assets(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=int(filters.get("days") or 90))
    rows = _asset_activity_rows(payload)
    unused = [item for item in rows if item["usage_count"] == 0]
    return _with_org_context({"summary": {"total_unused_assets": len(unused)}, "records": unused[: int(payload.get("limit") or 50)]})


def node_asset_distribution(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    rows = _build_asset_rows(payload)
    counter = Counter()
    assets_by_node = defaultdict(list)
    for item in rows:
        nodes = item.get("nodes")
        names: list[str] = []
        if isinstance(nodes, list):
            for node in nodes:
                if isinstance(node, dict):
                    names.append(_string_value(_first_field(node, "full_value", "value", "name", "id")))
                else:
                    names.append(_string_value(node))
        elif isinstance(nodes, dict):
            names.append(_string_value(_first_field(nodes, "full_value", "value", "name", "id")))
        elif nodes not in {None, ""}:
            names.append(_string_value(nodes))
        for name in [value for value in names if value]:
            counter[name] += 1
            assets_by_node[name].append(item["name"])
    records = []
    for node_name, count in counter.most_common(int(payload.get("limit") or 50)):
        records.append({"node": node_name, "asset_count": count, "assets": assets_by_node[node_name][:10]})
    return _with_org_context({"summary": {"node_count": len(counter), "total_assets": len(rows)}, "records": records})


def account_list(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    accounts = _fetch_list("/api/v1/accounts/accounts/", _account_inventory_filters(payload))
    rows = _build_account_rows(payload, accounts)
    privileged_accounts = sum(1 for item in rows if item["privileged"])
    distinct_assets = len({_normalize_match_key(item.get("asset")) for item in rows if _normalize_match_key(item.get("asset"))})
    return _with_org_context(
        {
            "summary": {
                "total": len(rows),
                "total_accounts": len(rows),
                "privileged_accounts": privileged_accounts,
                "distinct_assets": distinct_assets,
            },
            "records": rows[: int(payload.get("limit") or 50)],
        }
    )


def _build_account_rows(payload: dict[str, Any], accounts: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    accounts = list(accounts or _fetch_list("/api/v1/accounts/accounts/", _account_inventory_filters(payload)))
    rows = []
    for item in accounts:
        row = {
            "id": item.get("id"),
            "name": _extract_account(item),
            "asset": _extract_asset(item),
            "username": _string_value(_first_field(item, "username")),
            "privileged": parse_bool(item.get("privileged")),
            "is_active": item.get("is_active"),
            "template": _first_field(item, "template.name", "template", "source_id"),
            "source": _string_value(_first_field(item, "source.value", "source.label", "source")),
            "source_id": _string_value(_first_field(item, "source_id", "template.id", "source.id")),
        }
        if payload.get("account") and not _match_text(row["name"], payload["account"]):
            continue
        if payload.get("asset") and not _match_text(row["asset"], payload["asset"]):
            continue
        if payload.get("privileged") not in {None, ""} and row["privileged"] != parse_bool(payload["privileged"]):
            continue
        if payload.get("is_active") not in {None, ""} and bool(row["is_active"]) != parse_bool(payload["is_active"]):
            continue
        rows.append(row)
    return rows


def long_time_unused_accounts(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    days = int(payload.get("days") or 90)
    rows = _account_activity_rows(_normalize_time_filters({**payload, "days": days}, default_days=days))
    if payload.get("privileged") not in {None, ""}:
        wanted = parse_bool(payload["privileged"])
        rows = [item for item in rows if bool(item.get("privileged")) == wanted]
    unused = [item for item in rows if item["usage_count"] == 0]
    never_seen_count = sum(1 for item in unused if item["never_seen"])
    return _with_org_context(
        {
            "summary": {"total": len(unused), "total_unused_accounts": len(unused), "days": days, "never_seen_count": never_seen_count},
            "records": unused[: int(payload.get("limit") or 50)],
        }
    )


def high_privilege_accounts(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=int(filters.get("days") or 30))
    rows = _high_privilege_account_rows(_account_activity_rows(payload))
    asset_counter = Counter(item.get("asset") or "unknown" for item in rows)
    accounts_with_activity = sum(1 for item in rows if item["usage_count"] > 0)
    return _with_org_context(
        {
            "summary": {
                "total": len(rows),
                "total_high_privilege_accounts": len(rows),
                "accounts_with_activity": accounts_with_activity,
                "asset_distribution": _top(asset_counter, limit=int(payload.get("top") or 10)),
            },
            "records": rows[: int(payload.get("limit") or 50)],
        }
    )


def expired_accounts(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    users = _fetch_list("/api/v1/users/users/", payload)
    now = datetime.now(timezone.utc)
    rows = []
    for item in users:
        name = _string_value(_first_field(item, "name"))
        username = _string_value(_first_field(item, "username"))
        if payload.get("user") and not (_match_text(name, payload["user"]) or _match_text(username, payload["user"])):
            continue
        date_expired = _parse_datetime_value(_first_field(item, "date_expired"))
        is_expired = parse_bool(item.get("is_expired")) or (date_expired is not None and date_expired < now)
        if not is_expired:
            continue
        rows.append(
            {
                "id": item.get("id"),
                "name": name,
                "username": username,
                "email": _string_value(_first_field(item, "email")),
                "source": _string_value(_first_field(item, "source.label", "source.value", "source")),
                "scope": "jumpserver_user_accounts",
                "is_active": item.get("is_active"),
                "is_expired": is_expired,
                "date_expired": date_expired,
                "last_login": _parse_datetime_value(_first_field(item, "last_login")),
                "login_blocked": item.get("login_blocked"),
            }
        )
    rows.sort(key=lambda item: item["date_expired"] or datetime.fromtimestamp(0, tz=timezone.utc))
    return _with_org_context(
        {
            "summary": {"total": len(rows), "total_expired_accounts": len(rows), "scope": "jumpserver_user_accounts"},
            "records": rows[: int(payload.get("limit") or 50)],
        }
    )


def accounts_without_template(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    rows = []
    for item in _build_account_rows(payload):
        source = _lower(item.get("source"))
        template = _string_value(item.get("template"))
        if template:
            continue
        if "template" in source:
            continue
        judgement_reason = "source_not_template_based" if source else "missing_template_field"
        rows.append(
            {
                **item,
                "judgement_reason": judgement_reason,
            }
        )
    return _with_org_context({"summary": {"total": len(rows), "total_accounts_without_template": len(rows)}, "records": rows[: int(payload.get("limit") or 50)]})


def shared_account_usage(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=30)
    account_users = defaultdict(set)
    for item in _fetch_command_records(payload) + _fetch_session_records(payload):
        account = _extract_account(item)
        user = _extract_user(item)
        if account and user:
            account_users[account].add(user)
    rows = []
    for account, users in account_users.items():
        if len(users) > 1:
            rows.append({"account": account, "user_count": len(users), "users": sorted(users)})
    rows.sort(key=lambda item: item["user_count"], reverse=True)
    return _with_org_context({"summary": {"shared_account_count": len(rows)}, "records": rows[: int(payload.get("top") or 20)]})


def frequent_operation_users(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=30)
    records = _fetch_command_records(payload)
    counter = Counter()
    last_seen: dict[str, datetime] = {}
    assets_by_user = defaultdict(set)
    for item in records:
        user = _extract_user(item) or "unknown"
        counter[user] += 1
        assets_by_user[user].add(_extract_asset(item) or "unknown")
        timestamp = _extract_datetime(item)
        if timestamp and (user not in last_seen or timestamp > last_seen[user]):
            last_seen[user] = timestamp
    rows = []
    for user, count in counter.most_common(int(payload.get("top") or 20)):
        rows.append(
            {
                "user": user,
                "command_count": count,
                "asset_count": len(assets_by_user[user]),
                "last_seen": last_seen.get(user),
            }
        )
    return _with_org_context({"summary": {"total_users": len(counter), "total_commands": len(records)}, "records": rows})


def account_asset_bindings(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    rows = _build_account_rows(payload)
    by_account = Counter(item["name"] or "unknown" for item in rows)
    by_asset = Counter(item["asset"] or "unknown" for item in rows)
    records = [
        {
            "account": item["name"],
            "asset": item["asset"],
            "username": item.get("username"),
            "privileged": item.get("privileged"),
            "is_active": item.get("is_active"),
            "template": item.get("template"),
            "source": item.get("source"),
        }
        for item in rows
    ]
    return _with_org_context(
        {
            "summary": {
                "total": len(records),
                "total_bindings": len(records),
                "distinct_accounts": len({_normalize_match_key(item["account"]) for item in records if _normalize_match_key(item["account"])}),
                "distinct_assets": len({_normalize_match_key(item["asset"]) for item in records if _normalize_match_key(item["asset"])}),
                "bindings_by_account": _top(by_account, limit=int(payload.get("top") or 10)),
                "bindings_by_asset": _top(by_asset, limit=int(payload.get("top") or 10)),
            },
            "records": records[: int(payload.get("limit") or 50)],
        }
    )


def session_behavior_statistics(filters: dict[str, Any]) -> dict[str, Any]:
    return session_records(filters)



def suspicious_operation_summary(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=7)
    high_risk = high_risk_commands(payload)
    abnormal_login = abnormal_logins(payload)
    transfer_risk = file_transfer_risk(payload)
    records = [
        {
            "type": "high_risk_commands",
            "count": high_risk.get("summary", {}).get("total", len(high_risk.get("records", []))),
            "samples": high_risk.get("records", [])[:5],
        },
        {
            "type": "abnormal_hour_logins",
            "count": abnormal_login.get("summary", {}).get("total", len(abnormal_login.get("records", []))),
            "samples": abnormal_login.get("records", [])[:5],
        },
        {
            "type": "risky_file_transfers",
            "count": transfer_risk.get("summary", {}).get("total", len(transfer_risk.get("records", []))),
            "samples": transfer_risk.get("records", [])[:5],
        },
    ]
    total = sum(item["count"] for item in records)
    return _with_org_context({"summary": {"suspicious_event_count": total, "dimensions": len(records)}, "records": records})


def session_dimension_analysis(filters: dict[str, Any], dimension: str) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=30)
    records = _fetch_session_records(payload)
    counter = Counter()
    duration_totals = Counter()
    for item in records:
        key = _extract_user(item) if dimension == "user" else _extract_asset(item)
        key = key or "unknown"
        counter[key] += 1
        duration = _extract_duration(item)
        if duration is not None:
            duration_totals[key] += duration
    rows = []
    for key, count in counter.most_common(int(payload.get("top") or 20)):
        rows.append(
            {
                dimension: key,
                "session_count": count,
                "average_duration_seconds": round(duration_totals[key] / count, 2) if count and duration_totals[key] else None,
            }
        )
    return _with_org_context({"summary": {"total_groups": len(counter), "dimension": dimension}, "records": rows})


def privileged_account_activity(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_time_filters(filters, default_days=int(filters.get("days") or 30))
    rows = _high_privilege_account_rows(_account_activity_rows(payload))
    if payload.get("asset"):
        rows = [item for item in rows if _match_text(item.get("asset"), payload["asset"])]
    if not rows:
        return _with_org_context(_empty_result("No privileged account activity matched the current filters.", payload))
    active_rows = [item for item in rows if item["usage_count"] > 0]
    return _with_org_context(
        {
            "summary": {
                "total": len(rows),
                "total_high_privilege_accounts": len(rows),
                "active_accounts": len(active_rows),
                "top_accounts": _top_usage_rows(active_rows or rows, limit=int(payload.get("top") or 10)),
            },
            "records": rows[: int(payload.get("limit") or 20)],
        }
    )


def system_settings_overview(filters: dict[str, Any]) -> dict[str, Any]:
    client = create_client()
    settings = client.get("/api/v1/settings/setting/")
    public_settings = client.get("/api/v1/settings/public/")
    server_info = client.get("/api/v1/settings/server-info/")
    return _with_org_context(
        {
            "summary": {
                "settings_keys": len(settings or {}),
                "public_keys": len(public_settings or {}),
                "server_info_keys": len(server_info or {}),
            },
            "records": [
                {"module": "setting", "payload": settings},
                {"module": "public", "payload": public_settings},
                {"module": "server_info", "payload": server_info},
            ],
        }
    )


def _settings_payload(category: str | None = None) -> Any:
    client = create_client()
    params = {"category": category} if category else None
    return client.get("/api/v1/settings/setting/", params=params)


def _settings_slice(keywords: tuple[str, ...], *, category: str | None = None) -> list[dict[str, Any]]:
    settings = _settings_payload(category=category)
    rows = []
    if isinstance(settings, dict):
        iterable = settings.items()
    elif isinstance(settings, list):
        iterable = []
        for item in settings:
            if isinstance(item, dict):
                key = _coalesce(item.get("key"), item.get("name"), item.get("id"))
                iterable.append((str(key or ""), item))
    else:
        iterable = []
    for key, value in iterable:
        key_text = str(key or "")
        haystack = "%s %s" % (key_text, _string_value(value))
        if any(keyword in haystack.lower() for keyword in keywords):
            rows.append({"key": key_text, "value": value})
    return rows


def security_policy_check(filters: dict[str, Any]) -> dict[str, Any]:
    rows = _settings_slice(("security", "password", "login", "lock", "block", "ip"))
    blocked_ips = create_client().get("/api/v1/settings/security/block-ip/")
    return _with_org_context({"summary": {"matched_keys": len(rows), "blocked_ip_count": len(blocked_ips or []) if isinstance(blocked_ips, list) else None}, "records": rows[:100]})


def login_auth_config_check(filters: dict[str, Any]) -> dict[str, Any]:
    return auth_source_config_check(filters)


def audit_retention_check(filters: dict[str, Any]) -> dict[str, Any]:
    rows = _settings_slice(("audit", "log", "replay", "command_storage", "retention", "keep"))
    return _with_org_context({"summary": {"matched_keys": len(rows)}, "records": rows[:100]})


def mfa_config_check(filters: dict[str, Any]) -> dict[str, Any]:
    rows = _settings_slice(("mfa", "otp", "totp", "duo"))
    return _with_org_context({"summary": {"matched_keys": len(rows)}, "records": rows[:100]})


def auth_source_config_check(filters: dict[str, Any]) -> dict[str, Any]:
    rows = _settings_slice(("ldap", "oidc", "oauth", "saml", "auth", "cas"))
    return _with_org_context({"summary": {"matched_keys": len(rows)}, "records": rows[:100]})


def notification_config_check(filters: dict[str, Any]) -> dict[str, Any]:
    rows = _settings_slice(("mail", "sms", "slack", "dingtalk", "feishu", "lark", "wecom", "notify"))
    backends = create_client().get("/api/v1/notifications/backends/")
    return _with_org_context({"summary": {"matched_keys": len(rows), "backend_count": len(backends or []) if isinstance(backends, list) else None}, "records": rows[:100]})


def ticket_approval_config_check(filters: dict[str, Any]) -> dict[str, Any]:
    flows = _fetch_list("/api/v1/tickets/flows/", filters)
    tickets = _fetch_list("/api/v1/tickets/tickets/", filters)
    pending = [item for item in tickets if "pending" in _extract_status(item).lower()]
    return _with_org_context({"summary": {"flow_count": len(flows), "ticket_count": len(tickets), "pending_count": len(pending)}, "records": _sample(pending or tickets, size=20)})


def terminal_access_policy_check(filters: dict[str, Any]) -> dict[str, Any]:
    endpoints = _fetch_list(ENDPOINT_RULES_PATH, filters)
    terminals = _fetch_list(TERMINALS_PATH, filters)
    command_storages = _fetch_list(COMMAND_STORAGES_PATH, filters)
    replay_storages = _fetch_list(REPLAY_STORAGES_PATH, filters)
    return _with_org_context(
        {
            "summary": {
                "endpoint_rule_count": len(endpoints),
                "terminal_count": len(terminals),
                "command_storage_count": len(command_storages),
                "replay_storage_count": len(replay_storages),
            },
            "records": [
                {"module": "endpoint_rules", "items": _sample(endpoints, size=10)},
                {"module": "terminals", "items": _sample(terminals, size=10)},
                {"module": "command_storages", "items": _sample(command_storages, size=10)},
                {"module": "replay_storages", "items": _sample(replay_storages, size=10)},
            ],
        }
    )


def setting_category_query(filters: dict[str, Any]) -> dict[str, Any]:
    category = str(filters.get("category") or "").strip()
    if not category:
        raise CLIError("setting-category-query requires filters.category, e.g. {\"category\":\"security_auth\"}.")
    payload = _settings_payload(category=category)
    records = payload if isinstance(payload, list) else [payload]
    records = [item for item in records if item not in (None, "")]
    return _with_org_context(
        {
            "summary": {"category": category, "total": len(records)},
            "records": records,
        }
    )


def license_detail_query(filters: dict[str, Any]) -> dict[str, Any]:
    client = create_client()
    payload = client.get("/api/v1/xpack/license/detail")
    return _with_org_context(
        {
            "summary": {"resource": "license_detail", "available": bool(payload)},
            "records": [payload] if payload is not None else [],
        }
    )


def ticket_list_query(filters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(filters)
    rows = _fetch_list("/api/v1/tickets/tickets/", payload)
    match_strategy = "server"
    name_filter = payload.get("name") or payload.get("title")
    if name_filter:
        filtered = _exact_first_filter(rows, name_filter, "title", "serial_num", "comment")
        if filtered:
            if filtered != rows:
                match_strategy = "local_exact_first"
            rows = filtered
        else:
            fallback_filters = dict(payload)
            fallback_filters.pop("name", None)
            fallback_filters.pop("title", None)
            fallback_filters.pop("search", None)
            broader_rows = _fetch_list("/api/v1/tickets/tickets/", fallback_filters)
            rows = _exact_first_filter(broader_rows, name_filter, "title", "serial_num", "comment")
            match_strategy = "local_exact_first_broad_fetch"
    return _with_org_context(
        {
            "summary": {
                "ticket_count": len(rows),
                "match_strategy": match_strategy,
                "filters": {key: value for key, value in payload.items() if not str(key).startswith("_")},
            },
            "records": _sample(rows, size=int(payload.get("limit") or 50)),
        }
    )


def command_storage_query(filters: dict[str, Any]) -> dict[str, Any]:
    rows = _fetch_list(COMMAND_STORAGES_PATH, filters)
    defaults = [item for item in rows if parse_bool(item.get("is_default"))]
    return _with_command_storage_context(
        {
            "summary": {"storage_count": len(rows), "default_count": len(defaults)},
            "records": _sample(rows, size=int(filters.get("limit") or 50)),
        },
        filters,
    )


def replay_storage_query(filters: dict[str, Any]) -> dict[str, Any]:
    rows = _fetch_list(REPLAY_STORAGES_PATH, filters)
    defaults = [item for item in rows if parse_bool(item.get("is_default"))]
    return _with_org_context(
        {
            "summary": {"storage_count": len(rows), "default_count": len(defaults)},
            "records": _sample(rows, size=int(filters.get("limit") or 50)),
        }
    )


def terminal_component_query(filters: dict[str, Any]) -> dict[str, Any]:
    rows = _fetch_list(TERMINALS_PATH, filters)
    return _with_org_context({"summary": {"terminal_count": len(rows)}, "records": _sample(rows, size=int(filters.get("limit") or 50))})


def report_query(filters: dict[str, Any]) -> dict[str, Any]:
    report_type = str(filters.get("report_type") or "").strip()
    if not report_type:
        raise CLIError("report-query requires filters.report_type, e.g. {\"report_type\":\"account-statistic\",\"days\":30}.")
    report_paths = {
        "account-statistic": "/api/v1/reports/reports/account-statistic/",
        "account-automation": "/api/v1/reports/reports/account-automation/",
        "asset-statistic": "/api/v1/reports/reports/asset-statistic/",
        "asset-activity": "/api/v1/reports/reports/asset-activity/",
        "users": "/api/v1/reports/reports/users/",
        "user-change-password": "/api/v1/reports/reports/user-change-password/",
        "pam-dashboard": "/api/v1/accounts/pam-dashboard/",
        "change-secret-dashboard": "/api/v1/accounts/change-secret-dashboard/",
    }
    path = report_paths.get(report_type)
    if path is None:
        raise CLIError("Unsupported report_type: %s" % report_type)
    client = create_client()
    payload = client.get(path, params=_server_filters(filters))
    records = payload if isinstance(payload, list) else [payload]
    records = [item for item in records if item not in (None, "")]
    return _with_org_context(
        {
            "summary": {"report_type": report_type, "total": len(records)},
            "records": records,
        }
    )


def account_automation_overview(filters: dict[str, Any]) -> dict[str, Any]:
    specs = {
        "account_risks": "/api/v1/accounts/account-risks/",
        "backup_plans": "/api/v1/accounts/account-backup-plans/",
        "backup_executions": "/api/v1/accounts/account-backup-plan-executions/",
        "change_secret_automations": "/api/v1/accounts/change-secret-automations/",
        "change_secret_executions": "/api/v1/accounts/change-secret-executions/",
        "change_secret_records": "/api/v1/accounts/change-secret-records/",
        "change_secret_dashboard": "/api/v1/accounts/change-secret-records/dashboard/",
        "check_account_automations": "/api/v1/accounts/check-account-automations/",
        "check_account_executions": "/api/v1/accounts/check-account-executions/",
        "account_check_engines": "/api/v1/accounts/account-check-engines/",
    }
    client = create_client()
    records = []
    partial_failures = []
    params = _server_filters(filters)
    for name, path in specs.items():
        try:
            payload = client.get(path, params=params)
            records.append({"module": name, "payload": payload})
        except Exception as exc:  # noqa: BLE001
            partial_failures.append({"module": name, "error": str(exc)})
    return _with_org_context(
        {
            "summary": {
                "module_count": len(records),
                "partial_failure_count": len(partial_failures),
            },
            "records": records,
            "partial_failures": partial_failures,
        }
    )


def platform_access_config_query(filters: dict[str, Any]) -> dict[str, Any]:
    rows = _fetch_list("/api/v1/assets/platforms/", filters)
    return _with_org_context({"summary": {"platform_count": len(rows)}, "records": _sample(rows, size=int(filters.get("limit") or 30))})


def account_template_config_query(filters: dict[str, Any]) -> dict[str, Any]:
    return account_template_list(filters)


def asset_platform_config_query(filters: dict[str, Any]) -> dict[str, Any]:
    rows = _build_asset_rows(filters)
    return _with_org_context({"summary": {"asset_count": len(rows)}, "records": rows[: int(filters.get("limit") or 50)]})


def org_resource_overview(filters: dict[str, Any]) -> dict[str, Any]:
    orgs = _fetch_list("/api/v1/orgs/orgs/", filters)
    rows = []
    for item in orgs:
        stats = item.get("resource_statistics") or {}
        rows.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "users_amount": stats.get("users_amount"),
                "groups_amount": stats.get("groups_amount"),
                "assets_amount": stats.get("assets_amount"),
                "nodes_amount": stats.get("nodes_amount"),
                "asset_perms_amount": stats.get("asset_perms_amount"),
            }
        )
    return _with_org_context({"summary": {"org_count": len(rows)}, "records": rows[: int(filters.get("limit") or 50)]})


def role_binding_overview(filters: dict[str, Any]) -> dict[str, Any]:
    rows = []
    rows.extend(_fetch_list(ORG_ROLE_BINDINGS_PATH, filters))
    rows.extend(_fetch_list(SYSTEM_ROLE_BINDINGS_PATH, filters))
    rows.extend(_fetch_list(ROLE_BINDINGS_PATH, filters))
    return _with_org_context({"summary": {"binding_count": len(rows)}, "records": _sample(rows, size=int(filters.get("limit") or 50))})


HANDLERS = {
    "command_records": command_records,
    "session_records": session_records,
    "file_transfer_logs": file_transfer_logs,
    "high_risk_commands": high_risk_commands,
    "sensitive_asset_access": sensitive_asset_access,
    "abnormal_logins": abnormal_logins,
    "login_source_ip": login_source_ip,
    "failed_login_statistics": failed_login_statistics,
    "privileged_account_usage": privileged_account_usage,
    "file_transfer_risk": file_transfer_risk,
    "account_activity_overview": account_activity_overview,
    "asset_activity_overview": asset_activity_overview,
    "asset_type_distribution": asset_type_distribution,
    "asset_login_ranking": asset_login_ranking,
    "account_template_list": account_template_list,
    "asset_login_trend": asset_login_trend,
    "recent_active_users_ranking": recent_active_users_ranking,
    "recent_active_assets_ranking": recent_active_assets_ranking,
    "session_duration_ranking": session_duration_ranking,
    "file_transfer_heavy_entities": file_transfer_heavy_entities,
    "protocol_distribution": protocol_distribution,
    "platform_usage_distribution": platform_usage_distribution,
    "asset_list": asset_list,
    "uncategorized_assets": uncategorized_assets,
    "assets_without_valid_template": assets_without_valid_template,
    "duplicate_asset_names": duplicate_asset_names,
    "offline_disabled_assets": offline_disabled_assets,
    "unused_assets": unused_assets,
    "node_asset_distribution": node_asset_distribution,
    "account_list": account_list,
    "long_time_unused_accounts": long_time_unused_accounts,
    "high_privilege_accounts": high_privilege_accounts,
    "expired_accounts": expired_accounts,
    "accounts_without_template": accounts_without_template,
    "shared_account_usage": shared_account_usage,
    "account_asset_bindings": account_asset_bindings,
    "frequent_operation_users": frequent_operation_users,
    "privileged_account_activity": privileged_account_activity,
    "session_behavior_statistics": session_behavior_statistics,
    "suspicious_operation_summary": suspicious_operation_summary,
    "user_session_analysis": lambda filters: session_dimension_analysis(filters, "user"),
    "asset_session_analysis": lambda filters: session_dimension_analysis(filters, "asset"),
    "system_settings_overview": system_settings_overview,
    "security_policy_check": security_policy_check,
    "login_auth_config_check": login_auth_config_check,
    "audit_retention_check": audit_retention_check,
    "mfa_config_check": mfa_config_check,
    "auth_source_config_check": auth_source_config_check,
    "notification_config_check": notification_config_check,
    "ticket_approval_config_check": ticket_approval_config_check,
    "terminal_access_policy_check": terminal_access_policy_check,
    "setting_category_query": setting_category_query,
    "license_detail_query": license_detail_query,
    "ticket_list_query": ticket_list_query,
    "command_storage_query": command_storage_query,
    "replay_storage_query": replay_storage_query,
    "terminal_component_query": terminal_component_query,
    "report_query": report_query,
    "account_automation_overview": account_automation_overview,
    "platform_access_config_query": platform_access_config_query,
    "account_template_config_query": account_template_config_query,
    "asset_platform_config_query": asset_platform_config_query,
    "org_resource_overview": org_resource_overview,
    "role_binding_overview": role_binding_overview,
}


def run_capability(capability_id: str, filters: dict[str, Any]) -> dict[str, Any]:
    spec = CAPABILITY_BY_ID.get(capability_id)
    if spec is None:
        raise CLIError("Unknown capability: %s" % capability_id)
    handler = HANDLERS.get(spec.handler)
    if handler is None:
        raise CLIError("Capability handler is not implemented: %s" % spec.handler)
    result = handler(filters)
    payload = dict(result)
    payload["capability"] = {
        "id": spec.capability_id,
        "name": spec.name,
        "category": spec.category,
        "priority": spec.priority,
    }
    return payload
