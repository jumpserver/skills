# 审计与调查

## 快速概览

- 开始前先到 [runtime.md](runtime.md) 判断本次是“首次全量校验”还是“后续轻量校验”。
- 主入口：`python3 scripts/jms_audit.py <subcommand> ...`
- 支持子命令：`list`、`get`。
- 调查分析类请求也统一使用这份文档，不再分开读取额外 playbook。
- 未选组织时，先通过 `python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm` 选择组织；只有 `{0002}` 或 `{0002,0004}` 环境会自动写入 `0002`。
- `list` 默认自动翻页拉全量；只有在 `--filters` 里显式传 `limit` / `offset` 时才按分页结果返回。
- 未传 `date_from/date_to` 时，`list/get` 默认查询最近 7 天。

## `audit-type` 对应场景

| `audit-type` | 适用场景 | 详情查询备注 |
|---|---|---|
| `operate` | 资源变更、权限变更、配置操作 | 一般只需要 `--id` |
| `login` | 登录成功、登录失败、锁定、认证异常 | 一般只需要 `--id` |
| `session` | 会话建立、会话历史、在线连接 | 一般只需要 `--id` |
| `command` | 会话中的命令记录 | `list/get` 都必须提供 `command_storage_id` |

## 关键约束

| 条件 | 规则 |
|---|---|
| `command` 查询 | `list` 和 `get` 都必须提供 `command_storage_id` |
| `list/get` 未传时间范围 | 默认补最近 7 天；查更长范围时显式传 `date_from/date_to` |
| 调查分析 | 先缩小时间范围，再选 `audit-type` |
| 输出结果 | 优先给时间线摘要，不只回显原始事件 |
| 高风险结论 | 标出删除、权限扩大、重复失败、会话中断等异常点 |

## 调查流程图

```text
确定调查对象
  -> 缩小时间范围
  -> 选择 audit-type
  -> list / get
  -> 摘要关键发现
  -> 给出下一步建议
```

## 输出报告格式

| 字段 | 说明 |
|---|---|
| 时间范围 | 查询覆盖的时间窗口 |
| 查询范围 | 用户、资产、权限或节点 |
| `audit-type` | 使用的审计类型 |
| 关键发现 | 时间线、异常点、影响对象 |
| 相关标识符 | 用户名、对象 ID、`command_storage_id` |
| 下一步动作 | 建议继续查什么或确认什么 |

## 高频示例

最近操作日志：

```bash
python3 scripts/jms_audit.py list --audit-type operate --filters '{"limit":5}'
```

最近登录审计：

```bash
python3 scripts/jms_audit.py list --audit-type login --filters '{"limit":5}'
```

命令审计详情：

```bash
python3 scripts/jms_audit.py get --audit-type command --id <command-id> --filters '{"command_storage_id":"<command-storage-id>"}'
```
