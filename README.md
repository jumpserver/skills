# JumpServer Skills

`jumpserver-skills` 是一个面向 JumpServer V4.10 的查询、审计分析与模板化使用报告 skill 仓库，适用于对象查询、权限回看、审计调查、治理巡检、访问分析，以及某一天或某一段时间的堡垒机使用报告。它更像一套可复用的 skill 规则与正式入口封装，而不是要求使用者手动拼接脚本命令的 CLI 教程。

仓库内部会按请求类型自动路由到 `jms_query.py`、`jms_diagnose.py`、`jms_report.py` 三类正式入口。默认保持只读，仅允许本地运行时写入 `.env` 和当前组织上下文，不执行 JumpServer 业务写操作。

[English](./README.en.md)

## 最快上手

1. 把这个 skill 接到你的 agent 或 Codex 环境里。仓库中的 [agents/openai.yaml](./agents/openai.yaml) 可以直接作为接入描述使用。
2. 直接用自然语言初始化配置，例如“帮我生成 `.env`，JumpServer 地址是 `https://jump.example.com`，我用 AK/SK 登录”。
3. 然后继续直接提需求，例如“查某某用户在 Default 组织下有哪些资产”或“看看昨天使用情况”。

第一次使用时，优先推荐走“自然语言对话生成 `.env`”这条路径，通常比手动改模板更快。

## 这个 skill 能做什么

| 能力分组 | 适合处理的请求 | 入口名称 | 说明 |
|---|---|---|---|
| 对象查询 | 资产、账号、用户、用户组、组织、平台、节点、标签、网域查询 | `jms_query.py` | 适合精确查询对象清单或读取单个对象详情 |
| 权限关系 | 授权规则、ACL、RBAC、谁能访问某资产、某条权限详情 | `jms_query.py` | 只做读取和解释，不承担权限写入 |
| 审计调查 | 登录、会话、命令、文件传输、异常行为、高危命令、失败登录调查 | `jms_query.py` | 适合日志、记录、明细、详情类请求 |
| 配置与诊断 | 配置检查、连通性、组织切换、对象解析、许可证、系统设置、存储、工单 | `jms_diagnose.py` | 适合预检、环境确认和治理前置检查 |
| 用户有效访问范围 | 某某用户有哪些资产、某某用户在某组织下有哪些节点、某某用户在某资产下有哪些账号/协议 | `jms_diagnose.py` | 优先返回 effective access 结果，不默认展开授权规则说明 |
| 治理巡检 | 资产治理、账号治理、访问分析、系统巡检、capability 聚合分析 | `jms_diagnose.py` | 优先走能力化聚合，而不是让使用者手工拼零散查询 |
| 使用报告 | 日报、使用情况、使用分析、某天发生了什么、某时间段排行或概览 | `jms_report.py` | 这类请求默认输出完整 HTML 报告，而不是只给一句摘要 |

## 怎么使用这个 skill

1. 准备环境文件。在仓库根目录创建 `.env`，有两种方式：

手动方式：

```bash
cp .env.example .env
```

对话方式：

如果本地配置不完整，运行时也可以直接通过自然语言对话帮你生成 `.env`。它会按固定顺序收集 `JMS_API_URL`、认证方式、组织、超时和 TLS 配置，回显脱敏摘要后写入本地 `.env`。例如：

- “帮我生成 `.env`，JumpServer 地址是 `https://jump.example.com`，我用 AK/SK 登录。”
- “帮我初始化 JumpServer 配置，我用用户名密码登录，不校验证书。”

2. 把这个 skill 接到你的 agent 或 Codex 环境里使用。仓库中的 [agents/openai.yaml](./agents/openai.yaml) 提供了一个现成的 skill 接入描述，可作为引用或注册该 skill 的入口之一。

3. 直接用自然语言描述需求，不需要手动拼接脚本命令。例如“查某某用户在 Default 组织下有哪些资产”“看看昨天使用情况”“看某条授权规则详情”。

4. 根据返回结果继续补充上下文。如果结果提示 `candidate_orgs`、`switchable_orgs`、候选对象或缺少时间范围，就按提示补充组织、对象名称、平台或时间窗口。组织必须先选时，返回里还会带 `reason_code`、`user_message`、`action_hint` 和 `candidate_org_count`，方便直接按提示继续。

使用时不需要记住具体执行命令。这个 skill 会先做预检，再按路由规则自动选择正式入口，并在需要时提示你补充组织、对象或时间范围。

