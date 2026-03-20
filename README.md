# jumpserver-skills

`jumpserver-skills` 是一个面向 JumpServer V4 的查询型 skill 仓库。它支持环境初始化写入，包括根据用户回复生成 `.env.local`、持久化 `JMS_ORG_ID`，但资产、权限、审计相关业务动作仍然只保留查询。

[English](./README.en.md)

## 项目概览

| 入口 | 作用 | 当前范围 |
|---|---|---|
| `scripts/jms_assets.py` | 资产、账号、用户、用户组、平台、节点、组织查询 | `list`、`get` |
| `scripts/jms_permissions.py` | 授权规则查询 | `list`、`get` |
| `scripts/jms_audit.py` | 登录、操作、会话、命令审计 | `list`、`get` |
| `scripts/jms_diagnose.py` | 配置检查、配置写入、连通性、组织选择、对象解析、访问分析 | 环境初始化 + 只读诊断 |

## 核心规则

- 先执行 `python3 scripts/jms_diagnose.py config-status --json`
- 配置不完整时，按用户提供的信息执行 `python3 scripts/jms_diagnose.py config-write --payload '<json>' --confirm`
- 再执行 `python3 scripts/jms_diagnose.py ping`
- 缺少组织上下文时，执行 `python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm`
- 只有 `{0002}` 或 `{0002,0004}` 两种保留组织集合才会自动写入 `0002`
- 不支持业务对象和权限的 `create/update/delete/append/remove/unblock`

## 仓库结构

```text
.
├── SKILL.md
├── README.md
├── README.en.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── assets.md
│   ├── audit.md
│   ├── diagnose.md
│   ├── object-map.md
│   ├── permissions.md
│   ├── runtime.md
│   ├── safety-rules.md
│   └── troubleshooting.md
├── scripts/
│   ├── jms_assets.py
│   ├── jms_audit.py
│   ├── jms_bootstrap.py
│   ├── jms_diagnose.py
│   ├── jms_permissions.py
│   └── jms_runtime.py
├── env.sh
└── requirements.txt
```

## 组件职责

| 组件 | 职责 |
|---|---|
| `SKILL.md` | 定义 skill 的触发条件、预检顺序、边界与推荐命令 |
| `agents/openai.yaml` | 定义代理界面的展示名、简介和默认提示词 |
| `references/*.md` | 按领域拆分的详细规则、运行时说明、故障排查与边界约束 |
| `scripts/jms_assets.py` | 只读资产、账号、用户、用户组、平台、节点、组织查询入口 |
| `scripts/jms_permissions.py` | 只读权限查询入口 |
| `scripts/jms_audit.py` | 只读审计查询入口 |
| `scripts/jms_diagnose.py` | 配置检查、`.env.local` 写入、连通性检查、组织选择、对象解析和访问分析入口 |
| `scripts/jms_runtime.py` | 共享运行时：加载 `.env.local`、构造 SDK client、校验环境、处理组织上下文与自动写入逻辑 |

## 技术栈与依赖

| 项目 | 当前实现 |
|---|---|
| 语言 | Python 3 |
| 核心依赖 | `jumpserver-sdk-python>=0.9.1` |
| 运行方式 | 本地 CLI 脚本，通过 `python3 scripts/jms_*.py ...` 调用 |
| 目标系统 | JumpServer V4 |
| 配置来源 | `.env.local` + 进程环境变量 |
| 配置写入 | `jms_diagnose.py config-write --confirm` |
| 组织持久化 | `jms_diagnose.py select-org --confirm` |

安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

## 快速开始

检查与初始化环境：

```bash
python3 scripts/jms_diagnose.py config-status --json
python3 scripts/jms_diagnose.py config-write --payload '{"JMS_API_URL":"https://jump.example.com","JMS_ACCESS_KEY_ID":"<ak>","JMS_ACCESS_KEY_SECRET":"<sk>","JMS_VERSION":"4"}' --confirm
python3 scripts/jms_diagnose.py ping
```

查看和写入组织：

```bash
python3 scripts/jms_diagnose.py select-org
python3 scripts/jms_diagnose.py select-org --org-id <org-id>
python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm
```

之后再执行查询，例如：

```bash
python3 scripts/jms_assets.py list --resource user --filters '{"username":"demo-user"}'
python3 scripts/jms_permissions.py list --filters '{"limit":20}'
python3 scripts/jms_audit.py list --audit-type operate --filters '{"limit":30}'
```

## 环境变量

下表以当前实现为准，来源于 `references/runtime.md` 和 `scripts/jms_runtime.py`。首次调用时，skill 会按这些字段要求通过对话收集配置，并把结果写入本地 `.env.local`。

