---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'ccf8a2fb-1666-41b0-a602-5895977e9a1d'
  PropagateID: 'ccf8a2fb-1666-41b0-a602-5895977e9a1d'
  ReservedCode1: '739bce11-79e0-4e22-ba0d-9f001090a97a'
  ReservedCode2: '739bce11-79e0-4e22-ba0d-9f001090a97a'
---

# AI 助手模块技术设计方案

> 基于 `agent.md` 设计文档，适配到 gift_bookkeeping_app 项目（Flask + SQLAlchemy + Jinja2 + Bootstrap 5 架构）。

---

## 1. 架构概览

### 1.1 技术栈适配说明

| 层级 | agent.md 原设计 | 本项目适配 |
|------|----------------|-----------|
| 后端框架 | Django 4.x + DRF | Flask 3.0 + Flask-SQLAlchemy |
| 前端 | React 18 + TS + Vite | Jinja2 + Bootstrap 5 + 原生 JS |
| 认证 | JWT (SimpleJWT) | Flask-Login (session) |
| 数据库 | SQLite (Django ORM) | SQLite (SQLAlchemy) |
| 状态管理 | Zustand + persist | localStorage (原生 JS) |
| AI 接入 | OpenAI Python SDK | OpenAI Python SDK |
| 联网搜索 | DuckDuckGo Search | DuckDuckGo Search |

### 1.2 模块架构图

```
gift_bookkeeping_app/
├── models.py                   # 新增 AI 相关数据模型
├── ai_service.py               # [新增] AI 核心服务层
├── web_search.py               # [新增] 联网搜索模块
├── routes_ai.py                # [新增] AI 助手路由
├── routes_ext.py               # 已有扩展路由（注册 routes_ai）
├── app.py                      # 数据库迁移 SQL 追加
├── templates/
│   ├── ai_assistant.html       # [新增] AI 聊天主页面
│   └── admin_ai_config.html    # [新增] 管理员 AI 配置页面
├── static/
│   └── ai_assistant.js         # [新增] AI 助手前端交互逻辑
└── requirements.txt            # 追加 openai、duckduckgo_search 依赖
```

---

## 2. 数据库设计

### 2.1 ER 图

```
┌──────────────────────────┐
│         users             │
├──────────────────────────┤
│ id (PK)                   │
│ username                   │
│ ... (已有字段)             │
│ ai_api_key (VARCHAR 255)  │  ← 旧版单配置（向后兼容）
│ ai_base_url (VARCHAR 255) │
│ ai_model (VARCHAR 100)    │
│ ai_configs (TEXT/JSON)    │  ← 多配置列表 JSON
│ ai_authorized (BOOL)      │  ← AI 使用授权标记
└─────────┬────────────────┘
          │ 1:N
          │
    ┌─────┴──────────┐
    │                 │
    ▼                 ▼
┌──────────────┐  ┌────────────────────┐
│ chat_sessions │  │   ai_query_logs    │
├──────────────┤  ├────────────────────┤
│ id (PK)       │  │ id (PK)             │
│ user_id (FK)  │  │ user_id (FK→users)  │
│ title          │  │ session_id (VARCHAR) │
│ created_at     │  │ query_type          │
│ updated_at     │  │ query_text          │
└───┬──────────┘  │ response_text       │
    │ 1:N          │ response_time_ms    │
    │              │ created_at          │
    ▼              └────────────────────┘
┌──────────────────┐
│  chat_messages    │
├──────────────────┤
│ id (PK)           │
│ session_id (FK)   │
│ role (user/ai)    │
│ content (TEXT)    │
│ used_config_name  │
│ used_search (BOOL)│
│ error_hint (TEXT) │
│ created_at        │
└──────────────────┘
```

### 2.2 新增字段说明

#### User 模型追加字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ai_api_key` | VARCHAR(255) | "" | 旧版单配置 API Key（向后兼容） |
| `ai_base_url` | VARCHAR(255) | "" | 旧版单配置 Base URL |
| `ai_model` | VARCHAR(100) | "" | 旧版单配置 Model |
| `ai_configs` | TEXT | "[]" | JSON 数组：`[{name, api_key, base_url, model, enabled}]` |
| `ai_authorized` | Boolean | False | 是否被管理员授权使用 AI |

