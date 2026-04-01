# 诊断与访问分析

## 快速概览

- 开始前先到 [runtime.md](runtime.md) 判断本次是“首次全量校验”还是“后续轻量校验”。
- 主入口：`python3 scripts/jumpserver_api/jms_diagnose.py <subcommand> ...`
- 适合连通性检查、对象解析、服务端有效访问范围分析、最近审计预检、系统设置巡检、许可证读取、工单列表、终端组件/命令存储/录像存储查询、报表读取、账号自动化概览、核心端点 inventory 与按路径验证。
- `select-org` 是显式组织选择入口；未选组织时，除 `config-status`、`config-write`、`ping`、`select-org` 外，其余子命令都会先阻塞。
- 当当前组织已生效时，`ping`、`select-org` 以及主要查询结果会额外回显仍可切换的组织列表，便于继续按其他组织范围查询。
- 统计与巡检类聚合请求优先用 `inspect --capability ...`；需要直连读取某类设置或系统对象时，再用专用子命令。

## 子命令与适用场景

| 子命令 | 何时用 | 必需定位参数 | 关键输出 |
|---|---|---|---|
| `config-status` | 查看本地运行时配置是否完整 | 无 | `complete`、认证方式、`missing_fields`、`invalid_fields` |
| `config-write` | 把对话收集到的运行时配置写入 `.env` | `--payload` + `--confirm` | 脱敏后的当前配置摘要 |
| `ping` | 验证环境与 API client 连通性 | 无 | 是否可连接、当前用户、当前组织、可切换组织 |
| `select-org` | 查看当前环境组织或显式写入 `JMS_ORG_ID` | 可选 `--org-id` | `candidate_orgs`、`effective_org`、可切换组织 |
| `resolve` | 把自然语言名称解析成对象 | `--resource` + `--name` 或 `--id` | 规范对象 |
| `resolve-platform` | 解析资产筛选或平台识别里的 `platform` 值 | `--value` | `status`、`resolved`、候选平台列表 |
| `user-assets` | 查用户当前可访问资产 | `--user-id` 或 `--username` | 有效资产列表 |
| `user-nodes` | 查用户当前可访问节点 | `--user-id` 或 `--username` | 有效节点列表 |
| `user-asset-access` | 查用户在某资产下的账号与协议 | 一个用户定位 + 一个资产定位 | `permed_accounts`、`permed_protocols` |
| `asset-permission-explain` | 从资产视角解释命中的授权规则 | `--asset-id` 或 `--asset-name` | `matched_permissions`、`match_source`、`match_evidence` |
| `recent-audit` | 快速看最近审计 | `--audit-type` | 最近事件列表，包含 `data_source` / `filter_strategy` / `asset_evidence` |
| `settings-category` | 按设置分类读取系统配置 | `--category` | 原始设置项与分类摘要 |
| `license-detail` | 查看许可证详情 | 无 | 许可证原始详情 |
| `tickets` | 查看工单列表 | 可选 `--filters` | 工单记录 |
| `command-storages` | 查看命令存储列表 | 可选 `--filters` | 命令存储记录 |
| `replay-storages` | 查看录像存储列表 | 可选 `--filters` | 录像存储记录 |
| `terminals` | 查看终端组件列表 | 可选 `--filters` | 终端组件记录 |
| `reports` | 读取报表与 dashboard | `--report-type` | 报表原始返回与摘要 |
| `account-automations` | 汇总账号备份、改密、风险、检测任务 | 可选 `--filters` | 自动化概览 |
| `endpoint-inventory` | 查看核心端点在当前环境的 inventory / OPTIONS 缓存 | 可选 `--refresh` | 端点清单与方法能力 |
| `endpoint-verify` | 对单个端点做 GET/OPTIONS 验证 | `--path` 或 `filters.path` | `method`、`path`、原始 payload |
| `inspect` | 查询治理、统计、巡检能力单元 | `--capability` | 能力摘要、排行、样本 |
| `capabilities` | 列出所有 `inspect` 能力 | 无 | 能力目录 |

## 高频示例

预检与组织：

```bash
python3 scripts/jumpserver_api/jms_diagnose.py config-status --json
python3 scripts/jumpserver_api/jms_diagnose.py ping
python3 scripts/jumpserver_api/jms_diagnose.py select-org
```

对象解析：

```bash
python3 scripts/jumpserver_api/jms_diagnose.py resolve --resource account --name root
python3 scripts/jumpserver_api/jms_diagnose.py resolve --resource node --name ops-demo-node
python3 scripts/jumpserver_api/jms_diagnose.py resolve-platform --value Unix
```

用户可访问资产与节点：

