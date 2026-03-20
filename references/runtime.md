# 运行入口与环境

## 快速概览

- 这份文档是所有 `assets / permissions / audit / diagnose` 请求的统一预检入口。
- 所有正式 `jms_*.py` 入口都会在启动时先检查仓库根目录 `requirements.txt`；若缺依赖，需要用同一条命令补上 `--confirm-install` 后重试。
- 依赖就绪后，再执行 `python3 scripts/jms_diagnose.py config-status --json` 检查本地配置是否完整。
- 若配置不完整，按固定顺序对话收集 `JMS_API_URL -> 鉴权模式 -> 凭据 -> JMS_ORG_ID -> JMS_VERSION -> JMS_TIMEOUT`，回显脱敏摘要后执行 `config-write --confirm` 生成本地 `.env.local`。
- 预检分两级：同一终端环境首次运行做全量校验，后续请求做轻量校验。
- 若未指定 `JMS_ORG_ID`，运行时先读取当前环境全部可访问组织；默认不自动代选组织。
- 只有当可访问组织集合恰好是 `{0002}` 或 `{0002,0004}` 时，运行时才会自动将 `0002` 写入 `.env.local` 并继续。
- 除 `config-status`、`config-write`、`ping`、`select-org` 外，其余业务命令在未选组织时都会先停下。
- 当前 skill 只保留 4 个 `jms_*.py` 正式入口；旧快路径、兼容包装和后台热路径相关配置已不再使用。

## 预检模式总览

| 模式 | 何时使用 | 检查内容 | 失败动作 |
|---|---|---|---|
| 统一依赖自举 | 每次启动任一正式入口 | 检查 `requirements.txt` 是否缺包；缺包时要求同一条命令补 `--confirm-install` | 停止业务命令，先补依赖 |
| 全量校验 | 当前终端环境首次运行，且依赖已就绪 | Python 3、`config-status --json`、必要时 `config-write --confirm`、环境完整性、`jms_diagnose.py ping` | 停止业务命令，先补环境 |
| 轻量校验 | 同一终端环境的后续请求，且依赖已就绪 | 关键环境、`jms_diagnose.py ping` | 升级为全量校验 |
| 全量回退 | 环境变化或轻量校验失败 | 重新执行完整全量流程 | 仍失败则停止业务命令 |

说明：

- “同一终端环境”指同一台机器、同一 skill 工作目录、同一套 `.env.local` 或 shell 环境，且用户没有明确切换 JumpServer 环境。
- 这里的“首次 / 后续”由当前协作上下文和用户提供的环境变化信息判断，不依赖程序级状态文件。

## 首次全量校验

### 1. Python 3

| 平台 | 首选命令 | 回退命令 | 通过标准 |
|---|---|---|---|
| Linux/macOS | `python3 --version` | 无 | 返回 Python 3 版本 |
| Windows / PowerShell | `python --version` | `py -3 --version` | 返回 Python 3 版本 |

失败时固定动作：

- 提示未检测到 Python 3 或当前命令未指向 Python 3。
- 要求用户安装 Python 3。
- 要求用户明确提供可用命令名或解释器路径，例如 `python3`、`python`、`py -3`。

### 2. `requirements.txt` 依赖自举

| 步骤 | 命令 | 说明 |
|---|---|---|
| 检查 | 运行任一正式 `jms_*.py` 命令 | 启动时自动扫描 `requirements.txt` |
| 首选安装 | 同一条命令补 `--confirm-install` | 用当前解释器执行 `python -m pip install -r requirements.txt` |
| 离线回退 | 手动安装 | 自行准备本地 wheel 或内部镜像源；仓库当前不附带 wheel |
| 安装后复核 | 重新执行原命令 | bootstrap 会再次校验缺失依赖是否补齐 |

规则：