## 环境变量

仓库根目录下提供了 [`.env.example`](./.env.example) 作为模板。实际使用时，需要在仓库根目录准备 `.env` 文件；可以直接复制模板后修改，也可以参考模板手动新建。

如果不想手动编辑，也可以直接通过自然语言对话生成 `.env`。当检测到配置缺失或不完整时，skill 会按顺序收集必要字段，并通过正式入口把配置写入本地 `.env`。

如果你想一次把信息说清，通常准备下面这些就够了：

- `JMS_API_URL`
- 一组完整认证方式：`JMS_ACCESS_KEY_ID/JMS_ACCESS_KEY_SECRET` 或 `JMS_USERNAME/JMS_PASSWORD`
- `JMS_ORG_ID`，不确定时可以先留空
- `JMS_TIMEOUT`，不填则使用默认值
- `JMS_VERIFY_TLS`，不填时默认 `false`

| 变量 | 是否必需 | 说明 |
|---|---|---|
| `JMS_API_URL` | 必需 | JumpServer API / 访问地址 |
| `JMS_ACCESS_KEY_ID` | 与 `JMS_ACCESS_KEY_SECRET` 成组，或改用用户名密码 | API Access Key ID |
| `JMS_ACCESS_KEY_SECRET` | 与 `JMS_ACCESS_KEY_ID` 成组，或改用用户名密码 | API Access Key Secret |
| `JMS_USERNAME` | 与 `JMS_PASSWORD` 成组，或改用 AK/SK | JumpServer 登录用户名 |
| `JMS_PASSWORD` | 与 `JMS_USERNAME` 成组，或改用 AK/SK | JumpServer 登录密码 |
| `JMS_ORG_ID` | 初始化时可选 | 业务执行前会通过组织选择流程或保留组织规则写入 |
| `JMS_TIMEOUT` | 可选 | 请求超时秒数 |
| `JMS_VERIFY_TLS` | 可选 | 是否校验证书，默认 `false` |

环境变量规则：

- 必须提供 `JMS_API_URL`。
- 认证方式至少完整提供一组：`JMS_ACCESS_KEY_ID/JMS_ACCESS_KEY_SECRET` 或 `JMS_USERNAME/JMS_PASSWORD`。
- `.env` 会被运行时自动加载。
- 如果 `.env` 缺失或不完整，可以直接通过自然语言对话补齐，运行时会在确认后生成或覆盖本地 `.env`。
- 首次使用前，需要确保地址、认证方式、组织、超时和 TLS 配置齐全。
- 如果切换了 JumpServer、账号、组织或 `.env` 内容，应重新执行完整预检。

## 典型请求示例

- “查一下 `Demo-User` 这个用户的详情。”
- “看看名为 `Demo-Node` 的资产节点里有哪些资产。”
- “帮我看 `Linux` 平台下有哪些可用资产。”
- “查某某用户在 Default 组织下有哪些资产。”
- “看这条授权规则详情，顺便告诉我它影响哪些用户和资产。”
- “谁能访问这台资产？”
- “查最近一周的登录审计。”
- “看某个用户的会话记录和异常中断情况。”
- “帮我排查昨天的高危命令和文件传输审计。”
- “看看某天使用情况。”
- “帮我看昨天登录情况。”
- “想看上周谁登录最多。”
- “过一下 3 月上旬哪些资产最活跃。”
- “看某天登录日志明细。”
- “导出某天命令记录详情。”

这类边界尤其重要：

- `某某用户在 Default 组织下有哪些资产`、`某某用户有哪些节点`、`某某用户在某资产下有哪些账号` 这类结果型问法，属于用户有效访问范围，优先返回资产 / 节点 / 账号范围结果。
- `某某用户为什么能访问某资产`、`某条授权规则详情` 这类原因型问法，属于权限关系或访问分析。
- `某天登录情况`、`某天会话概览`、`某时间段谁最多` 这类表达，属于报告/使用分析。
- `某天登录日志`、`某天命令记录`、`某条会话详情` 这类表达，属于审计调查。

## 使用报告与时间范围规则

只要请求的核心对象是某一天或某一段时间内的 JumpServer 使用数据分析，就会优先走模板化报告流程。这包括：

- 使用报告、日报、周报、月报
- 使用情况、使用分析、使用统计、使用汇总、使用概览
- 审计分析、某天发生了什么
- 某天登录 / 会话 / 命令 / 传输情况
- 某时间段的排行、TOP、谁最多、哪些资产最活跃

