# 诊断与访问分析

## 快速概览

- 开始前先到 [runtime.md](runtime.md) 判断本次是“首次全量校验”还是“后续轻量校验”。
- 主入口：`python3 scripts/jms_diagnose.py <subcommand> ...`
- 适合连通性检查、对象解析、服务端有效访问范围分析、最近审计预检。
- `select-org` 是显式组织选择入口；未选组织时，除 `config-status`、`config-write`、`ping`、`select-org` 外，其余子命令都会先阻塞。
- 服务端已有有效权限视图时，不要再本地展开 `permissions list/get`。

## 子命令与适用场景

| 子命令 | 何时用 | 必需定位参数 | 关键输出 |
|---|---|---|---|
| `ping` | 验证环境与 SDK client 连通性 | 无 | 是否可连接 |
| `select-org` | 查看当前环境组织或显式写入 `JMS_ORG_ID` | 可选 `--org-id` | `candidate_orgs`、`effective_org` |
| `resolve` | 把自然语言名称解析成对象 | `--resource` + `--name` | 规范对象 |
| `resolve-platform` | 解析资产写路径里的 `platform` 值 | `--value` | `status`、`resolved`、候选平台列表 |
| `user-assets` | 查用户当前可访问资产 | `--user-id` 或 `--username` | 有效资产列表 |
| `user-nodes` | 查用户当前可访问节点 | `--user-id` 或 `--username` | 有效节点列表 |
| `user-asset-access` | 查用户在某资产下的账号与协议 | 一个用户定位 + 一个资产定位 | `permed_accounts`、`permed_protocols` |
| `recent-audit` | 快速看最近审计 | `--audit-type` | 最近事件列表 |

## 名称与参数映射

| 场景 | `--name` 实际映射字段 | 备注 |
|---|---|---|
| `resolve --resource account` | `username` | 不查 `name` |
| `resolve --resource node` | `value` | 返回节点对象列表 |
| `resolve --resource organization` | `name` | 返回组织对象列表 |
| `resolve --resource node` 输出 | `id`、`value`、`name`、`full_value`、`key`、`org_id`、`org_name` | 作为后续引用基准 |

## 关键约束

| 条件 | 规则 |
|---|---|
| `user-assets` / `user-nodes` | 必须且只能提供一个用户定位参数 |
| `user-assets` / `user-nodes` | `--username` 会先做 `assets list --resource user --filters '{"username":"..."}'` 精确解析 |
| `user-assets` / `user-nodes` | 支持 `--limit` / `--offset`；省略 `--limit` 时自动翻页拉全量，显式指定时按上限返回 |
| `user-asset-access` | 必须且只能提供一个用户定位参数 |
| `user-asset-access` | 必须且只能提供一个资产定位参数 |
| `resolve-platform` | 先按平台名称精确匹配；若只命中类型则返回候选并停止 |
| 全局可用账号 | 当前没有正式快路径；不要本地遍历所有资产做聚合 |
| `recent-audit` 未传时间范围 | 默认补最近 7 天；查更长范围时显式传 `date_from/date_to` |
| `recent-audit --audit-type command` | 需要 `command_storage_id` |
| 除 `config-status` / `config-write` / `ping` / `select-org` 外的其他子命令 | 未选组织时先 `select-org`；只有 `{0002}` 或 `{0002,0004}` 环境会自动写入 `0002` |

## 高频示例

连通性检查：

```bash
python3 scripts/jms_diagnose.py ping
python3 scripts/jms_diagnose.py select-org
```

对象解析：

```bash
python3 scripts/jms_diagnose.py resolve --resource account --name root
python3 scripts/jms_diagnose.py resolve --resource node --name ops-demo-node
python3 scripts/jms_diagnose.py resolve-platform --value Unix
```

用户可访问资产与节点：

```bash
python3 scripts/jms_diagnose.py user-assets --username openclaw
python3 scripts/jms_diagnose.py user-nodes --user-id 4f8b763f-5c21-4b77-903c-37a7838968ae --offset 100
```

资产级账号与协议：

```bash
python3 scripts/jms_diagnose.py user-asset-access --username openclaw --asset-name openclaw资产
python3 scripts/jms_diagnose.py user-asset-access --user-id 4f8b763f-5c21-4b77-903c-37a7838968ae --asset-id 84d763b2-08bb-4d39-8fab-993714857642
```
