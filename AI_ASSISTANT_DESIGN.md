---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'a8465ea2-dad8-4996-ab9e-8321e8c3e190'
  PropagateID: 'a8465ea2-dad8-4996-ab9e-8321e8c3e190'
  ReservedCode1: 'fba5dcd9-25b2-427f-b165-891a06933612'
  ReservedCode2: 'fba5dcd9-25b2-427f-b165-891a06933612'
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

---

## 第十一章 V5/V6/V7 修复与优化（2026-09-11）

### 11.1 V5 — Webhook 重复 JS 清理与前端健壮性（第一批）

**问题**：`admin_webhooks.html` 中 `showWebhookFormError` 和 `validateWebhookForm` 两个函数存在重复定义（768-797 行与 799-829 行），导致 JS 引擎使用后者覆盖前者，虽不影响功能但增加维护混乱。

**修复**：
- 删除 768-797 行的第一组重复定义，保留 799-829 行的第二组（更完整的实现）
- 清理冗余代码，提高可维护性

### 11.2 V6 — 用户管理与权限体系增强（第一批）

**涉及文件**：`admin_users.html`、`admin_webhooks.html`、`admin_backups.html`、`models.py`、`app.py`、`routes_ext.py`

**主要改进**：
- 用户管理页面权限配置 Modal 交互优化
- Webhook 管理页面前端体验改进
- 备份管理页面布局初步调整
- 数据模型字段补充与迁移 SQL 追加

### 11.3 V7 — 六项核心问题修复（第二批）

#### 问题 1：Webhook 保存按钮无响应

**根因**：`admin_create_webhook` 和 `admin_edit_webhook` 路由在保存时调用 `validate_wecom_credentials` 进行凭证校验，校验失败导致保存中断，前端表现为点击保存无反应。

**修复**：
- `routes_ext.py` 中移除 `admin_create_webhook`（~2883 行）和 `admin_edit_webhook`（~2966 行）的 `validate_wecom_credentials` 调用
- 保存按钮只负责保存配置，凭证校验由独立的"测试连接"按钮承担
- `admin_webhooks.html` 前端增加 loading 状态 + 显式必填字段校验 + 成功提示

#### 问题 2：加密密码明文回显

**根因**：WebDAV 备份加密密码框在编辑时直接回显已保存的密码明文，存在安全风险。

**修复**：
- 密码框改为动态 placeholder（"已设置，留空保持不变"），不回显明文
- 密码框旁增加"已设置/未设置"状态徽章
- 新增"清除加密密码"checkbox，勾选后无需填写新密码即可清除
- `routes_ext.py` 的 `admin_save_webdav_config`（~3428 行）改为 clear 优先逻辑：先检查 clear 标志，再处理新密码

#### 问题 3：无菜单权限用户首页循环跳转

**根因**：`routes_ext.py` 的 `menu_map` 中 `'index': 'ledger'` 映射导致无权限用户访问首页 `/` 时被重定向到礼金账本，但礼金账本也需要权限，形成循环跳转。

**修复**：
- `routes_ext.py` 的 `menu_map`（~518 行）移除 `'index': 'ledger'` 映射
- `app.py` 的 `index()` 路由（~810 行）增加 `can_access_menu('ledger')` 权限检查，无权限用户看到友好的权限申请引导卡片而非循环跳转

#### 问题 4：普通用户备份越权

**根因**：普通用户执行 WebDAV 备份/下载/定时任务时直接使用全局数据库文件，可能访问到其他用户的数据。

**修复**：
- `routes_ext.py` 新增 `build_user_scoped_backup_db()` 工具函数（~41-80 行）：创建仅包含当前用户数据的临时 SQLite 数据库
- `admin_trigger_webdav_backup`（~3482 行）、`admin_download_local_backup`（~3560 行）、`_backup_scheduler_worker`（~495 行）均改为使用临时库进行备份/下载
- `admin_backups.html` 备份列表 checkbox 增加权限控制：普通用户只能操作自己创建的备份文件

#### 问题 5：WebDAV 配置自动复制导致越权

**根因**：`models.py` 的 `BackupConfig.get_config()`（~922-947 行）在普通用户首次访问时自动复制管理员的 WebDAV 配置（含服务器地址、用户名、密码），导致普通用户可以访问管理员的 WebDAV 存储空间。

**修复**：
- `get_config()` 移除自动复制逻辑，普通用户首次访问创建空白私有配置
- 所有调用 `get_config()` 的地方已有空配置保护（检查 `config.server_url` 和 `config.username`），移除自动复制不会导致异常
- `admin_backups.html` 普通用户 WebDAV 配置区增加提示横幅："请填写您自己的 WebDAV 服务器信息"

#### 问题 6：备份页面布局优化

**改进内容**：
- **定时任务卡片移至右栏顶部**：从左栏（`col-lg-5`）移到右栏（`col-lg-7`）顶部，与 WebDAV 备份列表同栏，逻辑更紧凑
- **定时任务表格瘦身**：从 8 列精简为 4 列（任务名称+状态、类型+Cron、上次执行+创建人、操作+历史）
- **授权按钮文字化**：从纯图标改为"图标+文字"（"授权备份"/"撤销备份"、"授权任务"/"撤销任务"），撤销操作增加 `confirm()` 确认弹窗
- **授权同步说明**：授权卡片标题下增加"授权状态与「用户管理」页面实时同步，无需重复操作"说明文字
- **备份时间本地化**：WebDAV 备份列表时间列从 GMT 转为本地时间显示（JS `new Date(rawTime).toLocaleString('zh-CN', ...)`）
- **Jinja2 模板标签修复**：移动卡片过程中意外破坏了 `admin_backups.html` 的 Jinja 标签结构（`</div></div>{% endif %}` 闭合标签），经两次修复后标签平衡，服务编译无报错

### 11.4 涉及文件（V5/V6/V7 合计）

| 文件 | 改动内容 |
|------|----------|
| `routes_ext.py` | 移除 Webhook 校验、clear 优先逻辑、临时库备份、menu_map 修复 |
| `templates/admin_webhooks.html` | 重复 JS 清理、loading+校验+提示 |
| `templates/admin_backups.html` | 密码不回显、提示横幅、布局优化、授权按钮文字化、时间本地化 |
| `templates/admin_users.html` | 用户管理权限配置交互优化 |
| `app.py` | index() 权限检查 |
| `models.py` | get_config() 移除自动复制 |

### 11.5 浏览器验证结果（2026-09-11）

| 验证页面 | 验证项 | 结果 |
|----------|--------|------|
| `/`（首页） | 管理员正常加载，无循环跳转 | ✅ 通过 |
| `/admin/backups` | 无 500 错误，模板编译正常 | ✅ 通过 |
| `/admin/backups` | 定时任务卡片在右栏顶部 | ✅ 通过 |
| `/admin/backups` | 授权按钮文字化（授权备份/授权任务） | ✅ 通过 |
| `/admin/backups` | 授权同步说明文字显示 | ✅ 通过 |
| `/admin/backups` | 定时任务表格 4 列瘦身 | ✅ 通过 |
| `/admin/backups` | 加密密码区"已设置"标签+清除 checkbox | ✅ 通过 |
| `/admin/backups` | 备份时间本地化（2026/09/11 10:13） | ✅ 通过 |
| `/admin/backups` | WebDAV 备份列表 4 条记录正常 | ✅ 通过 |
| `/permission_tickets` | 3 条工单正常显示（已驳回/已撤销） | ✅ 通过 |
| 浏览器控制台 | 无 JS 错误 | ✅ 通过 |

---

## 第十二章 V8 修复与优化（2026-09-11）

### 12.1 需求总览

V8 批次共 12 项需求，覆盖三大模块：

| 编号 | 模块 | 类型 | 需求 |
|------|------|------|------|
| 1 | 工单页面 | 新增 | 列表排序功能 |
| 2 | 工单页面 | 新增 | 筛选功能扩展（补充"已撤销"状态） |
| 3 | 工单页面 | 新增 | 仅管理员可删除工单 |
| 4 | 工单页面 | 新增 | 分页，默认 10 条/页，可自定义每页条数 |
| 5 | 工单页面 | 优化 | 页面排版布局优化 |
| 6 | webhook 页面 | 修复 | 测试按钮无反应（超时过长） |
| 7 | webhook 页面 | 优化 | 测试过程 loading + 结果 toast 提示 |
| 8 | webdav 页面 | 修复 | 加密密码回显逻辑（未勾清除时保留） |
| 9 | webdav 页面 | 修复 | 普通用户不可编辑/删除管理员定时任务 → 按钮置灰 |
| 10 | webdav 页面 | 修复 | 手动备份只备份当前用户有权限数据（DROP 全局表） |
| 11 | webdav 页面 | 新增 | 一键引用管理员配置（去敏 + 一键更新） |
| 12 | webdav 页面 | 权限 | 本地备份卡片不隐藏，普通用户可备份/恢复自己的数据 |

