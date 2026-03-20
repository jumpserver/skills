# jumpserver-skills

`jumpserver-skills` is a query-oriented skill repository for JumpServer V4. It supports environment initialization writes, including generating `.env.local` from user-provided config and persisting `JMS_ORG_ID`, while asset, permission, and audit business operations remain read-only.

## Overview

| Entry point | Purpose | Current scope |
|---|---|---|
| `scripts/jms_assets.py` | asset, account, user, user-group, platform, node, and organization queries | `list`, `get` |
| `scripts/jms_permissions.py` | permission rule queries | `list`, `get` |
| `scripts/jms_audit.py` | login, operate, session, and command audits | `list`, `get` |
| `scripts/jms_diagnose.py` | config checks, config writes, connectivity, org selection, resolution, and access analysis | environment init + read-only diagnostics |

## Core Rules

- start with `python3 scripts/jms_diagnose.py config-status --json`
- if config is incomplete, collect user-provided values and run `python3 scripts/jms_diagnose.py config-write --payload '<json>' --confirm`
- then run `python3 scripts/jms_diagnose.py ping`
- if org context is missing, run `python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm`
- only the exact reserved org sets `{0002}` or `{0002,0004}` may auto-write `0002`
- business `create/update/delete/append/remove/unblock` operations remain unsupported

## Repository Structure

```text
.
├── SKILL.md
├── README.md
├── README.en.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── assets.md
│   ├── audit.md
│   ├── diagnose.md
│   ├── object-map.md
│   ├── permissions.md
│   ├── runtime.md
│   ├── safety-rules.md
│   └── troubleshooting.md
├── scripts/
│   ├── jms_assets.py
│   ├── jms_audit.py
│   ├── jms_bootstrap.py
│   ├── jms_diagnose.py
│   ├── jms_permissions.py
│   └── jms_runtime.py
├── env.sh
└── requirements.txt
```

## Component Responsibilities

| Component | Responsibility |
|---|---|
| `SKILL.md` | skill routing rules, preflight order, boundaries, and recommended commands |
| `agents/openai.yaml` | agent-facing display name, summary, and default prompt |
| `references/*.md` | detailed runtime rules, domain guides, troubleshooting, and safety boundaries |
| `scripts/jms_assets.py` | read-only asset, account, user, group, platform, node, and organization query entry point |
| `scripts/jms_permissions.py` | read-only permission query entry point |
| `scripts/jms_audit.py` | read-only audit query entry point |
| `scripts/jms_diagnose.py` | config inspection, `.env.local` writes, connectivity checks, org selection, object resolution, and access analysis |
| `scripts/jms_runtime.py` | shared runtime for `.env.local` loading, SDK client construction, env validation, org context handling, and auto-write logic |

## Tech Stack and Dependencies

| Item | Current implementation |
|---|---|
| Language | Python 3 |
| Core dependency | `jumpserver-sdk-python>=0.9.1` |
| Execution model | local CLI scripts invoked as `python3 scripts/jms_*.py ...` |
| Target system | JumpServer V4 |
| Config sources | `.env.local` + process environment variables |
| Config write path | `jms_diagnose.py config-write --confirm` |
| Org persistence | `jms_diagnose.py select-org --confirm` |

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Quick Start

Check and initialize config:

```bash
python3 scripts/jms_diagnose.py config-status --json
python3 scripts/jms_diagnose.py config-write --payload '{"JMS_API_URL":"https://jump.example.com","JMS_ACCESS_KEY_ID":"<ak>","JMS_ACCESS_KEY_SECRET":"<sk>","JMS_VERSION":"4"}' --confirm
python3 scripts/jms_diagnose.py ping
```

Inspect and persist org selection:

```bash
python3 scripts/jms_diagnose.py select-org
python3 scripts/jms_diagnose.py select-org --org-id <org-id>
python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm
```

Then run queries, for example:

```bash
python3 scripts/jms_assets.py list --resource user --filters '{"username":"demo-user"}'
python3 scripts/jms_permissions.py list --filters '{"limit":20}'
python3 scripts/jms_audit.py list --audit-type operate --filters '{"limit":30}'
```

## Environment Variables

The table below reflects the current implementation and is sourced from `references/runtime.md` and `scripts/jms_runtime.py`. On first use, the skill can collect these values in dialog and write the result into a local `.env.local`.

