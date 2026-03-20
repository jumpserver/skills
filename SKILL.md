---
name: jumpserver-skills
description: JumpServer V4 query and change-execution skill for bundled `jms_*.py` entrypoints. Use when users mention 资产、账号、用户、用户组、组织、平台、节点、权限、审计、访问分析、配置 JumpServer、切换环境，或出现 `asset`、`account`、`user`、`organization`、`platform`、`node`、`permission`、`audit`、`diagnose`、`resolve-platform` 等触发词。 Always do `config-status --json` and `ping` 预检 before choosing `jms_assets.py`、`jms_permissions.py`、`jms_audit.py`、`jms_diagnose.py`; when org is not selected, run `select-org` first, and only auto-write `00000000-0000-0000-0000-000000000002` when the accessible org set is exactly `{0002}` or `{0002,0004}`; `jms_audit.py` defaults to the last 7 days when `date_from/date_to` are omitted, omitting `limit` means auto-paging within the current time window rather than all history, and `audit-type=command` requires `command_storage_id`; Not for temporary SDK/HTTP scripts, guessed IDs or orgs, or cross-org authorization.
---

# JumpServer Skills

执行型 JumpServer operator：先预检，再选 4 个正式入口；高风险写操作固定 `预检 -> 预览 -> 确认 -> 回读确认`。

## Quick Reference / 快速路由

| Intent | Must Use | Precheck | Preview | Confirm | Readback | Stop If |
|---|---|---|---|---|---|---|
| 配置 JumpServer、切换环境、依赖异常、连通性异常、组织选择 | `jms_diagnose.py` | `config-status --json` | 否 | 仅 `config-write` / `select-org` | `ping` / `select-org` 结果 | 缺失配置字段、鉴权不完整 |
| 查资产、账号、用户、用户组、组织、平台、节点 | `jms_assets.py` | 依赖检查 -> `ping` -> 必要时 `select-org` | 否 | 否 | `get` / `list` | 名称不唯一、对象不清楚、尚未选组织 |
| 更新资产/平台/节点、创建用户、解锁用户、删除对象 | `jms_assets.py` | 依赖检查 -> `ping` | 是 | 是 | `get` / 关键状态查询 | 平台未解析、目标不唯一 |
| 给用户加授权、改授权、移除关系、删授权 | `jms_permissions.py` | `config-status --json` -> `ping` -> 必要时 `select-org` -> 解析 `effective_org` | `append` 之外通常是 | `update/remove/delete` 是 | `get` / 权限详情 | 尚未选组织、对象跨组织、名称多命中 |
| 查最近谁登过机器、查操作/会话/命令审计 | `jms_audit.py` | 依赖检查 -> `ping` -> 必要时 `select-org` | 否 | 否 | 时间线摘要 / `get` | 尚未选组织、`audit-type` 不明确、想查全部历史但未给时间范围、`command` 缺 `command_storage_id`、"所有日志" 同时指全部类型或全部组织 |
| 访问分析、对象解析、平台解析、最近审计预检 | `jms_diagnose.py` | 依赖检查 -> `ping` -> 必要时 `select-org` | 否 | 否 | 解析结果 / 有效视图 | 候选过多、定位参数不足、尚未选组织 |
| 想直接写临时 SDK/HTTP 脚本绕过正式入口 | 停止 | 说明已有正式入口或需扩展 wrapper | 否 | 否 | 否 | 标准流程已覆盖 |

- 所有正式动作只能走 `python3 scripts/jms_assets.py ...`、`python3 scripts/jms_permissions.py ...`、`python3 scripts/jms_audit.py ...`、`python3 scripts/jms_diagnose.py ...`。
- 未选组织时先读取当前环境全部可访问组织，并通过 `python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm` 写入 `JMS_ORG_ID`。
- 只有当可访问组织集合恰好是 `{0002}` 或 `{0002,0004}` 时，系统才会自动将 `0002` 写入 `.env.local` 并继续；这不是通用默认组织。
- 当前处理组织是 A、目标对象组织是 B 时直接阻塞，并返回 `cross_org_block_reason`；跨组织授权禁止。
- `jms_audit.py` 未传 `date_from/date_to` 时默认最近 7 天；省略 `limit` 时自动翻页拉当前时间窗内全量，不是全部历史。
- “查所有日志”若未明确 `audit-type`、时间范围或组织范围，先停下澄清；`command` 审计必须先拿到 `command_storage_id`。

