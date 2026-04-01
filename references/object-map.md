# 对象映射与歧义处理

## 快速概览

- 这份文档只负责“自然语言 -> 资源名 / 对象类型 / 定位字段”的跨域映射。
- 资产、用户、节点、平台的具体命令以 [assets.md](assets.md) 为准。
- 权限详情与访问关系回看以 [permissions.md](permissions.md) 为准。

## 核心对象映射

| 用户表达 | 归一化对象 |
|---|---|
| asset、server、host、target asset | `asset` |
| folder、asset tree node、grouping node | `node` |
| protocol template、OS type、connection platform | `platform` |
| account、credential binding、login identity | `account` |
| JumpServer user、login user、blocked user | `user` |
| group、team、user set | `user-group` |
| organization、org、组织、租户 | `organization` |
| authorization、grant、access rule | `permission` |
| audit log、operation log、session history | `audit` |

## CLI 资源映射

| 域 | 资源 / 类型 |
|---|---|
| `jms_query.py` | `asset`、`node`、`platform`、`account`、`user`、`user-group`、`organization` |
| `jms_diagnose.py` | `account`、`node`、用户有效范围相关子命令 |
| `jms_query.py` | `permission` |
| `jms_query.py` | `operate`、`login`、`session`、`command` |

## 高频意图路由

| 用户问题 | 首选入口 | 继续阅读 |
|---|---|---|
| 某某用户有哪些资产 | `diagnose user-assets` | [diagnose.md](diagnose.md) |
| 某某用户在某组织下有哪些资产 | `diagnose user-assets` | [diagnose.md](diagnose.md) |
| 某某用户有哪些节点 | `diagnose user-nodes` | [diagnose.md](diagnose.md) |
| 某某用户在某资产下有哪些账号 / 协议 | `diagnose user-asset-access` | [diagnose.md](diagnose.md) |
| 某某用户为什么能访问某资产 | `diagnose user-asset-access` + `permissions list/get` | [permissions.md](permissions.md) |
| 某资产授权给了谁 | `query asset-perm-users` | [permissions.md](permissions.md) |
| 某资产为什么会被授权 / 节点授权是否覆盖某资产 | `diagnose asset-permission-explain` | [diagnose.md](diagnose.md) |
| 某对象怎么精确解析 | `list/get/resolve/resolve-platform` | [assets.md](assets.md) / [diagnose.md](diagnose.md) |

## 名称字段映射

| 场景 | 用户输入 | 实际查询字段 |
|---|---|---|
| `assets list --resource account --name ...` | 账号名 | `username` |
| `assets list --resource node --name ...` | 节点名 | `value` |
| `assets list --resource user --name ...` | 用户显示名 | `name` |
| `assets list --resource organization --name ...` | 组织名 | `name` |
| `diagnose resolve --resource account --name ...` | 账号名 | `username` |
| `diagnose resolve --resource node --name ...` | 节点名 | `value` |
| `diagnose resolve --resource organization --name ...` | 组织名 | `name` |

补充说明：

- `user-assets` / `user-nodes` / `user-asset-access` 的用户定位同时尝试 `username` 与显示名 `name`；中文姓名可以直接作为自然语言输入。
- “在 Default 组织下”这类表达优先解析成 `--org-id` / `--org-name` 的命令级组织覆盖，再执行用户有效访问范围查询，不要求先写回 `.env`。

## 歧义处理

| 条件 | 动作 |
|---|---|
| 已知 ID | 优先用 ID，不按名称解析 |
| 名称唯一 | 先解析为 ID，再执行查询 |
| 名称匹配多个对象 | 停止并要求用户选择 |
| `platform` 输入为名称 | 先按平台 `name` 精确匹配；未唯一命中时列出类型候选并停止 |
| 用户要求对象变更 | 不在这里继续路由，直接说明本仓库不提供对象写操作 |