### 12.2 工单页面（需求 1-5）

#### 后端改动（`routes_ext.py` `permission_tickets_view`）

- **排序**：新增 URL 参数 `sort`（`created_at`/`updated_at`/`status`）、`order`（`asc`/`desc`，默认 desc），表头可点击切换升降序
- **筛选**：保留原有 `status` 筛选，补充"已撤销"（`status=revoked`）选项
- **分页**：新增 `page`（默认 1）、`per_page`（默认 10，可选 5/10/20/50/100），使用 `query.paginate()` 实现分页
- **删除**：新增 `POST /permission_tickets/<id>/delete` 路由，仅管理员可调用，删除后 `safe_log` 审计 + 尝试 webhook 推送
- **排版**：列表卡片顶部增加"共 N 条 / 当前第 X 页"统计信息，操作列间距统一

#### 前端改动（`templates/permission_tickets.html`）

- 表头"提交时间"列可点击排序，显示升降序箭头
- 筛选栏补充"已撤销"状态链接
- 表格下方新增分页条（上一页/页码/下一页 + 每页条数下拉选择器）
- 管理员操作列（非 pending 状态）增加"删除"按钮（带 `confirm()` 二次确认）
- 普通用户不显示删除按钮

#### Bug 修复

- **每页条数切换 404**：第 54 行 `onchange="window.location.href = updatePerPage(this.value)"` 缺少 `?` 前缀，修复为 `'?' + updatePerPage(this.value)`

### 12.3 Webhook 测试优化（需求 6-7）

#### 根因

`webhook_utils.py` `test_single_webhook` 的 `_send_payload` 调用超时为 12 秒，前端 JS 无超时控制，目标 URL 响应慢时按钮长时间停在"测试中..."状态，看起来像"无反应"。

#### 修复

- **后端超时缩短**：`webhook_utils.py` `test_single_webhook` 的 `_send_payload` 超时从 12 秒降至 **5 秒**
- **前端超时保护**：fetch 请求加 `AbortController` 10 秒超时，超时中断并提示
- **交互增强**：
  - 点击后按钮立即 loading（禁用 + 转圈 + "测试中..."）
  - 结果用 **toast 替换原生 `alert()`**：成功绿色 toast（含状态码），失败红色 toast（含错误信息与状态码）
  - toast 5 秒后自动移除

#### Bug 修复

- `admin_webhooks.html` 两处重复代码块（重复 fetch 调用 + 重复 form 处理）导致 JS 语法错误 `Unexpected token '}'`，全部删除后 `node --check` 通过

### 12.4 WebDAV 备份页面（需求 8-12）

#### 需求 8：加密密码回显

- **规则**：仅当未勾选「清除已保存的加密密码」时回显明文密码；勾选则置空
- `admin_backups()` 路由将 `config.backup_encrypt_password` 传入模板变量
- 模板密码框 `value` 回显明文，placeholder 提示"已设置，修改请直接输入新密码"
- 标题旁显示"已设置/未设置"状态徽章
- 勾选清除 checkbox 时 JS 清空输入框并禁用

#### 需求 9：定时任务按钮置灰

- 模板中计算 `can_operate = current_user.is_admin or t.created_by == current_user.id`
- 非创建者且非管理员：编辑/删除/启停按钮加 `disabled` 属性 + `title` 提示
- 执行历史按钮保留可点击（查看不影响数据）

#### 需求 10：备份范围限定（方案 B，用户已确认）

- `build_user_scoped_backup_db` 函数（`routes_ext.py` ~41-81 行）逻辑：
  1. 复制主库到临时文件
  2. `DELETE FROM gift_records WHERE user_id != ?`（仅保留本人数据）
  3. `DELETE FROM banquets WHERE user_id != ?`
  4. `DELETE FROM anniversary_reminders WHERE user_id != ?`
  5. DROP 19 张全局敏感表：`users, backup_configs, scheduled_backup_tasks, scheduled_task_execution_logs, webhook_configs, webhook_logs, operation_logs, login_risks, security_risks, system_settings, registration_tokens, broadcasts, broadcast_reads, shared_ledger_links, backup_attachments, permission_tickets, chat_sessions, chat_messages, ai_query_logs`
- 恢复侧：`admin_upload_local_backup` / `admin_restore_webdav_backup` 恢复后调用 `init_database()` 自动补建缺失表
- 普通用户 `download_local` 路由调用 `build_user_scoped_backup_db` 返回过滤后的临时文件

#### 需求 11：一键引用管理员配置

- 新增后端接口 `GET /admin/backups/reference_admin_config`（仅普通用户可调用）
- 返回管理员配置的去敏字段：`webdav_url`、`webdav_username`、`backup_subdir`（密码不返回）
- 前端两个按钮：
  - **一键引用管理员配置**：点击 → fetch 获取 → 自动填充服务器地址/账号/子目录 → toast 提示"已引用管理员配置（服务器地址/账号/子目录）。密码涉及敏感信息不自动填充"
  - **一键更新**：同样调用接口重新拉取管理员最新配置并覆盖填入

#### 需求 12：本地备份卡片不隐藏

- 前端不隐藏：本地数据库备份/附件恢复卡片对所有有备份权限的用户可见
- 普通用户执行下载本地备份时走 `build_user_scoped_backup_db` 过滤，备份文件仅含本人数据
- 普通用户可恢复自己的备份文件（恢复后 `init_database()` 补建全局表）

### 12.5 涉及文件清单

| 文件 | 改动内容 |
|------|----------|
| `routes_ext.py` | 工单排序/分页/删除路由；`build_user_scoped_backup_db` DROP 全局表；本地下载走过滤库；`reference_admin_config` 去敏接口 |
| `webhook_utils.py` | `test_single_webhook` 超时 12s→5s |
| `templates/permission_tickets.html` | 排序/筛选（含已撤销）/分页/删除按钮/排版优化；修复每页条数 `?` 前缀 bug |
| `templates/admin_webhooks.html` | 测试交互增强（toast 替代 alert、前端超时、loading）；删除两处重复代码块 |
| `templates/admin_backups.html` | 加密密码回显（未勾清除时）；定时任务按钮置灰；一键引用+一键更新按钮；卡片不隐藏 |

### 12.6 浏览器验证结果（2026-09-11）

| 验证项 | 结果 |
|--------|------|
| 工单删除：工单 #3 删除成功，列表从 3 条变 2 条 | ✅ 通过 |
| 工单排序：点击"提交时间"表头，URL `order=asc`，箭头切换 | ✅ 通过 |
| 工单筛选：点击"已撤销"，URL `status=revoked`，显示 2 条 | ✅ 通过 |
| 工单每页条数：修复后 URL `?per_page=5&page=1`，下拉框选中"5 条" | ✅ 通过 |
| Webhook 测试 toast：console 0 错误，红色 danger toast 显示错误信息 | ✅ 通过 |
| 管理员加密密码回显：密码框 `value="258369"`，"已设置"标签显示 | ✅ 通过 |
| 普通用户一键引用管理员配置：URL/账号/子目录自动填充，密码框为空 | ✅ 通过 |
| 普通用户定时任务按钮置灰：admin 任务的暂停/编辑/删除按钮 disabled | ✅ 通过 |
| 普通用户本地备份/附件卡片可见：下载和上传按钮均可点击 | ✅ 通过 |
| 普通用户 WebDAV 备份列表权限隔离：admin 备份恢复按钮 disabled | ✅ 通过 |
| 备份范围隔离：普通用户备份仅含 3 张业务表（gift_records/banquets/anniversary_reminders），19 张全局敏感表不存在 | ✅ 通过 |

### 12.7 用户确认事项

| # | 问题 | 结论 |
|---|------|------|
| 1 | 备份范围方案 | 方案 B：删全局表 + 恢复时 `init_database()` 自动建表 |
| 2 | 一键引用实现方式 | 一键复制 + 一键更新（避免管理员更新后用户无法获取最新数据） |
| 3 | 本地备份卡片是否隐藏 | 不隐藏：普通用户可备份/恢复自己创建的数据和配置 |
| 4 | 加密密码回显规则 | 仅当未勾选「清除已保存的加密密码」时回显 |
| 5 | webhook 测试无反应根因 | 后端超时 12s 过长 + 前端无超时提示，优化为后端 5s + 前端 10s + toast |