#### ChatSession 模型（新表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| user_id | FK → users.id | 所属用户（CASCADE 删除） |
| title | VARCHAR(100) | 会话标题 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

#### ChatMessage 模型（新表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| session_id | FK → chat_sessions.id | 所属会话（CASCADE 删除） |
| role | VARCHAR(10) | "user" 或 "ai" |
| content | Text | 消息内容 |
| used_config_name | VARCHAR(100) | 使用的 AI 配置名 |
| used_search | Boolean | 是否使用了联网搜索 |
| error_hint | Text | 错误提示 |
| created_at | DateTime | 创建时间 |

#### AIQueryLog 模型（新表，旧版兼容）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| user_id | FK → users.id | 所属用户（SET_NULL） |
| session_id | VARCHAR(100) | 会话标识 |
| query_type | VARCHAR(20) | 查询类型 |
| query_text | Text | 用户提问 |
| response_text | Text | AI 回复 |
| response_time_ms | Integer | 响应毫秒数 |
| created_at | DateTime | 创建时间 |

---

## 3. 后端核心服务层

### 3.1 ai_service.py 核心函数

```
ai_chat(query, user)
  ├─ needs_search(query)           → 判断是否需要联网
  ├─ search_and_summarize(query)    → DuckDuckGo 搜索
  ├─ _build_config_list(user)       → 构建 AI 配置优先级列表
  ├─ _call_openai(prompt, cfg)     → 逐个尝试配置
  └─ _local_question(query)        → 全部失败时的本地兜底
```

### 3.2 AI 配置优先级体系

```
第1优先级：用户多配置 (user.ai_configs 中 enabled=True 的条目)
第2优先级：用户旧版单配置 (user.ai_api_key)
第3优先级：全局配置 (环境变量 OPENAI_API_KEY)
第4优先级：管理员共享配置（仅当用户无配置 + ai_authorized=True + 非管理员时）
```

### 3.3 联网搜索触发条件

正则匹配关键词：天气、新闻、最新、现在、股价、汇率、节假日等

---

## 4. API 接口定义

### 4.1 AI 聊天

```
POST /api/ai/chat
Auth: Login + (ai_authorized or is_admin)
Body: { "query": "用户问题", "session_id": 123 (可选) }
Response: {
  "code": 200,
  "data": {
    "query": "...",
    "response": "AI回复",
    "used_openai": true/false,
    "used_config_name": "配置名",
    "used_search": true/false,
    "latency_ms": 500,
    "suggestions": ["推荐问题1", ...],
    "error_hint": "",
    "session_id": 123,
    "session_title": "会话标题"
  }
}
```

### 4.2 会话管理

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/ai/sessions | Login | 获取会话列表 |
| GET | /api/ai/sessions/{id} | Login | 获取会话详情（含消息） |
| POST | /api/ai/sessions/create | Login | 创建新会话 |
| PATCH | /api/ai/sessions/{id}/rename | Login | 重命名会话 |
| DELETE | /api/ai/sessions/{id}/delete | Login | 删除会话 |

### 4.3 AI 配置管理（仅管理员）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/ai/config | Admin | 获取 AI 配置 |
| PUT | /api/ai/config | Admin | 更新 AI 配置 |

### 4.4 AI 授权管理（仅管理员）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/ai/auth-list | Admin | 获取用户授权列表 |
| POST | /api/ai/auth-toggle | Admin | 切换用户授权 |

### 4.5 AI 推荐问题

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/ai/suggestions | Login | 获取推荐问题 |

### 4.6 页面路由

| 路径 | 权限 | 说明 |
|------|------|------|
| /ai-assistant | Login + Authorized | AI 聊天页面 |
| /admin/ai-config | Admin | AI 配置管理页面 |

---

## 5. 前端页面设计

### 5.1 AI 聊天页面 (ai_assistant.html)