## 你是什么 / What This Is

- 这是执行型 skill，不是概念说明书，也不是临时脚本生成器。
- 标准流程已覆盖时，直接用正式入口，不生成临时 SDK Python 脚本、一次性 HTTP 脚本或猜测性 fallback。
- 若仓库当前没有对应动作，停止执行并说明需要扩展 wrapper。

## Use when / 什么时候必须用

- 用户提到资产、账号、用户、用户组、组织、平台、节点、权限、审计、访问分析。
- 用户要求配置 JumpServer、切换环境、检查依赖、检查配置、检查连通性。
- 用户要求查询、创建、更新、删除、解锁、改密、追加授权、移除关系、调查最近登录/会话/命令记录。
- English triggers: `asset`, `account`, `user`, `user-group`, `organization`, `platform`, `node`, `permission`, `audit`, `diagnose`, `resolve-platform`, `access analysis`.

## 收到任何请求先做什么 / Precheck

```text
依赖检查 -> config-status --json -> config-write --confirm（如需） -> ping -> 选 1 个正式入口
```

- 配置或环境不确定时，先执行 `python3 scripts/jms_diagnose.py config-status --json`。
- `complete=false` 时，按 `JMS_API_URL -> 鉴权模式 -> 凭据 -> JMS_ORG_ID -> JMS_VERSION -> JMS_TIMEOUT` 收集，回显脱敏摘要后再 `config-write --confirm`。
- 未选组织时，先读取当前环境组织；若不是 `{0002}` 或 `{0002,0004}` 特判环境，则先 `select-org --org-id <org-id> --confirm`。
- 若当前配置的 `JMS_ORG_ID` 已不可访问，先重新 `select-org`，不要继续业务命令。
- 名称不唯一、对象不清楚、平台不是数字 ID 时，先 `resolve` 或 `resolve-platform`，不要直接变更。

## High-Risk Writes / 高风险写操作

- 固定顺序：`预检 -> 预览 -> 确认 -> 回读确认`。
- `update`、`unblock`、`delete`、`remove` 必须先走 `preview-*`，再执行 `--confirm`。
- `append` 只适用于单主体、单关系、范围明确的定向追加；不满足时改成预览或停止。
- 删除、大范围授权、关系移除前先总结影响范围；无法总结时拒绝执行。
- 用户解锁、用户改密、平台更新前先确认目标对象 ID；执行后回读关键状态。

## Not for / 不适用

- 不适用于“给我写个临时 SDK/HTTP 脚本直接调 API”这类绕过正式入口的请求。
- 不适用于“名字差不多就继续删/改/授权”的猜测式变更。
- 不适用于“多组织未说明组织，但仍要求继续做权限写操作”的场景。
- 不适用于“当前在 A 组织，却要求授权 B 组织资产/节点/用户组”的跨组织授权。
- 纯概念解释且不需要执行时，可以简要说明规则，但不要伪造执行结果或编造命令。

## Command Skeletons / 命令骨架

配置状态：

```bash
python3 scripts/jms_diagnose.py config-status --json
```

连通性检查：

```bash
python3 scripts/jms_diagnose.py ping
```

组织选择：

```bash
python3 scripts/jms_diagnose.py select-org
python3 scripts/jms_diagnose.py select-org --org-id <org-id>
python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm
```

平台解析：

```bash
python3 scripts/jms_diagnose.py resolve-platform --value Linux
```

精确查询资产或用户：

```bash
python3 scripts/jms_assets.py list --resource user --filters '{"username":"openclaw"}'
python3 scripts/jms_assets.py list --resource asset --filters '{"name":"openclaw资产"}'
```

预览权限创建：

```bash
python3 scripts/jms_permissions.py preview-create --payload '{"name":"openclaw授权规则","users":["<user-id>"],"assets":["<asset-id>"],"accounts":["@SPEC","root"],"actions":["connect"],"protocols":["all"],"is_active":true}'
```

预览用户解锁：

```bash
python3 scripts/jms_assets.py preview-unblock --resource user --id <user-id>
python3 scripts/jms_assets.py unblock --resource user --id <user-id> --confirm
```

审计查询：