这类请求默认直接产出完整 HTML 报告，不先回退成自由文本摘要。只有当用户明确说“不要生成报告，直接分析”“先简单说下”“只给我结论”“不用模板”时，才允许跳过模板直接给简短分析。

时间表达会先归一化为明确时间窗：

- “昨天” -> 前一天 `00:00:00 ~ 23:59:59`
- `20260310` -> `2026-03-10 00:00:00 ~ 23:59:59`
- `2026-03-10` / `2026/03/10` / `3月10号` / `3 月 10 日` -> 同一天 `00:00:00 ~ 23:59:59`
- “上周” -> 上一个自然周，周一 `00:00:00 ~ 周日 23:59:59`
- “本月” -> 本月 1 日 `00:00:00` 到当前日期或月末 `23:59:59`

报告固定输出到 `reports/JumpServer-YYYY-MM-DD.html`。如果请求里涉及命令审计字段，报告会按既定规则处理可访问的 command storage 汇总，不需要使用者手动选择内部取数逻辑。

## 组织选择与阻塞规则

- 用户显式指定组织时，按用户指定组织执行。
- 报告或使用分析请求未指定组织，或用户明确说“所有组织”“全局组织”时，默认优先尝试全局组织 `00000000-0000-0000-0000-000000000000`。
- 普通查询请求未指定组织时，会按现有组织规则处理；如果无法自动确定组织，会返回 `candidate_orgs`，并通过 `user_message` / `action_hint` 明确要求先选择查询组织。
- 当前组织已生效但仍有其他可切换组织时，结果会继续回显 `switchable_orgs`，并通过 `org_context_hint` 明确说明当前查询范围固定在哪个组织。
- 如果当前组织是 A、目标对象在 B，不会自动跨组织继续执行。

出现下面这些情况时，skill 会先阻塞，而不是继续猜测执行：

- 配置或鉴权不完整
- 组织不明确，且不能自动确定
- 对象名称重名或平台不明确
- 查询结果跨组织
- 报告请求的全局组织不可访问
- 用户试图绕过正式入口或跳过预检

其中组织阻塞响应会额外返回这些结构化字段：

- `reason_code=organization_selection_required`
- `user_message`：明确提示“继续前必须先选择一个组织”
- `action_hint`：给出安全下一步命令模板
- `candidate_org_count`：当前候选组织数量
- `org_selection_policy=required_before_query_when_multiple_accessible_orgs`

## 文档地图

| 文件 | 用途 |
|---|---|
| [SKILL.md](./SKILL.md) | skill 的顶部路由规则、组织优先级与响应约束 |
| [agents/openai.yaml](./agents/openai.yaml) | skill 接入描述与默认提示词入口 |
| [references/routing-playbook.md](./references/routing-playbook.md) | 普通路由、典型触发词、阻塞规则与反例 |
| [references/report-template-playbook.md](./references/report-template-playbook.md) | 模板化报告流程、组织优先级、时间范围与报告规则 |
| [references/runtime.md](./references/runtime.md) | 预检流程、环境变量模型、组织选择与运行时约束 |
| [references/capabilities.md](./references/capabilities.md) | capability 能力目录与能力说明 |
| [references/assets.md](./references/assets.md) | 资产、账号、用户、节点、平台等对象查询说明 |
| [references/permissions.md](./references/permissions.md) | 权限、ACL、RBAC 与授权关系查询说明 |
| [references/audit.md](./references/audit.md) | 登录、会话、命令、文件传输等审计说明 |
| [references/diagnose.md](./references/diagnose.md) | 连通性、对象解析、访问分析、系统巡检与治理说明 |
| [references/safety-rules.md](./references/safety-rules.md) | 查询边界、本地写入例外与阻塞规则 |
| [references/troubleshooting.md](./references/troubleshooting.md) | 常见错误排查与恢复建议 |

## 不支持范围

- 资产、平台、节点、账号、用户、用户组、组织的创建、更新、删除、解锁。
- 权限创建、更新、追加关系、移除关系、删除。
- 跳过预检直接执行业务动作。
- 临时 SDK/HTTP 脚本绕过正式入口。
- 报告类请求绕过 `jms_report.py` 正式入口，改用现场临时拼装逻辑。
- 在对象不明确、组织不明确或跨组织场景下继续猜测执行。
