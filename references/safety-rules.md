# 安全规则

## 快速概览

- 所有 JumpServer 写操作都按风险等级处理。
- 高风险操作先预览、再确认、最后回读验证。
- 歧义未消除、影响范围无法总结、对象无法精确定位时，拒绝执行。

## 风险等级

| 风险等级 | 场景 |
|---|---|
| 低 | 只读查询、审计查询、故障排查查询 |
| 中 | 完成重复检查后的定向创建、范围明确的定向追加授权 |
| 高 | 更新、解锁、删除、关系移除、大范围授权、任何批量变更 |

## 命令级确认矩阵

| 动作 | 是否需要 `--confirm` | 先做什么 |
|---|---|---|
| `jms_assets.py update` | 是 | `preview-update` |
| `jms_assets.py unblock` | 是 | `preview-unblock` 或先查当前状态 |
| `jms_assets.py delete` | 是 | `preview-delete` |
| `jms_permissions.py update` | 是 | `preview-update` |
| `jms_permissions.py remove` | 是 | `preview-remove` |
| `jms_permissions.py delete` | 是 | 先查权限详情和影响范围 |
| `jms_permissions.py append` | 否 | 仅限单主体、单关系、范围明确的定向追加 |
| `create` 类命令 | 否 | 仍需先完成重复检查和输入校验 |

## 变更防护规则

| 条件 | 要求 |
|---|---|
| 任何更新 | 先查询当前状态 |
| 解锁用户 | 执行前验证 `login_blocked`，执行后验证其为 `false` |
| 用户改密 | 执行前确认目标用户 ID，执行后回读关键状态 |
| 多个候选对象 | 拒绝执行 |
| 名称存在歧义 | 拒绝执行 |
| 无法总结删除影响 | 拒绝执行删除 |
| 变更完成 | 必须验证最终状态并报告结果 |

## `append` 的特殊说明

| 条件 | 处理方式 |
|---|---|
| 单主体、单关系、范围明确 | 可以直接 `append` |
| “全部”“所有”“整个节点下”“整个用户组” | 先查询范围，再请求确认 |
| 追加前要解析多个对象 | 先分别解析主体、权限对象、资源对象到 ID |

## 推荐确认模板

```text
目标：用户 "openclaw" (id=cc71c004-...)
动作：unblock
变更：
- login_blocked: true -> false

请用明确的确认语句回复，以执行这次变更。
```
