#!/usr/bin/env python3
"""JumpServer read-only queries for assets, nodes, platforms, accounts, users, and groups."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from jms_bootstrap import bootstrap_runtime

bootstrap_runtime()

import argparse
from typing import Any

from jms_runtime import (
    create_client,
    ensure_selected_org_context,
    import_string,
    parse_json_arg,
    run_and_print,
    run_request,
    serialize,
    temporary_org_client,
)


RESOURCE_MAP: dict[str, dict[str, str]] = {
    "asset": {
        "list": "jms_client.v1.models.request.assets.assets.DescribeAssetsRequest",
        "detail": "jms_client.v1.models.request.assets.assets.DetailAssetRequest",
    },
    "node": {
        "list": "jms_client.v1.models.request.assets.nodes.DescribeNodesRequest",
        "detail": "jms_client.v1.models.request.assets.nodes.DetailNodeRequest",
    },
    "platform": {
        "list": "jms_client.v1.models.request.assets.platforms.DescribePlatformsRequest",
        "detail": "jms_client.v1.models.request.assets.platforms.DetailPlatformRequest",
    },
    "account": {
        "list": "jms_client.v1.models.request.accounts.accounts.DescribeAccountsRequest",
        "detail": "jms_client.v1.models.request.accounts.accounts.DetailAccountRequest",
    },
    "user": {
        "list": "jms_client.v1.models.request.users.users.DescribeUsersRequest",
        "detail": "jms_client.v1.models.request.users.users.DetailUserRequest",
    },
    "user-group": {
        "list": "jms_client.v1.models.request.users.user_groups.DescribeUserGroupsRequest",
        "detail": "jms_client.v1.models.request.users.user_groups.DetailUserGroupRequest",
    },
    "organization": {
        "list": "jms_client.v1.models.request.organizations.organizations.DescribeOrganizationsRequest",
        "detail": "jms_client.v1.models.request.organizations.organizations.DetailOrganizationRequest",
    },
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

NODE_API_PATH = "api/v1/assets/nodes/"


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


def extract_choice_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def normalize_asset_kind(value: Any) -> str | None:
    raw = str(extract_choice_value(value) or "").strip().lower().replace("_", "-")
    return ASSET_KIND_ALIASES.get(raw)


def resolve_request_target(resource: str, action: str) -> str:
    resource_info = RESOURCE_MAP.get(resource)
    if resource_info is None:
        raise RuntimeError(f"Unsupported resource '{resource}'.")
    request_target = resource_info.get(action)
    if request_target is None:
        raise RuntimeError(f"Unsupported action '{action}' for resource '{resource}'.")
    return request_target


def build_request(resource: str, action: str, payload: dict[str, Any]) -> Any:
    request_cls = import_string(resolve_request_target(resource, action))
    return request_cls(**payload)


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
    return payload


def run_paginated_list_request(resource: str, payload: dict[str, Any]) -> list[Any]:
    if resource == "node":
        return list_node_objects(payload)

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
        if not any(
            str(candidate).strip().casefold() == folded
            for candidate in candidates
            if candidate is not None
        ):
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


def get_object(args: argparse.Namespace) -> Any:
    if not args.id:
        raise RuntimeError("Detail lookup requires --id.")
    if args.resource == "node":
        return get_node_object(args.id)
    return run_request(
        build_request(args.resource, "detail", {"id_": args.id}),
        with_model=True,
    )


def add_resource(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--resource",
        required=True,
        choices=sorted(RESOURCE_MAP),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

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
