# 权限与授权

## 快速概览

- 开始前先到 [runtime.md](runtime.md) 判断本次是“首次全量校验”还是“后续轻量校验”。
- 主入口：`python3 scripts/jms_permissions.py <subcommand> ...`
- 这份文档是账号别名规则和权限关系规则的唯一权威来源。
- `append` 适合单主体、单关系、范围明确的追加；`update/remove/delete` 属于高风险操作。
- 权限命令要求先有已选组织；未选组织时先 `select-org`，跨组织授权完全禁止，不自动切组织。
- 只有当环境组织集合恰好是 `{0002}` 或 `{0002,0004}` 时，运行时才会自动写入 `0002` 后继续。
- `list` 默认自动翻页拉全量；只有在 `--filters` 里显式传 `limit` / `offset` 时才按分页结果返回。

## 子命令与关系类型

### 子命令表

| 子命令 | 用途 | 是否需要 `--confirm` |
|---|---|---|
| `list` | 列出权限 | 否 |
| `get` | 查看权限详情 | 否 |
| `preview-create` | 预览创建 | 否 |
| `create` | 创建权限 | 否 |
| `preview-update` | 预览更新 | 否 |
| `update` | 更新权限 | 是 |
| `append` | 追加关系 | 否 |
| `preview-remove` | 预览移除关系 | 否 |
| `remove` | 移除关系 | 是 |
| `delete` | 删除权限 | 是 |

### 关系类型表

| 场景 | 参数 | 允许值 |
|---|---|---|
| `append` | `--relation` | `users`、`user-groups`、`assets`、`nodes` |
| `preview-remove` / `remove` | `--relation` | `user`、`user-group`、`asset`、`node` |

## 内置账号别名

| 中文输入 | 内部语义 | 是否查询资产账号 | 备注 |
|---|---|---|---|
| `手动账号` | `@INPUT` | 否 | JumpServer 内置账号语义 |
| `同名账号` | `@USER` | 否 | JumpServer 内置账号语义 |
| `匿名账号` | `@ANON` | 否 | JumpServer 内置账号语义 |
| `所有账号` | `@ALL` | 否 | JumpServer 内置账号语义 |
| `@SPEC` | 指定账号模式 | 否 | CLI 输出显示为 `指定账号` |

## 组合规则

| 输入形态 | 是否允许 | 备注 |
|---|---|---|
| `["@SPEC","root"]` | 允许 | 指定显式账号 |
| `["所有账号","手动账号","同名账号","匿名账号"]` | 允许 | 内置账号组合 |
| 显式账号 + 内置别名 | 允许 | 自动补 `@SPEC` |
| `["所有账号","root"]` | 不允许 | `所有账号` 不能和显式账号混用 |
| `["所有账号","@SPEC","root"]` | 不允许 | `所有账号` 不能和 `@SPEC` 混用 |
| `["所有账号","指定账号","root"]` | 不允许 | 中文 `指定账号` 不是输入语义 |
| `["排除账号"]` / `["无"]` | 不允许 | 当前不支持 |
| 账号 UUID | 不允许 | `accounts` 不是账号 ID 列表 |

## 关键约束

| 条件 | 规则 |
|---|---|
| 账号输入判定顺序 | 先识别 4 个内置别名，再处理普通 `username` |
| 命中内置别名 | 直接进入 payload，不做资产账号存在性校验 |
| 普通字符串 | 仅按显式账号 `username` 处理 |
| 混合输入 | 内置别名保留，显式账号补 `@SPEC` |
| 未选组织，且不属于 `{0002}` / `{0002,0004}` 特判环境 | `list`、`get`、`preview-create`、`create`、`preview-update`、`update`、`append`、`preview-remove`、`remove`、`delete` 全部直接阻塞，先 `select-org` |
| 环境组织集合恰好是 `{0002}` 或 `{0002,0004}` | 自动写入 `0002` 并继续，名称仍取运行时组织元数据 |
| `users` / `assets` / `nodes` / `user_groups` | 必须先确认对象属于当前 `effective_org` |
| 当前组织是 A，目标对象在 B | 直接阻塞，返回“跨组织授权已禁止；请先明确组织后重试” |
| 同名对象在多个组织都命中 | 返回 `candidate_orgs` 并停止，不默认选第一个 |
| `preview-remove` / `remove` | payload 必须带当前关系类型对应的单个 ID 字段 |
| `update` / `remove` / `delete` | 先预览，再补 `--confirm` |

