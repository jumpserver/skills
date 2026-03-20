# JumpServer Skills

`jumpserver-skills` 是一个面向 JumpServer V4 的执行型 skill 仓库。它通过内置的 `jms_*.py` 直连脚本，处理资产、账号、用户、用户组、平台、节点、权限、审计与访问分析任务，适合本地操作和代理接入场景。

`jumpserver-skills` is an execution-oriented skill repository for JumpServer V4. It uses bundled `jms_*.py` direct-entry scripts to handle asset, account, user, group, platform, node, permission, audit, and access-analysis workflows for local operators and agent runtimes.

[中文](#中文版) | [English](#english-version)

## Table of Contents

- [中文版](#中文版)
- [English Version](#english-version)

## 中文版

快速导航: [项目概览](#zh-overview) | [Quick Reference / 快速路由](#zh-quick-reference) | [模型触发与执行规则](#zh-model-routing) | [Canonical Commands / 常用命令](#zh-canonical-commands) | [快速开始](#zh-getting-started) | [环境变量](#zh-environment-variables) | [核心脚本入口](#zh-core-cli-entry-points) | [故障排查](#zh-troubleshooting)

<a id="zh-overview"></a>
### 项目概览

`jumpserver-skills` 是一个中文优先的 JumpServer V4 execution skill。它的核心价值不是“解释 JumpServer”，而是把用户请求稳定路由到 4 个正式 `jms_*.py` 入口，并把高风险操作强制收口到 `预检 -> 预览 -> 确认 -> 回读确认`。

这个仓库不是 JumpServer 服务端项目，也不是一个独立部署的 Web 应用。它适合作为本地技能仓库、代理执行资源或运维自动化入口，重点覆盖资产、用户、平台、权限、审计、访问分析和环境配置。

<a id="zh-quick-reference"></a>
### Quick Reference / 快速路由

| 正式入口 | Use when | 输出重点 | Stop when |
|---|---|---|---|
| `jms_assets.py` | 资产、账号、用户、用户组、组织、平台、节点的查询与变更 | 对象详情、预览变更、回读确认 | 名称不唯一、平台未解析、目标对象不清楚 |
| `jms_permissions.py` | 授权创建、更新、追加关系、移除关系、删除权限 | `effective_org`、`candidate_orgs`、`org_guard_status` | 未选组织、同名对象跨组织、多组织或跨组织授权 |
| `jms_audit.py` | 登录、操作、会话、命令审计 | 时间线摘要、异常点、相关标识符 | 未传 `date_from/date_to` 时默认最近 7 天；`command` 缺 `command_storage_id` 时停止 |
| `jms_diagnose.py` | 配置、预检、连通性、组织选择、对象解析、平台解析、访问分析 | 配置状态、组织候选、解析结果、有效访问视图 | 配置不完整、对象候选过多、需要先明确组织 |

<a id="zh-model-routing"></a>
### 模型触发与执行规则

这一节只同步 `SKILL.md` 首屏规则，目标是让低能力模型和发布平台都能快速理解：什么时候命中、先做什么、什么时候必须停下。

| 问题 | 固定规则 |
|---|---|
| Use when | 用户提到资产、账号、用户、用户组、组织、平台、节点、权限、审计、访问分析、配置 JumpServer、切换环境、依赖检查、连通性检查时必须命中 |
| 第一步做什么 | 先做 `预检`：依赖检查 -> `config-status --json` -> 必要时 `config-write --confirm` -> `ping` |
| 高风险写操作怎么走 | 固定 `预检 -> 预览 -> 确认 -> 回读确认` |
| 未指定组织怎么办 | 先读取当前环境组织并 `select-org`；只有 `{0002}` 或 `{0002,0004}` 环境会自动写入 `0002` |
| 什么时候必须停下 | 未选组织、名称不唯一、对象跨组织、平台未解析、配置不完整、动作超出 wrapper 覆盖范围 |
| Not for | 临时 SDK/HTTP 脚本、猜平台 ID/对象 ID/组织、绕过正式入口直接拼 API、跨组织授权 |

禁止行为固定如下：

- 不允许跳过预检。
- 不允许生成临时 SDK 脚本、一次性 HTTP 脚本或 HTTP fallback。
- 不允许猜平台 ID、对象 ID、组织、鉴权方式或凭据内容。
- 不允许把 `0002` 当作所有环境的通用默认组织。
- 不允许在未选组织时继续执行业务命令。
- 不允许自动切换到其他组织继续做授权。
- 不允许在名称不唯一时继续执行。

<a id="zh-canonical-commands"></a>
### Canonical Commands / 常用命令

预检：

```bash
python3 scripts/jms_diagnose.py config-status --json
python3 scripts/jms_diagnose.py ping
python3 scripts/jms_diagnose.py select-org
```

平台解析：

```bash
python3 scripts/jms_diagnose.py resolve-platform --value Linux
```

精确查询用户或资产：

```bash
python3 scripts/jms_assets.py list --resource user --filters '{"username":"openclaw"}'
python3 scripts/jms_assets.py list --resource asset --filters '{"name":"openclaw资产"}'
```

预览权限创建：

```bash
python3 scripts/jms_permissions.py preview-create --payload '{"name":"openclaw授权规则","users":["<user-id>"],"assets":["<asset-id>"],"accounts":["@SPEC","root"],"actions":["connect"],"protocols":["all"],"is_active":true}'
```

审计查询：

```bash
python3 scripts/jms_audit.py list --audit-type login --filters '{"limit":5}'
```

<a id="zh-repository-structure"></a>
### 仓库结构

```text
.
├── SKILL.md                    # 入口路由、执行策略、边界说明
├── .gitignore                  # 忽略本地 .env.local 与 .DS_Store
├── README.md                   # 本文档
├── agents/
│   └── openai.yaml             # 代理界面显示名与默认提示词
├── references/
│   ├── runtime.md              # 预检与环境模型
│   ├── assets.md               # 资产、用户、账号、节点、平台流程
│   ├── permissions.md          # 权限与授权规则
│   ├── audit.md                # 审计与调查流程
│   ├── diagnose.md             # 连通性、对象解析、访问分析
│   ├── object-map.md           # 自然语言到对象类型的映射
│   ├── safety-rules.md         # 高风险变更规则
│   └── troubleshooting.md      # 常见错误与排查路径
├── scripts/
│   ├── jms_assets.py           # 资产、用户、账号等对象的 CRUD 入口
│   ├── jms_permissions.py      # 权限与授权入口
│   ├── jms_audit.py            # 审计查询入口
│   ├── jms_diagnose.py         # 诊断与访问分析入口
│   └── jms_runtime.py          # 共享运行时、环境加载、SDK client 构造
├── env.sh                      # Bash 环境加载辅助脚本
├── requirements.txt            # Python 依赖
```

组件职责固定如下：

- `SKILL.md` 负责决定“什么时候用哪个入口、什么时候必须预览或确认”
- `references/*.md` 负责分域规则、约束和示例命令
- `scripts/*.py` 负责真正调用 JumpServer SDK
- `scripts/jms_runtime.py` 负责环境变量加载、认证模式处理和 client 复用
- `agents/openai.yaml` 负责代理展示与默认接入提示

<a id="zh-tech-stack"></a>
### 技术栈与依赖

- **语言**: Python 3
- **核心依赖**: `jumpserver-sdk-python==0.9.1`
- **目标系统**: JumpServer V4
- **调用方式**: 本地 CLI 脚本 + SDK client
- **环境管理**: `.env.local` 或 shell 环境变量
- **可选辅助**: `env.sh` 用于 Bash/macOS/Linux 下快速加载环境
- **代理接入**: `agents/openai.yaml` 提供代理显示元信息与默认提示词

依赖声明很轻量：

```bash
python3 -m pip install -r requirements.txt
```

所有正式 `jms_*.py` 入口都会在启动时检查 `requirements.txt`。如果发现缺依赖，使用同一条命令补上 `--confirm-install` 即可按当前解释器自动安装：

```bash
python3 scripts/jms_diagnose.py --confirm-install config-status --json
```

离线环境仍需手动准备本地 wheel 或内部源后再安装；当前仓库不内置 wheel 文件。

<a id="zh-getting-started"></a>
### 快速开始

下面的步骤按“第一次在新机器上使用这个仓库”来写。

#### 1. 获取代码并进入目录

```bash
git clone <your-repo-url>
cd jumpserver-skills
```

如果仓库已经在本地，直接进入目录即可。

#### 2. 准备 Python 3 环境

检查本机是否有可用的 Python 3：

```bash
python3 --version
```

可选但推荐使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows 可以使用：

```powershell
python -m venv .venv
.venv\Scripts\activate
```

#### 3. 依赖预检与安装

首次运行任意正式入口时，会先检查 `requirements.txt` 里的依赖。推荐直接从一个只读命令开始：

```bash
python3 scripts/jms_diagnose.py config-status --json
```

如果返回 `ok=false` 且提示缺少 requirements 依赖，就用同一条命令补上 `--confirm-install` 重试：

```bash
python3 scripts/jms_diagnose.py --confirm-install config-status --json
```

也可以手动安装：

```bash
python3 -m pip install -r requirements.txt
```

离线环境需要自行准备本地 wheel 或内部镜像源，仓库当前不附带离线 wheel。

#### 4. 配置环境变量

先检查当前本地配置状态：

```bash
python3 scripts/jms_diagnose.py config-status --json
```

如果返回 `complete=false`，按 skill 的对话式提示依次提供：

- `JMS_API_URL`
- 鉴权模式：`AK/SK` 或 `用户名/密码`
- 对应凭据
- `JMS_ORG_ID`，初始化时可留空
- `JMS_VERSION`，默认 `4`
- `JMS_TIMEOUT`，可留空

skill 会先回显脱敏摘要，再调用 `config-write --confirm` 在本地生成 `.env.local`。

注意：

- 对话中输入的 AK/SK 或密码会进入会话记录
- 如果你不想把敏感值发到对话里，可以手动创建本地 `.env.local`

#### 5. 按需加载环境

在 macOS/Linux/Bash 下，你可以显式加载环境：

```bash
source ./env.sh
```

这一步是可选的。所有正式 `jms_*.py` 脚本都会自动读取 `.env.local`，所以即使不执行 `env.sh`，脚本也能工作。Windows 下通常直接依赖 `.env.local` 或当前 shell 环境变量即可。

#### 6. 做首次连通性检查

```bash
python3 scripts/jms_diagnose.py ping
```

这是最推荐的第一条命令。它可以帮助你确认：

- Python 解释器可用
- `jumpserver-sdk-python` 已安装
- 环境变量足够构造 client
- 当前 JumpServer 地址和认证信息可用

#### 7. 选择组织

除了 `config-status`、`config-write`、`ping`、`select-org` 之外，其余业务命令都要求先有已选组织。

```bash
python3 scripts/jms_diagnose.py select-org
python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm
```

规则固定为：

- 如果当前环境组织集合恰好是 `{00000000-0000-0000-0000-000000000002}` 或 `{00000000-0000-0000-0000-000000000002,00000000-0000-0000-0000-000000000004}`，系统会自动把 `0002` 写入 `.env.local` 并继续。
- 其他环境不会自动代选组织，必须先显式 `select-org --confirm`。

#### 8. 执行第一条只读命令

例如按用户名精确查询用户：

```bash
python3 scripts/jms_assets.py list --resource user --filters '{"username":"demo-user"}'
```

或者查看某用户当前可访问资产：

```bash
python3 scripts/jms_diagnose.py user-assets --username demo-user
```

<a id="zh-environment-variables"></a>
### 环境变量

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

<a id="zh-core-cli-entry-points"></a>
### 核心脚本入口

| 脚本 | 子命令 | 用途 | 风险说明 |
|---|---|---|---|
| `scripts/jms_assets.py` | `list`、`get`、`preview-create`、`create`、`preview-create-user`、`create-user`、`preview-update`、`update`、`preview-unblock`、`unblock`、`preview-delete`、`delete` | 资产、节点、平台、账号、用户、用户组操作 | `update`、`unblock`、`delete` 属于高风险 |
| `scripts/jms_permissions.py` | `list`、`get`、`preview-create`、`create`、`preview-update`、`update`、`append`、`preview-remove`、`remove`、`delete` | 权限与授权规则操作 | `update`、`remove`、`delete` 需要先预览，`append` 只适合定向追加 |
| `scripts/jms_audit.py` | `list`、`get` | 审计查询与调查 | 未传 `date_from/date_to` 时默认最近 7 天；`command` 审计必须提供 `command_storage_id` |
| `scripts/jms_diagnose.py` | `config-status`、`config-write`、`ping`、`select-org`、`resolve`、`resolve-platform`、`user-assets`、`user-nodes`、`user-asset-access`、`recent-audit` | 配置状态检查、本地配置写入、环境连通性、组织选择、对象解析、访问范围分析、最近审计预检 | 优先作为只读诊断入口；持久写入类命令需要 `--confirm` |
| `scripts/jms_runtime.py` | 无公共业务子命令 | 共享运行时，不作为日常入口 | 仅供脚本内部复用 |

常用帮助命令：

```bash
python3 scripts/jms_diagnose.py config-status --json
python3 scripts/jms_assets.py --help
python3 scripts/jms_permissions.py --help
python3 scripts/jms_audit.py --help
python3 scripts/jms_diagnose.py --help
```

<a id="zh-workflow"></a>
### 标准工作流与安全规则

推荐工作流：

```text
判断是否首次运行
  -> 首次: 全量预检
  -> 后续: 轻量预检
  -> 选择对应 jms_*.py 入口
  -> 精确解析对象或确认 ID
  -> 只读请求直接执行
  -> 写请求先 preview
  -> 高风险操作显式确认
  -> 执行后回读最终状态
```

风险级别：

| 风险级别 | 典型场景 | 默认要求 |
|---|---|---|
| 低 | 只读查询、审计查询、故障排查 | 可直接执行 |
| 中 | 完成查重后的定向创建、范围明确的定向 `append` | 先校验输入与作用范围 |
| 高 | 更新、解锁、删除、关系移除、大范围授权、批量变更 | 必须先预览，再确认，再回读验证 |

命令级确认要点：

| 动作 | 是否需要 `--confirm` | 前置动作 |
|---|---|---|
| `jms_assets.py update` | 是 | `preview-update` |
| `jms_assets.py unblock` | 是 | `preview-unblock` 或先查当前状态 |
| `jms_assets.py delete` | 是 | `preview-delete` |
| `jms_permissions.py update` | 是 | `preview-update` |
| `jms_permissions.py remove` | 是 | `preview-remove` |
| `jms_permissions.py delete` | 是 | 先看权限详情和影响范围 |
| `jms_permissions.py append` | 否 | 仅限单主体、单关系、范围明确的追加 |
| `create` 类命令 | 否 | 仍需先做输入校验和必要查重 |

执行规则：

- 名称有歧义时，不直接变更
- 多个候选对象存在时，先让用户或操作者缩小范围
- `asset` 的 `platform` 字段只接受平台 ID 或唯一精确平台名称
- 平台名称应实时解析，不要硬编码平台 ID；类型命中只用于列出候选，不自动落单
- 标准流程已覆盖的能力，不要临时编写一次性 SDK 或 HTTP 脚本
- 如果现有 SDK/CLI 缺少某个动作，应扩展正式脚本，而不是猜测 HTTP fallback

<a id="zh-reference-map"></a>
### Reference 文档地图

| 文档 | 作用 | 什么时候读 |
|---|---|---|
| `SKILL.md` | 总入口、路由规则、执行边界 | 需要判断该走哪条流程时 |
| `references/runtime.md` | 首次/后续预检、环境加载、环境完整性 | 运行前、环境报错时 |
| `references/assets.md` | 资产、账号、用户、节点、平台相关流程 | 做对象 CRUD、用户改密、用户解锁时 |
| `references/permissions.md` | 授权规则、关系追加/移除、账号别名规则 | 做权限创建、更新、移除时 |
| `references/audit.md` | 审计查询与调查分析 | 查登录、操作、会话、命令记录时 |
| `references/diagnose.md` | 连通性、对象解析、可访问范围分析 | 做只读诊断、解析对象、分析有效权限时 |
| `references/object-map.md` | 自然语言到对象类型和字段的映射 | 用户描述模糊、不知道该查什么对象时 |
| `references/safety-rules.md` | 高风险变更门槛与确认模板 | 任何写操作前 |
| `references/troubleshooting.md` | 错误速查与最小排查路径 | 出现报错或流程偏离标准时 |

<a id="zh-common-use-cases"></a>
### 常见使用场景

下面的示例全部使用仓库中已经存在的正式入口。请把占位符替换成你的实际值。

#### 1. 先做连通性检查

```bash
python3 scripts/jms_diagnose.py ping
```

#### 2. 精确解析对象

```bash
python3 scripts/jms_diagnose.py resolve --resource account --name root
python3 scripts/jms_diagnose.py resolve --resource node --name demo-node
```

#### 3. 精确查询某个用户

```bash
python3 scripts/jms_assets.py list --resource user --filters '{"username":"demo-user"}'
```

#### 4. 查看某用户当前可访问的资产和节点

```bash
python3 scripts/jms_diagnose.py user-assets --username demo-user
python3 scripts/jms_diagnose.py user-nodes --username demo-user
```

#### 5. 查看某用户在某资产下可用的账号和协议

```bash
python3 scripts/jms_diagnose.py user-asset-access --username demo-user --asset-name demo-asset
```

#### 6. 预览权限创建

```bash
python3 scripts/jms_permissions.py preview-create --payload '{"name":"demo-access-rule","users":["<user-id>"],"assets":["<asset-id>"],"accounts":["@SPEC","root"],"actions":["connect"],"protocols":["all"],"is_active":true}'
```

#### 7. 预览并执行高风险更新

```bash
python3 scripts/jms_assets.py preview-update --resource user --id <user-id> --password '<new-password>' --need-update-password
python3 scripts/jms_assets.py update --resource user --id <user-id> --password '<new-password>' --need-update-password --confirm
```

#### 8. 查看最近审计

```bash
python3 scripts/jms_audit.py list --audit-type login --filters '{"limit":5}'
python3 scripts/jms_audit.py list --audit-type operate --filters '{"limit":5}'
```

未传 `date_from/date_to` 时，这两条命令默认查询最近 7 天。

#### 9. 查询命令审计详情

```bash
python3 scripts/jms_audit.py get --audit-type command --id <command-id> --filters '{"command_storage_id":"<command-storage-id>"}'
```

#### 10. 验证权限列表自动翻页与显式分页

`jms_permissions.py` 的 CLI 输出使用统一包装结构：

```json
{
  "ok": true,
  "result": [ ... ]
}
```

因此校验列表条数时，应统计 `result` 数组长度，而不是对最外层对象直接做 `len()`。

统计默认 `list` 返回条数：

```bash
PYTHONPATH=.pydeps python3 scripts/jms_permissions.py list \
  | python3 -c 'import sys,json; data=json.load(sys.stdin); print(len(data["result"]))'
```

统计显式 `limit=1` 返回条数：

```bash
PYTHONPATH=.pydeps python3 scripts/jms_permissions.py list --filters '{"limit":1}' \
  | python3 -c 'import sys,json; data=json.load(sys.stdin); print(len(data["result"]))'
```

验证结论：

- 默认 `list` 会自动翻页聚合结果
- 显式传 `limit` / `offset` 时，不会触发自动翻页
- 如果要确认真实请求是否携带分页参数，应检查最终 HTTP query string 中的 `limit` / `offset`

<a id="zh-troubleshooting"></a>
### 故障排查

| 常见报错或现象 | 常见原因 | 优先动作 |
|---|---|---|
| `python3: command not found` | 没有可用的 Python 3，或命令名不对 | 先安装/确认 Python 3 |
| `No module named jms_client` | 依赖尚未装到当前解释器，常见于只看帮助或绕过 bootstrap 的场景 | 用同一条命令补上 `--confirm-install`，或手动执行 `python3 -m pip install -r requirements.txt` |
| `JMS_API_URL or JMS_WEB_URL is required.` | 地址变量未配置 | 先跑 `config-status --json`，再按提示初始化本地 `.env.local` 或补齐 shell 环境 |
| `Provide either JMS_ACCESS_KEY_ID/... or JMS_USERNAME/...` | 认证方式不完整 | 补齐 AK/SK 或用户名密码 |
| `This action requires --confirm after the change preview is reviewed.` 出现在 `config-write` | 配置写入没有显式确认 | 先回显脱敏摘要，再带 `--confirm` 重试 |
| `Invalid JSON payload: ...` | `--payload` 或 `--filters` JSON 非法 | 检查引号、花括号、逗号 |
| `This action requires --confirm after the change preview is reviewed.` | 对受保护操作跳过了 `--confirm` | 先 preview，再补 `--confirm` |
| `--need-update-password requires --password.` | 改密时只传了标志没传密码 | 同时传入 `--password` |
| 结果对象不对或返回多个候选对象 | 名称歧义，未先解析对象 | 先用 `list/get/resolve` 精确定位 |
| 想做标准操作却开始写临时 SDK 脚本 | 偏离既有流程 | 回到正式 `jms_*.py` 入口 |

最小排查路径：

```text
检查 Python 3
  -> 检查 jumpserver-sdk-python
  -> 执行 config-status --json
  -> 检查 .env.local / 环境变量
  -> 执行 jms_diagnose.py ping
  -> 重新精确解析对象
  -> 对高风险操作先 preview
  -> 必要时查看 audit
```

<a id="zh-maintenance"></a>
### 扩展与维护

如果你要维护这个仓库，建议遵循下面的规则：

- 新增或修改业务动作时，优先扩展 `scripts/jms_*.py`
- 不要为标准流程临时生成一次性 SDK Python 文件或 HTTP 探测脚本
- 一旦环境模型变化，至少同时检查这三个地方：
  - `scripts/jms_diagnose.py` 里的 `config-status/config-write`
  - `references/runtime.md`
  - `scripts/jms_runtime.py`
- 一旦脚本子命令变化，至少同时更新：
  - 对应 `references/*.md`
  - `SKILL.md`
  - `README.md`
- 让 `SKILL.md` 保持“路由与边界”，让 `references/` 保持“分域细节”

`agents/openai.yaml` 说明了这个仓库在代理界面中的展示名和默认提示词。如果你要把仓库接入某个支持 skill 的代理环境，这个文件通常是接入端会读取的元信息之一。

## English Version

Quick links: [Overview](#en-overview) | [Model Trigger and Execution Rules](#en-model-routing) | [Getting Started](#en-getting-started) | [Environment Variables](#en-environment-variables) | [Core CLI Entry Points](#en-core-cli-entry-points) | [Common Use Cases](#en-common-use-cases) | [Troubleshooting](#en-troubleshooting)

<a id="en-overview"></a>
### Overview

This repository is not the JumpServer server application, and it is not a standalone web service. It is an execution-oriented skill package designed to be used locally or by an agent runtime.

Its core responsibilities are:

- call JumpServer V4 through fixed Python CLI entry points
- use one shared runtime model for environment loading, authentication, and SDK client construction
- keep routing rules and execution boundaries in `SKILL.md`, while keeping domain-specific procedures in `references/*.md`
- enforce preview, confirmation, and post-change verification for high-impact operations

This repository is intended for workflows such as:

- querying assets, accounts, users, platforms, nodes, and user groups
- previewing or executing targeted create, update, delete, unblock, permission append, and relation removal operations
- auditing login, operation, session, and command records
- analyzing a user's effective assets, effective nodes, and asset-level account/protocol access

There is no Docker, CI/CD, or PaaS deployment configuration in the current repository, so this README does not pretend that the project is a deployable service. It is best treated as a local skill repository or an agent execution bundle.

<a id="en-model-routing"></a>
### Model Trigger and Execution Rules

This section mirrors the first-screen rules in `SKILL.md` so smaller models can route requests correctly before reading the detailed references.

| Question | Fixed Rule |
|---|---|
| When must this skill be triggered | Any request about assets, accounts, users, user groups, organizations, platforms, nodes, permissions, audits, access analysis, JumpServer configuration, environment switching, dependency checks, or connectivity checks |
| What is the first step after triggering | Always run the preflight flow first: dependency check -> `config-status --json` -> `config-write --confirm` if needed -> `ping` |
| What are the four formal entry points | `jms_assets.py` for assets/accounts/users/user-groups/organizations/platforms/nodes; `jms_permissions.py` for permissions and authorization; `jms_audit.py` for audits; `jms_diagnose.py` for configuration, resolution, connectivity, and access analysis |
| How must high-impact writes run | Always preview first, then confirm, then read back to verify |
| What happens when org is not specified | Read the accessible orgs first and require `select-org`; only the exact sets `{0002}` or `{0002,0004}` auto-write `0002` |

Fixed prohibitions:

- Do not skip the preflight.
- Do not generate ad hoc SDK scripts, one-off HTTP scripts, or HTTP fallbacks.
- Do not guess platform IDs, object IDs, organizations, auth modes, or credential values.
- Do not treat `0002` as a universal default org outside the `{0002}` / `{0002,0004}` reserved cases.
- Do not continue business commands when no org has been selected.
- Do not auto-switch to another org to continue authorization changes.
- Stop and ask for confirmation when the name is not unique.

<a id="en-key-capabilities"></a>
### Key Capabilities

| Domain | Primary Entry | Coverage | Notes |
|---|---|---|---|
| Runtime preflight | `references/runtime.md` + `jms_diagnose.py ping` | Python, dependency, environment, connectivity checks | First run uses a full preflight, later runs use a lightweight preflight |
| Assets and user objects | `scripts/jms_assets.py` | `asset`, `node`, `platform`, `account`, `user`, `user-group` | Supports query, preview-create, create, preview-update, update, preview-unblock, unblock, preview-delete, and delete |
| Permissions and authorization | `scripts/jms_permissions.py` | permission query, create, update, relation append, relation removal, delete | `append` is for narrow targeted additions; `update/remove/delete` are high-impact |
| Audit and investigation | `scripts/jms_audit.py` | `operate`, `login`, `session`, and `command` audits | Defaults to the last 7 days when `date_from/date_to` are omitted; `command` audits require `command_storage_id` |
| Diagnostics and access analysis | `scripts/jms_diagnose.py` | connectivity, object resolution, effective-access analysis, recent audit pre-checks | Prefer service-side effective views over local permission expansion |
| Routing and boundaries | `SKILL.md` | intent routing, execution rules, safety boundaries | This is an execution skill, not just a documentation index |

<a id="en-repository-structure"></a>
### Repository Structure

```text
.
├── SKILL.md                    # routing rules, execution policy, boundaries
├── .gitignore                  # ignores local .env.local and .DS_Store
├── README.md                   # this document
├── agents/
│   └── openai.yaml             # agent display metadata and default prompt
├── references/
│   ├── runtime.md              # preflight and environment model
│   ├── assets.md               # asset, user, account, node, and platform workflows
│   ├── permissions.md          # permission and authorization rules
│   ├── audit.md                # audit and investigation workflows
│   ├── diagnose.md             # connectivity, resolution, access analysis
│   ├── object-map.md           # natural-language to object mapping
│   ├── safety-rules.md         # high-impact mutation guardrails
│   └── troubleshooting.md      # common errors and troubleshooting paths
├── scripts/
│   ├── jms_assets.py           # CRUD entry point for assets, users, accounts, etc.
│   ├── jms_permissions.py      # permission and authorization entry point
│   ├── jms_audit.py            # audit query entry point
│   ├── jms_diagnose.py         # diagnostics and access analysis entry point
│   └── jms_runtime.py          # shared runtime, env loading, SDK client construction
├── env.sh                      # Bash helper for loading the environment
├── requirements.txt            # Python dependencies
```

Responsibility split:

- `SKILL.md` decides which workflow should be used and when preview/confirmation is mandatory
- `references/*.md` store domain rules, constraints, and example commands
- `scripts/*.py` are the actual executable SDK-backed entry points
- `scripts/jms_runtime.py` handles environment loading, auth selection, and client reuse
- `agents/openai.yaml` defines agent-facing metadata

<a id="en-tech-stack"></a>
### Tech Stack and Dependencies

- **Language**: Python 3
- **Core dependency**: `jumpserver-sdk-python==0.9.1`
- **Target system**: JumpServer V4
- **Invocation model**: local CLI scripts backed by the SDK client
- **Environment handling**: `.env.local` or shell environment variables
- **Optional helper**: `env.sh` for Bash/macOS/Linux shells
- **Agent integration**: `agents/openai.yaml` for display metadata and default prompting

Install dependencies online:

```bash
python3 -m pip install -r requirements.txt
```

Every formal `jms_*.py` entry point checks `requirements.txt` on startup. If packages are missing, rerun the same command with `--confirm-install` to install them with the active interpreter:

```bash
python3 scripts/jms_diagnose.py --confirm-install config-status --json
```

Offline environments still need a locally prepared wheel or internal package mirror; this repository does not bundle a wheel file.

<a id="en-getting-started"></a>
### Getting Started

These steps assume you are setting up the repository on a fresh machine.

#### 1. Get the code and enter the directory

```bash
git clone <your-repo-url>
cd jumpserver-skills
```

If the repository is already present on disk, just `cd` into it.

#### 2. Prepare a Python 3 environment

Check that Python 3 is available:

```bash
python3 --version
```

Using a virtual environment is optional but recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

#### 3. Dependency preflight and installation

The first run of any formal entry point checks the dependencies declared in `requirements.txt`. A good starting point is a read-only command:

```bash
python3 scripts/jms_diagnose.py config-status --json
```

If the command returns `ok=false` and reports missing requirements, rerun the same command with `--confirm-install`:

```bash
python3 scripts/jms_diagnose.py --confirm-install config-status --json
```

You can still install manually:

```bash
python3 -m pip install -r requirements.txt
```

For offline environments, prepare a local wheel or internal mirror yourself; the repository does not ship an offline wheel.

#### 4. Configure environment variables

Check the current local configuration state first:

```bash
python3 scripts/jms_diagnose.py config-status --json
```

If `complete=false`, let the skill collect the following fields in dialog order:

- `JMS_API_URL`
- auth mode: `AK/SK` or `username/password`
- the matching credentials
- `JMS_ORG_ID`, optional
- `JMS_VERSION`, default `4`
- `JMS_TIMEOUT`, optional

The skill should echo a masked summary first, then call `config-write --confirm` to create a local `.env.local`.

Important:

- any AK/SK or password sent in chat will appear in the conversation transcript
- if you do not want that, create the local `.env.local` manually instead

#### 5. Load the environment if needed

On macOS/Linux/Bash you can explicitly load the environment:

```bash
source ./env.sh
```

This step is optional. All official `jms_*.py` scripts auto-load `.env.local`, so the scripts still work even if you do not run `env.sh`. On Windows you would usually rely on `.env.local` or shell environment variables directly.

#### 6. Run the first connectivity check

```bash
python3 scripts/jms_diagnose.py ping
```

This is the recommended first command because it validates:

- the Python interpreter
- the installed `jumpserver-sdk-python`
- the environment required to construct a client
- the current JumpServer address and credentials

#### 7. Execute the first read-only command

For example, query a user by exact username:

```bash
python3 scripts/jms_assets.py list --resource user --filters '{"username":"demo-user"}'
```

Or inspect the effective assets available to a user:

```bash
python3 scripts/jms_diagnose.py user-assets --username demo-user
```

<a id="en-environment-variables"></a>
### Environment Variables

The following table reflects the current implementation in `references/runtime.md` and `scripts/jms_runtime.py`. On first use, the skill can collect these values in chat and persist them into a local `.env.local`.

| Variable | Required | Description | Example |
|---|---|---|---|
| `JMS_API_URL` | one of `JMS_API_URL` or `JMS_WEB_URL` is required | JumpServer API/access URL | `https://jump.example.com` |
| `JMS_WEB_URL` | one of `JMS_API_URL` or `JMS_WEB_URL` is required | fallback URL variable accepted by the runtime | `https://jump.example.com` |
| `JMS_VERSION` | recommended | JumpServer version, currently defaulted to `4` | `4` |
| `JMS_ACCESS_KEY_ID` | required together with `JMS_ACCESS_KEY_SECRET`, unless using username/password | access key ID | `your-access-key-id` |
| `JMS_ACCESS_KEY_SECRET` | required together with `JMS_ACCESS_KEY_ID`, unless using username/password | access key secret | `your-access-key-secret` |
| `JMS_USERNAME` | required together with `JMS_PASSWORD`, unless using AK/SK | username for basic auth | `ops-user` |
| `JMS_PASSWORD` | required together with `JMS_USERNAME`, unless using AK/SK | password for basic auth | `your-password` |
| `JMS_ORG_ID` | optional | organization scope | `00000000-0000-0000-0000-000000000000` |
| `JMS_TIMEOUT` | optional | SDK request timeout in seconds | `30` |
| `JMS_SDK_MODULE` | optional | custom SDK module path, default `jms_client.client` | `jms_client.client` |
| `JMS_SDK_GET_CLIENT` | optional | custom client factory name, default `get_client` | `get_client` |

Generated `.env.local` example:

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

Environment rules:

- you must provide at least one address variable: `JMS_API_URL` or `JMS_WEB_URL`
- you must choose exactly one auth mode: `AK/SK` or `username/password`
- `.env.local` is auto-loaded by the scripts
- when config is missing, start with `python3 scripts/jms_diagnose.py config-status --json`
- if you switch JumpServer targets, accounts, organizations, or `.env.local` values, treat the next run like a first-run full preflight

Implementation note:

- `scripts/jms_runtime.py` currently constructs the client with `verify=False`
- HTTPS certificate warnings are suppressed
- these behaviors are code-defined and are not currently controlled through environment variables

<a id="en-core-cli-entry-points"></a>
### Core CLI Entry Points

| Script | Subcommands | Purpose | Risk Notes |
|---|---|---|---|
| `scripts/jms_assets.py` | `list`, `get`, `preview-create`, `create`, `preview-create-user`, `create-user`, `preview-update`, `update`, `preview-unblock`, `unblock`, `preview-delete`, `delete` | asset, node, platform, account, user, and user-group operations | `update`, `unblock`, and `delete` are high-impact |
| `scripts/jms_permissions.py` | `list`, `get`, `preview-create`, `create`, `preview-update`, `update`, `append`, `preview-remove`, `remove`, `delete` | permission and authorization rule operations | `update`, `remove`, and `delete` require preview first; `append` is for narrow targeted additions |
| `scripts/jms_audit.py` | `list`, `get` | audit queries and investigations | defaults to the last 7 days when `date_from/date_to` are omitted; `command` audit queries require `command_storage_id` |
| `scripts/jms_diagnose.py` | `config-status`, `config-write`, `ping`, `select-org`, `resolve`, `resolve-platform`, `user-assets`, `user-nodes`, `user-asset-access`, `recent-audit` | config-state inspection, local config writes, connectivity, org selection, object resolution, effective-access analysis, recent audit checks | preferred diagnostics entry point; persistent writes require `--confirm` |
| `scripts/jms_runtime.py` | no public business subcommands | shared runtime, not a day-to-day entry point | internal helper module |

Helpful discovery commands:

```bash
python3 scripts/jms_diagnose.py config-status --json
python3 scripts/jms_assets.py --help
python3 scripts/jms_permissions.py --help
python3 scripts/jms_audit.py --help
python3 scripts/jms_diagnose.py --help
```

<a id="en-workflow"></a>
### Workflow and Safety Rules

Recommended flow:

```text
decide whether this is the first run
  -> first run: full preflight
  -> later run: lightweight preflight
  -> choose the correct jms_*.py entry point
  -> resolve objects exactly or confirm IDs
  -> execute read-only requests directly
  -> preview write requests first
  -> require explicit confirmation for high-impact actions
  -> read back the final state after execution
```

Risk levels:

| Risk Level | Typical Scenarios | Default Requirement |
|---|---|---|
| Low | read-only queries, audit queries, troubleshooting | direct execution is fine |
| Medium | deduplicated targeted create, narrow targeted `append` | validate inputs and scope first |
| High | update, unblock, delete, relation removal, broad authorization changes, batch mutations | preview first, then confirm, then verify final state |

Confirmation matrix:

| Action | Requires `--confirm` | What to do first |
|---|---|---|
| `jms_assets.py update` | yes | `preview-update` |
| `jms_assets.py unblock` | yes | `preview-unblock` or inspect current state first |
| `jms_assets.py delete` | yes | `preview-delete` |
| `jms_permissions.py update` | yes | `preview-update` |
| `jms_permissions.py remove` | yes | `preview-remove` |
| `jms_permissions.py delete` | yes | inspect permission details and blast radius first |
| `jms_permissions.py append` | no | only for single-subject, single-relation, well-scoped additions |
| `create` commands | no | still validate input and perform necessary deduplication first |

Execution rules:

- do not mutate objects when names are ambiguous
- if multiple candidate objects exist, narrow the scope before acting
- resolve platform names dynamically instead of hard-coding platform IDs
- treat asset `platform` strings as exact platform names; type matches are hints that must be confirmed before mutation
- do not create ad hoc SDK or HTTP scripts for capabilities already covered by the standard workflow
- if the SDK/CLI is missing a required action, extend the official scripts instead of guessing an HTTP fallback

<a id="en-reference-map"></a>
### Reference Map

| Document | Purpose | When to Read It |
|---|---|---|
| `SKILL.md` | top-level routing rules and execution boundaries | when deciding which workflow should be used |
| `references/runtime.md` | first-run vs later-run preflight, environment loading, environment completeness | before execution and when environment issues appear |
| `references/assets.md` | asset, account, user, node, and platform procedures | when doing object CRUD, password reset, or unblock flows |
| `references/permissions.md` | authorization rules, relation append/remove, account alias rules | when creating, updating, or removing permissions |
| `references/audit.md` | audit query and investigation workflow | when investigating login, operation, session, or command events |
| `references/diagnose.md` | connectivity, object resolution, effective-access analysis | when performing read-only diagnostics or access analysis |
| `references/object-map.md` | natural-language to object and field mapping | when the requested object type is unclear |
| `references/safety-rules.md` | mutation guardrails and confirmation rules | before any write action |
| `references/troubleshooting.md` | quick error lookup and minimal troubleshooting path | when commands fail or the workflow drifts |

<a id="en-common-use-cases"></a>
### Common Use Cases

All examples below use real entry points that already exist in this repository. Replace placeholders with your own values.

#### 1. Run a connectivity check first

```bash
python3 scripts/jms_diagnose.py ping
```

#### 2. Resolve objects exactly

```bash
python3 scripts/jms_diagnose.py resolve --resource account --name root
python3 scripts/jms_diagnose.py resolve --resource node --name demo-node
```

#### 3. Query a user exactly

```bash
python3 scripts/jms_assets.py list --resource user --filters '{"username":"demo-user"}'
```

#### 4. Inspect effective assets and nodes for a user

```bash
python3 scripts/jms_diagnose.py user-assets --username demo-user
python3 scripts/jms_diagnose.py user-nodes --username demo-user
```

#### 5. Inspect accounts and protocols for one user on one asset

```bash
python3 scripts/jms_diagnose.py user-asset-access --username demo-user --asset-name demo-asset
```

#### 6. Preview permission creation

```bash
python3 scripts/jms_permissions.py preview-create --payload '{"name":"demo-access-rule","users":["<user-id>"],"assets":["<asset-id>"],"accounts":["@SPEC","root"],"actions":["connect"],"protocols":["all"],"is_active":true}'
```

#### 7. Preview and execute a high-impact update

```bash
python3 scripts/jms_assets.py preview-update --resource user --id <user-id> --password '<new-password>' --need-update-password
python3 scripts/jms_assets.py update --resource user --id <user-id> --password '<new-password>' --need-update-password --confirm
```

#### 8. Inspect recent audit activity

```bash
python3 scripts/jms_audit.py list --audit-type login --filters '{"limit":5}'
python3 scripts/jms_audit.py list --audit-type operate --filters '{"limit":5}'
```

When `date_from/date_to` are omitted, these commands default to the last 7 days.

#### 9. Get command audit details

```bash
python3 scripts/jms_audit.py get --audit-type command --id <command-id> --filters '{"command_storage_id":"<command-storage-id>"}'
```

#### 10. Verify permission-list auto-pagination and explicit pagination

The `jms_permissions.py` CLI uses a consistent wrapper payload:

```json
{
  "ok": true,
  "result": [ ... ]
}
```

So when validating list sizes, count the length of `result` instead of calling `len()` on the outer object.

Count the default `list` result size:

```bash
PYTHONPATH=.pydeps python3 scripts/jms_permissions.py list \
  | python3 -c 'import sys,json; data=json.load(sys.stdin); print(len(data["result"]))'
```

Count the explicit `limit=1` result size:

```bash
PYTHONPATH=.pydeps python3 scripts/jms_permissions.py list --filters '{"limit":1}' \
  | python3 -c 'import sys,json; data=json.load(sys.stdin); print(len(data["result"]))'
```

Validation summary:

- the default `list` command auto-paginates and aggregates results
- when `limit` / `offset` is explicitly provided, auto-pagination is skipped
- if you need to confirm whether pagination parameters were actually sent, inspect the final HTTP query string for `limit` / `offset`

<a id="en-troubleshooting"></a>
### Troubleshooting

| Common Error or Symptom | Likely Cause | First Action |
|---|---|---|
| `python3: command not found` | Python 3 is unavailable or the command name is different | install or locate Python 3 first |
| `No module named jms_client` | dependencies are not installed into the active interpreter, often when viewing help or bypassing bootstrap | rerun the same command with `--confirm-install`, or install manually with `python3 -m pip install -r requirements.txt` |
| `JMS_API_URL or JMS_WEB_URL is required.` | no address variable is configured | run `config-status --json`, then initialize `.env.local` or populate shell environment variables |
| `Provide either JMS_ACCESS_KEY_ID/... or JMS_USERNAME/...` | the chosen auth mode is incomplete | provide either AK/SK or username/password |
| `This action requires --confirm after the change preview is reviewed.` for `config-write` | the local config write was not explicitly confirmed | echo the masked summary first, then retry with `--confirm` |
| `Invalid JSON payload: ...` | invalid JSON in `--payload` or `--filters` | inspect quotes, braces, and commas |
| `This action requires --confirm after the change preview is reviewed.` | a protected mutation skipped `--confirm` | run preview first, then repeat with `--confirm` |
| `--need-update-password requires --password.` | password-update flag was set without a password | pass `--password` together with the flag |
| wrong object returned or multiple candidates returned | ambiguous object resolution | resolve the object exactly with `list/get/resolve/resolve-platform` first |
| you started writing temporary SDK scripts for a standard task | the workflow drifted from the supported path | go back to the official `jms_*.py` scripts |

Minimal troubleshooting path:

```text
check Python 3
  -> check jumpserver-sdk-python
  -> run config-status --json
  -> check .env.local / environment variables
  -> run jms_diagnose.py ping
  -> resolve the target object exactly
  -> preview high-impact actions first
  -> inspect audit data if needed
```

<a id="en-maintenance"></a>
### Extending and Maintaining

If you maintain this repository, follow these rules:

- add or change business behavior by extending `scripts/jms_*.py`
- do not generate one-off SDK Python files or ad hoc HTTP probes for workflows already covered by the standard path
- whenever the environment model changes, review at least:
  - `scripts/jms_diagnose.py` `config-status/config-write`
  - `references/runtime.md`
  - `scripts/jms_runtime.py`
- whenever script subcommands change, update at least:
  - the matching `references/*.md`
  - `SKILL.md`
  - `README.md`
- keep `SKILL.md` focused on routing and boundaries, and keep `references/` focused on domain details

`agents/openai.yaml` describes how the repository should appear in an agent UI and what default prompt should be used. If you integrate this repository into a skill-capable agent environment, that file is usually one of the metadata entry points the integration layer reads.