```bash
python3 scripts/jms_audit.py list --audit-type operate
python3 scripts/jms_audit.py list --audit-type login --filters '{"limit":30}'
python3 scripts/jms_audit.py list --audit-type login --filters '{"date_from":"2026-03-01 00:00:00","date_to":"2026-03-20 23:59:59"}'
python3 scripts/jms_audit.py get --audit-type command --id <command-id> --filters '{"command_storage_id":"<command-storage-id>"}'
```

访问分析：

```bash
python3 scripts/jms_diagnose.py user-assets --username openclaw
python3 scripts/jms_diagnose.py user-asset-access --username openclaw --asset-name openclaw资产
```

## 命中示例 / Use when Examples

| 用户说法 | 正确动作 |
|---|---|
| 帮我查某用户有哪些资产 | 命中 `jms_diagnose.py user-assets`，先预检；若未选组织则先 `select-org` |
| 帮我查某用户有哪些节点 | 命中 `jms_diagnose.py user-nodes`，先解析用户 |
| 给这个用户加授权 | 命中 `jms_permissions.py`，先确保已选组织，再解析 `effective_org`、主体和资源 |
| 把这个用户直接解锁 | 改写成 `preview-unblock -> unblock --confirm -> 回读确认` |
| 删除这个节点 | 改写成 `preview-delete -> delete --confirm -> 回读确认` |
| 把 Linux 平台改一下 | 先 `resolve-platform`，唯一命中后再 `preview-update -> update --confirm` |
| 查最近谁登过这台机器 | 命中 `jms_audit.py`，先明确 `audit-type` 和时间范围 |
| 查最近 30 条操作日志 | 直接命中 `jms_audit.py list --audit-type operate`；默认时间窗是最近 7 天 |
| 查这个组织最近 30 条登录日志 | 直接命中 `jms_audit.py list --audit-type login`；按当前组织上下文执行 |
| 帮我配置 JumpServer | 命中 `config-status --json -> config-write --confirm -> ping` |
| 我还没选组织，先帮我切到 Default | 命中 `jms_diagnose.py select-org --org-id 00000000-0000-0000-0000-000000000002 --confirm` |
| 查某用户在某资产下有哪些账号 | 命中 `jms_diagnose.py user-asset-access` |
| 没说组织，直接给用户加授权 | 先解析 `effective_org`；若可访问组织大于 1，则返回 `candidate_orgs` 并停止 |
| 我在 A 组织给 B 组织资产加授权 | 直接阻止，返回 `cross_org_block_reason` |

## 不命中示例 / Not for Examples

| 用户说法 | 正确处理 |
|---|---|
| 给我写个临时脚本调一下 API | 拒绝临时脚本；改用正式入口，或说明需要扩展 wrapper |
| Linux 平台大概就是 1，直接改吧 | 拒绝猜平台 ID；先 `resolve-platform` |
| 这个名字差不多，先删了 | 拒绝；先列候选并要求确认 |
| 跳过 `config-status`，直接帮我改 | 拒绝跳过预检 |
| 这个组织名字看起来像 Default，就直接用它 | 拒绝按名字猜组织；先列出环境组织并显式 `select-org` |
| 所有环境都默认用 0002 就行 | 拒绝；只有 `{0002}` 或 `{0002,0004}` 两种保留组织环境才自动写入 0002 |
| 当前在 A 组织，直接给 B 组织资产授权 | 拒绝；跨组织授权禁止 |
| 查所有日志 | 先追问 `audit-type`、时间范围、组织范围；不要默认理解为全部历史 + 全部类型 + 全部组织 |
| 查全部命令日志 | 若无 `command_storage_id`，停止并要求补充；不要伪造全局命令审计 |

## 输出模板 / Output

查询类输出：

```text
已走预检：<依赖检查 / config-status / ping>
正式入口：<jms_assets.py / jms_permissions.py / jms_audit.py / jms_diagnose.py>
effective_org：<id + name + source>
参考文档：<reference>
执行命令：<command>
结果摘要：<summary>
```

变更类输出：

```text
已走预检：<依赖检查 / config-status / ping>
effective_org：<id + name + source>
目标对象：<object + id>
预览命令：<preview command>
确认后执行：<command with --confirm>
回读确认：<readback command or key state>
```

阻塞类输出：

```text
已走预检：<done steps>
effective_org：<id + name + source>
阻塞原因：<missing env / ambiguous object / unsupported action>
candidate_orgs：<when multi-org or ambiguous>
cross_org_block_reason：<when current org != target org>
还缺什么：<fields or user confirmation>
下一步：<next safe action>
```