```
┌──────────────────────────────────────────────┐
│  侧边栏(可折叠)  │  对话区                      │
│  ┌────────────┐  │  ┌──────────────────────┐  │
│  │ 新建会话    │  │  │ AI 助手标题           │  │
│  │ ─────────  │  │  │ ───────────────────  │  │
│  │ 会话1 [选中]│  │  │ 消息气泡区(滚动)      │  │
│  │ 会话2      │  │  │ user消息(右对齐)      │  │
│  │ 会话3      │  │  │ ai消息(左对齐+头像)   │  │
│  │ ...        │  │  │ loading动画           │  │
│  └────────────┘  │  └──────────────────────┘  │
│                  │  输入框 + 发送按钮           │
│                  │  "AI回答仅供参考"            │
└──────────────────────────────────────────────┘
```

### 5.2 AI 配置页面 (admin_ai_config.html)

- 多配置卡片列表（名称、API Key 密码框+显隐切换、Base URL、Model、启用开关）
- 支持上下移动调整优先级
- 支持删除/添加配置
- AI 授权管理面板（勾选/取消普通用户授权）

---

## 6. 权限体系

### 6.1 认证与授权矩阵

| 功能 | 管理员 | 被授权用户 | 未授权用户 |
|------|--------|-----------|-----------|
| AI 配置管理 | 完整访问 | 不可访问 | 不可访问 |
| AI 授权管理 | 完整访问 | 不可访问 | 不可访问 |
| AI 聊天 | 可用 | 可用（共享管理员配置） | 不可见 |
| 会话管理 | 管理自己的 | 管理自己的 | 不可用 |

### 6.2 安全边界

- API Key 使用 AES-256-GCM 加密存储（复用项目已有 `encrypt_credential`/`decrypt_credential`）
- 前端配置页面 API Key 输入框 `type="password"`，支持显隐切换
- 被授权用户无法查看管理员配置内容，仅能间接使用
- 全局配置（环境变量）不暴露 key 明文，仅返回 `has_global_key` 布尔值

---

## 7. 实现步骤

1. **更新 `requirements.txt`**：追加 `openai`、`duckduckgo_search` 依赖
2. **更新 `models.py`**：User 模型追加 AI 字段 + 新增 ChatSession/ChatMessage/AIQueryLog 模型
3. **更新 `app.py`**：在 `init_database()` 中追加 AI 相关表的迁移 SQL
4. **新增 `web_search.py`**：联网搜索模块
5. **新增 `ai_service.py`**：AI 核心服务层
6. **新增 `routes_ai.py`**：AI 助手路由
7. **更新 `routes_ext.py`**：注册 AI 路由
8. **新增 `templates/ai_assistant.html`**：AI 聊天页面
9. **新增 `templates/admin_ai_config.html`**：管理员 AI 配置页面
10. **新增 `static/ai_assistant.js`**：前端交互逻辑
11. **更新 `templates/base.html`**：导航栏追加 AI 助手入口
12. **数据库迁移与验证**

> AI生成

---

## 第十章 V3 修复与优化（2026-09-10）

### 10.1 权限工单撤销功能
- 新增 `permission_ticket_revoke` 路由（POST `/permission_tickets/<id>/revoke`），管理员可撤销已批准的工单
- 撤销时从 `user.allowed_menus` 移除该工单 `granted_menus` 中的菜单项，工单状态改为 `revoked`
- `PermissionTicket.status` 新增 `revoked` 状态值（pending/approved/rejected/revoked）
- `permission_tickets.html` 已批准工单增加撤销按钮和确认 Modal
- 工单列表状态过滤支持 `revoked`

### 10.2 WebDAV 备份文件删除 + 恢复 500 修复
- `webdav_utils.py` 新增 `delete_webdav_backup` 函数（HTTP DELETE 删除指定备份文件）
- `routes_ext.py` 新增 `admin_delete_webdav_backup` 路由（POST `/admin/backups/delete`），支持单文件和批量删除
- `admin_backups.html` 备份列表增加复选框列、全选、批量删除按钮、单行删除按钮
- 恢复路由 `admin_restore_webdav_backup` 增加 try-except 错误处理，修复 500 错误
- 修复 delete 路由 `request.get_json()` 运算符优先级 bug：改为先判断 `request.is_json` 再安全调用

### 10.3 加密密码回显 + 定时任务加密
- `admin_backups.html` 加密密码区域增加"已设置/未设置"徽章（基于 `has_encrypt_password` 布尔值回显）
- 定时任务 Modal 新增 `encrypt_enabled` 复选框（仅当全局加密密码已配置时显示）
- `admin_save_scheduled_task` 路由新增读取 `encrypt_enabled` 参数
- 定时备份执行时根据 `encrypt_enabled` 标志决定是否加密

