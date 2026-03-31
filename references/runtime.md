# 运行入口与环境

## 快速概览

- 这份文档是所有 `query / diagnose / report` 请求的统一预检入口。
- 面向用户的正式业务入口固定为 `scripts/jumpserver_api/jms_query.py`、`jms_diagnose.py`、`jms_report.py`；同目录下其余 `jms_*.py` 文件是公共运行时/请求/发现/聚合模块，不作为独立业务入口。
- 首次运行任一正式入口时，脚本会先按当前解释器环境自动检查 `requirements.txt` 中的依赖；缺失时自动安装，再执行 `python3 scripts/jumpserver_api/jms_diagnose.py config-status --json` 检查本地配置是否完整。
- 若配置不完整，按固定顺序对话收集 `JMS_API_URL -> (JMS_ACCESS_KEY_ID + JMS_ACCESS_KEY_SECRET 或 JMS_USERNAME + JMS_PASSWORD) -> JMS_ORG_ID -> JMS_TIMEOUT -> JMS_VERIFY_TLS`，回显脱敏摘要后执行 `config-write --confirm` 生成本地 `.env`。
- 预检分两级：当前解释器环境缺依赖时先做依赖自愈 + 全量校验，依赖已就绪的后续请求做轻量校验。
- 若未指定 `JMS_ORG_ID`，运行时先读取当前环境全部可访问组织；默认不自动代选组织。
- 只有当可访问组织集合恰好是 `{0002}` 或 `{0002,0004}` 时，运行时才会自动将 `0002` 写入 `.env` 并继续。
- 即使 `.env` 中的 `JMS_ORG_ID` 已生效，查询结果也会回显当前仍可切换到哪些组织，并通过 `org_context_hint` 说明当前查询范围固定在哪个组织。
- 除 `config-status`、`config-write`、`ping`、`select-org` 外，其余业务命令在未选组织时都会先停下；组织阻塞时会额外返回 `reason_code`、`user_message`、`action_hint`、`candidate_org_count` 等结构化提示字段。

## 预检模式总览

| 模式 | 何时使用 | 检查内容 | 失败动作 |
|---|---|---|---|
| 全量校验 | 当前解释器环境首次运行，或检测到缺依赖 | Python 3、自动依赖检查/安装、`config-status --json`、必要时 `config-write --confirm`、环境完整性、`ping` | 停止业务命令，先补环境 |
| 轻量校验 | 同一解释器环境且依赖已就绪的后续请求 | 关键环境、`ping` | 升级为全量校验 |
| 全量回退 | 环境变化、依赖自检失败或轻量校验失败 | 重新执行完整全量流程 | 仍失败则停止业务命令 |

说明：

- “同一解释器环境”指同一台机器、同一 skill 工作目录、同一个 Python 解释器 / venv，以及同一套 `.env` 或 shell 环境，且用户没有明确切换 JumpServer 环境。
- 这里的“首次 / 后续”不依赖程序级状态文件，而是按当前解释器环境中依赖是否已安装来判断。

## 首次全量校验

### 1. Python 3

| 平台 | 首选命令 | 回退命令 | 通过标准 |
|---|---|---|---|
| Linux/macOS | `python3 --version` | 无 | 返回 Python 3 版本 |
| Windows / PowerShell | `python --version` | `py -3 --version` | 返回 Python 3 版本 |

### 2. 依赖自动检查与安装

正式入口会先检查当前解释器环境是否已安装 `requirements.txt` 中的依赖；如果缺失，会自动执行等价于下列命令的安装流程：

```bash
python3 -m pip install -r requirements.txt
```

规则：

- 自动安装始终绑定当前实际运行脚本的 Python 解释器。
- 自动安装失败时，不继续执行业务命令，并返回手动兜底安装命令。
- 离线环境需要自行准备本地 wheel、内部镜像源，或手动补齐 pip 安装能力。

### 3. 本地配置状态检查