## 组织安全边界

| 场景 | 处理方式 |
|---|---|
| `effective_org` 已明确，且目标对象也在该组织 | 允许继续执行预览或变更 |
| `effective_org` 已明确，但目标对象只在其他组织存在 | 阻塞，不自动切组织 |
| 当前处理组织是 A，目标授权对象组织是 B | 视为跨组织授权，直接禁止 |
| 用户或资产在多个组织都存在，且当前未选组织 | 阻塞，返回 `candidate_orgs`，要求用户先 `select-org` |
| 预览输出 | 必须包含 `effective_org`、`org_source`、`org_guard_status`；有组织歧义时补 `candidate_orgs` |
| 阻塞输出 | 如为跨组织场景，补充 `cross_org_block_reason` |

## 高频示例

预览复杂授权创建：

```bash
python3 scripts/jms_permissions.py preview-create --payload '{"name":"openclaw授权规则2","users":["<user-id>"],"assets":["<asset-id>"],"accounts":["@SPEC","root"],"actions":["connect","upload","download","copy","paste","delete","share"],"protocols":["all"],"is_active":true}'
```

使用中文内置账号别名：

```bash
python3 scripts/jms_permissions.py preview-create --payload '{"name":"openclaw授权规则3","users":["<user-id>"],"assets":["<asset-id>"],"accounts":["所有账号","手动账号","同名账号","匿名账号"],"actions":["connect"],"protocols":["all"],"is_active":true}'
```

追加用户到权限：

```bash
python3 scripts/jms_permissions.py append --permission-id <permission-id> --relation users --payload '{"users":["<user-id>"]}'
```

移除用户关系：

```bash
python3 scripts/jms_permissions.py preview-remove --permission-id <permission-id> --relation user --payload '{"user_id":"<user-id>"}'
python3 scripts/jms_permissions.py remove --permission-id <permission-id> --relation user --payload '{"user_id":"<user-id>"}' --confirm
```

未选组织时的预期行为：

```text
selection_required: true
org_guard_status: {
  "status": "blocked",
  "reason": "org_selection_required"
}
candidate_orgs: [ ... ]
next_step: python3 scripts/jms_diagnose.py select-org --org-id <org-id> --confirm
```

跨组织授权时的预期行为：

```text
effective_org: <A 组织>
cross_org_block_reason: 当前处理组织=A，目标对象组织=B，跨组织授权已禁止；请先明确组织后重试。
```

## 列表验证与计数

`jms_permissions.py` 的 CLI 输出是统一包装结构：

```json
{
  "ok": true,
  "result": [ ... ]
}
```

因此验证列表结果数量时，应统计 `result` 数组长度，而不是对外层对象直接做 `len()`。

默认自动翻页返回条数：

```bash
PYTHONPATH=.pydeps python3 scripts/jms_permissions.py list \
  | python3 -c 'import sys,json; data=json.load(sys.stdin); print(len(data["result"]))'
```

显式 `limit=1` 返回条数：

```bash
PYTHONPATH=.pydeps python3 scripts/jms_permissions.py list --filters '{"limit":1}' \
  | python3 -c 'import sys,json; data=json.load(sys.stdin); print(len(data["result"]))'
```

如果要确认真实请求是否携带分页参数，应检查最终 HTTP query string 中的 `limit` / `offset`，不要仅凭 CLI 包装后的输出对象做长度推断。