| Variable | Required | Description | Example |
|---|---|---|---|
| `JMS_API_URL` | one of `JMS_API_URL` or `JMS_WEB_URL` is required | JumpServer API/access URL | `https://jump.example.com` |
| `JMS_WEB_URL` | one of `JMS_API_URL` or `JMS_WEB_URL` is required | runtime fallback URL variable | `https://jump.example.com` |
| `JMS_VERSION` | recommended | JumpServer version, currently treated as `4` by default | `4` |
| `JMS_ACCESS_KEY_ID` | must be paired with `JMS_ACCESS_KEY_SECRET`, or use username/password instead | AK/SK auth ID | `your-access-key-id` |
| `JMS_ACCESS_KEY_SECRET` | must be paired with `JMS_ACCESS_KEY_ID`, or use username/password instead | AK/SK auth secret | `your-access-key-secret` |
| `JMS_USERNAME` | must be paired with `JMS_PASSWORD`, or use AK/SK instead | username/password auth username | `ops-user` |
| `JMS_PASSWORD` | must be paired with `JMS_USERNAME`, or use AK/SK instead | username/password auth password | `your-password` |
| `JMS_ORG_ID` | optional during initialization | written before business execution through `select-org` or the reserved-org auto-selection rule | `00000000-0000-0000-0000-000000000000` |
| `JMS_TIMEOUT` | optional | SDK request timeout in seconds | `30` |
| `JMS_SDK_MODULE` | optional | custom SDK module path, default `jms_client.client` | `jms_client.client` |
| `JMS_SDK_GET_CLIENT` | optional | custom client factory function name, default `get_client` | `get_client` |

Generated `.env.local` example:

```dotenv
JMS_API_URL="https://jump.example.com"
JMS_VERSION="4"
JMS_ORG_ID=""

JMS_ACCESS_KEY_ID="your-access-key-id"
JMS_ACCESS_KEY_SECRET="your-access-key-secret"

# JMS_USERNAME="ops-user"
# JMS_PASSWORD="your-password"

# JMS_TIMEOUT="30"
# JMS_SDK_MODULE="jms_client.client"
# JMS_SDK_GET_CLIENT="get_client"
```

Environment variable rules:

- provide at least one address: `JMS_API_URL` or `JMS_WEB_URL`
- choose exactly one auth mode: `AK/SK` or `username/password`
- `.env.local` is auto-loaded by the scripts
- when first-time config is missing, start with `python3 scripts/jms_diagnose.py config-status --json`
- if you switch JumpServer targets, accounts, orgs, or `.env.local` content, rerun the full first-run validation flow

Implementation notes:

- `scripts/jms_runtime.py` currently constructs the client with `verify=False`
- HTTPS certificate warnings are suppressed
- these two behaviors are not currently controlled by environment variables

## Common Commands

Object queries:

```bash
python3 scripts/jms_assets.py list --resource asset --filters '{"name":"demo-asset"}'
python3 scripts/jms_assets.py get --resource user --id <user-id>
python3 scripts/jms_diagnose.py resolve --resource node --name demo-node
python3 scripts/jms_diagnose.py resolve-platform --value Linux
```

Access analysis:

```bash
python3 scripts/jms_diagnose.py user-assets --username demo-user
python3 scripts/jms_diagnose.py user-nodes --username demo-user
python3 scripts/jms_diagnose.py user-asset-access --username demo-user --asset-name demo-asset
```

Audit queries:

```bash
python3 scripts/jms_audit.py list --audit-type login --filters '{"limit":10}'
python3 scripts/jms_audit.py get --audit-type command --id <command-id> --filters '{"command_storage_id":"<command-storage-id>"}'
```

## Docs Map

| File | Purpose |
|---|---|
| `SKILL.md` | routing rules, environment-init boundaries, and query boundaries |
| `references/runtime.md` | environment model, `.env.local` writes, and org persistence |
| `references/assets.md` | asset query guide |
| `references/permissions.md` | permission query guide |
| `references/audit.md` | audit query guide |
| `references/diagnose.md` | config/org/resolution/access-analysis guide |
| `references/safety-rules.md` | allowed environment writes and forbidden business writes |
| `references/troubleshooting.md` | common troubleshooting paths |

## Unsupported Scope

- asset, platform, node, account, user, user-group, and organization create/update/delete/unblock operations
- permission create/update/append/remove/delete operations
- temporary SDK/HTTP scripts that bypass the supported workflow
