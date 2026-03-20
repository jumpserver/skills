# 2026-03-19 验证结论：`jms_permissions.py list` 自动翻页

## 结论

- `jms_permissions.py list` 在未显式传 `limit` / `offset` 时，会自动按页拉取并聚合结果。
- `jms_permissions.py list --filters '{"limit":1}'` 不会触发自动翻页。
- 真实 JumpServer 接口对 `limit=1` 生效，返回结果长度为 1。

## 已验证内容

### 1. 本地逻辑验证（stub）

通过替换 `run_request()` 的本地 stub 验证：

- 显式 `limit=1` 时：只发 1 次请求
- 默认无 `limit/offset` 时：按 `200 / 200 / 50` 发 3 次请求并聚合

### 2. 真实环境验证

使用当前 `.env.local` 配置和真实 JumpServer 环境验证：

- `python3 scripts/jms_diagnose.py config-status --json` 返回 `complete=true`
- `python3 scripts/jms_permissions.py --help` 正常
- `python3 scripts/jms_permissions.py list --filters '{"limit":1}'` 请求已携带：
  - `limit=1`
  - `offset=0`
- SDK 解析后的 `result` 长度为 1

## 注意事项

之前曾出现“`limit=1` 仍返回 2 条”的误判，原因不是服务端分页失效，而是错误地统计了 CLI 外层 JSON 包装对象的键数量：

```json
{
  "ok": true,
  "result": [ ... ]
}
```

对整个对象执行 `len(data)` 会得到 `2`（`ok` 和 `result` 两个键），而不是结果列表长度。

正确做法应统计 `data["result"]` 的长度。

## 推荐验证命令

统计默认列表返回条数：

```bash
PYTHONPATH=.pydeps python3 scripts/jms_permissions.py list \
  | python3 -c 'import sys,json; data=json.load(sys.stdin); print(len(data["result"]))'
```

统计显式 `limit=1` 的返回条数：

```bash
PYTHONPATH=.pydeps python3 scripts/jms_permissions.py list --filters '{"limit":1}' \
  | python3 -c 'import sys,json; data=json.load(sys.stdin); print(len(data["result"]))'
```