```bash
python3 scripts/jumpserver_api/jms_diagnose.py user-assets --username openclaw
python3 scripts/jumpserver_api/jms_diagnose.py user-assets --org-name Default --username jingyu.qi
python3 scripts/jumpserver_api/jms_diagnose.py user-assets --user-name openclaw
python3 scripts/jumpserver_api/jms_diagnose.py user-nodes --user-id 4f8b763f-5c21-4b77-903c-37a7838968ae
```

这两个子命令会直接读取 JumpServer effective access 接口：
- `user-assets` 从 `/api/v1/perms/users/{user_id}/assets/` 获取用户当前可访问资产。
- `user-nodes` 从 `/api/v1/perms/users/{user_id}/nodes/` 获取用户当前可访问节点。
- `user-assets` / `user-nodes` / `user-asset-access` 支持额外传 `--org-id` 或 `--org-name`，只在当前命令内临时限定查询组织，不会写回 `.env`。
- `user-assets` 会按服务端返回的分页 `next` 自动继续拉取并去重，最终输出聚合后的 `asset_count` 与完整 `assets` 列表。
- `user-nodes` 输出聚合后的 `node_count` 与完整 `nodes` 列表。
- `data_source` 会保留本次查询使用的 endpoint 与参数，便于对照页面请求排查。
- `effective_org`、`switchable_orgs` 与 `org_context_hint` 会保留本次命令实际使用的组织范围，便于排查“结果查到哪里去了”。
- 当前输出已去掉 `reported_*` 与 `*_record_count` 这类重复字段；若接口没有异常，`warnings` 通常为空数组。

资产级账号与协议：

```bash
python3 scripts/jumpserver_api/jms_diagnose.py user-asset-access --username openclaw --asset-name openclaw资产
python3 scripts/jumpserver_api/jms_diagnose.py user-asset-access --org-name Default --username jingyu.qi --asset-name shengchan
python3 scripts/jumpserver_api/jms_diagnose.py user-asset-access --user-name openclaw --asset-name openclaw资产
python3 scripts/jumpserver_api/jms_diagnose.py user-asset-access --user-id 4f8b763f-5c21-4b77-903c-37a7838968ae --asset-id 84d763b2-08bb-4d39-8fab-993714857642
```

资产视角解释规则命中：

```bash
python3 scripts/jumpserver_api/jms_diagnose.py asset-permission-explain --asset-name 'AI 自动创建测试'
python3 scripts/jumpserver_api/jms_diagnose.py asset-permission-explain --org-name Default --asset-name 'AI 自动创建测试'
```

- `asset-permission-explain` 会按资产 id、标签和节点继承关系解释命中的权限规则。
- 节点继承使用 `full_value` 的前缀关系：授权 `/Default` 会覆盖 `/Default/Linux` 及更深层后代；授权 `/Default/Linux` 只覆盖该分支及其后代。
- `match_source` 固定为 `direct_asset`、`shared_label` 或 `node_ancestor`。

设置、许可证与系统对象：

```bash
python3 scripts/jumpserver_api/jms_diagnose.py settings-category --category security_auth
python3 scripts/jumpserver_api/jms_diagnose.py license-detail
python3 scripts/jumpserver_api/jms_diagnose.py tickets --filters '{"limit":10}'
python3 scripts/jumpserver_api/jms_diagnose.py command-storages
python3 scripts/jumpserver_api/jms_diagnose.py replay-storages
python3 scripts/jumpserver_api/jms_diagnose.py terminals
```

`recent-audit` 补充说明：

- `session` 优先读取 `/api/v1/terminal/sessions/`；只有 terminal 侧没有命中时，才回退到 `/api/v1/audits/user-sessions/`。
- 返回摘要会带 `data_sources` 与 `filter_strategies`，用于判断本次命中了哪个端点、是否走了 fallback。
- 每条 `session` 记录都会带 `asset_evidence`，其中包含 `asset_id`、`candidate_values`、`matched_filter`、`matched_values`，用于证明该记录为什么算作目标资产。
- 若目标资产的会话是历史记录而非最近 7 天，请显式传 `days` 或 `date_from/date_to`，否则可能返回空列表。
- `tickets` 传 `name/title` 时会先尝试服务端过滤；若服务端不稳定，会自动做一次本地 exact-first 兜底，并在 `summary.match_strategy` 里说明。

报表、治理与端点验证：

```bash
python3 scripts/jumpserver_api/jms_diagnose.py reports --report-type account-statistic --days 30
python3 scripts/jumpserver_api/jms_diagnose.py account-automations
python3 scripts/jumpserver_api/jms_diagnose.py inspect --capability system-settings-overview
python3 scripts/jumpserver_api/jms_diagnose.py inspect --capability hot-assets-ranking --filters '{"days":30}'
python3 scripts/jumpserver_api/jms_diagnose.py endpoint-inventory --refresh
python3 scripts/jumpserver_api/jms_diagnose.py endpoint-verify --path /api/v1/settings/setting/ --method GET
python3 scripts/jumpserver_api/jms_diagnose.py capabilities
```