- 缺依赖但未带 `--confirm-install` 时，命令直接返回 JSON 失败，并给出可直接重试的命令。
- `--confirm-install` 是启动参数，不是子命令参数；放在脚本名后或子命令后都可用。
- 自动安装只补缺失依赖，不因为已安装版本和 `requirements.txt` 不一致而阻塞。
- 安装失败时，不继续执行正式 `jms_*.py` 业务命令。
- 若用户使用 Windows，命令中的 `python3` 改成可用的 `python` 或 `py -3`。
- 若报 `No module named jms_client`，先回到这一步处理。

### 3. 本地配置状态检查

```text
python3 scripts/jms_diagnose.py config-status --json
  -> complete=true: 继续全量校验
  -> complete=false: 对话收集配置 -> 脱敏确认 -> python3 scripts/jms_diagnose.py config-write --payload '<json>' --confirm
```

规则：

- 交互式收集顺序固定为：
  - `JMS_API_URL`
  - 鉴权模式：`AK/SK` 或 `用户名/密码`
  - 对应密钥或用户名密码
  - `JMS_ORG_ID`，允许留空
  - `JMS_VERSION`，默认 `4`
  - `JMS_TIMEOUT`，允许留空
- 写入前必须先回显脱敏摘要：
  - URL 可明文回显
  - AK/SK 或密码必须做掩码处理
- `config-write` 会在 skill 本地目录生成或覆盖 `.env.local`
- 生成后的 `.env.local` 只保留一种鉴权模式

### 4. 环境完整性

| 类别 | 变量 | 要求 | 说明 |
|---|---|---|---|
| 地址 | `JMS_API_URL` 或 `JMS_WEB_URL` | 必需其一 | JumpServer 地址 |
| AK/SK 鉴权 | `JMS_ACCESS_KEY_ID`、`JMS_ACCESS_KEY_SECRET` | 可作为一组满足 | 优先级高于用户名密码 |
| 用户名密码鉴权 | `JMS_USERNAME`、`JMS_PASSWORD` | 可作为一组满足 | 仅在未提供 AK/SK 时使用 |
| 版本 | `JMS_VERSION` | 可选但建议检查 | 默认按仓库支持版本处理 |
| 组织 | `JMS_ORG_ID` | 初始可留空 | 业务执行前需通过 `select-org` 或保留组织特判写入 |
| 超时 | `JMS_TIMEOUT` | 可选 | 请求超时秒数 |
| SDK 模块 | `JMS_SDK_MODULE` | 可选 | 自定义 SDK 模块路径，默认 `jms_client.client` |
| 客户端工厂 | `JMS_SDK_GET_CLIENT` | 可选 | 自定义 client 工厂函数名，默认 `get_client` |

规则：

- 地址缺失时，固定进入交互式初始化，要求用户提供 `JMS_API_URL` 或 `JMS_WEB_URL`。
- 鉴权缺失时，要求用户二选一提供 `AK/SK` 或 `用户名/密码`。
- 不猜测地址、组织、认证方式或密钥内容。
- 若需要兼容自定义 SDK 导入路径，使用 `JMS_SDK_MODULE` 和 `JMS_SDK_GET_CLIENT`，不要继续使用旧的 `JMS_SDK_CLIENT` 约定。

### 5. 连通性进入检查

```text
python3 scripts/jms_diagnose.py ping
  -> 进入 assets / permissions / audit / diagnose
```

## 后续轻量校验

| 步骤 | 检查内容 | 通过标准 |
|---|---|---|
| 本地配置状态 | `python3 scripts/jms_diagnose.py config-status --json` | `complete=true` |
| 连通性 | `python3 scripts/jms_diagnose.py ping` | 返回可连接结果 |

规则：

- 轻量校验不重复检查 `python3 --version`；依赖缺失检查仍由每次启动时的 requirements bootstrap 统一处理。
- 关键环境只检查：
  - `JMS_API_URL` 或 `JMS_WEB_URL`
  - `JMS_ACCESS_KEY_ID/JMS_ACCESS_KEY_SECRET` 或 `JMS_USERNAME/JMS_PASSWORD`
- 任一步失败，都升级为全量校验。

## 组织选择与保留组织特判