> AI生成

---

## 第十三章 V9 修复与优化（2026-09-11）

### 13.1 V9-A — 普通用户恢复 .db 备份导致系统崩溃（核心 Bug 修复）

**问题现象**：普通用户在备份页执行 .db 备份恢复后，全站 Internal Server Error。

**根因链**：
1. V7/V8 的安全机制：普通用户备份是「过滤库」——19 张全局表（users 等）被 DROP，仅含本人 3 张业务表
2. 但恢复流程却是「文件级替换」：直接用该过滤库覆盖整个主库
3. 主库 users 表等核心表全部丢失 → 任何页面查询 users 表即 500 → 全站崩溃

**修复方案**：按身份分流恢复策略
- **普通用户（无跨用户查看权限）**：改走「数据级合并」——`merge_user_scoped_backup()` 用 `ATTACH DATABASE` 在同一 sqlite3 连接内，删除主库中本人旧数据，再把备份中本人数据（防御性校验 user_id）列对齐插入，不触碰全局表与其他用户数据
- **管理员 / can_view_others_for('ledger')**：保持原文件级替换 + WAL 清理 + init_database 重建
- 覆盖两个恢复入口：`admin_upload_local_backup`（本地 .db 上传恢复）与 `admin_restore_webdav_backup`（云端恢复），均含 `PRAGMA integrity_check` 预校验

### 13.2 V9-B — 数据级合并的 database is locked 坑

**复现**：合并时 DELETE 成功但最终报 `database main_db is locked`。

**根因**：`merge_user_scoped_backup()` 原顺序为 `DETACH → commit`。SQLite 不允许 DETACH 一个存在未提交事务的数据库，必然报 locked。

**修复**：调整为 `commit → DETACH`，同时：
- 合并连接加 `PRAGMA busy_timeout = 8000`（瞬时锁冲突时重试而非立即失败）
- 两个恢复路由在调用合并前先 `db.session.commit()`（落盘请求内未提交事务，如操作日志）+ `db.engine.dispose()`（释放连接池）
- 函数内兜底：尝试提交 Flask-SQLAlchemy session 中的未提交事务

### 13.3 V9-C — WAL 模式下备份丢数据（隐藏 Bug，测试时发现）

**现象**：`build_user_scoped_backup_db()` 用 `shutil.copy2` 复制主库，但主库为 WAL 模式，最新数据在 `-wal` 文件中未落盘（主文件 LastWriteTime 停留在 09-10 17:13，-wal 已积累 168KB），复制的库是过时快照——**用户最新记账数据会从备份中丢失**。

**修复**：改用 SQLite 在线备份 API（`Connection.backup()`），获得包含 WAL 数据的一致性快照。

**验证**：为李文伟新增 2 条礼金记录后生成过滤库，旧逻辑 gift_records=0 条，新逻辑正确包含 2 条。

### 13.4 V9-D — 普通用户一键引用改为「别称 + 服务端密文复制」（安全增强）

**原问题**（V8 遗留）：一键引用把管理员 WebDAV URL/账号填充到普通用户页面表单，密码虽留空但账号地址可见，不满足「敏感信息一律不可见」要求。

**方案**：
- `BackupConfig` 新增 `config_alias`（别称，String(100)）与 `adopted_from_admin`（Boolean，引用标记）字段；`app.py` migration_sqls 追加两条 ALTER TABLE
- 管理员配置表单新增「配置别称」输入框（推荐填写）
- 一键引用改造为两步：
  1. `GET /admin/backups/reference_admin_config`：只返回 `config_alias`/`has_password`/`adopted`，**地址/账号/子目录/密码一概不返回**
  2. `POST /admin/backups/adopt_admin_config`：服务端直读管理员配置，密文直传 `webdav_password`（不经前端），复制 URL/账号/子目录，标记 `adopted_from_admin=True`
- 普通用户页面双状态：已引用 → 只显示绿色状态卡片（别称 + 安全说明）+「一键更新」/「停用引用，自行配置」；未引用 → 原表单 +「一键采用管理员配置」
- 普通用户手动保存自己配置时自动清除 `adopted_from_admin`（视为脱离引用）
- 停用引用：提交空表单触发后端清除 + confirm 提示备份操作将不可用

### 13.5 浏览器验证结果（2026-09-11）

| 验证项 | 结果 |
|--------|------|
| 管理员保存别称「坚果云家庭备份盘」成功，表单回显 | ✅ 通过 |
| 普通用户确认弹窗仅显示别称，无地址/账号/密码泄露 | ✅ 通过 |
| 一键采用后页面仅显示别称状态卡片，敏感表单完全消失 | ✅ 通过 |
| 引用后 WebDAV 列表正常加载（服务端密文复制生效，连接真正可用） | ✅ 通过 |
| 普通用户上传过滤库 .db 恢复：数据级合并成功恢复 2 条，不崩溃 | ✅ 通过 |
| 恢复后主库 integrity ok、users 6 条、全局数据完好 | ✅ 通过 |
| 普通用户 WebDAV 恢复自己创建的备份：数据级合并 0 条（空备份），不崩溃 | ✅ 通过 |
| 一键更新：成功且只显示别称 | ✅ 通过 |
| 停用引用：confirm 后回到未引用状态，表单清空，按钮恢复 | ✅ 通过 |
| admin 备份恢复按钮置灰隔离（V8 回归验证） | ✅ 通过 |

### 13.6 涉及文件清单

| 文件 | 改动内容 |
|------|----------|
| `routes_ext.py` | `merge_user_scoped_backup()` 新增；`build_user_scoped_backup_db()` 改用 backup API；两个恢复路由按身份分流；`reference_admin_config` 只返回别称；新增 `adopt_admin_config`；保存配置处理别称与引用标记；`admin_backups` 传 `admin_config_alias` |
| `models.py` | `BackupConfig` 新增 `config_alias`、`adopted_from_admin` |
| `app.py` | migration_sqls 追加 `config_alias`、`adopted_from_admin` 两条 ALTER TABLE |
| `templates/admin_backups.html` | 管理员别称输入框；普通用户双状态 UI（引用卡片/原表单）；`adoptAdminConfig()`/`confirmDetachAdminConfig()` JS |

> AI生成

---

## 第十四章 V10 修复与优化（2026-09-14）

### 14.1 需求总览

V10 批次共 5 模块 15 项改动，覆盖 Webhook 推送修复、审计日志可配置化、WebDAV 页面布局优化与权限工单增强：

| 编号 | 模块 | 类型 | 需求 |
|------|------|------|------|
| 1.1 | Webhook | 修复 | 测试成功后 toast 被立即刷新销毁，不可见 |
| 2.1 | Webhook | 修复 | 5 处 `trigger_webhook_event` 调用缺少 `webhooks` 参数 |
| 2.2 | Webhook | 修复 | 对账同步路由 `reconciliation_sync` 缺少推送 |
| 2.3 | Webhook | 修复 | 审计日志删除/清空/批量删除路由缺少推送 |
| 2.4 | Webhook | 修复 | 页面推送矩阵 + PAGE_NAMES 缺少 `permission_tickets` |
| 3.1 | 审计日志 | 新增 | 可配置记录模块（SystemSetting key `audit_log_modules`） |
| 3.2 | 审计日志 | 新增 | `log_action` 函数按模块过滤 |
| 3.3 | 审计日志 | 新增 | 管理员配置面板（13 模块 checkbox） |
| 3.4 | 审计日志 | 新增 | `POST /admin/audit-log-config` 保存配置路由 |
| 4.1 | WebDAV | 优化 | 备份页面整体布局重排（三行两栏） |
| 4.2 | WebDAV | 优化 | 普通用户本地备份卡片差异化提示横幅 |
| 4.3 | WebDAV | 修复 | 合并函数空库保护（DELETE 前 COUNT 检查） |
| 5.1 | 权限工单 | 新增 | 关键词搜索（申请人/理由模糊匹配） |
| 5.2 | 权限工单 | 新增 | 申请模块筛选下拉框 |
| 5.3 | 权限工单 | 新增 | 扩展排序列（applicant/reason） |
| 5.4 | 权限工单 | 新增 | 多选 checkbox + 批量删除路由 |
| 5.5 | 权限工单 | 优化 | ID 列改为分页行序号 |
| 5.6 | 权限工单 | 修复 | 排序时 JS 丢失筛选/搜索参数 |

### 14.2 模块一：Webhook 测试成功无提示

**根因**：测试成功后立即 `window.location.reload()` 刷新页面，toast 被 DOM 销毁不可见。