### 10.4 定时任务执行人 + 执行历史
- `models.py` 新增 `ScheduledTaskExecutionLog` 模型（task_id, start_time, end_time, status, output_log, executed_by）
- `ScheduledBackupTask` 新增 `created_by` 字段 + `creator` relationship
- `_backup_scheduler_worker` 每次执行创建执行日志记录（running → success/failed）
- `admin_backups.html` 定时任务列表增加"创建人"列和"执行历史"按钮
- 新增 `admin_get_execution_logs` 路由（GET `/admin/backups/scheduled_tasks/<id>/execution_logs`）

### 10.5 附件上传到 WebDAV
- `admin_upload_attachment` 路由在本地保存后调用 `upload_file_to_webdav` 上传到 WebDAV `attachments/` 子目录
- WebDAV 上传失败不阻断本地保存，记录 warning 日志

### 10.6 Webhook 凭证校验 AJAX 化
- `admin_create_webhook` 和 `admin_edit_webhook` 路由改为兼容 AJAX（检测 `X-Requested-With` header）
- 校验失败返回 `jsonify` 错误信息而非重定向页面
- `admin_webhooks.html` 表单提交改为 `e.preventDefault()` + `submitWebhookFormAjax` 函数
- Modal 内新增错误提示容器（`newWebhookError`/`editWebhookError`），校验失败就地显示红色 alert

### 10.7 多用户 WebDAV 配置/定时任务隔离
- `BackupConfig` 新增 `user_id` 字段（关联 users.id）和 `allow_view_others_tasks` 字段
- `get_config(user_id)` 改为按用户查询：NULL=管理员全局配置，非 NULL=用户私有配置（自动复制全局配置作为副本）
- 所有备份路由改为 `BackupConfig.get_config(None if current_user.is_admin else current_user.id)`
- 定时任务 CRUD 按 `created_by` 过滤，普通用户只能操作自己的任务
- `admin_backups.html` 普通用户区域从只读卡片改为可编辑自己的私有 WebDAV 配置表单
- 管理员配置区增加"允许普通用户查看他人任务"复选框

### 10.8 备份文件权限控制
- 备份文件名格式改为 `{timestamp}_{username}_{type}.db`（如 `20260910_142300_admin_db_backup.db`）
- `admin_backups_list_ajax` 解析文件名中的用户标识，返回 `created_by`、`can_restore`、`can_delete` 字段
- `admin_backups.html` 备份列表增加"创建者"列，恢复/删除按钮按权限启用/禁用
- `admin_restore_webdav_backup` 增加权限判断（仅管理员或创建者可恢复）

### 10.9 AI 授权同步到用户管理页面
- `app.py` 的 `admin_update_user_permissions` 路由新增读取 `ai_authorized` 参数
- `app.py` 的 `admin_batch_user_permissions` 路由新增批量 AI 授权
- `admin_users.html` 权限配置 Modal 新增 AI 授权 checkbox
- `admin_users.html` 批量权限配置 Modal 新增 AI 授权 checkbox

### 10.10 数据模型变更
- `BackupConfig` 新增 `user_id`（Integer, nullable）、`allow_view_others_tasks`（Boolean, default=0）
- `ScheduledBackupTask` 新增 `created_by`（Integer, FK users.id, nullable）
- 新增 `ScheduledTaskExecutionLog` 模型：id, task_id(FK), start_time, end_time, status, output_log(Text), executed_by
- `PermissionTicket.status` 新增 `revoked` 状态值
- 迁移 SQL 已追加到 app.py migration_sqls 列表

### 10.11 涉及文件
- `models.py` — 数据模型修改（BackupConfig/ScheduledBackupTask/ScheduledTaskExecutionLog/PermissionTicket）
- `app.py` — 迁移 SQL + 用户权限路由（ai_authorized）
- `webdav_utils.py` — 新增 delete_webdav_backup 函数
- `routes_ext.py` — 全部 9 项问题的后端路由修改
- `templates/admin_backups.html` — 备份管理页面全面改造
- `templates/admin_webhooks.html` — Webhook 页面 AJAX 化
- `templates/permission_tickets.html` — 工单页面撤销功能
- `templates/admin_users.html` — 用户管理页面 AI 授权

