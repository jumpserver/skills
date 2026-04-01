# 能力目录与优先级

## 快速概览

- 这份文档是 `inspect/analyze + capability` 能力单元的人类索引。
- 机器可执行的能力元数据位于 `references/metadata/capabilities.json`，由 `scripts/jumpserver_api/jms_capabilities.py` 负责加载。
- 当前共维护 `67` 个能力单元，其中 `P0=5`、`P1=54`、`P2=8`。
- 每个能力单元都在元数据里固定维护以下字段：
  - 功能名称
  - 能力分类
  - 触发描述
  - 用户常见提问示例
  - 对应 API 接口
  - 使用的脚本文件
  - 输入参数
  - 返回结果摘要方式
  - 异常处理建议
  - 能力属性（核心能力 / 专项能力）

## 使用规则

- `jms_query.py audit-analyze --capability <capability-id>` 负责审计、调查、行为分析类能力。
- `jms_diagnose.py inspect --capability <capability-id>` 负责治理、统计、巡检、配置类能力。
- 当用户问题天然跨多个接口时，优先使用能力单元，而不是手工拼接多个 `list/get`。
- 当结果过多时，能力单元应优先返回统计摘要、Top 排行和样本记录。
- inventory 未明确的接口或字段，不在这里硬写成“已确认能力”；相关事项统一标记为“待确认”。

## P0

| capability_id | 功能名称 | 分类 | 正式入口 | 覆盖属性 |
|---|---|---|---|---|
| `command-record-query` | 命令记录查询 | 日志与审计类 | `jms_query.py audit-analyze` | 核心能力 |
| `session-record-query` | 会话记录查询 | 日志与审计类 | `jms_query.py audit-analyze` | 核心能力 |
| `asset-list-query` | 资产列表查询 | 资产治理类 | `jms_diagnose.py inspect` | 核心能力 |
| `account-list-query` | 账号列表查询 | 账号治理类 | `jms_diagnose.py inspect` | 核心能力 |
| `system-settings-overview` | 系统设置总览 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |

## P1

