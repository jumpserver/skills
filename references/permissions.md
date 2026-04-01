# 权限与授权

## 快速概览

- 开始前先到 [runtime.md](runtime.md) 判断本次是“首次全量校验”还是“后续轻量校验”。
- 主入口：`python3 scripts/jumpserver_api/jms_query.py <subcommand> ...`
- 资产视角的规则命中解释入口：`python3 scripts/jumpserver_api/jms_diagnose.py asset-permission-explain ...`
- 这个入口只提供查询：`permission-list`、`permission-get` 与 `asset-perm-users`
- 权限命令要求先有已选组织；未选组织时先 `select-org`，跨组织授权完全禁止，不自动切组织。
- `permission-list` 默认自动翻页拉全量；只有在 `--filters` 里显式传 `limit` / `offset` 时才按分页结果返回。
- `asset-permission` 传 `name` 时，若服务端名称过滤不稳定，CLI 会自动做一次本地 exact-first 兜底，并在结果顶层返回 `match_strategy`。
- `asset-permission` 传 `user` / `users` 时，若服务端主体过滤不稳定，CLI 会自动拉取当前组织可见规则并做一次本地 detail 级用户/用户组兜底过滤。
- `asset-permission` 传 `is_expired` 时，若结果为空，顶层 `summary` 会补充当前组织下实时可见规则数量、过期/未过期计数、候选摘要与 `empty_reason_hint`，用于区分“当前确实没有”与“历史工件里曾出现过”。
- `permission-list` / `permission-get` 只用于权限关系解释，不用于判定“某用户当前有哪些资产”；资产/节点清单应回到 `jms_diagnose.py user-assets` / `user-nodes`。
- `asset-perm-users` 用于回答“这台资产授权给了谁”；若返回空列表但同组织下 `asset-permission-explain` 命中规则，应把它视为服务端授权用户视图与规则解释视图不一致，而不是直接翻译成“只有超级管理员可访问”。

## 子命令

| 子命令 | 用途 | 风险 |
|---|---|---|
| `permission-list` | 列出权限规则、ACL、RBAC 资源或按条件筛选 | 低 |
| `permission-get` | 查看权限、ACL、RBAC 详情与主体/资源关联 | 低 |
| `asset-perm-users` | 查看某资产当前有哪些授权用户 | 低 |

## 关键约束

| 条件 | 规则 |
|---|---|
| 未选组织 | `permission-list/permission-get` 直接阻塞，先 `select-org` |
| 当前组织是 A，目标对象在 B | 直接阻塞；跨组织授权禁止 |
| 结果过多 | 先加 `name`、`limit`、对象 ID 或时间条件缩小范围；若 `name` 直查为空，再结合 `match_strategy` 判断是否需要扩大时间窗或确认对象已不存在 |
| 需要解释“为什么能访问” | 先查 `jms_diagnose.py user-asset-access`，再回到 `permission-get` 看命中的权限详情 |
| 需要解释“这台资产为什么被授权 / 节点授权是否覆盖它” | 优先 `jms_diagnose.py asset-permission-explain` |
| 业务写请求 | 本入口不提供创建、更新、追加关系、移除关系、删除等动作 |

## 高频示例

查询权限列表：

```bash
python3 scripts/jumpserver_api/jms_query.py permission-list --resource asset-permission --filters '{"name":"生产环境授权"}'
python3 scripts/jumpserver_api/jms_query.py permission-list --resource login-acl --filters '{"users":"<user-id>"}'
python3 scripts/jumpserver_api/jms_query.py permission-list --resource system-role --filters '{"limit":20}'
python3 scripts/jumpserver_api/jms_query.py asset-perm-users --asset-id <asset-id>
```

读取权限详情：

```bash
python3 scripts/jumpserver_api/jms_query.py permission-get --resource asset-permission --permission-id <permission-id>
python3 scripts/jumpserver_api/jms_query.py permission-get --resource login-acl --id <acl-id>
```

结合访问分析解释权限：

```bash
python3 scripts/jumpserver_api/jms_diagnose.py user-asset-access --username openclaw --asset-name prod-host-01
python3 scripts/jumpserver_api/jms_diagnose.py asset-permission-explain --asset-name prod-host-01
python3 scripts/jumpserver_api/jms_query.py asset-perm-users --asset-id <asset-id>
python3 scripts/jumpserver_api/jms_query.py permission-get --resource asset-permission --permission-id <permission-id>
```

## 建议输出关注点

| 场景 | 建议先看什么 |
|---|---|
| 某用户为什么能访问某资产 | `users`、`user_groups`、`assets`、`nodes` |
| 某权限覆盖了哪些对象 | `assets`、`nodes`、`protocols`、`actions` |
| 某权限影响面有多大 | 主体数量、资产数量、节点数量、账号范围 |
| 排查权限接口异常 | 先确认组织、当前账号权限、接口可用性 |