> AI生成

---

## 8. 综合增强功能（feature/ai-assistant 分支）

> 以下功能在 AI 助手模块基础上同步开发，共同构成 feature/ai-assistant 分支的完整功能集。

---

### 8.1 Webhook 推送修复与增强

#### 概述

对 Webhook 通知系统进行全面增强：支持页面级推送过滤、自定义消息模板、敏感页面内容脱敏、扩展事件类型。

#### 新增字段（WebhookConfig 模型）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `notify_on_update` | Boolean | False | 修改/更新操作通知 |
| `notify_on_security` | Boolean | False | 安全相关操作通知 |
| `notify_on_system` | Boolean | False | 系统配置变更通知 |
| `notify_on_status_change` | Boolean | False | 状态变更通知 |
| `notify_pages` | Text | `'{}'` | JSON：页面推送矩阵 `{event_category: [page_keys]}` |
| `message_templates` | Text | `'{}'` | JSON：自定义消息模板 |

#### 页面推送矩阵

前端提供 14 个页面 checkbox（全选/清空按钮），提交时通过 JS `assembleNotifyPages()` 将选中项组装为 JSON 并填入隐藏字段 `notify_pages`，后端直接读取该 JSON 存储。

后端 `_page_matches()` 在 `trigger_webhook_event()` 调用时检查当前页面是否在 Webhook 配置的允许列表中，未匹配则跳过推送。

#### 敏感页面脱敏

`SENSITIVE_PAGES` 集合定义需脱敏的页面（如 `admin_users`、`admin_backups`、`security`），`_sanitize_details()` 对推送内容进行脱敏处理，仅保留操作人和操作类型，不泄露具体数据。

#### 涉及文件

- `webhook_utils.py` — `trigger_webhook_event()` 重写，支持页面过滤/脱敏/模板
- `routes_ext.py` — Webhook CRUD 路由处理扩展字段
- `templates/admin_webhooks.html` — 扩展事件开关 + 页面推送矩阵 + 编辑回填
- `app.py` / `routes_ext.py` / `routes_ai.py` — 全项目约 40 处 webhook 推送补全

---

### 8.2 纪念日删除 Bug 修复

#### 问题

`templates/reminders.html` 中删除表单嵌套在另一个表单内，导致 HTML 规范不允许的嵌套 `<form>`，提交时删除操作的 CSRF token 和记录 ID 丢失。

#### 修复

改为 JS 动态创建外部独立表单提交删除请求，避免 form 嵌套问题。

---

### 8.3 数据模型扩展

#### User 模型新增字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `backup_authorized` | Boolean | False | 备份功能授权标记 |
| `allowed_menus` | String(256) | `''`（空） | 允许访问的菜单列表（逗号分隔），空=无权限 |

新增方法 `can_use_backup()` — 返回 `backup_authorized` 布尔值
新增方法 `can_access_menu(menu_key)` — 检查 `allowed_menus` 是否包含指定菜单

#### BackupConfig 模型新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `_backup_encrypt_password` | String(512) | AES-256-GCM 密文存储的备份加密密码 |

通过 property `backup_encrypt_password` setter/getter 自动加解密。

#### 新增数据表

**ScheduledBackupTask（定时备份任务）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| name | String(100) | 任务名称 |
| cron_expr | String(50) | Cron 表达式（默认 `0 2 * * *`） |
| is_enabled | Boolean | 是否启用 |
| encrypt_enabled | Boolean | 是否使用加密 |
| last_run_time | DateTime | 最近执行时间 |
| last_run_status | String(255) | 最近执行状态 |
| created_at / updated_at | DateTime | 时间戳 |

**BackupAttachment（备份附件）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| filename | String(255) | 文件名 |
| file_size | Integer | 文件大小 |
| file_type | String(50) | MIME 类型 |
| is_encrypted | Boolean | 是否加密 |
| uploaded_by | FK → users.id | 上传者 |
| storage_path | String(500) | 存储路径 |
| created_at | DateTime | 创建时间 |