**修复**：`templates/admin_webhooks.html` 测试成功分支改为延迟 2 秒再刷新页面（`setTimeout(() => location.reload(), 2000)`），确保 toast 完整展示。

### 14.3 模块二：Webhook 推送缺失修复

#### 2.1 — 6 处参数签名错误

`routes_ext.py` 中 6 处 `trigger_webhook_event` 调用缺少第一个 `webhooks` 参数（`WebhookConfig.query.filter_by(is_enabled=True).all()`），导致推送静默失败：
- 行 4297（纪念日批量删除推送）
- 行 4534（权限工单创建推送）
- 行 4592（权限工单批准推送）
- 行 4635（权限工单驳回推送）
- 行 4685（权限工单撤销推送）
- 行 4745（权限工单删除推送）

**修复**：全部补齐 `WebhookConfig.query.filter_by(is_enabled=True).all()` 作为第一个参数。

#### 2.2 — 对账同步路由缺少推送

`routes_ext.py` 的 `reconciliation_sync` 路由执行同步后无 webhook 推送。

**修复**：补充 `trigger_webhook_event` 调用，`page_key='reconciliation'`。

#### 2.3 — 审计日志操作缺少推送

`app.py` 中三个审计日志路由（`admin_delete_log`/`admin_clear_logs`/`admin_batch_delete_logs`）执行后无推送。

**修复**：三个路由均补充 `trigger_webhook_event`，`page_key='admin_logs'`。

#### 2.4 — 页面推送矩阵与 PAGE_NAMES 补全

- `templates/admin_webhooks.html` 的 14 个 checkbox 缺少 `permission_tickets` 选项 → 补充第 15 个 checkbox
- `webhook_utils.py` 的 `PAGE_NAMES` 字典缺少 `permission_tickets` 条目 → 补充 `'permission_tickets': '权限工单'`

### 14.4 模块三：审计日志可配置记录

#### 设计思路

复用现有 `SystemSetting` 表，新增 key `audit_log_modules`，值为 JSON 数组（如 `["ledger","banquets","reconciliation"]`）。管理员在审计日志页面配置需要记录的模块，未勾选模块的操作不写入审计日志。

#### 模块映射

`app.py` 新增 `AUDIT_MODULE_MAP` 字典，13 个模块标识：

| 模块标识 | 匹配关键词 | 说明 |
|----------|-----------|------|
| `ledger` | 礼金/账本 | 礼金账本 |
| `banquets` | 宴席 | 专属宴席 |
| `reconciliation` | 对账 | 人情对账 |
| `reminders` | 纪念日/备忘 | 亲友纪念日 |
| `recycle_bin` | 回收站 | 回收站 |
| `admin_users` | 用户/权限/注册 | 用户管理 |
| `webhooks` | webhook/机器人/通道 | Webhook |
| `backups` | 备份/恢复/webdav/定时任务 | 备份 |
| `permission_tickets` | 工单/权限申请 | 权限工单 |
| `broadcasts` | 广播 | 系统广播 |
| `ai_assistant` | AI/聊天/会话 | AI 助手 |
| `auth` | 登录/注册/密码 | 认证 |
| `system` | 系统设置/审计/安全 | 系统管理 |

#### 实现

- `app.py` `log_action` 函数增加模块过滤：按 action 关键词匹配模块标识，未在配置中勾选的模块跳过写入
- `templates/admin_logs.html` 增加可折叠配置面板，列出 13 个模块 checkbox + 全选/清空按钮
- 新增 `POST /admin/audit-log-config` 路由保存配置到 `SystemSetting`
- `admin_logs` 路由将当前配置传入模板

### 14.5 模块四：WebDAV 页面布局优化

#### 4.1 — 整体布局重排

原布局为 `col-lg-5`（WebDAV 配置 + 备份授权）+ `col-lg-7`（定时任务 + 云端备份 + 本地备份 + 附件恢复）两栏，右栏过长左栏过短。

**新布局**（四行）：
- 第一行（`col-12`）：WebDAV 配置 + 备份授权管理
- 第二行（`col-12`）：定时任务
- 第三行（`col-12`）：WebDAV 云端备份与恢复
- 第四行（`col-lg-6` + `col-lg-6`）：本地数据库备份与恢复 | 附件文件恢复

#### 4.2 — 普通用户本地备份差异化提示

普通用户本地备份卡片新增蓝色提示横幅："您下载的备份仅包含本人数据；上传恢复时系统将只合并您的数据，不影响其他用户或系统配置。"

管理员视图文案保持"下载完整数据库备份 (.db)"，普通用户文案改为"下载我的数据备份 (.db)"。

#### 4.3 — 合并函数空库保护

`routes_ext.py` `merge_user_scoped_backup()` 中 DELETE 前先 `SELECT COUNT(*)` 检查备份库中该用户是否有数据，为 0 则跳过删除+插入，避免上传空库导致本人数据被清空。

### 14.6 模块五：权限工单增强

#### 5.1 — 关键词搜索

- **后端**：`permission_tickets_view` 新增 `q` 参数，使用 `User.username.ilike()` + `PermissionTicket.reason.ilike()` 联合模糊匹配
- **前端**：筛选区新增搜索输入框 + 搜索按钮 + 清除按钮

#### 5.2 — 申请模块筛选

- **后端**：`permission_tickets_view` 新增 `module` 参数，使用 `PermissionTicket.requested_menus.ilike()` 模糊匹配
- **前端**：筛选区新增下拉框（全部模块 + TICKET_MENU_OPTIONS 所有选项），选中后自动提交表单

#### 5.3 — 扩展排序列

`sort_map` 新增 `applicant`（`User.username`）和 `reason`（`PermissionTicket.reason`）两个排序字段。前端表头对应列增加排序链接与升降序箭头。

#### 5.4 — 多选 + 批量删除

- **后端**：新增 `POST /permission_tickets/batch_delete` 路由，接收 `ticket_ids` 列表，管理员专属，删除后审计日志 + webhook 推送
- **前端**：表头新增全选 checkbox，每行新增行 checkbox，选中后显示"批量删除选中"按钮，提交动态创建表单 POST

#### 5.5 — ID 列改为分页行序号

原 `{{ t.id }}` 改为 `{{ loop.index + (pagination.page - 1) * per_page }}`，显示分页内连续序号而非数据库 ID，不受删除影响。

#### 5.6 — 排序时保留筛选参数

`toggleSortQs()` 原实现只构造 sort/order/page 参数，会丢失 q/module/status 等筛选参数。改为基于 `new URL(window.location.href)` 修改，自动保留当前 URL 中已有的所有查询参数。

### 14.7 涉及文件清单

| 文件 | 改动内容 |
|------|----------|
| `templates/admin_webhooks.html` | 测试成功延迟 2 秒刷新 + 页面矩阵补充 permission_tickets checkbox |
| `routes_ext.py` | 6 处 webhook 参数修复 + 对账同步推送 + 合并函数空库保护 + 权限工单后端增强（搜索/筛选/排序/批量删除） |
| `app.py` | 审计日志删除推送 + log_action 模块过滤 + AUDIT_MODULE_MAP + 审计配置路由 + admin_logs 传配置 |
| `webhook_utils.py` | PAGE_NAMES 补充 permission_tickets |
| `templates/admin_logs.html` | 审计日志配置面板 + JS |
| `templates/admin_backups.html` | 布局重排（四行）+ 普通用户差异化提示 |
| `templates/permission_tickets.html` | 筛选/搜索/排序/批量删除/序号/JS 修复 |

### 14.8 浏览器验证结果（2026-09-14）

| 验证项 | 结果 |
|--------|------|
| 服务启动无报错，模板编译正常 | ✅ 通过 |
| WebDAV 备份页面四行布局正常 | ✅ 通过 |
| 普通用户本地备份卡片差异化提示 | ✅ 通过 |
| 权限工单关键词搜索功能 | ✅ 通过 |
| 权限工单模块筛选下拉框 | ✅ 通过 |
| 权限工单排序（申请人/理由列） | ✅ 通过 |
| 权限工单排序时保留筛选参数 | ✅ 通过 |
| 审计日志配置面板（13 模块可折叠） | ✅ 通过 |
| 审计日志列表 303 条正常显示 | ✅ 通过 |

> AI生成

---

## 第十五章 V10.1 Webhook 推送系统全面重构（2026-09-14）

### 15.1 需求总览

V10.1 批次聚焦 Webhook 推送系统的全面重构与修复，共 5 大模块改动：

