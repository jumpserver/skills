# 故障排查

## 快速概览

- 优先按“判断当前是首次全量还是后续轻量 -> 环境 -> 连通性 -> 对象解析 -> 预览 -> 审计”顺序排查。
- 这份文档只保留错误速查和最小排查路径。
- 环境与入口问题看 [runtime.md](runtime.md)；资源与标准流程看 [assets.md](assets.md)。

## 报错速查

| 报错文本 | 常见原因 | 优先动作 |
|---|---|---|
| `python3: command not found` / 无可用 Python 3 | 本机未安装 Python 3，或命令名不对 | 回到 [runtime.md](runtime.md) 的 Python 3 检查，先安装并确认可执行命令 |
| `No module named jms_client` | `jumpserver-sdk-python` 未安装或当前解释器环境不对 | 回到 [runtime.md](runtime.md) 的 SDK 检查与安装 |
| `.env.local` 缺失，或 `JMS_API_URL or JMS_WEB_URL is required.` | 本地配置未初始化，或地址变量没配置 | 先执行 `python3 scripts/jms_diagnose.py config-status --json`，再回到 [runtime.md](runtime.md) 的交互式初始化流程 |
| `Invalid JSON payload: ...` | `--payload` 或 `--filters` 不是合法 JSON | 检查引号、逗号和花括号 |
| `JSON payload must be an object.` | 传入了数组、字符串或其他非对象类型 | 改成 JSON 对象 |
| `This action requires --confirm after the change preview is reviewed.` | 执行了受保护变更但没有带 `--confirm` | 先预览，再补 `--confirm` |
| `--need-update-password requires --password.` | 用户改密时只传了强制改密标志 | 同时补上 `--password` |
| `Create password options are only supported for --resource user.` | 对非用户资源错误地传了密码参数 | 只在 `--resource user` 下使用 |
| `User create password fields must use --password/--need-update-password, not --payload.` | 把密码字段塞进了 JSON payload | 把密码相关字段移到 CLI 参数 |
| `User update requires --payload, --password, or both.` | 用户更新时没有提供任何变更内容 | 至少提供密码或 JSON patch |
| `asset update requires --payload.` | 非用户资源更新未传 `--payload` | 补上 JSON patch |
| `Provide either JMS_ACCESS_KEY_ID/JMS_ACCESS_KEY_SECRET or JMS_USERNAME/JMS_PASSWORD ...` | 缺少鉴权信息 | 补齐 AK/SK 或用户名密码 |
| `SyntaxError: invalid syntax` 且文件名类似 `tmp/create_user_final.py` | 走错执行路径，拼了临时 SDK 脚本 | 直接改回正式 `jms_*.py` 标准流程 |
| 用户创建成功但角色设置失败 | 把用户创建和角色设置拆成了两段 | 同一次创建请求里附带角色 |
| `create-user` 失败，提示用户名/邮箱/名称已存在 | 默认只做了 `username` 预查，剩余冲突在创建阶段暴露 | 保持平衡版流程，再按需补严格查重 |
| 把 `手动账号` / `同名账号` / `匿名账号` / `所有账号` 当普通账号查询 | 内置账号别名判断顺序错误 | 回到 [permissions.md](permissions.md) 的别名归一化流程 |
| 服务端对象不存在 / `object_does_not_exist` | ID 错误、组织错误或对象已删除 | 先重新 `list/get/resolve` |

## 轻量失败后的升级动作

| 轻量校验失败点 | 升级动作 |
|---|---|
| `jms_diagnose.py ping` 失败 | 立即回到 [runtime.md](runtime.md) 执行首次全量校验 |
| 缺关键环境变量 | 立即回到 [runtime.md](runtime.md) 的环境完整性检查 |
| `No module named jms_client` | 立即回到 [runtime.md](runtime.md) 的 SDK 检查与安装 |
| Python 3 不可用 | 立即回到 [runtime.md](runtime.md) 的 Python 3 检查 |

## 最小排查流程

```text
判断当前是首次全量失败还是后续轻量失败
  -> 若为轻量失败，先升级到全量校验
  -> 检查 Python 3 和 jumpserver-sdk-python
  -> 执行 config-status --json
  -> 按需加载 env.sh 或等价环境
  -> 检查环境变量
  -> jms_diagnose.py ping
  -> 精确解析对象
  -> 预览当前变更
  -> 必要时查看审计
```

## 常见误用

| 误用 | 正确做法 |
|---|---|
| 为标准流程写临时 SDK Python 文件 | 回到正式 `jms_*.py` |
| 用模糊名称直接变更对象 | 先解析为精确对象或 ID |
| 用本地权限展开代替服务端可访问范围 | 优先用 `diagnose user-assets/user-nodes` |
| 在权限创建里查找内置账号别名 | 直接按别名规则写 payload |
| 跳过 preview 直接更新/删除 | 先走 `preview-*` |