**PermissionTicket（权限申请工单）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增主键 |
| user_id | FK → users.id | 申请用户 |
| requested_menus | String(256) | 申请的菜单列表（逗号分隔） |
| reason | Text | 申请理由 |
| status | String(20) | pending / approved / rejected |
| reviewed_by | FK → users.id | 审批人 |
| reviewed_at | DateTime | 审批时间 |
| review_comment | Text | 审批备注 |
| granted_menus | String(256) | 实际批准的菜单列表 |
| created_at / updated_at | DateTime | 时间戳 |

---

### 8.4 工单审批流程

#### 流程说明

```
新用户注册 → 默认无菜单权限（allowed_menus 为空）
    ↓
用户提交权限申请工单（选择需要申请的菜单 + 填写理由）
    ↓
管理员在工单管理页面查看 → 审批通过/驳回
    ↓
审批通过：管理员勾选的菜单项写入用户 allowed_menus
审批驳回：工单标记为 rejected，附驳回理由
```

#### 可申请菜单

`TICKET_MENU_OPTIONS`：ledger（礼金账本）、banquets（专属宴席）、reconciliation（人情对账）、reminders（纪念日备忘）、recycle_bin（回收站）

#### API 路由

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /permission-tickets | Login | 工单管理页面 |
| POST | /permission-tickets/create | Login | 提交权限申请 |
| POST | /permission-tickets/{id}/approve | Admin | 审批通过 |
| POST | /permission-tickets/{id}/reject | Admin | 驳回申请 |

#### 涉及文件

- `routes_ext.py` — 4 个工单路由
- `templates/permission_tickets.html` — 工单管理页面（管理员审批/驳回 + 普通用户申请）
- `templates/base.html` — 导航栏：管理员「权限审批」入口 + 普通用户「权限申请」入口
- `templates/index.html` — 无权限提示卡片

---

### 8.5 加密与备份功能

#### 加密方案

- 使用 `pyzipper` 库实现 AES-256 加密 zip
- **自动任务**：使用管理员预设的加密密码（`BackupConfig.backup_encrypt_password`）
- **手动操作**：用户可自由选择是否加密，自由输入密码（双输入框确认 + 可见性切换按钮）

#### 备份功能权限

参照 AI 模块的 `ai_authorized` + `can_use_ai()` 模式：
- User 模型新增 `backup_authorized` + `can_use_backup()`
- 管理员可在用户管理页面勾选授权
- 被授权用户可执行备份操作，未授权用户不可见

#### WebDAV 备份增强

- `webdav_utils.py` 新增 `create_encrypted_zip()`、`upload_encrypted_backup()`、`upload_file_to_webdav()`
- 手动备份支持选择是否加密 + 自定义密码
- 定时备份使用预设密码自动加密

#### 定时备份调度器

后台守护线程 `_backup_scheduler_worker`，参照 `_anniversary_reminder_worker` 模式：
- 每 60 秒检查一次 `ScheduledBackupTask` 表中启用的任务
- 使用内置 cron 表达式解析器 `_cron_match()` 匹配当前时间
- 匹配时执行加密备份上传到 WebDAV
- 更新 `last_run_time` / `last_run_status`，推送 Webhook 通知
- 防止同一分钟内重复执行（120 秒冷却）

#### API 路由

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | /admin/backups/webdav/trigger | Admin + backup_authorized | 手动触发 WebDAV 备份 |
| GET | /admin/backup/download_local | Admin + backup_authorized | 下载本地数据库 |
| POST | /admin/backup/upload_local | Admin + backup_authorized | 上传恢复本地备份 |
| POST | /admin/backups/scheduled_tasks | Admin | 创建/更新定时备份任务 |
| POST | /admin/backups/scheduled_tasks/{id}/delete | Admin | 删除定时任务 |
| POST | /admin/backups/scheduled_tasks/{id}/toggle | Admin | 启用/禁用定时任务 |
| POST | /admin/backups/authorize/{user_id} | Admin | 切换用户备份授权 |

#### 涉及文件