| 编号 | 模块 | 类型 | 需求 |
|------|------|------|------|
| A | 推送配置 UI | 重构 | 三段式（触发事件+扩展事件+页面矩阵）合并为"页面×事件"矩阵 + Tab 内嵌消息模板 |
| B | 推送覆盖 | 补全 | 宴席同步、批量移出明细、回收站手动清理、定时任务增删改状态变更 |
| C | 提示词优化 | 新增 | 场景化默认提示词 + 页面×事件自定义模板，敏感数据脱敏 |
| D | WebDAV 权限 | 修复 | 定时任务查看权限解耦（查看开关与备份数据权限分离） |
| E | 回显 Bug | 修复 | 编辑 Webhook 时页面矩阵回显硬编码 allPageKeys 缺少 permission_tickets |

### 15.2 模块 A：推送配置 UI 重构为"页面×事件"矩阵

**原设计问题**：
- 三段式配置（触发通知事件 4 项 + 扩展事件类型 4 项 + 页面推送矩阵 15 项）需要管理员理解两套开关的与关系，不直观
- 页面矩阵只有"是否推送该页面"一个维度，无法精细化控制"该页面的哪些事件推送"

**新设计**：Tab 内嵌三面板模式
- **Tab 1 - 基础事件开关**：8 个事件大类开关（新增/删除/修改/提醒/广播/安全/系统/状态变更），作为第一层过滤
- **Tab 2 - 推送配置矩阵**：15 行（页面）× 12 列（事件类型），每格勾选 = "该页面该事件是否推送"
  - 列定义（EVENT_COLUMNS）：create/update/delete/batch_delete/clear/sync/restore/status_change/reminder/broadcast/security/system
  - 矩阵适用性（PAGE_EVENT_MATRIX）：每页面仅显示适用的事件列，不适用列显示"—"
  - 全选/清空按钮控制矩阵内所有勾选
- **Tab 3 - 消息模板**：按页面×事件维度，管理员可对每个功能点的推送消息内容自定义
  - 支持占位符：`{user}` `{page}` `{action}` `{title}` `{detail}` `{time}` `{count}`
  - 留空则使用系统默认模板（DEFAULT_MESSAGE_TEMPLATES）

**数据存储兼容**：
- `notify_pages` 字段格式从 `{"事件分类": ["页面列表"]}` 扩展为支持新事件分类（batch_delete/clear/sync/restore 独立）
- `_page_matches` 兼容旧数据：空配置 = 不过滤（对全部页面放行）
- `message_templates` 字段格式为 `{"事件:页面": "自定义模板内容"}`

### 15.3 模块 B：推送覆盖补全

补充以下操作的 webhook 推送：

| 操作 | page_key | event_type | 说明 |
|------|----------|------------|------|
| 宴席同步 | banquets | sync | 宴席台账自动同步操作 |
| 宴席批量移出明细 | banquets | update | 从宴席批量移出明细记录 |
| 回收站手动过期清理 | recycle_bin | clear | 手动清理过期回收站记录 |
| 定时任务保存 | admin_backups | create | 新建/编辑定时备份任务 |
| 定时任务删除 | admin_backups | delete | 删除定时备份任务 |
| 定时任务启用/禁用 | admin_backups | status_change | 启停定时备份任务 |

### 15.4 模块 C：提示词优化 + 自定义模板

#### 场景化默认模板

`webhook_utils.py` 新增 `DEFAULT_MESSAGE_TEMPLATES` 字典，按事件类型场景化：

```
create:        【{page}·新增】操作人 {user} 在{page}新增了「{title}」
update:        【{page}·修改】操作人 {user} 更新了「{title}」的信息
delete:        【{page}·删除】操作人 {user} 删除了「{title}」（已移入回收站）
batch_delete:  【{page}·批量删除】操作人 {user} 批量删除了 {count} 条记录
clear:         【{page}·清空】操作人 {user} 清空了{page}数据（共 {count} 条）
sync:          【{page}·同步】操作人 {user} 执行了同步操作：{detail}
restore:       【{page}·还原】操作人 {user} 还原了「{title}」
...
```

#### 自定义模板渲染逻辑

`_render_message` 函数优先级：
1. 页面×事件级别自定义模板（`templates["event:page"]`）
2. 事件级别自定义模板（`templates["event"]`）
3. 系统默认模板（`DEFAULT_MESSAGE_TEMPLATES[event_category]`）
4. 兜底格式 `【{page_name}·{action_label}】{default_title}`

#### 敏感页面脱敏

`SENSITIVE_PAGES = {'ai_assistant', 'ai_config', 'security', 'admin_webhooks', 'admin_backups'}`

敏感页面的推送消息详情部分按事件类型细化脱敏描述，不泄露 Token/密钥/密码等敏感信息。

### 15.5 模块 D：WebDAV 定时任务查看权限修复

**根因**：`routes_ext.py` 第 3460 行条件 `_allow_view and current_user.can_view_others_backup()` 把"查看开关"（`allow_view_others_tasks`）与"备份数据权限"（`can_view_others_backup()`）强绑定，导致管理员开启查看开关后普通用户仍看不到他人定时任务。

**修复**：解耦为两个独立维度
- 查看：仅由 `allow_view_others_tasks` 全局开关控制
- 编辑/删除：由 `scheduled_task_authorized` + 创建者隔离控制

### 15.6 模块 E：编辑回显 Bug 修复

**根因**：`admin_webhooks.html` 第 923 行 `allPageKeys` 硬编码 14 项，缺少 `permission_tickets`，导致编辑时权限工单页面的矩阵勾选无法正确回填。

**修复**：
- 新增 Modal 和编辑 Modal 的矩阵改为后端动态注入 `ALL_PAGES`/`EVENT_COLUMNS`/`PAGE_EVENT_MATRIX`，前端不再硬编码
- 编辑回填逻辑重构为 `fillEditMatrix(notifyPagesJson)` 函数，从 JSON 数据自动回填
- 新增 `fillEditTemplates(templatesJson)` 回填消息模板自定义内容
- 编辑按钮新增 `data-message-templates` 属性传值

### 15.7 事件分类体系重构

`webhook_utils.py` 新增以下数据结构：

- `EVENT_COLUMNS`：12 个事件大类及显示名称
- `PAGE_EVENT_MATRIX`：15 个页面各自适用的事件列（适用才显示勾选框）
- `EVENT_SWITCH_MAP`：事件类型到 WebhookConfig 开关字段的映射（batch_delete/clear 归 delete 开关；sync 归 system 开关；restore 归 status_change 开关）
- `DEFAULT_MESSAGE_TEMPLATES`：12 个事件大类的场景化默认提示词
- `SENSITIVE_PAGES`：需要脱敏的页面集合
- `_get_event_category()`：将具体事件类型（如 record_create）归入大类（如 create）
- `_render_message()`：渲染推送消息，支持自定义模板优先 + 默认模板 + 脱敏

### 15.8 后端注入适配

`routes_ext.py` `admin_webhooks()` 路由新增模板变量注入：
- `ALL_PAGES`：PAGE_NAMES 字典（页面标识 → 显示名称）
- `EVENT_COLUMNS`：事件类型 → 显示名称
- `PAGE_EVENT_MATRIX`：页面×事件适用矩阵
- `DEFAULT_TEMPLATES`：默认提示词模板

### 15.9 涉及文件清单

| 文件 | 改动内容 |
|------|----------|
| `webhook_utils.py` | 新增 EVENT_COLUMNS/PAGE_EVENT_MATRIX/EVENT_SWITCH_MAP/DEFAULT_MESSAGE_TEMPLATES/SENSITIVE_PAGES；_get_event_category/_render_message/_sanitize_details 重构；_page_matches 空配置放行 |
| `routes_ext.py` | WebDAV 定时任务查看权限解耦；推送覆盖补全（宴席同步/批量移出/回收站清理/定时任务增删改）；admin_webhooks 路由注入矩阵数据 |
| `templates/admin_webhooks.html` | 新增/编辑 Modal 三段式→Tab 三面板（事件开关/矩阵/模板）；JS 函数重构（matrixSelectAll/matrixClearAll/assembleNotifyPages/assembleMessageTemplates/fillEditMatrix/fillEditTemplates）；编辑按钮新增 data-message-templates |
| `templates/admin_backups.html` | allow_view_others_tasks 复选框补充说明文案 |

> AI生成

---

## 第十六章 V10.2 修复与优化（2026-09-15）

### 16.1 需求总览

V10.2 批次覆盖 5 大方向：WebDAV 定时任务权限细化、备份授权模块排版优化、Webhook 自定义模板渲染修复、推送事件类型分类修正、补充缺失推送。