| capability_id | 功能名称 | 分类 | 正式入口 | 覆盖属性 |
|---|---|---|---|---|
| `file-transfer-log-query` | 文件传输日志查询 | 日志与审计类 | `jms_query.py audit-analyze` | 专项能力 |
| `high-risk-command-audit` | 高危命令审计 | 日志与审计类 | `jms_query.py audit-analyze` | 专项能力 |
| `sensitive-asset-access-audit` | 敏感资产访问审计 | 日志与审计类 | `jms_query.py audit-analyze` | 专项能力 |
| `abnormal-hours-login-query` | 异常时间段登录查询 | 日志与审计类 | `jms_query.py audit-analyze` | 专项能力 |
| `abnormal-source-ip-login-query` | 异常来源 IP 登录查询 | 日志与审计类 | `jms_query.py audit-analyze` | 专项能力 |
| `failed-login-statistics` | 多次失败登录统计 | 日志与审计类 | `jms_query.py audit-analyze` | 专项能力 |
| `privileged-account-usage-audit` | 特权账号使用审计 | 日志与审计类 | `jms_query.py audit-analyze` | 专项能力 |
| `file-transfer-risk-audit` | 文件上传/下载风险审计 | 日志与审计类 | `jms_query.py audit-analyze` | 专项能力 |
| `account-activity-overview` | 账号活跃情况 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `asset-activity-overview` | 资产活跃情况 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `asset-type-distribution` | 资产类型占比 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `asset-login-ranking` | 登录资产排名 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `account-template-list` | 账号模板列表 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `asset-login-trend` | 近 7 天/30 天资产登录趋势 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `protocol-usage-distribution` | 协议使用分布 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `uncategorized-assets-query` | 未分类资产查询 | 资产治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `assets-without-valid-account-template` | 无有效账号模板的资产 | 资产治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `duplicate-asset-name-query` | 重复命名资产查询 | 资产治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `offline-disabled-assets-statistics` | 离线/禁用资产统计 | 资产治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `node-asset-distribution` | 按节点统计资产数量 | 资产治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `expired-account-query` | 失效账号查询 | 账号治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `long-time-unused-accounts` | 长期未使用账号 | 账号治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `high-privilege-account-list` | 高权限账号清单 | 账号治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `accounts-without-template` | 未绑定模板的账号 | 账号治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `account-asset-bindings` | 账号与资产绑定关系查询 | 账号治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `session-behavior-statistics` | 会话行为统计 | 会话与行为分析类 | `jms_query.py audit-analyze` | 专项能力 |
| `frequent-operation-user-ranking` | 高频操作用户排行 | 会话与行为分析类 | `jms_query.py audit-analyze` | 专项能力 |
| `suspicious-operation-summary` | 可疑操作行为汇总 | 会话与行为分析类 | `jms_query.py audit-analyze` | 专项能力 |
| `security-policy-check` | 安全策略配置检查 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `mfa-config-check` | MFA 配置检查 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `auth-source-config-check` | LDAP / OIDC / SAML 等认证源配置检查 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `notification-config-check` | 通知配置检查 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `ticket-approval-config-check` | 工单/审批配置检查 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `recent-active-users-ranking` | 最近活跃用户排行 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `recent-active-assets-ranking` | 最近活跃资产排行 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `hot-assets-ranking` | 热门资产排行 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `session-duration-ranking` | 会话时长排行 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `file-transfer-heavy-ranking` | 文件传输最多的用户/资产 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `platform-usage-distribution` | 平台或资产类型使用分布 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `long-time-unlogged-assets` | 长时间未登录资产 | 资产治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `long-time-unused-assets` | 长时间未使用资产 | 资产治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `shared-account-usage` | 共享账号使用情况 | 账号治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `privileged-account-activity` | 特权账号活跃情况 | 账号治理类 | `jms_diagnose.py inspect` | 专项能力 |
| `user-session-analysis` | 用户维度会话分析 | 会话与行为分析类 | `jms_query.py audit-analyze` | 专项能力 |
| `asset-session-analysis` | 资产维度会话分析 | 会话与行为分析类 | `jms_query.py audit-analyze` | 专项能力 |
| `login-auth-config-check` | 登录认证配置检查 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `audit-retention-check` | 审计日志保存配置检查 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `setting-category-query` | 系统设置分类查询 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `license-detail-query` | 许可证详情查询 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `ticket-list-query` | 工单列表查询 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `command-storage-query` | 命令存储查询 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `replay-storage-query` | 录像存储查询 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `report-query` | 统计报告查询 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `account-automation-overview` | 账号自动化与风险概览 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |

## P2

| capability_id | 功能名称 | 分类 | 正式入口 | 覆盖属性 |
|---|---|---|---|---|
| `terminal-access-policy-check` | 终端接入策略检查 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `org-resource-overview` | 组织/节点维度资源统计 | 组织/节点维度统计类 | `jms_diagnose.py inspect` | 专项能力 |
| `role-binding-overview` | 权限与授权关系查询 | 权限与授权关系查询类 | `jms_diagnose.py inspect` | 专项能力 |
| `cold-assets-ranking` | 冷门资产排行 | 活跃与统计分析类 | `jms_diagnose.py inspect` | 专项能力 |
| `platform-access-config-query` | 平台接入配置查询 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `account-template-config-query` | 账号模板配置查询 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `asset-platform-config-query` | 资产平台配置查询 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |
| `terminal-component-query` | 终端组件列表查询 | 系统设置与配置巡检类 | `jms_diagnose.py inspect` | 专项能力 |

## 待确认项

- `失效账号查询` 当前以 `/api/v1/users/users/` 为准输出 JumpServer 用户账号；资产账号失效字段在 inventory 中未形成统一语义，暂不臆造。
- `permissions` 与 `user-asset-access` 依赖 `/api/v1/perms/asset-permissions/` 的实际可用性；`user-assets` / `user-nodes` 直接依赖 `/api/v1/perms/users/{user_id}/assets|nodes/` 的 effective access 接口。
- 系统设置类能力统一基于 `/api/v1/settings/setting/` 做键值切片；具体键名因环境配置差异可能不同，脚本会保留原始键值并提示人工复核。