- `requirements.txt` — 追加 `pyzipper>=0.3.1`
- `webdav_utils.py` — 加密 zip 功能
- `routes_ext.py` — 备份路由权限控制 + 加密 + 定时任务管理 + 授权管理 + 调度器
- `templates/admin_backups.html` — 加密配置区 + 定时任务管理 + 授权管理 + 手动加密备份
- `templates/admin_users.html` — 权限配置 Modal 增加备份授权勾选框
- `templates/base.html` — 被授权用户导航增加「备份」入口

---

### 8.6 页面优化

#### Webhook 管理页面增强

- 新增/编辑 Modal 添加扩展事件开关（修改/安全/系统/状态变更）
- 新增/编辑 Modal 添加 14 页面推送矩阵 checkbox（全选/清空按钮）
- 编辑按钮 data 属性增加扩展事件和 `notify_pages` 数据
- JS 回填逻辑实现扩展事件和页面矩阵的编辑回填
- 列表"触发通知"列增加扩展事件 badge 显示

---

## 第九章 V2 修复与优化（2026-09-10）

### 9.1 Webhook 修复
- 新增 Modal 补全 modal-footer 保存按钮（问题 #2）
- 编辑按钮因 HTML 结构修复而恢复（问题 #3）
- pyzipper 依赖安装确认（问题 #4）
- WebhookLog 新增 operator_id 字段，记录操作发起人（问题 #11）
- 日志表格新增"发起用户"列，展示操作人用户名（问题 #11）
- trigger_webhook_event 函数新增 operator_id 参数，所有调用点已传入 current_user.id（问题 #11）
- Webhook CRUD 路由补充 safe_log 审计日志（问题 #13）：toggle/test/delete_log 路由新增 safe_log 调用

### 9.2 权限工单优化
- 后端查询用户已申请(pending)和已拥有(allowed_menus)的菜单集合，传给模板（问题 #1）
- 前端 checkbox 对已申请/已有权限的菜单添加 disabled 属性 + 删除线样式 + "已有/申请中"标签（问题 #1）
- 后端提交校验：提交的菜单如在 pending 工单或已有权限中，拒绝并提示（问题 #1）

### 9.3 WebDAV 备份增强
- WebDAV 配置权限隔离：管理员可编辑完整配置 / 普通用户只读状态卡片，不显示敏感信息（问题 #5）
- admin_save_webdav_config 路由增加管理员权限限制（问题 #5）
- 定时任务对授权用户可见（is_admin or can_use_backup），授权用户只读查看（问题 #6）
- 备份页排版重构：WebDAV配置 → 定时任务 → WebDAV云端备份 → 本地数据库备份 → 附件恢复 → 授权管理（问题 #9）
- 本地上传分拆：数据库恢复(.db) + 附件恢复(.json/.csv/.txt/.xlsx/.docx/.zip)独立卡片（问题 #7）
- 新增 admin_upload_attachment 路由处理附件文件上传（问题 #7）

### 9.4 WebDAV 上传 404 修复
- 新增 _resolve_target_dir_url() 函数：对 /dav 根路径自动追加 backup_subdir 子目录（问题 #8）
- ensure_remote_dir() 改为递归多级目录创建：逐级 PROPFIND 检查 → MKCOL 创建（问题 #8）
- upload_backup() 和 list_backups() 使用 _resolve_target_dir_url 标准化 URL（问题 #8）
- BackupConfig 新增 backup_subdir 字段（默认 gift_backups），模板增加子目录输入框（问题 #8）

### 9.5 恢复数据库修复
- admin_upload_local_backup 和 admin_restore_webdav_backup 路由在文件覆盖后调用 db.engine.dispose()（问题 #10）
- dispose 释放连接池旧句柄，下次访问自动重建连接读取新数据库文件（问题 #10）
- flash 提示用户刷新页面确认数据更新（问题 #10）

### 9.6 定时任务改造
- ScheduledBackupTask 模型新增 task_type、target_files、custom_script 字段（问题 #9）
- 定时任务支持三种类型：db_backup(数据库备份) / file_backup(文件备份) / custom(自定义脚本)（问题 #9）
- _backup_scheduler_worker 根据 task_type 执行不同逻辑分支（问题 #9）
- 模板定时任务 Modal 新增任务类型选择下拉框，动态显示对应配置区域（问题 #9）
- 卡片标题从"定时备份任务"改为"定时任务"（问题 #9）

