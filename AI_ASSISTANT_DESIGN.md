---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'ca8b6e36-4c79-4033-9663-00e0db20fd43'
  PropagateID: 'ca8b6e36-4c79-4033-9663-00e0db20fd43'
  ReservedCode1: '1b6621b5-87da-4fe2-b875-17d42f09a1ce'
  ReservedCode2: '1b6621b5-87da-4fe2-b875-17d42f09a1ce'
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