---
name: jumpserver-skills
description: JumpServer V4.10 查询与分析 skill。Use when users ask to query assets/accounts/users/organizations/permissions, inspect access or governance, audit logins/sessions/commands/file transfers, diagnose config or organization issues, or analyze JumpServer usage data for a specific day or time range such as 使用报告、日报、某天使用情况、某天登录/会话/命令/传输情况、usage report, daily usage report, usage analysis, or JumpServer usage overview.
---

# JumpServer Skills

只使用正式 CLI 入口：

- `python3 scripts/jumpserver_api/jms_query.py ...`
- `python3 scripts/jumpserver_api/jms_diagnose.py ...`
- `python3 scripts/jumpserver_api/jms_report.py ...`

这是查询与分析 skill。允许本地运行时写入 `config-write --confirm` 和 `select-org --confirm`。不执行 JumpServer 业务写操作。

## Route First

按下面顺序判路由。上面的规则优先于下面的规则。

1. 如果用户请求的核心对象是某一天或某一段时间内的 JumpServer 使用数据分析，优先命中 HTML 模板工作流。这包括：使用报告、日报、使用情况、使用分析、审计分析、某天发生了什么、分析 `20260310`、看下 / 看看 `3 月 10 号` 使用情况、帮我看 / 帮我看看某天登录/会话/命令/传输情况、想看上周谁登录最多、过一下 `3 月上旬` 哪些资产最活跃，以及类似的“时间范围内使用情况 / 概览 / 汇总 / 排行 / TOP”表达。
动作：优先使用 `python3 scripts/jumpserver_api/jms_report.py daily-usage ...`，并由它加载 [template/bastion-daily-usage-template.html](template/bastion-daily-usage-template.html) 和 [references/metadata/daily_usage_report_template_fields.json](references/metadata/daily_usage_report_template_fields.json)；先把“昨天 / 20260310 / 3月10号 / 上周 / 本月”等时间表达归一化为明确时间窗，再生成并验证完整 HTML 报告；模板细节见 [references/report-template-playbook.md](references/report-template-playbook.md)。

2. 如果用户要配置 JumpServer、检查依赖、检查配置、检查连通性、切换组织、查看许可证、系统设置、报表、工单、存储、终端或做对象解析，先走 `jms_diagnose.py`。
动作：先预检，再用 `config-status` / `ping` / `select-org` / `inspect` / `resolve`。

3. 如果用户要查某某用户当前能访问哪些资产、节点，或在某资产下有哪些账号 / 协议，归为“用户有效访问范围”，先走 `jms_diagnose.py`。
动作：显式给了组织就先按用户指定组织执行；结果型问法优先 `user-assets` / `user-nodes` / `user-asset-access`，先返回有效访问范围结果，不回退成授权规则说明；`user-assets` / `user-nodes` 的 effective access 结果是资产/节点清单的唯一权威来源。

4. 如果用户要看授权规则、ACL、RBAC、为什么某人能访问某资产、某条权限详情，走 `jms_query.py`。
动作：`资产授权给了谁 / 谁被授权到这台资产 / 这台资产有哪些授权用户` 优先 `asset-perm-users`；`为什么会被授权 / 节点授权是否覆盖它 / 权限详情` 优先 `jms_diagnose.py asset-permission-explain` + `permission-list/get`；必要时再做访问分析。
只有明确问“为什么 / 依据 / 授权规则 / 权限详情”时，才进入这一类。

5. 如果用户要查登录、会话、终端会话、命令记录、文件传输、异常行为、高危命令、失败登录、特权账号使用审计，走 `jms_query.py`。
动作：优先 `audit-analyze --capability ...`，需要明细时再用 `audit-list` / `audit-get` / `terminal-sessions`。如果问法是“某用户某天连接过哪些机器 / 某天会话数 / 某天连了几次”，先解析用户，再优先 `audit-analyze --capability session-record-query`；不要先用 `audit-list --audit-type session` 下结论。

6. 如果用户要查资产、节点、平台、账号、账号模板、用户、用户组、组织、标签、网域等对象，走 `jms_query.py`。
动作：只做 `object-list` / `object-get`；名称不唯一时先解析，不要猜。

7. 如果用户要做治理巡检、聚合分析、账号治理、资产治理、访问分析、系统巡检或 capability 型统计，走 `jms_diagnose.py inspect --capability ...`。
动作：优先 capability，不手工拼多条零散查询。

普通路由细节、更多命中说法和反例见 [references/routing-playbook.md](references/routing-playbook.md)。

## Template Overrides

按下面顺序处理模板例外。上面的规则优先于下面的规则。

1. 如果用户明确说“不要生成报告，直接分析”“先简单说下”“只给我结论”“不用模板”，才允许跳过模板，直接给简短分析。
2. 除上述明确例外外，只要是某一天或某一段时间的 JumpServer 使用情况 / 使用分析 / 审计分析，或者表达为某时间段的登录 / 会话 / 命令 / 传输情况、排行、TOP、谁最多，就必须先走模板工作流。
3. “分析”不等于自由文本优先。带时间范围的使用分析、情况概览或排行类问题，默认先产出完整 HTML 报告；摘要只能作为补充，不能替代报告。

## Organization Priority

按下面顺序处理组织。上面的规则优先于下面的规则。