| 条件 | 固定规则 |
|---|---|
| `JMS_ORG_ID` 已设置且可访问 | 直接把该值作为当前处理组织 |
| `JMS_ORG_ID` 已设置但不可访问 | 阻塞，要求重新 `select-org` |
| `JMS_ORG_ID` 为空，且可访问组织集合是 `{0002}` | 自动写入 `0002`，重新加载后继续 |
| `JMS_ORG_ID` 为空，且可访问组织集合是 `{0002,0004}` | 自动写入 `0002`，重新加载后继续 |
| `JMS_ORG_ID` 为空，且是其他组织集合 | 阻塞，返回 `candidate_orgs`，要求先 `select-org` |
| 当前组织是 A，目标对象在 B | 不自动切换组织；返回跨组织阻塞信息 |

说明：

- `effective_org` 是所有后续业务操作使用的真实处理组织。
- 显式切组织通过 `python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm` 写回 `.env.local`。
- `{0002}` / `{0002,0004}` 特判写回的 `0002` 也必须读取运行时组织名称，不按 `Default` 字符串判断。

## 回退到全量校验的条件

| 条件 | 动作 |
|---|---|
| 用户明确说环境变了 | 回退全量校验 |
| 用户切换了 JumpServer、账号或组织 | 回退全量校验 |
| `.env.local` 被修改，或重新提供了环境值 | 回退全量校验 |
| `jms_diagnose.py ping` 失败 | 回退全量校验 |
| 报错指向 Python、SDK、环境变量或鉴权缺失 | 回退全量校验 |

## 正式入口

| 入口 | 用途 |
|---|---|
| `python3 scripts/jms_diagnose.py config-status --json` | 查看当前本地配置状态 |
| `python3 scripts/jms_diagnose.py config-write --payload '<json>' --confirm` | 生成或覆盖本地 `.env.local` |
| `python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm` | 显式选择组织并写回 `JMS_ORG_ID` |
| `python3 scripts/jms_assets.py ...` | 资产、节点、平台、账号、用户、用户组 |
| `python3 scripts/jms_permissions.py ...` | 权限与授权 |
| `python3 scripts/jms_audit.py ...` | 审计查询 |
| `python3 scripts/jms_diagnose.py ...` | 连通性、解析、访问分析 |

## 阻塞时的固定输出模板

### 缺 Python 3

```text
已检查到：当前环境没有可用的 Python 3 命令。
缺少内容：Python 3 解释器或可执行命令映射。
下一步：请先安装 Python 3，并告诉我可用命令名或路径，例如 python3、python 或 py -3。
```

### 缺 `jumpserver-sdk-python`

```text
已检查到：Python 3 可用，但未检测到 jumpserver-sdk-python。
缺少内容：`requirements.txt` 中声明的运行依赖。
下一步：请用同一条命令补上 --confirm-install 后重试；如仍无法联网，请手动准备本地 wheel 或内部源并执行 python3 -m pip install -r requirements.txt，完成后再继续运行正式的 jms_*.py 命令。
```

### 缺环境变量

```text
已检查到：本地运行依赖和解释器可用，但环境配置不完整。
缺少内容：列出缺失字段，例如 JMS_API_URL、JMS_ACCESS_KEY_ID、JMS_ACCESS_KEY_SECRET。
下一步：我会先执行 python3 scripts/jms_diagnose.py config-status --json；若配置仍不完整，就按交互式初始化顺序收集缺失字段，回显脱敏摘要后执行 config-write --confirm。在环境补齐前我不会继续执行业务命令。
```

### 未选组织

```text
已检查到：当前尚未选择组织。
阻塞原因：除 config-status/config-write/ping/select-org 外，其余业务命令都必须先确定组织上下文。
候选组织：返回当前环境全部可访问组织。
下一步：请先执行 python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm；若环境组织集合恰好是 {0002} 或 {0002,0004}，系统会自动写入 0002 后继续。
```

### 当前组织与目标对象组织不一致

```text
已检查到：当前处理组织与目标对象组织不一致。
阻塞原因：跨组织授权已禁止；系统不会自动切换到其他组织继续执行。
下一步：请先明确组织并在该组织上下文中重新解析对象，再继续执行。
```