| 编号 | 模块 | 类型 | 需求 |
|------|------|------|------|
| 1 | WebDAV 权限 | 优化 | 定时任务操作权限从粗粒度（查看开关+使用授权）细化为查看/编辑/删除三个独立维度 |
| 2 | 页面排版 | 优化 | 备份授权卡片拆分为「WebDAV 备份授权」与「定时任务授权与权限」两张独立卡片，紧邻各自功能区 |
| 3 | Webhook 模板 | 修复 | 自定义模板命中后 details 被置空，导致推送消息详情显示"无" |
| 4 | 事件分类 | 修复 | 单条还原/批量还原误用 status_change、清空回收站误用 batch_delete |
| 5 | 推送补缺 | 修复 | admin_toggle_task_auth 缺少 Webhook 推送 |

### 16.2 模块 A：WebDAV 定时任务权限细化

**问题**：原仅有 `allow_view_others_tasks`（查看开关）和 `scheduled_task_authorized`（按用户授权使用），缺少编辑/删除他人任务的独立控制。`can_edit_others_backup()`/`can_delete_others_backup()` 方法定义了但未用于定时任务路由。

**方案**：

1. **BackupConfig 新增 2 字段**（`models.py`）：
   - `allow_edit_others_tasks`：允许普通用户编辑他人定时任务
   - `allow_delete_others_tasks`：允许普通用户删除他人定时任务

2. **User 模型新增 3 方法**（`models.py`）：
   - `can_view_others_scheduled_tasks()`：管理员 True / 普通用户看全局 `allow_view_others_tasks`
   - `can_edit_others_scheduled_tasks()`：管理员 True / 普通用户看全局 `allow_edit_others_tasks`
   - `can_delete_others_scheduled_tasks()`：管理员 True / 普通用户看全局 `allow_delete_others_tasks`

3. **4 处路由权限校验更新**（`routes_ext.py`）：
   - 保存任务（编辑）：`task.created_by != self 且 !can_edit_others_scheduled_tasks()` → 拒绝
   - 删除任务：`task.created_by != self 且 !can_delete_others_scheduled_tasks()` → 拒绝
   - 启停任务：`task.created_by != self 且 !can_edit_others_scheduled_tasks()` → 拒绝
   - 执行历史：`task.created_by != self 且 !can_view_others_scheduled_tasks()` → 拒绝

4. **全局开关保存**（`routes_ext.py`）：
   - `admin_save_webdav_config` 路由新增读取并保存 `allow_edit_others_tasks`/`allow_delete_others_tasks`
   - 新增 AJAX 路由 `admin_save_task_permissions`，供前端开关即时保存

5. **数据库迁移**（`app.py`）：migration_sqls 追加 2 条 ALTER TABLE

### 16.3 模块 B：备份授权模块排版优化

**问题**：原"备份功能授权"卡片混合了备份授权和定时任务授权两类不同维度的权限，与下方紧邻的"定时任务"管理区割裂感强；V10.2 新增的编辑/删除开关无处安放。

**方案**：

将原单一卡片拆分为两张：

1. **WebDAV 备份授权**卡片（紧邻 WebDAV 配置区下方）：
   - 仅含用户名、备份授权状态、授权/撤销备份按钮

2. **定时任务授权与权限**卡片（紧邻定时任务列表上方）：
   - 顶部三列全局开关：允许查看他人任务 / 允许编辑他人任务 / 允许删除他人任务
   - 开关通过 AJAX 即时保存（`saveTaskPermissionToggles()` JS 函数），保存后自动刷新页面更新按钮状态
   - 下方用户表：用户名、任务授权状态、授权/撤销任务按钮

3. **定时任务列表按钮权限**：
   - 编辑按钮（启停+编辑）：`is_owner or can_edit_others_tasks` → 可操作，否则置灰
   - 删除按钮：`is_owner or can_delete_others_tasks` → 可操作，否则置灰
   - 执行历史按钮：始终可用（查看权限由后端路由校验）

### 16.4 模块 C：Webhook 自定义模板渲染修复

**根因**：`_render_message()` 第 583 行，自定义模板命中后 `details = ''`，导致所有推送平台详情显示"无"。

**修复**：自定义模板仅覆盖标题格式，详情保留原始内容（敏感页面仍脱敏）：

```python
# 修复前
title = tpl.format(**fmt_ctx)
details = ''
return title, details

# 修复后
title = tpl.format(**fmt_ctx)
details = default_details or ''
if page_key in SENSITIVE_PAGES:
    details = _sanitize_details(page_key, event_type, user_name, details)
return title, details
```

### 16.5 模块 D：推送事件类型分类修正

| 行号 | 场景 | 修正前 | 修正后 | 原因 |
|------|------|--------|--------|------|
| 987 | 单条还原 | `status_change` | `restore` | 还原操作应归 restore 类，对应矩阵"还原"列 |
| 1092 | 批量还原 | `status_change` | `restore` | 同上 |
| 1206 | 清空回收站 | `batch_delete` | `clear` | 清空≠批量删除，应归 clear 类，对应矩阵"清空"列 |

### 16.6 模块 E：补充缺失推送

`admin_toggle_task_auth` 路由（定时任务授权切换）缺少 Webhook 推送，而对比 `admin_toggle_backup_auth`（备份授权切换）有推送。

**修复**：在 commit 后添加 `status_change` 类型推送，page_key 为 `admin_backups`，与备份授权切换推送格式对齐。

### 16.7 涉及文件清单

| 文件 | 改动内容 |
|------|----------|
| `models.py` | BackupConfig 新增 `allow_edit_others_tasks`/`allow_delete_others_tasks` 字段；User 新增 `can_view_others_scheduled_tasks`/`can_edit_others_scheduled_tasks`/`can_delete_others_scheduled_tasks` 方法 |
| `routes_ext.py` | 4 处定时任务路由权限校验更新；`admin_save_webdav_config` 读取保存新字段；新增 `admin_save_task_permissions` AJAX 路由；`admin_backups` 传参新增 4 个权限变量；3 处 event_type 修正；`admin_toggle_task_auth` 补充推送 |
| `webhook_utils.py` | `_render_message` 自定义模板 details 保留原始内容（不再置空） |
| `templates/admin_backups.html` | 授权卡片拆分为「WebDAV 备份授权」+「定时任务授权与权限」；新增 3 个全局开关+AJAX 保存；定时任务列表按钮权限细化（编辑/删除独立判断） |
| `app.py` | migration_sqls 追加 2 条 ALTER TABLE |

> AI生成

## 第十七章 V10.3 推送全覆盖与用户级监控（2026-09-15）

### 17.1 需求总览

V10.3 批次覆盖 4 大方向：普通用户 WebDAV 配置体验对齐管理员、推送事件类型分类修正、全面补充缺失推送（18 处）、新增用户级 Webhook 监控过滤。

| 编号 | 模块 | 类型 | 需求 |
|------|------|------|------|
| 1 | WebDAV 配置 | 优化 | 普通用户 WebDAV 配置对齐管理员体验：密码回显、可查看密码、可测试连接、加密密码配置区、空值校验 |
| 2 | 事件分类 | 修复 | 礼金账本"全部删除"应为 clear、审计日志"清空"应为 clear、宴席移出明细应推送 update |
| 3 | 推送补缺 | 修复 | 排查出 18 处缺失推送的操作点需补充（app.py 6 处 + routes_ext.py 12 处） |
| 4 | 用户级监控 | 新增 | 管理员可自定义 Webhook 通道仅推送特定用户的操作或特定事件类型 |

### 17.2 模块 A：普通用户 WebDAV 配置体验对齐

**问题**：普通用户表单缺少密码回显、测试连接按钮、加密密码配置区，且空配置可保存。

**方案**：

1. **表单 HTML**（`admin_backups.html`）：
   - 密码输入框添加 `value="{{ config_data.get_webdav_password() or '' }}"` 回显
   - placeholder 改为 `请输入密码或应用授权码`
   - 地址/账号输入框添加 `required` 属性
   - 新增加密密码配置区（与管理员表单结构一致）
   - 新增"测试连接"按钮（`id="btnTestWebdavUser"`）
   - 新增清除加密密码复选框（`id="clearEncryptPwdUser"`）

2. **JS 函数**（`admin_backups.html`）：
   - `toggleClearEncryptPwdUser()`：勾选清除加密密码时禁用密码输入框
   - `btnTestWebdavUser` 事件监听：通过 AJAX 调用 `admin_test_webdav` 测试连接

3. **后端校验**（`routes_ext.py`）：
   - `admin_save_webdav_config` 路由新增空值校验：URL 和账号为空时返回错误提示

### 17.3 模块 B：推送事件类型分类修正