1. 用户显式给组织：按用户指定组织执行。
2. 报告或使用分析模板请求且用户未指定组织，或明确指定“所有组织”“全局组织”：默认执行 `python3 scripts/jumpserver_api/jms_diagnose.py select-org --org-id 00000000-0000-0000-0000-000000000000 --confirm`。
3. 全局组织 `00000000-0000-0000-0000-000000000000` 的可访问性不只看候选组织列表；允许通过显式 `select-org` / 直连探测确认。
4. 如果全局组织 `00000000-0000-0000-0000-000000000000` 的直连探测或显式选择验证失败：直接阻塞并返回 `candidate_orgs`；不要回退到 `{0002}` / `{0002,0004}` 自动规则。
5. 非报告类请求且未指定组织：沿用保留组织逻辑。只有可访问组织集合恰好是 `{0002}` 或 `{0002,0004}` 时，才自动写入 `0002`。
6. 当前 `JMS_ORG_ID` 已不可访问：先重新 `select-org`，不要继续业务命令。
7. 查询类请求在未确定组织且存在多个可访问组织时：先返回 `candidate_orgs` 并要求用户选择查询组织。
8. 查询类请求在当前组织已生效且仍有其他可切换组织时：继续返回 `switchable_orgs`，提示用户还可以切换到哪些组织查询。
9. 用户明确说“在 Default 组织下”“在某组织下”这类表达时，视为显式组织，不是弱过滤提示；先解析组织并切到目标组织，再查用户有效访问范围。

## Standard Flow

收到请求先做：

```text
自动检查依赖 -> config-status --json -> 必要时 config-write --confirm -> ping -> 按路由和组织优先级选择正式入口
```

执行规则：

- 配置或环境不确定时，先执行 `python3 scripts/jumpserver_api/jms_diagnose.py config-status --json`。
- `complete=false` 时，先补齐配置，再继续。
- 名称不唯一、平台不明确、对象跨组织时，先解析或阻塞，不要猜。
- “某某用户在某组织下有哪些资产 / 节点 / 账号” 这类请求先解析组织；优先直接使用 `--org-id` / `--org-name` 在单次命令内限定组织，不要求先写回 `.env`。对中文姓名等显示名，允许先解析用户对象，再用 `user-id` 执行 `user-assets` / `user-nodes` / `user-asset-access`。
- 审计类问题没有 `date_from/date_to` 时，默认最近 7 天；想查更大范围时优先要求明确时间窗。
- “某用户某天连接过哪些机器 / 某天会话数” 这类问题，优先返回两套口径：`session_count` 与去重后的 `assets`；机器列表用去重资产，不要把会话条数直接说成机器数。
- 模板化使用报告/使用分析请求必须先走 `python3 scripts/jumpserver_api/jms_report.py daily-usage ...`；它会负责时间归一化、组织处理、字段元数据取数、模板填充和生成后自检。普通查询优先只选 1 个正式入口。

## Guardrails

- 不生成临时 SDK Python 脚本或 HTTP 脚本。
- 不猜对象 ID、平台 ID、组织、鉴权信息或筛选条件。
- 不创建、更新、删除、解锁对象，也不追加或移除权限关系。
- 权限问题只做读取和解释，不做权限写入。
- 对“某某用户在某组织下有哪些资产”不要直接返回授权规则说明，也不要把“有哪些资产”自动翻译成“解释访问依据”；显式组织问法不得回退成“检查所有组织”。
- 不要因为句子里带了“用户”二字就优先落到权限关系；结果型问法先返回有效访问范围结果。
- 只有正式入口在精确时间窗和正确组织下实际返回 `0` 条时，才能说“没有记录”；不要因为单个入口没命中就下结论。
- 未经验证，不要猜测“页面选错日期”“时区差异”“数据同步延迟”“数据未同步”等原因。
- 页面总数与用户过滤结果不一致时，要明确区分“当天总会话数”和“该用户会话数”，不要混成一个数字。
- 模板化报告请求必须优先使用 `python3 scripts/jumpserver_api/jms_report.py daily-usage ...`；不要现场写临时拼装逻辑。若正式入口缺失，应先补齐正式入口，再使用它。
- 模板化报告请求只使用字段元数据里声明的来源，不用 Markdown 模板替代 HTML 模板。
- 模板化报告请求中的命令审计字段，未显式给 `command_storage_id` 时默认汇总全部可访问 command storage；普通命令审计查询仍沿用默认 storage / 单个 storage / 多 storage 阻塞逻辑。

## Respond With

成功时至少回显：

- 已走预检
- 选中的正式入口或模板路径
- `effective_org`
- `switchable_orgs`（当当前组织已生效且仍有其他可切换组织时）
- 执行命令摘要
- 用户有效访问范围：`asset_count` + `assets`，或 `node_count` + `nodes`，或 `permed_accounts` + `permed_protocols`
- 其他普通查询：结果摘要
- 模板报告：完整 HTML 报告，且已经通过生成后自检

模板报告成功时还至少回显：

- 正式入口：`python3 scripts/jumpserver_api/jms_report.py daily-usage ...`
- 报告文件路径
- 模板路径：`template/bastion-daily-usage-template.html`
- 字段元数据路径：`references/metadata/daily_usage_report_template_fields.json`
- `queried_command_storage_ids`
- `queried_command_storage_count`
- `report_date`
- `date_from`
- `date_to`
- `validation_summary`
- 可附加简短摘要，但不得仅返回摘要替代报告

阻塞时至少回显：

- 已走预检
- `effective_org`
- 阻塞原因
- `candidate_orgs` 或 `candidate_objects`
- 下一步安全动作

## References

- [普通路由与阻塞规则](references/routing-playbook.md)
- [报告模板工作流](references/report-template-playbook.md)
- [运行入口与环境](references/runtime.md)
- [诊断与访问分析](references/diagnose.md)
- [安全规则](references/safety-rules.md)
