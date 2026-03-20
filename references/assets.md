# 资产、用户与账号

## 快速概览

- 开始前先到 [runtime.md](runtime.md) 判断本次是“首次全量校验”还是“后续轻量校验”。
- 主入口：`python3 scripts/jms_assets.py <subcommand> ...`
- 组织对象也走这个入口：`--resource organization`
- 标准用户创建固定采用平衡版流程，不回退到临时 SDK Python 脚本。
- 所有列表型读取入口默认自动翻页拉全量；只有在 filters 里显式传 `limit` / `offset` 时才按分页结果返回。

## 目录

- 子命令与资源
- 关键约束
- 标准流程
- 高频命令

## 子命令与资源

### 子命令表

| 子命令 | 用途 | 风险 |
|---|---|---|
| `list` | 列出对象或按条件筛选 | 低 |
| `get` | 读取单个对象详情 | 低 |
| `preview-create` | 预览通用创建请求 | 低 |
| `create` | 执行通用创建 | 中 |
| `preview-create-user` | 预览专用用户创建请求 | 低 |
| `create-user` | 执行专用用户创建请求 | 中 |
| `preview-update` | 预览变更内容 | 低 |
| `update` | 执行更新 | 高 |
| `preview-unblock` | 预览用户解锁 | 低 |
| `unblock` | 执行用户解锁 | 高 |
| `preview-delete` | 预览删除目标 | 低 |
| `delete` | 执行删除 | 高 |

### 资源表

| 资源 | 说明 | 常见定位字段 |
|---|---|---|
| `asset` | 主机、数据库、设备、云、Web 资产 | `id`、`name` |
| `node` | 资产树节点 | `id`、`value` |
| `platform` | 平台模板 | `id`、`name` |
| `account` | 资产账号 | `id`、`username` |
| `user` | JumpServer 用户 | `id`、`username` |
| `user-group` | 用户组 | `id`、`name` |
| `organization` | JumpServer 组织 | `id`、`name` |

## 关键约束

| 条件 | 规则 |
|---|---|
| `asset` create | 必须带 `--kind` |
| `asset` update | 无法自动识别类型时必须带 `--kind` |
| `user` create | 密码只能通过 `--password` / `--need-update-password` 传入 |
| `user` update | 至少提供 `--payload` 或 `--password` |
| 标准用户创建 | 固定采用平衡版流程，不回退到临时 SDK Python 脚本 |
| 用户角色 | 系统角色、组织角色必须在同一次创建请求里传入 |
| `platform` 字段 | 只接受平台 ID 或唯一精确平台名称；名称未命中时仅按类型列候选，不自动解析 |
| 平台 ID | 不要硬编码 `Linux -> 1`、`MySQL -> 17` 这类映射 |
| `account --name` | 实际映射到 `username` |
| `node --name` | 实际映射到 `value` |
| `preview-unblock` / `unblock` | 只适用于 `user` |
| 高风险写操作 | 先 `preview-*`，再补 `--confirm` |

## 标准流程

### 标准用户创建

```text
list --filters '{"username":"..."}'
  -> preview-create-user
  -> create-user
  -> get --resource user --id <new-id>
```

补充规则：

| 条件 | 规则 |
|---|---|
| 默认查重 | 只按 `username` 做一次精确查重 |
| 邮箱/名称冲突 | 在创建失败后再升级到更严格流程 |
| 需要角色 | 直接在 `create-user` 同次请求中传 `--system-role-id` / `--org-role-id` |
| Windows 输出 | 使用 `python` 或 `py -3`，不要生成临时 Python 文件 |

## 高频命令

精确查询用户：

```bash
python3 scripts/jms_assets.py list --resource user --filters '{"username":"openclaw"}'
```

标准用户创建：

```bash
python3 scripts/jms_assets.py list --resource user --filters '{"username":"openclaw1"}'
python3 scripts/jms_assets.py preview-create-user --name 'openclaw机器人1' --username 'openclaw1' --email 'openclaw1@qq.com' --password 'openclaw@2026'
python3 scripts/jms_assets.py create-user --name 'openclaw机器人1' --username 'openclaw1' --email 'openclaw1@qq.com' --password 'openclaw@2026'
python3 scripts/jms_assets.py get --resource user --id <new-user-id>
```

用户改密：

```bash
python3 scripts/jms_assets.py preview-update --resource user --id <user-id> --password '<new-password>' --need-update-password
python3 scripts/jms_assets.py update --resource user --id <user-id> --password '<new-password>' --need-update-password --confirm
```

资产或平台更新：

```bash
python3 scripts/jms_diagnose.py resolve-platform --value Linux
python3 scripts/jms_assets.py preview-update --resource asset --kind host --id <asset-id> --payload '{"comment":"updated by ops","platform":"Linux"}'
python3 scripts/jms_assets.py update --resource asset --kind host --id <asset-id> --payload '{"comment":"updated by ops","platform":"Linux"}' --confirm
python3 scripts/jms_assets.py preview-update --resource platform --id <platform-id> --payload '{"comment":"updated by ops"}'
python3 scripts/jms_assets.py update --resource platform --id <platform-id> --payload '{"comment":"updated by ops"}' --confirm
```

节点生命周期：

```bash
python3 scripts/jms_assets.py preview-create --resource node --payload '{"full_value":"/ops-demo-node"}'
python3 scripts/jms_assets.py create --resource node --payload '{"full_value":"/ops-demo-node"}'
python3 scripts/jms_assets.py preview-update --resource node --id <node-id> --payload '{"value":"ops-demo-node-renamed"}'
python3 scripts/jms_assets.py update --resource node --id <node-id> --payload '{"value":"ops-demo-node-renamed"}' --confirm
python3 scripts/jms_assets.py preview-delete --resource node --id <node-id>
python3 scripts/jms_assets.py delete --resource node --id <node-id> --confirm
```