| 路由 | 文件 | 修正前 | 修正后 | 原因 |
|------|------|--------|--------|------|
| `delete_all_records` | app.py | `batch_delete` | `clear` | 全部清空≠批量删除，应归 clear 类 |
| `admin_clear_logs` | app.py | `security` | `clear` | 清空日志应归 clear 类 |
| `banquet_unlink_record` | routes_ext.py | 无推送 | `update` | 移出宴席明细是更新操作，需补充推送 |

### 17.4 模块 C：全面补充缺失推送（18 处）

**PAGE_EVENT_MATRIX 补充**（4 个页面）：

| 页面 | 原有事件 | 新增事件 |
|------|----------|----------|
| `admin_broadcasts` | create, broadcast | delete, status_change |
| `admin_webhooks` | create, update, delete, status_change | clear |
| `admin_users` | create, update, delete, status_change | batch_delete |
| `admin_backups` | create, update, delete, status_change, system | clear |

**app.py 补充推送（6 处）**：

| 路由 | event_type | 说明 |
|------|------------|------|
| `admin_batch_delete_users` | batch_delete | 批量删除用户 |
| `admin_batch_user_permissions` | update | 批量配置权限 |
| `admin_reset_user_security` | security | 重置用户密保 |
| `update_session_timeout` | system | 系统安全配置 |
| `admin_save_audit_log_config` | system | 审计日志配置 |
| `admin_set_registration_mode` | system | 注册模式变更 |

**routes_ext.py 补充推送（12 处）**：

| 路由 | event_type | 说明 |
|------|------------|------|
| `admin_toggle_broadcast` | status_change | 广播状态切换 |
| `admin_delete_broadcast` | delete | 删除广播 |
| `banquet_share` | update | 配置分享链接 |
| `banquet_share_delete` | delete | 删除分享链接 |
| `admin_delete_webhook_log` | delete | 删除推送日志 |
| `admin_batch_delete_webhook_logs` | batch_delete | 批量删除推送日志 |
| `admin_clear_webhook_logs` | clear | 清空推送日志 |
| `admin_delete_webdav_backup` | delete | 删除WebDAV备份 |
| `admin_upload_local_backup`（普通用户） | restore | 上传恢复（数据级合并） |
| `admin_upload_local_backup`（管理员） | restore | 上传恢复（文件级替换） |
| `admin_set_recycle_retention` | system | 回收站策略设置 |
| `admin_save_task_permissions` | system | 定时任务权限设置 |
| `admin_adopt_admin_config` | system | 采用管理员配置 |

### 17.5 模块 D：用户级 Webhook 监控过滤

**需求**：管理员可为每个 Webhook 通道配置"仅推送特定用户的操作"或"仅推送特定事件类型"，实现精细化监控。

**方案**：

1. **WebhookConfig 新增 2 字段**（`models.py`）：
   - `monitor_user_ids` (Text/JSON)：监控用户 ID 列表，空=不限制
   - `monitor_event_types` (Text/JSON)：监控事件大类列表，空=不限制

2. **trigger_webhook_event 新增过滤**（`webhook_utils.py`）：
   - 新增 `_get_monitor_user_ids()` / `_get_monitor_event_types()` / `_monitor_matches()` 辅助函数
   - 在事件开关+页面过滤之后，增加用户 ID 过滤和事件类型过滤
   - `monitor_user_ids` 为空 = 不限制用户；非空 = 仅推送列表内用户的操作
   - `monitor_event_types` 为空 = 不限制事件类型；非空 = 仅推送列表内事件大类

3. **前端 UI**（`admin_webhooks.html`）：
   - 新增/编辑 Modal 新增第 4 个 Tab「监控范围」
   - 用户多选列表（普通用户列表，复选框）
   - 事件类型多选列表（12 个事件大类，复选框）
   - 新增 `assembleMonitorData()` / `fillEditMonitor()` JS 函数

4. **保存路由**（`routes_ext.py`）：
   - `admin_create_webhook` / `admin_edit_webhook` 读取并保存 `monitor_user_ids` / `monitor_event_types`

5. **数据库迁移**（`app.py`）：
   - migration_sqls 追加 2 条 ALTER TABLE

### 17.6 涉及文件清单

| 文件 | 改动内容 |
|------|----------|
| `models.py` | WebhookConfig 新增 `monitor_user_ids`/`monitor_event_types` 字段 |
| `webhook_utils.py` | `trigger_webhook_event` 新增监控过滤；`PAGE_EVENT_MATRIX` 补充 4 页面；新增 `_monitor_matches` 等辅助函数 |
| `routes_ext.py` | 12 处缺失推送补充；`admin_save_webdav_config` 空值校验；`admin_create_webhook`/`admin_edit_webhook` 读取 monitor 字段；`admin_webhooks` 传参新增 `all_users` |
| `app.py` | 6 处缺失推送补充；3 处 event_type 修正；migration_sqls 追加 2 条 |
| `templates/admin_backups.html` | 普通用户 WebDAV 表单增强（密码回显+测试连接+加密密码区+required）；新增 `toggleClearEncryptPwdUser`/`btnTestWebdavUser` JS |
| `templates/admin_webhooks.html` | 新增/编辑 Modal 第 4 个 Tab「监控范围」+ JS 函数；编辑按钮 data 属性新增 monitor 数据 |

> AI生成

## 第十八章 V10.4 权限粒度优化与 Webhook 监控修复（2026-09-16）

### 18.1 需求总览

V10.4 批次覆盖 3 个方向：WebDAV 保存路由空值校验误拦截修复、权限级别 1 语义修正、Webhook 监控过滤未生效修复。

| 编号 | 模块 | 类型 | 需求 |
|------|------|------|------|
| 1 | WebDAV 配置 | 修复 | 普通用户"停用引用、自行配置"保存空表单时被后端空值校验+前端 required 双重拦截 |
| 2 | 权限管理 | 修复 | 权限级别 1（仅查看他人数据）被实现为"全只读"，连自身数据都不能增删改，需修正为"自身全权+他人只读" |
| 3 | Webhook 监控 | 修复 | trigger_webhook_event 调用未传 operator_id，导致用户级监控过滤形同虚设 |

### 18.2 方向一：WebDAV 保存路由空值校验修复

**问题**：普通用户点击"停用引用、自行配置"后保存空表单，被 `routes_ext.py:3778-3781` 后端空值校验 + `admin_backups.html` 前端 `required` 属性双重拦截。

**方案**：
1. `routes_ext.py`：移除 `admin_save_webdav_config` 中的 `if not server_url or not username` 空值校验块
2. `admin_backups.html`：移除普通用户 WebDAV 表单中 `webdav_url`、`webdav_username`、`webdav_password` 的 `required` 属性

### 18.3 方向二：权限级别 1 语义修正

**问题**：权限级别 1（仅查看他人数据）当前被实现为"全只读"模式——连自身数据都不能增删改导入，与用户预期不符。

**修正后语义**：

| 级别 | 前端标签 | 自身数据 | 他人数据 |
|------|----------|----------|----------|
| 0 | 仅管理自身数据 | 增删改查导入 | 不可见 |
| 1 | 自身全权 + 仅查看他人数据 | **增删改查导入** | **可查看，不可改不可删** |
| 2 | 查看+修改他人数据 | 增删改查导入 | 可查看可改，不可删 |
| 3 | 查看+修改+删除他人数据 | 增删改查导入 | 查改删 |

**后端核心函数修改**（app.py）：

| 函数 | 修改前 | 修改后 |
|------|--------|--------|
| `can_user_edit_entity` | `if perm == 1: return False` | 自身实体可编辑，他人实体需 perm >= 2 |
| `can_user_delete_entity` | `if perm in (1, 2): return False` | 自身实体 perm != 2 可删，他人实体需 perm >= 3 |
| `add_record` | `if perm == 1: abort(403)` | 移除拦截 |
| `batch_delete_records` | `if perm in (1, 2): abort(403)` | 改为 `if perm in (2,): abort(403)` |
| `import_csv` | `if perm == 1: abort(403)` | 移除拦截 |
| `PERM_LABELS` | `1: '查他人'` | `1: '自身全权+查他人'` |

**routes_ext.py 拦截点修改**（17 处）：
- 回收站 3 处：还原操作移除 `== 1` 拦截；彻底删除/清空 `in (1, 2)` → `in (2,)`
- 宴席 8 处：创建/同步移除 `== 1` 拦截；批量删除 `in (1, 2)` → `in (2,)`；编辑操作（移出/登记/引入/配置分享/删除分享）移除 `== 1` 前置条件，保留 `can_user_edit_entity` 检查
- 纪念日 5 处：创建/推送移除 `== 1` 拦截；批量删除 `in (1, 2)` → `in (2,)`
- 对账 1 处：无 `== 1` 拦截点（查看页面，无需修改）