### 9.7 审计日志补全
- admin_test_webdav 路由新增 safe_log 记录测试连接结果（问题 #12）
- admin_backups_list_ajax 路由新增 safe_log 记录查看备份列表（问题 #12）

### 9.8 数据模型变更
- BackupConfig 新增 backup_subdir (String(100), default='gift_backups')
- ScheduledBackupTask 新增 task_type (String(20), default='db_backup')
- ScheduledBackupTask 新增 target_files (Text, nullable)
- ScheduledBackupTask 新增 custom_script (Text, nullable)
- WebhookLog 新增 operator_id (Integer, FK users.id, nullable)
- 迁移 SQL 已追加到 app.py migration_sqls 列表

---

## 第十章 V4 修复记录 — WebDAV 安全恢复与缺陷修复

### 10.1 恢复备份导致全站 500 Internal Server Error（核心修复）

**根因分析**：恢复备份时直接覆盖正在使用的数据库文件，未释放 SQLAlchemy 连接池，未清理 WAL/SHM 文件，导致 `malformed database schema (sqlite_autoindex_security_risks_1) - orphan index` 错误。此外旧备份缺少 V2/V3 新增的表和字段，恢复后应用访问报 500。

**安全恢复流程**（admin_restore_webdav_backup + admin_upload_local_backup）：
1. `db.engine.dispose()` 释放连接池，防止覆盖正在使用的文件
2. 下载/上传到临时文件（tempfile.mkdtemp），不直接覆盖目标文件
3. `PRAGMA integrity_check` 校验临时文件完整性，校验失败则中止恢复
4. 备份当前数据库（shutil.copy2 到 .bak_时间戳）
5. 用校验通过的临时文件替换目标数据库文件
6. 清理 WAL/SHM 文件（-wal、-shm 后缀），防止旧 WAL 日志导致 schema 损坏
7. 调用 `init_database()` 重新执行迁移 SQL，补建缺失的表/字段
8. Webhook 通知 + flash 提示用户刷新页面

**init_database 延迟导入**：`routes_ext.py` 中通过 `from app import init_database` 在函数内部延迟导入，避免 `app.py` 与 `routes_ext.py` 之间的循环导入问题。

### 10.2 加密 zip 恢复报错 quote_from_bytes() expected bytes

**根因**：`webdav_utils.py` 的 `download_backup` 函数参数重映射条件写反（`remote_filename is not None` 应为 `is None`），导致 `remote_filename` 保持 None。

**修复**：
- `download_backup` 参数映射修正为 `if remote_filename is None and username is not None`
- 新增 `decrypt_encrypted_zip()` 函数（AES-256 解密，基于 pyzipper）
- 新增 `download_and_decrypt_backup()` 函数（下载+解密一体化）
- 前端 `admin_backups.html` 中 .zip 文件恢复按钮改为调用 `restoreEncryptedBackup()` 弹窗输入密码

### 10.3 删除 WebDAV 文件失败（远端文件不存在）

**根因**：`delete_webdav_backup` 和 `download_backup` 使用 `_normalize_url` 而非 `_resolve_target_dir_url`，导致 URL 缺少 `backup_subdir` 子目录路径。

**修复**：两个函数都改为使用 `_resolve_target_dir_url`，确保 URL 包含 backup_subdir 子目录路径。

### 10.4 附件上传 WebDAV 409 错误

**根因**：附件上传到 `attachments/` 子目录，但远端该子目录不存在，WebDAV 服务器返回 409 Conflict。

**修复**：
- `routes_ext.py` 中 `admin_upload_attachment` 路由将 `remote_name` 从 `f"attachments/{filename}"` 改为直接 `filename`（放到备份根目录）
- `webdav_utils.py` 中 `upload_file_to_webdav` 增加自动创建远端子目录逻辑（MKCOL）

### 10.5 数据库路径说明

- `app.py` 第 68-71 行：如果 `data/` 目录存在，优先使用 `data/gift_bookkeeping.db`；否则使用根目录的 `gift_bookkeeping.db`
- V3 开发过程中创建了 `data/` 目录，导致数据库路径切换，曾出现数据丢失问题
- 已用根目录完整数据库覆盖 `data/gift_bookkeeping.db`，integrity_check=ok，数据完整恢复

> AI生成