```text
python3 scripts/jumpserver_api/jms_diagnose.py config-status --json
  -> complete=true: 继续全量校验
  -> complete=false: 查看 missing_fields / invalid_fields -> 对话收集配置 -> 脱敏确认 -> python3 scripts/jumpserver_api/jms_diagnose.py config-write --payload '<json>' --confirm
```

说明：

- `missing_fields` 表示缺失的必需字段。
- `invalid_fields` 表示字段已提供，但格式或取值非法；当前至少会校验 `JMS_API_URL` 与 `JMS_TIMEOUT`。

### 4. 环境完整性

| 类别 | 变量 | 要求 | 说明 |
|---|---|---|---|
| 地址 | `JMS_API_URL` | 必需 | JumpServer 地址 |
| AK/SK 鉴权 | `JMS_ACCESS_KEY_ID`、`JMS_ACCESS_KEY_SECRET` | 与用户名密码二选一，且需成组完整 | API Access Key |
| 用户名密码鉴权 | `JMS_USERNAME`、`JMS_PASSWORD` | 与 AK/SK 二选一，且需成组完整 | JumpServer 登录凭据 |
| 组织 | `JMS_ORG_ID` | 初始可留空 | 业务执行前需通过 `select-org` 或保留组织特判写入 |
| 超时 | `JMS_TIMEOUT` | 可选 | 请求超时秒数 |
| TLS 校验 | `JMS_VERIFY_TLS` | 可选 | 默认 `false` |

### 5. 连通性进入检查

```text
python3 scripts/jumpserver_api/jms_diagnose.py ping
  -> 进入 query / diagnose / report
```

## 后续轻量校验

| 步骤 | 检查内容 | 通过标准 |
|---|---|---|
| 本地配置状态 | `python3 scripts/jumpserver_api/jms_diagnose.py config-status --json` | `complete=true` |
| 连通性 | `python3 scripts/jumpserver_api/jms_diagnose.py ping` | 返回可连接结果 |

## 组织选择与保留组织特判

| 条件 | 固定规则 |
|---|---|
| `JMS_ORG_ID` 已设置且可访问 | 直接把该值作为当前处理组织 |
| `JMS_ORG_ID` 已设置但不可访问 | 阻塞，要求重新 `select-org` |
| `JMS_ORG_ID` 为空，且可访问组织集合是 `{0002}` | 自动写入 `0002`，重新加载后继续 |
| `JMS_ORG_ID` 为空，且可访问组织集合是 `{0002,0004}` | 自动写入 `0002`，重新加载后继续 |
| `JMS_ORG_ID` 为空，且是其他组织集合 | 阻塞，返回 `candidate_orgs`，并通过 `user_message` / `action_hint` 要求先 `select-org` |
| 当前组织是 A，目标对象在 B | 不自动切换组织；返回跨组织阻塞信息 |

组织阻塞返回字段：

- `reason_code=organization_selection_required`
- `user_message`：明确要求先选择组织
- `action_hint`：返回 `select-org --org-id <org-id> --confirm` 的安全命令模板
- `candidate_org_count`：候选组织数量
- `org_selection_policy=required_before_query_when_multiple_accessible_orgs`

## 正式入口

| 入口 | 用途 |
|---|---|
| `python3 scripts/jumpserver_api/jms_diagnose.py config-status --json` | 查看当前本地配置状态 |
| `python3 scripts/jumpserver_api/jms_diagnose.py config-write --payload '<json>' --confirm` | 生成或覆盖本地 `.env` |
| `python3 scripts/jumpserver_api/jms_diagnose.py select-org --org-id <org-id> --confirm` | 显式选择组织并写回 `JMS_ORG_ID` |
| `python3 scripts/jumpserver_api/jms_query.py ...` | 对象查询、权限查询、审计查询的统一入口 |
| `python3 scripts/jumpserver_api/jms_diagnose.py ...` | 连通性、解析、访问分析、设置/许可证/报表/工单/存储查询、巡检与治理分析 |
| `python3 scripts/jumpserver_api/jms_report.py ...` | 模板化报告生成与契约检查 |