| 变量 | 是否必需 | 说明 | 示例 |
|---|---|---|---|
| `JMS_API_URL` | 与 `JMS_WEB_URL` 二选一 | JumpServer API/访问地址 | `https://jump.example.com` |
| `JMS_WEB_URL` | 与 `JMS_API_URL` 二选一 | 运行时接受的地址回退变量 | `https://jump.example.com` |
| `JMS_VERSION` | 建议配置 | JumpServer 版本，当前默认按 `4` 处理 | `4` |
| `JMS_ACCESS_KEY_ID` | 与 `JMS_ACCESS_KEY_SECRET` 成组，或改用用户名密码 | AK/SK 鉴权 ID | `your-access-key-id` |
| `JMS_ACCESS_KEY_SECRET` | 与 `JMS_ACCESS_KEY_ID` 成组，或改用用户名密码 | AK/SK 鉴权密钥 | `your-access-key-secret` |
| `JMS_USERNAME` | 与 `JMS_PASSWORD` 成组，或改用 AK/SK | 用户名密码鉴权用户名 | `ops-user` |
| `JMS_PASSWORD` | 与 `JMS_USERNAME` 成组，或改用 AK/SK | 用户名密码鉴权密码 | `your-password` |
| `JMS_ORG_ID` | 初始化时可选 | 业务执行前通过 `select-org` 或保留组织特判写入 | `00000000-0000-0000-0000-000000000000` |
| `JMS_TIMEOUT` | 可选 | SDK 请求超时秒数 | `30` |
| `JMS_SDK_MODULE` | 可选 | 自定义 SDK 模块路径，默认 `jms_client.client` | `jms_client.client` |
| `JMS_SDK_GET_CLIENT` | 可选 | 自定义 client 工厂函数名，默认 `get_client` | `get_client` |

生成后的 `.env.local` 示例：

```dotenv
JMS_API_URL="https://jump.example.com"
JMS_VERSION="4"
JMS_ORG_ID=""

JMS_ACCESS_KEY_ID="your-access-key-id"
JMS_ACCESS_KEY_SECRET="your-access-key-secret"

# JMS_USERNAME="ops-user"
# JMS_PASSWORD="your-password"

# JMS_TIMEOUT="30"
# JMS_SDK_MODULE="jms_client.client"
# JMS_SDK_GET_CLIENT="get_client"
```

环境变量规则：

- 地址至少提供 `JMS_API_URL` 或 `JMS_WEB_URL` 之一
- 认证方式必须二选一：`AK/SK` 或 `用户名/密码`
- `.env.local` 会被脚本自动加载
- 首次配置缺失时，推荐先执行 `python3 scripts/jms_diagnose.py config-status --json`
- 如果你切换了 JumpServer、账号、组织或 `.env.local` 内容，应该按首次运行重新做全量校验

实现备注：

- 当前 `scripts/jms_runtime.py` 在构造 client 时固定使用 `verify=False`
- HTTPS 证书告警会被抑制
- 这两个行为目前不是通过环境变量控制的

## 常用命令

对象查询：

```bash
python3 scripts/jms_assets.py list --resource asset --filters '{"name":"demo-asset"}'
python3 scripts/jms_assets.py get --resource user --id <user-id>
python3 scripts/jms_diagnose.py resolve --resource node --name demo-node
python3 scripts/jms_diagnose.py resolve-platform --value Linux
```

访问分析：

```bash
python3 scripts/jms_diagnose.py user-assets --username demo-user
python3 scripts/jms_diagnose.py user-nodes --username demo-user
python3 scripts/jms_diagnose.py user-asset-access --username demo-user --asset-name demo-asset
```

审计查询：

```bash
python3 scripts/jms_audit.py list --audit-type login --filters '{"limit":10}'
python3 scripts/jms_audit.py get --audit-type command --id <command-id> --filters '{"command_storage_id":"<command-storage-id>"}'
```

## 文档地图

| 文件 | 用途 |
|---|---|
| `SKILL.md` | 路由规则、环境初始化边界、查询边界 |
| `references/runtime.md` | 环境变量模型、`.env.local` 写入、组织持久化 |
| `references/assets.md` | 资产类查询 |
| `references/permissions.md` | 权限查询 |
| `references/audit.md` | 审计查询 |
| `references/diagnose.md` | 配置/组织/解析/访问分析 |
| `references/safety-rules.md` | 允许的环境写入与禁止的业务写入 |
| `references/troubleshooting.md` | 常见错误排查 |

## 不支持范围

- 资产、平台、节点、账号、用户、用户组、组织的创建/更新/删除/解锁
- 权限创建、更新、追加关系、移除关系、删除
- 临时 SDK/HTTP 脚本绕过正式流程