**模板文件修改**（约 12 处）：
- `index.html`：移除新增按钮 `!= 1` 限制；`can_view_others` → `can_view_others_for('ledger')`
- `reminders.html`：移除 `== 1` 仅查看模式标签和相关按钮限制；`user_can_edit` 直接为 True
- `banquets.html`：移除 `== 1` 仅查看模式标签；批量删除 `in (1, 2)` → `in (2,)`
- `banquet_detail.html`：批量删除 `in (1, 2)` → `in (2,)`
- `recycle_bin.html`：移除 `== 1` 仅查看模式标签
- `admin_users.html`：权限标签和下拉选项描述更新为"自身全权 + 仅查看他人数据"

### 18.4 方向三：Webhook 监控过滤修复

**问题**：`trigger_webhook_event` 调用时未传 `operator_id`，导致 `_monitor_matches` 函数中 `if monitor_uids and operator_id is not None` 条件不满足（operator_id 为 None），跳过用户过滤（全部放行），监控配置形同虚设。

**排查结果**：全项目 82 处 `trigger_webhook_event` 调用中，17 处缺少 `operator_id` 参数。

**app.py 补充 14 处**：

| 路由 | event_type | page_key |
|------|------------|----------|
| `add_record` | record_create | ledger |
| `edit_record` | record_update | ledger |
| `delete_record` | record_delete | ledger |
| `batch_delete_records` | batch_delete | ledger |
| `delete_all_records` | clear | ledger |
| `change_password` | security | security |
| `generate_invite_link` | system | invites |
| `admin_delete_invite_link` | record_delete | invites |
| `admin_batch_delete_invite_links` | batch_delete | invites |
| `admin_update_user_permissions` | status_change | admin_users |
| `admin_toggle_user_status` | status_change | admin_users |
| `admin_reset_user_pass` | security | admin_users |
| `admin_delete_user` | record_delete | admin_users |
| `import_csv` | record_create | ledger |

**routes_ai.py 补充 3 处**：

| 路由 | event_type | page_key |
|------|------------|----------|
| `api_ai_delete_session` | record_delete | ai_assistant |
| `api_ai_save_config` | system | ai_config |
| `api_ai_set_auth` | status_change | ai_config |

**不修改 1 处**：
- `routes_ext.py:349` `check_and_trigger_due_reminders`：后台定时任务，无 `current_user` 上下文，`force_channels=True` 跳过全部过滤

### 18.5 涉及文件清单

| 文件 | 改动内容 |
|------|----------|
| `routes_ext.py` | 移除 WebDAV 空值校验；17 处权限拦截点修改 |
| `app.py` | 6 处权限核心函数/路由修改；14 处 webhook 调用补充 operator_id；PERM_LABELS 更新 |
| `routes_ai.py` | 3 处 webhook 调用补充 operator_id |
| `templates/admin_backups.html` | 移除 3 个 required 属性 |
| `templates/index.html` | 移除新增按钮限制；can_view_others → can_view_others_for('ledger') |
| `templates/reminders.html` | 移除 == 1 限制标签和按钮限制 |
| `templates/banquets.html` | 移除 == 1 限制标签；批量删除条件修改 |
| `templates/banquet_detail.html` | 批量删除条件修改 |
| `templates/recycle_bin.html` | 移除 == 1 仅查看模式标签 |
| `templates/admin_users.html` | 权限标签和下拉选项描述更新 |

## 第十九章 V10.5 Webhook 推送系统增强（2026-09-16）

### 19.1 需求总览

V10.5 批次覆盖 3 个方向：监控范围增加管理员用户、基础事件与监控范围页面增加全选/清空按钮、Webhook 推送全覆盖审计与补全。

| 编号 | 模块 | 类型 | 需求 |
|------|------|------|------|
| 1 | Webhook 监控 | 增强 | 监控范围用户列表仅含普通用户，管理员操作无法被监控推送 |
| 2 | Webhook 配置 UI | 增强 | 基础事件开关 Tab 和监控范围 Tab 缺少全选/清空按钮（矩阵 Tab 已有） |
| 3 | Webhook 推送覆盖 | 审计补全 | 全项目 131 个路由函数系统性审计，14 个写操作缺少推送调用 |

### 19.2 方向一：监控范围增加管理员用户

**问题**：`routes_ext.py` 行 3118 和 3593 的 `all_users` 查询使用 `filter_by(is_admin=False)`，管理员不在监控用户勾选列表中，导致管理员操作无法被监控推送（`_monitor_matches` 中 `operator_id not in monitor_uids → return False`）。

**方案**：
1. `routes_ext.py` 两处 `all_users` 查询改为 `User.query.order_by(User.is_admin.desc(), User.id).all()`（管理员排前面）
2. `admin_webhooks.html` 新增/编辑模态框中，用户名后增加管理员标识 `{{ u.username }}{% if u.is_admin %}（管理员）{% endif %}`
3. 空列表提示从"暂无普通用户"改为"暂无用户"

### 19.3 方向二：基础事件与监控范围页面增加全选/清空按钮

**问题**：Tab2 推送配置矩阵已有全选/清空按钮（`matrixSelectAll`/`matrixClearAll`），但 Tab1 基础事件开关（8 个复选框）和 Tab4 监控范围（监控用户+监控事件类型）缺少。

**方案**：
- Tab1 新增/编辑模态框：在事件开关区域上方添加全选/清空按钮，复选框添加 `event-switch-cb` class
- Tab4 新增/编辑模态框：监控用户区域添加用户全选/清空按钮，监控事件类型区域添加事件全选/清空按钮
- JS 新增 6 个函数：`eventSelectAll`、`eventClearAll`、`monitorUserSelectAll`、`monitorUserClearAll`、`monitorEventSelectAll`、`monitorEventClearAll`，均接收 prefix 参数区分 new/edit

### 19.4 方向三：推送全覆盖审计与补全

#### 审计总览

| 文件 | 路由函数总数 | 已有推送 | 无需推送 | 缺少推送 |
|------|------------|---------|---------|---------|
| app.py | 36 | 23 | 6 | 7（含登录成功+失败2处） |
| routes_ext.py | 82 | 62 | 16 | 6 |
| routes_ai.py | 13 | 3 | 8 | 2 |
| **合计** | **131** | **88** | **30** | **14** |

#### app.py 补充 7 处推送

| 路由 | event_type | page_key | 说明 |
|------|------------|----------|------|
| `login`（成功） | security | security | 登录成功安全事件 |
| `login`（失败） | security | security | 登录失败安全事件 |
| `register` | system | security | 新用户注册 |
| `forgot_password` | security | security | 密保重置密码 |
| `logout` | security | security | 退出登录 |
| `admin_user_credentials` | security | admin_users | 查看用户明文密码+密保 |
| `export_csv` | security | ledger | 批量数据导出 |

#### routes_ext.py 补充 6 处推送

| 路由 | event_type | page_key | 说明 |
|------|------------|----------|------|
| `toggle_share_ledger` | status_change | ledger | 切换共享链接启用/禁用 |
| `banquet_export_excel` | security | banquets | 导出宴席台账CSV |
| `admin_upload_attachment` | system | admin_backups | 上传附件文件 |
| `admin_test_webdav` | system | admin_backups | 测试WebDAV连接 |
| `admin_download_local_backup` | security | admin_backups | 下载本地数据库备份 |
| `admin_restore_webdav_backup`（普通用户路径） | restore | admin_backups | 数据级合并恢复成功 |

#### routes_ai.py 补充 2 处推送

| 路由 | event_type | page_key | 说明 |
|------|------------|----------|------|
| `api_ai_session_create` | system | ai_assistant | 创建AI会话 |
| `api_ai_session_rename` | system | ai_assistant | 重命名AI会话 |

#### 不补充推送的函数（2 个，用户确认）

| 路由 | 原因 |
|------|------|
| `admin_test_webhook` | 循环推送风险：测试推送本身即触发 webhook |
| `api_ai_chat` | AI 聊天高频调用，推送会造成大量噪音 |

### 19.5 涉及文件清单

| 文件 | 改动内容 |
|------|----------|
| `routes_ext.py` | 2 处 all_users 查询含管理员；6 处补充 trigger_webhook_event |
| `app.py` | 7 处补充 trigger_webhook_event（含登录成功+失败） |
| `routes_ai.py` | 2 处补充 trigger_webhook_event |
| `templates/admin_webhooks.html` | Tab1/Tab4 全选清空按钮；管理员标识；6 个 JS 函数 |