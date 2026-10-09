---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '1b232354-e410-498f-9bf7-470d56e411d1'
  PropagateID: '1b232354-e410-498f-9bf7-470d56e411d1'
  ReservedCode1: '9d894392-9c41-47c7-b912-2ac2560b67ef'
  ReservedCode2: '9d894392-9c41-47c7-b912-2ac2560b67ef'
---

# 人情礼金记账系统 PSD 设计与重构决策文档

> **版本**：V10.11.8  
> **生成日期**：2026-10-09  
> **项目根目录**：`C:\Users\cheng\Documents\akshare-test\gift_bookkeeping_app`  
> **审计基线**：代码 commit `f1e6744`（main 分支，filter-repo 重写后；原 6360bb6），README.md V10.10.10，Project_Survey.md ADR-01~38  
> **文档定位**：以代码为实现真相（Ground Truth），历史文档为设计意图真相，显式揭露漂移，证据链闭环。

---

## 目录

- [阶段 0：资产自发现与执行计划](#阶段-0资产自发现与执行计划)
- [第 1 部分：项目全局概览](#第-1-部分项目全局概览)
- [第 2 部分：文档-代码差异与漂移矩阵 (Drift Matrix)](#第-2-部分文档-代码差异与漂移矩阵-drift-matrix)
- [第 3 部分：架构模式识别](#第-3-部分架构模式识别)
- [第 4 部分：架构耦合度诊断](#第-4-部分架构耦合度诊断)
- [第 5 部分：架构替换与轻量化可行性决策](#第-5-部分架构替换与轻量化可行性决策)
- [第 6 部分：前后端详尽规格（校准整合版）](#第-6-部分前后端详尽规格校准整合版)
- [第 7 部分：数据持久化设计](#第-7-部分数据持久化设计)
- [第 8 部分：工程与安全保障](#第-8-部分工程与安全保障)
- [第 9 部分：综合问题排查与渐进演进路线图](#第-9-部分综合问题排查与渐进演进路线图)

---

## 阶段 0：资产自发现与执行计划

### 0.1 历史设计资产探测

递归检索项目内所有 `.md` 文档及含有架构/设计/规范关键字的文件，共发现 **4 份历史文档**：

| # | 文件路径 | 行数 | 预估用途 | 时效性判定 |
|---|---------|------|---------|-----------|
| 1 | `README.md` | 1042 | **用户手册 + 版本变更日志**（V2~V10.10.10，含功能说明、部署指南、样例数据、多仓库矩阵） | **新** — 最后更新 2026-09-22，版本迭代到 V10.10.10，与代码高度同步 |
| 2 | `Project_Survey.md` | 948+ | **系统架构设计规范 + ADR 决策记录**（ADR-01~ADR-38，含 6 大故障根因审计、业务模块设计规范、权限模型、Webhook/WebDAV/纪念日架构决策） | **新** — 最后更新 2026-09-22，ADR 追加到 38 条，是核心设计意图资产 |
| 3 | `AI_ASSISTANT_DESIGN.md` | 1932+ | **AI 助手模块技术设计 + 综合修复记录**（ER 图、API 规范、前端设计、V2~V10.7 逐版本修复详情） | **较新** — 最后更新约 V10.7（2026-09-17），后续 V10.8~V10.10.10 的修复记录仅在 README.md 中，未同步至此文档 |
| 4 | `V8_修复设计方案.md` | 240 | **V8 修复设计方案**（12 项需求的独立方案文档，已确认定稿） | **草稿/已归档** — 内容已被 AI_ASSISTANT_DESIGN.md 第十二章完整吸收，无独立参考价值 |

### 0.2 代码骨架与技术栈初判

#### 代码体量分布（行数为编辑器总行数口径，2026-09-23 实测）

| 文件 | 行数 | 占比 | 职责 |
|------|------|------|------|
| `routes_ext.py` | 5,231 | 40.3% | 业务扩展路由（最大单体文件） |
| `app.py` | 3,193 | 24.6% | Flask 核心 + 礼金 CRUD + 用户管理 |
| 21 个 HTML 模板 | 11,785 | — | 前端视图层（最大 1,527 行） |
| `models.py` | 1,071 | 8.2% | 22+ 张数据表模型定义 |
| `webhook_utils.py` | 918 | 7.1% | Webhook 推送引擎 |
| `webdav_utils.py` | 556 | 4.3% | WebDAV 客户端 |
| `run.sh` | 551 | 4.2% | 部署脚本 |
| `ai_service.py` | 424 | 3.3% | AI 核心服务 |
| `routes_ai.py` | 423 | 3.3% | AI 路由 |
| `gift_utils.py` | 322 | 2.5% | NLP 与对账工具 |
| 其他 | 302 | 2.3% | SSL 生成（152）、Web 搜索（81）、Nginx 配置（69） |
| **核心代码合计** | **12,991** | — | 不含模板；含模板共 24,776 行 |

#### 模板文件行数

| 文件 | 行数 |
|------|------|
| `admin_webhooks.html` | 1527 |
| `admin_users.html` | 1359 |
| `admin_backups.html` | 1249 |
| `index.html` | 1079 |
| `banquet_detail.html` | 994 |
| `reminders.html` | 862 |
| `banquets.html` | 648 |
| `ai_assistant.html` | 502 |
| `permission_tickets.html` | 461 |
| `admin_ai_config.html` | 450 |
| `base.html` | 493 |
| `recycle_bin.html` | 370 |
| `reconciliation.html` | 368 |
| `admin_logs.html` | 265 |
| `profile_security.html` | 262 |
| `admin_broadcasts.html` | 231 |
| `login.html` | 199 |
| `forgot_password.html` | 193 |
| `register.html` | 171 |
| `shared_ledger.html` | 261 |
| `change_password.html` | 52 |
| **合计** | **11,990** |

### 0.3 文档采纳决策

| 文档 | 采纳角色 | 理由 |
|------|---------|------|
| `Project_Survey.md` | **架构意图主源** | 38 条 ADR 是架构决策的权威记录，业务模块设计规范详尽 |
| `README.md` | **功能现状与版本演进主源** | 版本变更日志完整到 V10.10.10，功能清单与部署指南准确 |
| `AI_ASSISTANT_DESIGN.md` | **AI 模块与 V2~V10.7 修复细节参考** | ER 图、API 规范、前端设计详实，但需标注 V10.8+ 记录缺失 |
| `V8_修复设计方案.md` | **排除**（已被 AI_ASSISTANT_DESIGN.md 第十二章完整吸收） | 独立草稿，无增量信息 |

> **归档说明**（2026-09-23）：上表所列 Project_Survey.md、AI_ASSISTANT_DESIGN.md、V8_修复设计方案.md 三份历史文档，已在本 PSD 定稿后移入回收站归档。全文对其引用均记录审计时点状态，不影响本 PSD 的代码事实结论。

---

## 第 1 部分：项目全局概览

### 1.1 业务定位

人情礼金记账系统（Gift Bookkeeping App）是一套面向中国家庭/小团队的人情往来资产管理工具，核心解决三大痛点：
1. **礼金收支记账**：收礼/送礼双向记录，自然语言复合拆分一键入库
2. **人情对账追踪**：按亲友聚合收送差额，自动判定"待补礼/待还礼/已平账"
3. **多渠道预警推送**：企业微信/钉钉/飞书 Webhook + 企微官方长连接机器人，纪念日到期主动推送

系统具备多用户细粒度权限、WebDAV 加密云备份、AI 助手、权限工单审批等企业级能力，部署形态覆盖 Web 原生、Docker Compose 和 Android APK 三种交付。

### 1.2 真实技术栈全景清单

| 层级 | 技术选型 | 版本 | 代码依据 |
|------|---------|------|---------|
| **后端语言** | Python | 3.12（本地）/ 3.11-slim（Docker） | `run.sh:367` |
| **Web 框架** | Flask | 3.0.3 | `requirements.txt:1`、`app.py:42` |
| **ORM** | Flask-SQLAlchemy | 3.1.1 | `requirements.txt:2`、`models.py:75` |
| **认证** | Flask-Login (Session) | 0.6.3 | `requirements.txt:4`、`app.py:90-93` |
| **CSRF** | Flask-WTF | 1.2.1 | `requirements.txt:3`、`app.py:214-238` |
| **密码哈希** | Werkzeug | 3.0.3 | `requirements.txt:5`、`models.py:9` |
| **对称加密** | cryptography (AES-256-GCM) | 42.0.8 | `requirements.txt:7`、`models.py:10,27-43` |
| **数据库** | SQLite (WAL) / PostgreSQL (可选) | — | `app.py:68-78`，`DATABASE_URL` 环境变量切换 |
| **PostgreSQL 驱动** | psycopg2-binary + psycopg[binary]（V10.10.20 新增，SQLAlchemy 2.0 默认 psycopg3 驱动） | 2.9.9 / >=3.1 | `requirements.txt:8-9`（切换 PostgreSQL 的必要依赖；psycopg2-binary 供 webhook_utils 原生连接保留） |
| **WSGI 容器** | Gunicorn (已声明但**未实际使用**) | 22.0.0 | `requirements.txt:6`；`run.sh:167-174` 实际用 `python3 app.py` |
| **反向代理** | Nginx (SNI 多项目 443) | — | `nginx_ssl.conf`、`run.sh:224-291` |
| **前端** | Jinja2 + Bootstrap 5 + 原生 JS | — | `templates/base.html:23-25、256`（**V10.10.18 已本地化 `static/vendor/` 加载**） |
| **图表** | ECharts 5.5.0（V10.11 新增，本地化 `static/vendor/echarts/`） | 5.5.0 | `templates/dashboard.html`、`static/vendor/echarts/5.5.0/echarts.min.js` |
| **Excel 解析** | openpyxl（V10.11 新增） | >=3.1.0 | `requirements.txt:18`、`routes_ext.py` 导入路由 |
| **PDF 生成** | reportlab（V10.11 新增） | >=4.0.0 | `requirements.txt:19`、`pdf_generator.py` |
| **长图海报** | html2canvas（V10.11 新增，本地化 `static/vendor/html2canvas/`） | 1.4.1 | `templates/poster_template.html`、`static/vendor/html2canvas/1.4.1/html2canvas.min.js` |
| **PWA** | Service Worker | — | `static/sw.js`（1053 bytes） |
| **AI 接入** | OpenAI Python SDK | >=1.0.0 | `requirements.txt:14`、`ai_service.py` |
| **联网搜索** | DuckDuckGo Search | >=4.0.0 | `requirements.txt:15`、`web_search.py` |
| **企微机器人** | wecom-aibot-python-sdk | >=1.0.2 | `requirements.txt:11`、`aibot/` 目录 |
| **企微 SDK 运行依赖** | websockets + pyee | >=12.0 / >=11.0 | `requirements.txt:12-13`（长连接与事件循环） |
| **Webhook 网络** | requests + aiohttp | >=2.31.0 / >=3.9.0 | `requirements.txt:9-10`、`webhook_utils.py:18,47` |
| **加密备份** | pyzipper | >=0.3.1 | `requirements.txt:16`、`webdav_utils.py` |
| **部署脚本** | POSIX Shell (`#!/bin/sh`) | — | `run.sh:1`（551 行，兼容 dash/sh） |
| **SSL 证书** | 自签（cryptography 库生成） | — | `generate_ssl_certs.py` |

### 1.3 端到端架构拓扑图

```mermaid
graph TB
    subgraph "客户端层"
        WEB[浏览器 Web 端<br/>Jinja2 + Bootstrap 5 + 原生JS]
        APK[Android APK<br/>WebView 封装]
    end

    subgraph "接入层"
        NGINX[Nginx 反向代理<br/>SNI 多项目 443 端口<br/>TLS 1.2/1.3 + HTTP/2]
    end

    subgraph "应用层 Flask 单体"
        APP[app.py 3193行<br/>核心路由 + 认证 + 权限引擎<br/>礼金CRUD + 用户管理 + 审计日志]
        EXT[routes_ext.py 5231行<br/>宴席/对账/纪念日/回收站<br/>广播/备份/工单/Webhook CRUD<br/>WeCom回调 + 定时调度器]
        AI[routes_ai.py 423行<br/>AI 聊天/会话/配置/授权]
        GIFT[gift_utils.py 322行<br/>NLP分词 + 中文大写 + 对账聚合]
        WHK[webhook_utils.py 918行<br/>推送矩阵 + 模板 + 脱敏<br/>企微SDK长连接 + 监控过滤]
        WDV[webdav_utils.py 556行<br/>WebDAV客户端 + 加密zip]
        AIS[ai_service.py 424行<br/>多配置优先级 + 联网搜索 + 兜底]
    end

    subgraph "后台守护线程"
        T1[_anniversary_reminder_worker<br/>每60秒巡检纪念日]
        T2[_backup_scheduler_worker<br/>每60秒检查定时备份]
        T3[_wecom_listener_worker<br/>企微长连接常驻监听]
    end

    subgraph "数据层"
        SQLite[(SQLite WAL 模式<br/>22+ 张表<br/>data/gift_bookkeeping.db)]
        PG[(PostgreSQL<br/>可选, DATABASE_URL切换)]
    end

    subgraph "外部服务"
        WDAV[WebDAV 云端<br/>坚果云/NAS/Nextcloud]
        WHK_EXT[Webhook 目标<br/>企微/钉钉/飞书/Bark]
        WECOM[企业微信官方<br/>wss://openws.work.weixin.qq.com]
        OPENAI[OpenAI 兼容 API<br/>多配置优先级]
        DDG[DuckDuckGo Search]
    end

    WEB --> NGINX
    APK --> NGINX
    NGINX -->|http://127.0.0.1:11443| APP
    APP --> EXT
    APP --> AI
    EXT --> GIFT
    EXT --> WHK
    EXT --> WDV
    AI --> AIS

    APP --> SQLite
    EXT --> SQLite
    AI --> SQLite
    SQLite -.->|DATABASE_URL| PG

    T1 --> SQLite
    T1 --> WHK
    T2 --> SQLite
    T2 --> WDV
    T3 --> WECOM
    T3 --> SQLite

    WDV --> WDAV
    WHK --> WHK_EXT
    WHK --> WECOM
    AIS --> OPENAI
    AIS --> DDG
```

---

## 第 2 部分：文档-代码差异与漂移矩阵 (Drift Matrix)

> 以下矩阵基于 `Project_Survey.md`（38 条 ADR）、`AI_ASSISTANT_DESIGN.md`、`README.md` 与实际代码的逐条交叉核验。

### 2.1 关键漂移项

| # | 模块/功能 | 历史文档记载 | 代码真实实现 | 状态 | 影响评估 |
|---|---------|------------|------------|------|---------|
| D-01 | **akshare 金融数据集成** | `Project_Survey.md` §3 详述 akshare 集成方案、熔断/降级/超时守卫规范；§1.1 定位含"金融量化/市场数据中台能力" | `requirements.txt` 无 akshare 依赖；全项目无 `import akshare`；`web_search.py` 仅用 DuckDuckGo | **未落地** | **低** — 业务上从未使用，文档描述与系统实际定位脱节，建议从文档中标注为"规划中/搁置" |
| D-02 | **Gunicorn 多 Worker 生产部署** | `Project_Survey.md` ADR-01 决策"全面采用 Gunicorn -w 4 -k gthread --threads 4"；`requirements.txt:6` 声明 gunicorn==22.0.0 | `run.sh:362-368` 实际启动命令为 `python3 $APP_SCRIPT`（Werkzeug 开发服务器），无 Gunicorn 调用 | **已废弃** | **高** — 开发服务器在生产环境存在并发瓶颈（Project_Survey.md §2 BUG-02 已诊断此问题），ADR-01 的解决方案未落地 |
| D-03 | **CDN 依赖彻底移除** | `Project_Survey.md` ADR-03 决策"彻底移除国外外部公共 CDN 链接，静态资源本地化" | ~~仍从 `cdn.jsdelivr.net`/`cdnjs.cloudflare.com` 加载~~ **✅ V10.10.18 已落地**：`static/vendor/` 本地化 14 个资源文件（Bootstrap 5.3.0/Font Awesome 6.4.0/Bootstrap Icons 1.11.3，版本与原 CDN 一致），`base.html` 4 处 + `shared_ledger.html` 2 处改为 `url_for` 本地引用 | **已落地** | **高→已清偿** — 内网/弱网白屏问题（BUG-04）随之解决 |
| D-04 | **Celery/Redis 任务队列** | `Project_Survey.md` ADR-04 决策"企业级方案引入 Redis + Celery 任务队列" | 代码使用 Python `threading.Thread` daemon 线程（`_anniversary_reminder_worker`、`_backup_scheduler_worker`、`_wecom_listener_worker`），无 Celery/Redis 依赖 | **方案降级** | **低** — 对当前单机部署规模合理，但文档应标注实际选型为轻量线程池方案 |
| D-05 | **权限级别 1 语义** | `Project_Survey.md` ADR-25 决策"级别 1 为全局绝对全只读模式，严禁修改或删除任何数据（包括自身创建的实体）" | V10.4 已修正为"自身全权 + 仅查看他人数据"（`app.py` `can_user_edit_entity` 自身实体可编辑，他人实体需 perm>=2）；`README.md` V10.4 记录了此变更但 ADR-25 未更新 | **已重构** | **中** — ADR-25 文档与代码语义矛盾，需更新 ADR 或新增 ADR 记录此次修正 |
| D-06 | **AI_ASSISTANT_DESIGN.md 版本覆盖** | 文档覆盖到 V10.7（2026-09-17），含 ER 图/API 规范/前端设计/逐版本修复 | V10.8~V10.10.10（约 20+ 条修复）仅在 `README.md` 变更日志中，未同步至本文档 | **版本断层** | **低** — 文档参考价值降低但不影响运行；新 PSD 应以 README.md 为最新事实源 |
| D-07 | **Service Worker 超时熔断** | `Project_Survey.md` BUG-06 决策"为 Service Worker fetch 增加超时限制与离线降级分支" | `static/sw.js` 仅 1053 bytes，无 `fetch` 事件拦截逻辑，无超时/降级代码 | **未落地** | **低** — 当前 SW 仅做 manifest 缓存壳，实际未拦截请求，反而避免了 BUG-06 描述的问题 |
| D-08 | **数据库连接超时** | `Project_Survey.md` ADR-02 决策 `connect_args={'timeout': 30}` | `app.py:83-84` 确实设置 `'timeout': 30`；`app.py:878-879` 设置 `PRAGMA busy_timeout=30000` | **一致** | — |
| D-09 | **AES-256-GCM 加密存储** | `Project_Survey.md` ADR-05/ADR-36 决策"敏感凭据 AES-256-GCM 加密落盘" | `models.py:27-43` `encrypt_credential`/`decrypt_credential` 实现 AESGCM；`WebhookConfig._secret_token`/`_bot_secret`、`BackupConfig._backup_encrypt_password`、`User._ai_api_key`、`SharedLedgerLink._access_password` 均密文存储 | **一致** | — |
| D-10 | **CSRF 全局保护** | `Project_Survey.md` ADR-05 决策"CSRF 强校验" | `app.py:214-238` 手动实现 CSRF token 生成与校验（非依赖 Flask-WTF 内置 decorator），企微回调/根路径/Webhook 接口免除 | **一致** | — |

### 2.2 漂移影响汇总

| 严重度 | 数量 | 漂移项 |
|--------|------|--------|
| **高影响** | 1 | D-02（Gunicorn 未落地）；D-03（CDN 未移除）✅ 已于 V10.10.18 清偿 |
| **中影响** | 1 | D-05（权限级别 1 语义矛盾） |
| **低影响** | 4 | D-01（akshare 未落地）、D-04（Celery 降级）、D-06（文档断层）、D-07（SW 未落地） |
| **一致** | 3 | D-08、D-09、D-10 |

---

## 第 3 部分：架构模式识别

### 3.1 模式判定：经典单体应用（Monolith）

**判定依据**：

| 维度 | 观察结论 | 代码依据 |
|------|---------|---------|
| **部署单元** | 单一 Python 进程，无微服务拆分 | `run.sh:362` `python3 $APP_SCRIPT` |
| **路由装配** | Flask 单 app 实例 + `register_routes_ext()` 注册扩展路由 + `routes_ai` 模块注册 AI 路由 | `app.py:33` `from routes_ext import register_routes_ext`；`routes_ext.py` 在函数内用 `@app.route` 注册 |
| **数据访问** | 全量 ORM（SQLAlchemy），无 Repository/DAO 抽象层；Model 直接在路由中 `query` | `app.py:960` `get_accessible_records_query(current_user)` 直接操作 Model |
| **通信模式** | 进程内同步调用，无 RPC/消息队列；异步任务用 daemon 线程 | `routes_ext.py:7` `import threading`；无 Celery/RabbitMQ/Kafka |
| **状态管理** | 服务端 Session（Flask-Login），无 JWT/Token 无状态设计 | `app.py:90-93` `LoginManager` |
| **前端渲染** | 服务端渲染（Jinja2 SSR），无 SPA/CSR 分离 | `templates/*.html` 21 个模板 |

### 3.2 分层结构（实际 vs 理想）

```
理想分层:                          实际分层:
┌─────────────────┐               ┌─────────────────────┐
│  Controller     │               │  Route Handler      │  ← 胖 Controller
│  (薄路由)        │               │  (路由+业务+数据访问  │     (app.py 3193行
├─────────────────┤               │   +权限校验+日志     │      routes_ext.py 5231行)
│  Service        │               │   +Webhook推送       │
│  (业务逻辑)     │  ← 缺失       ├─────────────────────┤
├─────────────────┤               │  Model              │
│  Repository     │  ← 缺失       │  (SQLAlchemy ORM     │
├─────────────────┤               │   +加解密property    │
│  Model          │               │   +权限方法)          │
└─────────────────┘               └─────────────────────┘
```

**关键发现**：系统**无 Service 层和 Repository 层**，业务逻辑直接内嵌在路由函数中。权限校验、Webhook 推送、审计日志、数据查询全部在同一个函数内完成，形成典型的**胖 Controller 反模式**。

### 3.3 模块间通信模式

| 通信类型 | 实现方式 | 代码依据 |
|---------|---------|---------|
| **同步 HTTP** | Flask 路由处理 → Jinja2 渲染 → 返回 HTML | 全部 `@app.route` |
| **AJAX 异步** | 前端 `fetch()` → 后端 `jsonify()` | `templates/base.html:233-259` 全局 Fetch 拦截器 |
| **后台线程** | `threading.Thread(daemon=True)` 三常驻线程 | `routes_ext.py` 三个 worker 函数 |
| **外部 HTTP** | `requests.Session()` 连接池 | `webhook_utils.py:47`、`webdav_utils.py` |
| **WebSocket 长连接** | `aibot.WSClient` 企微官方 SDK | `webhook_utils.py:29` `from aibot import WSClient` |
| **数据库直连** | SQLite 文件级 / PostgreSQL TCP | `app.py:80` `SQLALCHEMY_DATABASE_URI` |

---

## 第 4 部分：架构耦合度诊断

### 4.1 纯业务代码（框架无关，可直接复用）

| 模块 | 文件 | 行数 | 复用评估 |
|------|------|------|---------|
| NLP 分词引擎 | `gift_utils.py:58-86` `split_gift_nlp_text` | ~30 | 纯 Python 正则，零框架依赖，**可直接复用** |
| 中文大写数字转换 | `gift_utils.py:13-55` `cn2num` | ~43 | 纯算法，零依赖，**可直接复用** |
| 对账聚合计算 | `gift_utils.py` `calculate_reconciliation` | ~50 | 纯数据计算逻辑，**可直接复用** |
| AES-256-GCM 加解密 | `models.py:14-73` `encrypt_credential`/`decrypt_credential` | ~60 | 仅依赖 `cryptography` 库，**可直接复用** |
| CSV 导出逻辑 | `app.py:2961-2998` `export_csv` 核心 | ~40 | CSV 格式化逻辑可复用，路由绑定需剥离 |
| Cron 表达式解析 | `routes_ext.py` `_cron_match` | ~40 | 纯算法，**可直接复用** |

**纯业务代码占比估计：约 15-20%**（~2,200 行）

### 4.2 强侵入代码（强依赖框架 API，替换必须重写）

| 模块 | 文件 | 行数 | 耦合点 |
|------|------|------|--------|
| **全部路由处理** | `app.py` + `routes_ext.py` + `routes_ai.py` | ~7,942 | `@app.route`、`request`/`flash`/`redirect`/`url_for`/`jsonify`、`render_template` |
| **认证中间件** | `app.py:155-261` | ~107 | `@app.before_request`、`current_user`、`login_user`/`logout_user`、`session` |
| **CSRF 保护** | `app.py:214-238` | ~25 | Flask `request.form`/`session`/`abort` |
| **模板渲染** | 21 个 HTML 模板 | 11,785 | Jinja2 模板语法 `{% %}`、`{{ }}`、`url_for()` |
| **ORM 模型** | `models.py` 全量 | 1,071 | `db.Model`、`db.Column`、`db.relationship`、`db.session` |
| **Webhook 推送引擎** | `webhook_utils.py` | 918 | `trigger_webhook_event` 直接操作 `WebhookConfig.query` |
| **权限引擎** | `app.py` `can_user_*` 系列 + `models.py` `get_menu_perm` | ~200 | 与 Flask `current_user`、SQLAlchemy `query` 深度耦合 |

**强侵入代码占比估计：约 80-85%**

### 4.3 分层退化坏味道

#### 坏味道 1：胖 Controller — 路由函数承载全部逻辑

**典型代码**：`routes_ext.py` `admin_upload_local_backup` 路由（~130 行）

```
路由函数内完成：
  ① 文件上传校验 → ② 文件命名/归属校验 → ③ 数据库完整性检查 →
  ④ 权限判定（管理员/普通用户分流）→ ⑤ 文件级替换 或 数据级合并 →
  ⑥ ATTACH DATABASE 跨库操作 → ⑦ init_database 迁移 →
  ⑧ Webhook 推送 → ⑨ 审计日志 → ⑩ Flash 提示 + 重定向
```

**影响**：单个函数职责超过 10 个，任何修改都有高回归风险。

#### 坏味道 2：SQL 外露 — ORM 之外直接执行原生 SQL

**典型代码**：`routes_ext.py:47-105` `build_user_scoped_backup_db`

```python
# 直接 sqlite3.connect 而非 SQLAlchemy
_src_conn = _sqlite3.connect(db_path)
_dst_conn = _sqlite3.connect(tmp_db)
with _dst_conn:
    _src_conn.backup(_dst_conn)
# 直接执行 DELETE/DROP TABLE
c.execute("DELETE FROM gift_records WHERE user_id != ?", (user.id,))
c.execute(f'DROP TABLE IF EXISTS "{tbl}"')
```

**影响**：绕过 ORM 的事务管理和连接池，存在数据库状态不一致风险。

#### 坏味道 3：数据库迁移硬编码 SQL — 无版本管理

**典型代码**：`app.py:681-817` `init_database` migration_sqls

```python
migration_sqls.extend([
    "ALTER TABLE backup_configs ADD COLUMN config_alias VARCHAR(100)",
    "ALTER TABLE backup_configs ADD COLUMN adopted_from_admin BOOLEAN DEFAULT 0",
    ...
])
# 逐条 try-except 忽略错误
for sql in migration_sqls:
    try:
        conn.execute(db.text(sql))
        conn.commit()
    except Exception:
        pass  # 已存在则跳过
```

**影响**：无 Alembic/Flask-Migrate 版本管理，迁移失败被静默吞没，无法回滚。

#### 坏味道 4：路由文件膨胀失控

| 文件 | 行数 | 路由数量（估计） | 单文件职责 |
|------|------|---------------|---------|
| `routes_ext.py` | 5,231 | ~82 个路由 | 宴席/对账/纪念日/回收站/广播/备份/工单/Webhook/WeCom/定时任务 |
| `app.py` | 3,193 | ~37 个路由 | 礼金CRUD/认证/用户管理/审计日志/安全配置/导出导入 |

**影响**：单文件 5231 行已超出可维护阈值，模块边界模糊。

#### 坏味道 5：前端逻辑内联 — JS 与 HTML 混杂

`admin_webhooks.html`（1527 行）中包含大量内联 `<script>`，矩阵配置/事件绑定/AJAX 逻辑全部嵌在 HTML 中，无独立 JS 模块。

---

## 第 5 部分：架构替换与轻量化可行性决策

### 5.1 评估动机

| 评估维度 | 当前状态 | 是否存在瓶颈 |
|---------|---------|------------|
| **框架重量** | Flask 3.0 轻量级，无过度抽象 | **否** — Flask 本身足够轻量，非瓶颈 |
| **并发性能** | Werkzeug 开发服务器单线程 | **是** — 生产部署仍用 `python3 app.py`，无多 Worker（D-02 漂移） |
| **代码可维护性** | 5231 行单文件，无 Service 层 | **是** — 胖 Controller 已导致修改回归风险高 |
| **前端体验** | Jinja2 SSR + 本地静态资源 + 内联 JS | **否** — V10.10.18 前端资源已本地化（D-03 已清偿），SSR 满足业务需求 |
| **数据库扩展** | SQLite WAL 足够单机场景 | **否** — 已支持 PostgreSQL 无缝切换 |
| **部署复杂度** | 单文件部署 + run.sh 自动化 | **否** — 部署体验优秀 |

**核心结论**：框架本身不是瓶颈，**工程纪律缺失**（无 Service 层、无迁移版本管理、CDN 未本地化、Gunicorn 未启用）才是真正的问题。

### 5.2 替换代价 vs 收益矩阵

| 方案 | 代价 | 收益 | ROI |
|------|------|------|-----|
| **A. 维持 Flask + 局部治理** | 低（重构内部结构，不换框架） | 中（可维护性提升，并发修复） | **高** |
| **B. 换 FastAPI + 前后端分离** | 极高（全部路由+模板+认证重写，~14,000 行） | 高（异步原生支持、自动文档、类型安全） | **低** |
| **C. 换 Django + DRF** | 极高（ORM 迁移、模板迁移、认证迁移） | 中（admin 内置、migrate 内置） | **低** |
| **D. 换 Go/Rust 重写** | 灾难级（全量重写） | 高（性能极大提升） | **极低** |

### 5.3 模块可替换性资产分级表

| Level | 定义 | 模块 | 估计行数 |
|-------|------|------|---------|
| **Level 1** | 纯业务复用（零框架依赖，可直接搬运） | `cn2num`、`split_gift_nlp_text`、`calculate_reconciliation`、`encrypt_credential`/`decrypt_credential`、`_cron_match` | ~2,200 |
| **Level 2** | 轻度适配可复用（改 import 和接口签名即可） | `webdav_utils.py`（WebDAV 协议无关）、`ai_service.py`（OpenAI SDK 无框架绑定）、`web_search.py`、`gift_utils.py` 的 `parse_gift_nlp` | ~1,000 |
| **Level 3** | 强框架耦合，替换需大幅重写 | 全部 `@app.route` 路由（~7,942 行）、`models.py`（SQLAlchemy 模型）、`webhook_utils.py`（依赖 `WebhookConfig.query`）、权限引擎、CSRF 中间件 | ~9,500 |
| **Level 4** | 架构级推倒重写 | 21 个 Jinja2 模板（11,785 行）— 换前端框架必须全量重写 | ~11,785 |

### 5.4 最终结论

> **【不建议替换，仅局部治理】**

**理由**：

1. **Flask 本身不是瓶颈**。系统并发问题的根因是未启用 Gunicorn（D-02 漂移），而非框架选型。启用 Gunicorn 多 Worker 即可解决，代价仅修改 `run.sh` 一行启动命令。

2. **替换 ROI 极低**。Level 3+4 代码占总量 80%+（~20,400 行），任何框架替换都意味着近乎全量重写，而当前系统功能完整、业务运行正常，重写收益无法覆盖代价。

3. **真正需要的是工程纪律**。当前技术债来自"有决策未执行"（Gunicorn；CDN 本地化已于 V10.10.18 执行）和"无规范的开发模式"（无 Service 层、无迁移版本管理），而非框架能力不足。

**推荐治理清单（P0 立即执行）**：

| 优先级 | 治理项 | 漂移编号 | 预估工作量 | 具体操作 |
|--------|--------|---------|-----------|---------|
| **P0** | 启用 Gunicorn 多 Worker | D-02 | 0.5 人日 | `run.sh` 启动命令从 `python3 app.py` 改为 `gunicorn -w 4 -k gthread --threads 4 -b 127.0.0.1:$PORT app:app --timeout 60` |
| **P0** | ~~CDN 资源本地化~~ **✅ V10.10.18 已完成** | D-03 | — | Bootstrap 5.3.0/Font Awesome 6.4.0/Bootstrap Icons 1.11.3 共 14 个文件已落地 `static/vendor/`，`base.html` 4 处 + `shared_ledger.html` 2 处改本地引用 |
| **P1** | 更新 ADR-25 权限语义 | D-05 | 0.5 人日 | 在 `Project_Survey.md` 中追加 ADR-39 记录 V10.4 权限级别 1 语义修正 |
| **P1** | 标注 akshare 为"规划搁置" | D-01 | 0.5 人日 | 在 `Project_Survey.md` §3 添加状态标注 |
| **P2** | routes_ext.py 拆分 | — | 3 人日 | 按业务域拆分为 `routes_banquets.py`/`routes_backups.py`/`routes_webhooks.py` 等 |
| **P2** | 引入 Flask-Migrate | — | 2 人日 | 替换 `init_database` 硬编码 SQL 为 Alembic 版本管理 |
| **P2** | 提取 Service 层 | — | 5 人日 | 将路由中的业务逻辑抽离为 `services/` 模块，路由仅负责参数校验和响应 |

---

## 第 6 部分：前后端详尽规格（校准整合版）

### 6.1 前端架构

#### 6.1.1 技术栈与渲染模式

| 维度 | 实现 | 代码依据 |
|------|------|---------|
| 渲染模式 | 服务端渲染（SSR），Jinja2 模板继承 | `templates/base.html` 为布局模板，各页面 `{% extends 'base.html' %}` |
| CSS 框架 | Bootstrap 5.3.0（本地 `static/vendor/bootstrap/5.3.0/`，V10.10.18 起替代 CDN） | `base.html:23、256` |
| 图标库 | Font Awesome 6.4.0 + Bootstrap Icons 1.11.3（本地 `static/vendor/`，V10.10.18 起替代 CDN） | `base.html:24-25` |
| 图表库 | 无（历史文档记载 Chart.js，实际模板内已无引用） | — |
| JavaScript | 原生 JS（无框架、无构建工具），`fetch()` API 做 AJAX 通信 | 全部模板内联 `<script>` |
| PWA | `static/manifest.json` + `static/sw.js`（仅 manifest 壳，无 fetch 拦截） | `base.html:9-10` |
| CSRF | 全局 `<meta name="csrf-token">` 注入，fetch 请求头携带 `X-CSRF-Token` | `base.html:6、396-400、418` |
| 主题系统 | Bootstrap 5.3 原生 `data-bs-theme` 双主题（白天/黑夜），CSS 变量（`--app-bg`/`--app-card-bg` 等 6 个）驱动；导航栏主题切换按钮 + `localStorage('gift_theme')` 持久化，默认白天零回归；暗色下统一覆盖 `bg-white/bg-light/text-dark/text-muted/table-light` 等浅色工具类 | `base.html` 全局 `<style>`、`V10.10.13` 新增 |
| 输入框提示语 | 全局 `::placeholder` 统一美化（浅灰蓝 `--ph-color`、常规字重 400、0.875em、半透明、聚焦淡出），覆盖全部 20 个含输入框页面约 122 处 | `base.html` 全局 `<style>`、`V10.10.13` 新增 |

#### 6.1.2 路由（前端导航）

前端无 SPA 路由，全部通过 Flask `url_for()` 生成后端路由链接，浏览器整页跳转。AJAX 请求仅用于局部刷新（如 WebDAV 列表异步加载、Webhook 测试 toast、权限配置即时保存等）。

**全局导航栏**（`base.html:56-80`）基于 `current_user.can_access_menu(menu_key)` 动态渲染：

| 菜单项 | menu_key | 可见条件 |
|--------|---------|---------|
| 礼金账本 | `ledger` | 管理员或 `can_access_menu('ledger')` |
| 专属宴席 | `banquets` | 管理员或 `can_access_menu('banquets')` |
| 人情对账 | `reconciliation` | 管理员或 `can_access_menu('reconciliation')` |
| 纪念日备忘 | `reminders` | 管理员或 `can_access_menu('reminders')` |
| 回收站 | `recycle_bin` | 管理员或 `can_access_menu('recycle_bin')` |

#### 6.1.3 前端全局 Fetch 拦截器

`base.html:233-259` 定义全局 fetch 响应拦截逻辑：
- HTTP 401 + JSON 含 `need_verify` 字段 → 豁免跳转（V10.7 修复凭证验证误跳转）
- HTTP 401（非 need_verify）→ 判定登录失效，`alert()` + `window.location.href = '/login'`
- 其余响应透传

#### 6.1.4 模板清单与职责

| 模板 | 行数 | 核心职责 |
|------|------|---------|
| `base.html` | 398 | 全局布局、导航栏、Flash 提示、全局 JS/CSS 引入 |
| `index.html` | 1079 | 礼金账本首页：列表/搜索/分页/统计/新增编辑模态框/NLP 录入/CSV 导入导出 |
| `admin_webhooks.html` | 1527 | Webhook 管理：4-Tab 配置（事件开关/页面×事件矩阵/消息模板/监控范围）+ 推送日志 |
| `admin_users.html` | 1359 | 用户管理：列表/权限配置模态框/AI+备份授权/凭证查看/重置密码+密保 |
| `admin_backups.html` | 1249 | WebDAV 备份：配置/定时任务/云端备份列表/本地备份/附件恢复/授权管理 |
| `banquet_detail.html` | 994 | 宴席明细：现场收礼/分页/搜索/批量操作/分享链接 |
| `reminders.html` | 862 | 纪念日备忘：列表/搜索/批量推送模态框/多通道选择/定时调度 |
| `banquets.html` | 648 | 宴席总览：卡片/表格双视图/搜索/批量删除 |

### 6.2 后端核心服务分层

#### 6.2.1 路由装配机制

```
app.py (Flask app 实例创建)
  ├── @app.route 核心路由 (37 个) → 直接定义在 app.py
  ├── register_routes_ext(app) → 从 routes_ext.py 注册扩展路由 (82 个)
  └── register_ai_routes(app, log_action) → 从 routes_ai.py 注册 AI 路由 (14 个)
```

**代码依据**：`app.py:33` `from routes_ext import register_routes_ext`；`routes_ai.py:17` `def register_ai_routes(app, log_action=None)`

#### 6.2.2 中间件流水线（`@app.before_request` 执行顺序）

| 顺序 | 函数 | 文件位置 | 职责 |
|------|------|---------|------|
| 1 | `check_session_timeout` | `app.py:155` | 会话超时检测 + 服务重启强制重新登录（`APP_START_TIME` 比对） |
| 2 | `csrf_protect` | `app.py:214` | CSRF Token 生成与校验（企微回调/根路径/Webhook 接口免除） |
| 3 | `handle_wecom_root_callback` | `app.py:240` | 企微回调请求打到根路径 `/` 时自动分发 |

| 顺序 | 函数 | 文件位置 | 职责 |
|------|------|---------|------|
| 后置 | `add_header` | `app.py:207` | 全局 `Cache-Control: no-cache, no-store` |

#### 6.2.3 权限引擎核心函数

| 函数 | 位置 | 职责 |
|------|------|------|
| `get_accessible_records_query(user, menu_key)` | `app.py:465` | 按菜单权限返回可见记录的 Query 对象 |
| `can_user_view_entity(user, entity, menu_key)` | `app.py:501` | 判断查看权限（自身→True；他人→perm>=1） |
| `can_user_edit_entity(user, entity, menu_key)` | `app.py:516` | 判断修改权限（自身→True；他人→perm>=2；管理员实体→False） |
| `can_user_delete_entity(user, entity, menu_key)` | `app.py:532` | 判断删除权限（自身→perm!=2；他人→perm>=3；管理员实体→False） |
| `is_entity_owner_admin(entity)` | `app.py:479` | 判断实体创建者是否为管理员（防越权红线） |

#### 6.2.4 后台异步任务

| 守护线程 | 位置 | 轮询周期 | 职责 |
|---------|------|---------|------|
| `_anniversary_reminder_worker` | `routes_ext.py:380` | 60 秒 | 巡检到达预警天数的纪念日，自动推送 Webhook（周期锁防重 `last_notified_target`） |
| `_backup_scheduler_worker` | `routes_ext.py:499` | 60 秒 | 检查 `ScheduledBackupTask` 表中启用任务，按 cron 表达式执行加密备份 |
| `_wecom_listener_worker` | `webhook_utils.py` | 常驻 | 企微 WebSocket 长连接监听，自动捕获群聊 `chatid`（V10.10.14 修正写库路径；V10.10.15 修正 `bot_secret` AES-256-GCM 密文解密——raw SQL 读取的是密文，需 `decrypt_credential()` 解密后传给 SDK 认证；真实企微群 @机器人 实测通过，全链路闭环确认） |

### 6.3 核心 API 规范清单（10 个核心接口）

#### API-01: 用户登录

| 属性 | 值 |
|------|-----|
| 路径 | `POST /login` |
| 鉴权 | 公开（未登录） |
| 校验 | 用户名+密码；连续失败>=5 次触发验证码+锁定；管理员额外校验密保 |
| 代码 | `app.py:1190-1305` |
| 成功 | redirect → `index`，session 注入 `session_token` + `login_time` |
| 失败 | HTTP 200 + flash 消息（非 JSON），渲染 `login.html` |
| 风控 | `LoginRisk` 表 + 内存字典双重计数；锁定时长由 `SystemSetting.login_lockout_seconds` 控制 |

#### API-02: 新增礼金记录

| 属性 | 值 |
|------|-----|
| 路径 | `POST /record/add` |
| 鉴权 | `@login_required` |
| 校验 | name 必填、amount 必填（支持中文大写 `cn2num` 转换）、event_reason 必填 |
| 代码 | `app.py:1605-1695` |
| 权限 | 级别 0~3 均可新增自身记录（V10.4 移除级别 1 拦截） |
| 成功 | AJAX → `{"code":200, "record_id": N}`；表单 → flash + redirect |
| Webhook | `trigger_webhook_event` → `record_create` / `ledger` |
| 审计 | `log_action('新增记录', ...)` |

#### API-03: NLP 复合录入

| 属性 | 值 |
|------|-----|
| 路径 | `POST /api/record/nlp_quick_add` |
| 鉴权 | `@login_required` |
| 校验 | 文本非空；`split_gift_nlp_text()` 分词 + `parse_gift_nlp_multi()` 解析 |
| 代码 | `routes_ext.py` 内定义 |
| 成功 | `{"code":200, "data":{"created_count":N, "records":[...]}}` |
| 特性 | 支持顿号/分号/换行/竖线/连词分割，原子级多笔提交 |

#### API-04: CSV 导出

| 属性 | 值 |
|------|-----|
| 路径 | `GET /export/csv` |
| 鉴权 | `@login_required` |
| 参数 | `scope` (all/filtered/page)、`ids`、`search`、`reason`、`type`、`sort`、`page`、`per_page` |
| 代码 | `app.py:2887-2998` |
| 输出 | CSV（UTF-8 BOM），列：ID/姓名/往来类型/年龄/电话/金额/大写金额/事由/宴席/地址/备注/时间/录入人 |
| Webhook | `security` / `ledger` |

#### API-05: 纪念日手动推送

| 属性 | 值 |
|------|-----|
| 路径 | `POST /api/reminders/custom_push` |
| 鉴权 | `@login_required` + `can_access_menu('reminders')` + `get_menu_perm('reminders') != 1` |
| 参数 | `reminder_ids`（多选）、`webhook_ids`（多通道）、`repeat_count`(1~5)、`interval_seconds`(0~300)、`custom_content` |
| 代码 | `routes_ext.py` |
| 特性 | 异步线程多轮推送；每轮记录 WebhookLog；权限级别 1（只读）拦截 |

#### API-06: AI 聊天

| 属性 | 值 |
|------|-----|
| 路径 | `POST /api/ai/chat` |
| 鉴权 | `@login_required` + `can_use_ai()` |
| 参数 | `{"query": "...", "session_id": 123}` |
| 代码 | `routes_ai.py:61-90` |
| 响应 | `{"code":200, "data":{"query":"...", "response":"...", "used_openai":true, "used_config_name":"...", "used_search":false, "latency_ms":500, "session_id":123, "session_title":"..."}}` |
| 配置优先级 | 用户多配置 → 旧版单配置 → 环境变量 → 管理员共享 → 本地兜底 |

#### API-07: WebDAV 备份触发

| 属性 | 值 |
|------|-----|
| 路径 | `POST /admin/backups/trigger` |
| 鉴权 | `@login_required` + `can_use_backup()` |
| 代码 | `routes_ext.py` |
| 特性 | 管理员→完整库文件级备份；普通用户→`build_user_scoped_backup_db()` 过滤库（DROP 19 张全局表） |
| 加密 | 可选 AES-256 加密 zip（`pyzipper`） |

#### API-08: 备份恢复

| 属性 | 值 |
|------|-----|
| 路径 | `POST /admin/backup/upload_local` + `POST /admin/backup/restore`（代码注册别名：`/admin/backups/restore`、`/admin/backups/restore/<path:filename>`，`routes_ext.py:4221-4223`） |
| 鉴权 | `@login_required` + `can_use_backup()` |
| 代码 | `routes_ext.py` `admin_upload_local_backup` / `admin_restore_webdav_backup` |
| 管理员路径 | `sqlite3.backup()` 原子替换 + WAL/SHM 清理 + `init_database()` 迁移 |
| 普通用户路径 | `merge_user_scoped_backup()` 数据级合并（ATTACH DATABASE 跨库，仅本人三张业务表） |
| 安全 | 文件命名校验 + 归属校验 + 完整库拦截 + `PRAGMA integrity_check` |

#### API-09: 管理员查看用户凭证

| 属性 | 值 |
|------|-----|
| 路径 | `GET/POST /admin/user/<int:user_id>/credentials` |
| 鉴权 | 管理员专属 + 管理员目标需二次验证 |
| 代码 | `app.py:2743-2802` |
| 特性 | 管理员查看管理员凭证需验证原密码或密保；HTTP 200 + JSON `code:401` + `need_verify:true`（V10.7 修复避免全局拦截器误判） |

#### API-10: 权限工单审批

| 属性 | 值 |
|------|-----|
| 路径 | `POST /permission_tickets/<int:ticket_id>/approve` |
| 鉴权 | 管理员专属 |
| 代码 | `routes_ext.py:4977-5034` |
| 逻辑 | 工单 status → approved；勾选的菜单合并到 `user.allowed_menus`；Webhook 推送 + 审计日志 |

---

## 第 7 部分：数据持久化设计

### 7.1 核心实体关系（ER 图）

```mermaid
erDiagram
    users ||--o{ gift_records : "1:N owns"
    users ||--o{ banquets : "1:N owns"
    users ||--o{ anniversary_reminders : "1:N owns"
    users ||--o{ webhook_configs : "1:N owns"
    users ||--o{ chat_sessions : "1:N owns"
    users ||--o{ permission_tickets : "1:N applies"
    users ||--o{ operation_logs : "1:N logs"

    banquets ||--o{ gift_records : "1:N FK banquet_id"
    gift_records }o--|| banquets : "N:1 belongs_to"

    users ||--o{ shared_ledger_links : "1:N creates"
    banquets ||--o{ shared_ledger_links : "1:N shared"

    chat_sessions ||--o{ chat_messages : "1:N messages"
    users ||--o{ ai_query_logs : "1:N queries"

    webhook_configs ||--o{ webhook_logs : "1:N logs"
    users ||--o{ webhook_logs : "1:N operator"

    backup_configs ||--o{ scheduled_backup_tasks : "config"
    users ||--o{ scheduled_backup_tasks : "1:N created_by"
    scheduled_backup_tasks ||--o{ scheduled_task_execution_logs : "1:N execution"

    users {
        int id PK
        string username UK
        string password_hash
        string encrypted_password "AES-256-GCM"
        string security_question_1
        string security_answer_hash_1
        string encrypted_security_answer_1 "AES-256-GCM"
        string security_question_2
        string security_answer_hash_2
        string encrypted_security_answer_2 "AES-256-GCM"
        boolean is_admin
        boolean is_active
        string session_token
        string allowed_menus "CSV: ledger,banquets,..."
        text menu_permissions "JSON: {menu:perm_level}"
        string _ai_api_key "AES-256-GCM"
        text ai_configs "JSON array"
        boolean ai_authorized
        boolean backup_authorized
        boolean scheduled_task_authorized
    }

    gift_records {
        int id PK
        string name "必填"
        string record_type "receive|send"
        float amount "必填"
        string event_reason "必填"
        int banquet_id FK "SET NULL on delete"
        int user_id FK "NOT NULL"
        datetime deleted_at "软删除标记"
        datetime created_at
    }

    banquets {
        int id PK
        string title "必填"
        string event_type "婚宴/满月酒/寿宴/..."
        float budget
        float banquet_cost
        string creator_type "manual|auto"
        int creator_id
        string source_username
        int user_id FK
        datetime deleted_at "软删除"
    }

    anniversary_reminders {
        int id PK
        string name "必填"
        string target_date "MM-DD 或 YYYY-MM-DD"
        string anniversary_type "birthday|wedding|other"
        int advance_days "默认3"
        string last_notified_target "周期锁 YYYY-MM-DD"
        boolean is_active
        int user_id FK
        datetime deleted_at "软删除"
    }

    webhook_configs {
        int id PK
        int user_id FK
        string channel_name
        string webhook_url
        string _secret_token "AES-256-GCM"
        string connection_type "webhook_url|long_connection"
        string bot_id
        string _bot_secret "AES-256-GCM"
        text notify_pages "JSON: {event:[pages]}"
        text message_templates "JSON"
        text monitor_user_ids "JSON array"
        text monitor_event_types "JSON array"
    }

    backup_configs {
        int id PK
        int user_id "NULL=管理员全局"
        string webdav_url
        string webdav_username
        string webdav_password "AES-256-GCM"
        string _backup_encrypt_password "AES-256-GCM"
        string config_alias
        boolean adopted_from_admin
        boolean allow_view_others_tasks
        boolean allow_edit_others_tasks
        boolean allow_delete_others_tasks
    }

    permission_tickets {
        int id PK
        int user_id FK
        string requested_menus "CSV"
        string status "pending|approved|rejected|revoked"
        int reviewed_by FK
        string granted_menus "CSV"
    }
```

### 7.2 完整数据表清单（22 张表）

| # | 表名 | ORM 模型 | 行数估计 | 核心用途 |
|---|------|---------|---------|---------|
| 1 | `users` | `User` | ~10 | 用户账号、权限、AI/备份授权、密保 |
| 2 | `gift_records` | `GiftRecord` | ~150 | 礼金收送记录（核心业务表） |
| 3 | `banquets` | `Banquet` | ~4 | 专属宴席大账本 |
| 4 | `anniversary_reminders` | `AnniversaryReminder` | ~6 | 纪念日提醒 |
| 5 | `operation_logs` | `OperationLog` | ~300 | 操作审计日志 |
| 6 | `system_settings` | `SystemSetting` | ~10 | 系统配置键值对 |
| 7 | `registration_tokens` | `RegistrationToken` | ~5 | 邀请注册令牌 |
| 8 | `login_risks` | `LoginRisk` | ~5 | 登录失败计数与锁定 |
| 9 | `security_risks` | `SecurityRisk` | ~5 | 密保验证失败计数 |
| 10 | `broadcasts` | `Broadcast` | ~2 | 系统广播 |
| 11 | `broadcast_reads` | `BroadcastRead` | ~10 | 广播已读记录 |
| 12 | `webhook_configs` | `WebhookConfig` | ~3 | Webhook 通道配置 |
| 13 | `webhook_logs` | `WebhookLog` | ~50 | Webhook 推送日志 |
| 14 | `shared_ledger_links` | `SharedLedgerLink` | ~2 | 宴席只读分享外链 |
| 15 | `backup_configs` | `BackupConfig` | ~2 | WebDAV 备份配置 |
| 16 | `scheduled_backup_tasks` | `ScheduledBackupTask` | ~2 | 定时备份任务 |
| 17 | `scheduled_task_execution_logs` | `ScheduledTaskExecutionLog` | ~10 | 定时任务执行历史 |
| 18 | `backup_attachments` | `BackupAttachment` | ~0 | 备份附件 |
| 19 | `permission_tickets` | `PermissionTicket` | ~3 | 权限申请工单 |
| 20 | `chat_sessions` | `ChatSession` | ~5 | AI 聊天会话 |
| 21 | `chat_messages` | `ChatMessage` | ~20 | AI 聊天消息 |
| 22 | `ai_query_logs` | `AIQueryLog` | ~10 | AI 查询日志 |

### 7.3 字段约束与安全机制

| 机制 | 实现 | 代码依据 |
|------|------|---------|
| 密码存储 | Werkzeug `generate_password_hash`（单向） + AES-256-GCM `encrypted_password`（可逆） | `models.py:128-130` |
| 密保存储 | 双密保：`security_answer_hash_1/2`（单向哈希） + `encrypted_security_answer_1/2`（AES-256-GCM 可逆） | `models.py:215-231` |
| 敏感凭证加密 | `secret_token`、`bot_secret`、`webdav_password`、`backup_encrypt_password`、`access_password`、`ai_api_key` 全部 AES-256-GCM 密文 | `models.py:781-906` |
| 软删除 | `gift_records`、`banquets`、`anniversary_reminders` 含 `deleted_at` 字段 | `models.py:498,460,539` |
| 外键级联 | `ondelete='CASCADE'`：ChatSession→ChatMessage、User→GiftRecord/Banquet/Reminder；`ondelete='SET NULL'`：GiftRecord→Banquet | `models.py:408,466,501` |
| UNIQUE 约束 | `users.username`（唯一） | `models.py:81` |
| 非空约束 | `GiftRecord.name`、`amount`、`event_reason`、`user_id` 非空 | `models.py:489,494,495,501` |

### 7.4 索引有效性评估

| 表 | 显式索引 | 代码依据 | 有效性评估 |
|------|---------|---------|-----------|
| `users` | `username` UNIQUE → 自动索引 | `models.py:81` | **有效** — 登录查询按 username |
| `gift_records` | 无显式索引 | — | **缺失** — `user_id`、`event_reason`、`deleted_at` 高频查询无索引，150 条数据量下暂无性能问题 |
| `webhook_configs` | 无显式索引 | — | `user_id` 查询无索引，数据量小可忽略 |
| `operation_logs` | 无显式索引 | — | **潜在风险** — `created_at` 排序+清理按时间范围扫描，日志量增长后可能变慢 |

**结论**：当前数据量极小（样例 151 条礼金记录），无索引性能瓶颈。但 `operation_logs` 随时间累积（90 天自动清理）后在百级数据量下仍可接受。若迁移 PostgreSQL 建议补充 `user_id`、`deleted_at` 索引。

### 7.5 事务机制

| 场景 | 事务实现 | 代码依据 |
|------|---------|---------|
| 常规 CRUD | SQLAlchemy `db.session.commit()` 自动事务 | 全部路由 |
| 备份合并 | 原生 sqlite3 `ATTACH DATABASE` → `commit` → `DETACH`（顺序敏感） | `routes_ext.py:162-200` |
| 数据库恢复 | `sqlite3.backup()` 原子操作 + WAL/SHM 清理 | `routes_ext.py` 恢复路由 |
| 日志写入 | `try-except` 包裹，日志失败不回滚主业务事务 | `app.py:406-408` |
| WAL 模式 | `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=30000` | `app.py:876-879` |

### 7.6 数据库迁移机制

**现状**：无 Alembic/Flask-Migrate 版本管理。`init_database()` 函数（`app.py:653-939`）在应用启动时自动执行：

1. **orphan index 修复**（V5）：`PRAGMA writable_schema=1` 查找并删除孤儿索引
2. `db.create_all()`：创建缺失表
3. **migration_sqls 列表**：约 60 条 `ALTER TABLE ADD COLUMN` 语句，逐条 `try-except` 忽略已存在错误
4. **V10.9 数据迁移**：将空 Webhook 监控范围预填为全选
5. **WAL 模式开启** + **风控状态重置** + **管理员账号同步**

**风险**：迁移失败被静默吞没（`except Exception: pass`），无回滚能力，无版本追踪。

---

## 第 8 部分：工程与安全保障

### 8.1 环境变量与配置分离

| 环境变量 | 默认值 | 用途 | 代码依据 |
|---------|--------|------|---------|
| `PORT` | `11443` | Flask 后端监听端口 | `run.sh:31`、`app.py` `__main__` |
| `NGINX_PORT` | `443` | Nginx 对外监听端口 | `run.sh:32` |
| `ADMIN_USER` | `admin` | 管理员用户名 | `run.sh:33`、`app.py:901` |
| `ADMIN_PASS` | `admin123` | 管理员初始密码 | `run.sh:34`、`app.py:902` |
| `DATABASE_URL` | (空) | PostgreSQL 连接串（空则降级 SQLite） | `app.py:76-78` |
| `SECRET_KEY` | 硬编码默认值 | Flask 会话密钥 | `app.py:43` |
| `SESSION_COOKIE_SECURE` | `false` | HTTPS Cookie 传输 | `app.py:53` |
| `OPENAI_API_KEY` | (空) | 全局 AI 配置（第3优先级） | `ai_service.py:90` |
| `OPENAI_BASE_URL` | (空) | 全局 AI Base URL | `ai_service.py:95` |
| `OPENAI_MODEL` | `gpt-4o-mini` | 全局 AI Model | `ai_service.py:96` |
| `PROJECT_NAME` | `gift_app` | Nginx 配置文件名/upstream 名 | `run.sh:14` |
| `SNI_DOMAIN` | `localhost` | SNI 域名（证书 CN/SAN） | `run.sh:15` |
| `SNI_DEFAULT_SERVER` | `1` | 是否作为 443 兜底 default_server | `run.sh:18` |
| `SSL_CERT`/`SSL_KEY` | `$APP_DIR/ssl/*` | SSL 证书路径（可指向正式证书） | `run.sh:16-17` |
| `SSL_FORCE_UPDATE` | (空) | 强制更新 SSL 证书 | `run.sh:27` |
| `NGINX_CONF_FORCE_UPDATE` | (空) | 强制覆盖 Nginx 配置 | `run.sh:28` |

### 8.2 认证与鉴权模型

```mermaid
flowchart TD
    A[请求到达] --> B{check_session_timeout}
    B -->|超时/重启| C[logout + redirect login]
    B -->|正常| D{csrf_protect}
    D -->|CSRF失败| E[403 拦截]
    D -->|通过/豁免| F{endpoint为login/register等公开?}
    F -->|是| G[公开访问]
    F -->|否| H{current_user.is_authenticated?}
    H -->|否| I[redirect login]
    H -->|是| J{endpoint需管理员权限?}
    J -->|是| K{current_user.is_admin?}
    K -->|否| L[403/redirect]
    K -->|是| M[放行]
    J -->|否| N{can_access_menu?}
    N -->|否| O[redirect 权限工单]
    N -->|是| P[放行]
    P --> Q{数据操作: view/edit/delete}
    Q --> R{can_user_view/edit/delete_entity}
    R -->|管理员| S[全权限]
    R -->|自身实体| T[允许]
    R -->|他人实体| U{get_menu_perm >= N?}
    U -->|否| V[403 拦截]
    U -->|是| W[放行]
    W --> X{is_entity_owner_admin?}
    X -->|是| Y[拦截: 禁止触碰管理员数据]
    X -->|否| Z[操作执行]
```

### 8.3 安全防护体系

| 层面 | 措施 | 代码依据 |
|------|------|---------|
| **传输安全** | Nginx TLS 1.2/1.3 + HTTP/2 + HSTS（`max-age=63072000`） | `nginx_ssl.conf:30-31,39` |
| **会话安全** | Session Cookie HttpOnly + SameSite=Lax；服务重启强制重新登录（`APP_START_TIME`） | `app.py:50-54,168-182` |
| **CSRF** | 手动 Token 生成 + 校验（POST/PUT/PATCH/DELETE）；企微回调/根路径豁免 | `app.py:214-238` |
| **密码安全** | Werkzeug 哈希存储 + AES-256-GCM 可逆加密存储（管理员可查看明文） | `models.py:128-130` |
| **凭证加密** | 全部敏感字段 AES-256-GCM 密文落盘（secret_token/bot_secret/webdav_password/encrypt_password/access_password/ai_api_key） | `models.py:27-43` |
| **日志脱敏** | `_sanitize_log_data()` 递归脱敏（secret/token/pass/key/credential/auth/webhook_url → `***MASKED***`） | `webhook_utils.py:84-97` |
| **登录风控** | 双重计数（内存字典 + DB `LoginRisk` 表）+ 阶梯式锁定 + 算术验证码 | `app.py:1062-1161` |
| **密保风控** | `SecurityRisk` 表 + 连续错误锁定 + 管理员额外验证码 | `app.py:1128-1152` |
| **权限分级** | 4 级菜单权限（0 自管 / 1 查他人 / 2 改他人 / 3 删他人）+ 管理员实体保护 | `app.py:501-546` |
| **防越权红线** | 普通用户不得修改/删除管理员创建的实体（`is_entity_owner_admin` 拦截） | `app.py:479-488,522,538` |
| **备份隔离** | 普通用户备份 DROP 19 张全局表；恢复用数据级合并不越界 | `routes_ext.py:47-96,113-205` |
| **ProxyFix** | 信任 Nginx 透传的 `X-Forwarded-*` | `app.py:57` |
| **样例库防泄漏** | 推送前 9 项规则校验（真实用户名/冻结状态/会话令牌/WebDAV·Webhook 凭据密文/邀请码/口令密文，异常即拦截推送；规则与工具解耦，明细见 README"样例库维护约定"） | README 样例库维护约定；V10.10.12 建立 |
| **广播敏感内容隔离** | 广播内容含敏感词（管理员账号/初始密码/admin123 等）自动强制 `scope='admin'`（仅管理员可见）且不触发 Webhook 推送，防止敏感信息流出到前端与群聊；历史敏感广播已收敛为 admin 范围 | `routes_ext.py` 广播发布路由，V10.10.14 |

### 8.4 部署架构

```
客户端 (浏览器/APK)
    │
    ▼ HTTPS (443)
Nginx (SNI 多项目)
    │ proxy_pass http://127.0.0.1:11443
    ▼
Flask (app.py)
    │ Gunicorn 多 Worker (已声明未启用，实际 python3 app.py)
    ▼
SQLite (data/gift_bookkeeping.db, WAL 模式)
```

**run.sh 生命周期**：

| 命令 | 执行流程 |
|------|---------|
| `start` | `preflight_check()`【V10.10.18】→ `ensure_ssl_certs()` → `check_port_conflict()` → `setup_nginx_config()` → `cleanup_cache()` → `select_db_mode()`【V10.10.17】→ `ensure_sqlite_runtime_db()`【V10.10.18，仅 SQLite 模式；V10.10.20 起仅就绪 data/ 目录、不再复制样例库，初次部署为纯净空库 + 单一管理员】→ 创建 venv → pip install（清华→阿里云→官方三源兜底【V10.10.18】）→ `python3 app.py` |
| `stop` | PID 文件 + 端口双重清理 → 进程组 kill |
| `restart` | stop + sleep 2 + start |
| `status` | PID 文件 + 端口检测 + `print_access_info()` 访问地址/本地直连/日志 + `print_db_mode_info()` 数据库模式【V10.10.19】 |
| `clean` | git gc + __pycache__ 清理 + /tmp/gift-backup 清理 |

### 8.5 Docker 部署（Docker 版仓库）

| 维度 | 传统版 | Docker 版 |
|------|--------|-----------|
| 仓库 | `gift-bookkeeping-app` | `gift-bookkeeping-app-docker` |
| 容器 | 无 | `docker compose up -d --build` |
| 数据库 | `data/gift_bookkeeping.db` | `/app/data/gift_bookkeeping.db`（卷挂载） |
| Nginx | 宿主机 Nginx | 容器内 Nginx 或宿主机 Nginx |
| Python | 宿主机 venv | `python:3.11-slim` 镜像 |
| 共享文件 | — | 两版共享文件 MD5 逐字一致（`routes_ext.py`/`app.py`/模板等） |

---

## 第 9 部分：综合问题排查与渐进演进路线图

### 9.1 五维技术债清单

#### 维度一：代码质量

| # | 技术债 | 严重度 | 代码依据 | 影响 |
|---|--------|--------|---------|------|
| CQ-01 | `routes_ext.py` 5231 行单文件膨胀 | 高 | `routes_ext.py` 全文 | 模块边界模糊，修改回归风险高 |
| CQ-02 | 无 Service 层，业务逻辑全在路由函数内 | 高 | `routes_ext.py:admin_upload_local_backup`（~130 行单函数） | 函数职责超 10 个，测试困难 |
| CQ-03 | 数据库迁移硬编码 SQL，无版本管理 | 中 | `app.py:681-817` ~60 条 `ALTER TABLE` | 迁移失败静默吞没，无回滚 |
| CQ-04 | 前端 JS 与 HTML 混杂，无模块化 | 中 | `admin_webhooks.html`（1527 行含大量内联 JS） | 前端逻辑不可复用、不可测试 |
| CQ-05 | `app.py` 与 `gift_utils.py` 各有一份 `cn2num` 实现重复 | 低 | `app.py:425-462`、`gift_utils.py:13-55` | 逻辑重复，维护需同步两处 |
| CQ-06 | `decrypt_credential` 函数内含两段完全相同的 try-except 块 | 低 | `models.py:45-73` | 死代码，第二段永不执行 |

#### 维度二：高并发性能

| # | 技术债 | 严重度 | 代码依据 | 影响 |
|---|--------|--------|---------|------|
| PF-01 | 生产环境使用 Werkzeug 开发服务器（`python3 app.py`） | 高 | `run.sh:167-174` | 单线程，多 Tab 请求排队阻塞（ADR-01 已诊断但未落地） |
| PF-02 | ~~CDN 资源未本地化~~ **✅ V10.10.18 已修复** | ~~高~~ 已清偿 | `base.html:23-25、256`（本地 `static/vendor/` 引用） | 内网/弱网白屏问题已随本地化解决，浏览器实测无 CDN 请求 |
| PF-03 | `query.all()` 全量加载再 Python 端统计 | 中 | `app.py:1005-1006` `all_filtered_records = query.all()` | 数据量增长后内存+查询效率问题 |
| PF-04 | SQLite 单文件并发写锁 | 低 | `app.py:83-84` | 已开启 WAL + 30s busy_timeout，单机场景足够 |

#### 维度三：扩展性

| # | 技术债 | 严重度 | 代码依据 | 影响 |
|---|--------|--------|---------|------|
| EX-01 | 无消息队列，异步任务依赖 daemon 线程 | 中 | `routes_ext.py:380,499` | 线程内异常仅 print，无重试/死信；多进程部署时线程不共享 |
| EX-02 | 权限方法中硬编码菜单列表 | 低 | `models.py:155` `ALL_MENUS = ['ledger','banquets',...]` | 新增菜单需修改多处代码 |
| EX-03 | Webhook 推送全项目 ~106 处调用点手动传参 | 中 | 全项目 `trigger_webhook_event` 调用（app.py 31 + routes_ext.py 70 + routes_ai.py 5） | 每次新增路由需手动补全推送，遗漏风险高 |

#### 维度四：安全漏洞

| # | 技术债 | 严重度 | 代码依据 | 影响 |
|---|--------|--------|---------|------|
| SEC-01 | `SECRET_KEY` 硬编码默认值 | 中 | `app.py:43` `'gift-bookkeeping-secret-key-2026-prod-secure'` | 未设置环境变量时使用默认密钥，会话可被伪造 |
| SEC-02 | 加密密钥派生自 `SECRET_KEY`（SHA-256） | 中 | `models.py:14-25` `get_aes_key` | AES 密钥与 Flask 密钥耦合，密钥泄露=全部加密凭证可解 |
| SEC-03 | `app.py:43` 和 `models.py:12` 各定义一份 `DEFAULT_SECRET_KEY` | 低 | 两处值一致但重复定义 | 修改时需同步两处 |
| SEC-04 | Nginx `ssl_prefer_server_ciphers off` | 低 | `nginx_ssl.conf:33` | 依赖客户端选择密码套件，安全性略低于 `on` |

#### 维度五：部署运维

| # | 技术债 | 严重度 | 代码依据 | 影响 |
|---|--------|--------|---------|------|
| OP-01 | Gunicorn 声明依赖但未使用 | 高 | `requirements.txt:6` vs `run.sh:367` | 生产环境并发能力不足 |
| OP-02 | 无健康检查端点 | 低 | — | Docker/负载均衡器无法做存活探针 |
| OP-03 | 无日志轮转配置 | 低 | `run.sh:11` `LOG_FILE` 直接追加 | 长期运行日志文件膨胀 |
| OP-04 | 根目录残留 `.bak` 备份文件和样例数据库 | 低 | `gift_bookkeeping.db.bak_*` | `.gitignore` 已忽略但不整洁 |

### 9.2 分期演进路线图

#### P0（立即执行，1-2 人日，零风险）

| # | 治理项 | 关联技术债 | 具体操作 | 验证方式 |
|---|--------|---------|---------|---------|
| P0-1 | 启用 Gunicorn 多 Worker | PF-01, OP-01 | `run.sh` 启动命令改为 `gunicorn -w 4 -k gthread --threads 4 -b 127.0.0.1:$PORT app:app --timeout 60` | 并发请求测试无阻塞 |
| P0-2 | ~~CDN 资源本地化~~ **✅ V10.10.18 已完成** | PF-02 | Bootstrap 5.3.0/FontAwesome 6.4.0/Bootstrap Icons 1.11.3 已落地 `static/vendor/`（14 文件），`base.html` 4 处 + `shared_ledger.html` 2 处改本地引用 | 浏览器实测无 CDN 请求、断网环境页面正常渲染 |

#### P1（短期执行，1-2 周，低风险）

| # | 治理项 | 关联技术债 | 具体操作 | 验证方式 |
|---|--------|---------|---------|---------|
| P1-1 | 引入 Flask-Migrate | CQ-03 | `pip install Flask-Migrate` → `flask db init` → 将 `init_database()` 中的 `ALTER TABLE` 逐步迁移为 Alembic migration 脚本 | `flask db upgrade` 正常执行 |
| P1-2 | 健康检查端点 | OP-02 | 新增 `GET /health` 返回 `{"status":"ok"}` | curl 测试 200 |
| P1-3 | `SECRET_KEY` 安全加固 | SEC-01 | 启动时检查环境变量 `SECRET_KEY`，未设置则生成随机密钥并打印警告 | 不设环境变量启动时看到警告 |
| P1-4 | 更新 ADR 文档 | D-05, D-01 | 在 `Project_Survey.md` 追加 ADR-39（权限级别 1 语义修正）、ADR-40（akshare 搁置标注）、ADR-41（Gunicorn 落地执行） | 文档审阅 |

#### P2（中期执行，1-2 月，需测试验证）

| # | 治理项 | 关联技术债 | 具体操作 | 验证方式 |
|---|--------|---------|---------|---------|
| P2-1 | `routes_ext.py` 拆分 | CQ-01 | 按业务域拆分为 `routes_banquets.py`/`routes_reconciliation.py`/`routes_reminders.py`/`routes_backups.py`/`routes_webhooks.py`/`routes_tickets.py`，各文件 < 800 行 | 拆分后全功能回归测试 |
| P2-2 | 提取 Service 层 | CQ-02 | 将路由中的业务逻辑抽离为 `services/banquet_service.py`/`services/backup_service.py` 等，路由仅负责参数校验和响应 | 单元测试覆盖核心逻辑 |
| P2-3 | Webhook 推送装饰器化 | EX-03 | 创建 `@notify_webhook(event_type='record_create', page_key='ledger')` 装饰器，自动在路由后触发推送 | 新增路由时减少手动推送遗漏 |
| P2-4 | 前端 JS 模块化 | CQ-04 | 将 `admin_webhooks.html` 等模板中的内联 JS 抽离为 `static/js/webhooks.js` 等独立文件 | 浏览器无 JS 报错 |
| P2-5 | 统计查询优化 | PF-03 | 将 `query.all()` + Python 端统计改为 `db.func.sum()`/`db.func.count()` SQL 聚合 | 性能基准测试 |

### 9.3 绞杀者模式（Strangler Pattern）— 如未来考虑渐进迁移

> **前提**：仅在业务规模增长到单机 Flask 无法承载时启动，当前不建议执行。

```mermaid
graph LR
    subgraph "阶段0: 当前单体"
        A1[Flask Monolith] --> DB1[(SQLite)]
    end

    subgraph "阶段1: 引入API网关"
        GW[API Gateway] --> A1[Flask Monolith]
        GW --> A2[新微服务: 统计分析]
        A2 --> DB1
    end

    subgraph "阶段2: 逐步剥离"
        GW --> A3[新微服务: 备份服务]
        GW --> A4[新微服务: Webhook服务]
        GW --> A1[Flask Monolith<br/>仅剩礼金CRUD+认证]
        A3 --> DB2[(独立存储)]
        A4 --> MQ[消息队列]
    end

    subgraph "阶段3: 完全迁移"
        GW --> A5[认证服务]
        GW --> A6[礼金服务]
        GW --> A7[宴席服务]
        A5 --> DB3[(PostgreSQL)]
        A6 --> DB3
        A7 --> DB3
    end
```

**关键原则**：
1. **不一次性重写**，而是在 Nginx 层逐步将特定路由前缀代理到新服务
2. **共享数据库**直到新服务完全就绪，再分库
3. **传统版与 Docker 版共享文件 MD5 一致**的约束需在拆分时重新评估
4. 每个阶段都可独立回退到上一阶段

---

## 第 10 部分：V10.11 四项新功能设计

### 10.1 可视化数据分析看板（功能一）

| 项 | 说明 |
|------|------|
| **图表库** | ECharts 5.5.0，本地化至 `static/vendor/echarts/5.5.0/echarts.min.js`（~1MB），不依赖 CDN |
| **页面路由** | `GET /dashboard` → `templates/dashboard.html` |
| **数据 API** | `GET /api/dashboard/stats` → JSON（summary + monthly_trend + yearly_trend + reason_distribution + top10_contacts） |
| **权限控制** | 新增 `dashboard` 菜单键，复用 4 级权限体系（ALL_MENUS 已扩展） |
| **图表组件** | ① 月度/年度收送走势折线图（双线+区域填充）② 事由分布环形饼图 ③ 亲友往来 TOP10 横向堆叠柱状图 |
| **主题适配** | ECharts 主题色随 `data-bs-theme` 属性动态切换（黑夜/白天） |

### 10.2 家庭多成员协作记账（功能二）

| 项 | 说明 |
|------|------|
| **数据模型** | `FamilyGroup`（家庭组）+ `FamilyMember`（成员关联），`_SCHEMA_VERSION` 1017→1018 |
| **角色体系** | `head`（家长，可管理成员与查看全家数据）、`member`（成员，可记账与查看自己数据）、`viewer`（只读，仅可查看家庭汇总数据） |
| **页面路由** | `GET /family` → `templates/family.html` |
| **API 路由** | `POST /api/family/create`、`GET /api/family/my-groups`、`POST /api/family/<id>/invite`、`DELETE /api/family/<id>/dissolve`、`GET /api/family/<id>/invitable-users` |
| **权限控制** | 新增 `family` 菜单键，家长角色自动获得组内所有成员 view 权限 |
| **DB 迁移** | `CREATE TABLE IF NOT EXISTS family_groups` + `family_members`（幂等，SQLite/PG 双模式兼容） |

### 10.3 批量导入与智能识别（功能三）

#### 10.3.1 Excel 批量导入（字段映射）

| 项 | 说明 |
|------|------|
| **Excel 解析** | `openpyxl>=3.1.0`（纯 Python，无 C 扩展，~5MB） |
| **导入流程** | 上传文件 → `POST /api/import/preview` 解析表头+前5行 → 前端展示字段映射界面 → `POST /api/import/confirm` 确认映射批量入库 |
| **智能列名匹配** | 中英文列名自动匹配（姓名/name、金额/amount、事由/reason、收送/type 等） |
| **CSV 兼容** | 原 CSV 导入路由保留，Excel 导入支持 .csv/.xlsx/.xls 三格式统一入口 |

#### 10.3.2 OCR 图片智能识别

| 项 | 说明 |
|------|------|
| **OCR 引擎** | 复用 AI 服务（OpenAI 兼容 Vision API），`ai_service.py` 新增 `recognize_gift_image()` 函数 |
| **调用流程** | 上传图片 → `POST /api/ocr/recognize` → AI Vision 返回结构化 JSON → 用户编辑勾选 → `POST /api/ocr/batch-add` 批量入库 |
| **兜底方案** | 未配置 AI 或 AI 不支持 Vision 时显示「需配置支持图片识别的 AI 服务」提示 |
| **安全限制** | 单张图片 ≤ 5MB，支持 jpg/png/webp |

### 10.4 人情簿打印与海报导出（功能四）

#### 10.4.1 A4 打印人情簿

| 项 | 说明 |
|------|------|
| **方案** | 纯 CSS `@media print`，浏览器原生打印对话框支持「另存为 PDF」 |
| **模板** | `templates/print_giftbook.html`（独立全页面，不继承 base.html） |
| **路由** | `GET /export/print-giftbook` |
| **排版** | A4 纵向，每页 20 行，深红 #8B0000 主色调，楷体/宋体字体栈 |

#### 10.4.2 PDF 对账单

| 项 | 说明 |
|------|------|
| **PDF 引擎** | `reportlab>=4.0.0`（纯 Python，~4MB），`pdf_generator.py` 独立模块 |
| **路由** | `GET /export/pdf-statement` → 返回 PDF 文件下载 |
| **内容** | 封面页 → 汇总页（收/送/净额统计表）→ 明细页（全量记录分页表格） |
| **中文字体** | 三级兜底：NotoSansCJK → SimSun → MSYH → reportlab CID STSong-Light |

#### 10.4.3 手机分享长图海报

| 项 | 说明 |
|------|------|
| **方案** | `html2canvas 1.4.1` 本地化（~200KB），客户端渲染 PNG |
| **模板** | `templates/poster_template.html`（375px 手机宽度，暖色中式风格） |
| **数据 API** | `GET /api/poster/data` → JSON（summary + top5 + reasons） |
| **内容** | 顶部标题 → 收送汇总卡片 → TOP5 亲友排行 → 事由分布进度条 → 品牌水印 |

### 10.5 V10.11 文件变更清单

| 操作 | 文件 | 涉及功能 |
|------|------|---------|
| 新增 | `templates/dashboard.html` | 1 |
| 新增 | `templates/family.html` | 2 |
| 新增 | `templates/print_giftbook.html` | 4 |
| 新增 | `templates/poster_template.html` | 4 |
| 新增 | `pdf_generator.py` | 4 |
| 新增 | `static/vendor/echarts/5.5.0/echarts.min.js` | 1 |
| 新增 | `static/vendor/html2canvas/1.4.1/html2canvas.min.js` | 4 |
| 修改 | `models.py` | 2（FamilyGroup/FamilyMember 模型 + ALL_MENUS 扩展） |
| 修改 | `app.py` | 2（迁移SQL + _SCHEMA_VERSION 1018）+ 1/2（菜单权限） |
| 修改 | `routes_ext.py` | 1/2/3/4（全部新路由 + 权限映射） |
| 修改 | `ai_service.py` | 3（OCR 识别函数） |
| 修改 | `templates/base.html` | 1/2（导航栏新增菜单项） |
| 修改 | `templates/index.html` | 3（导入弹窗+OCR弹窗）+ 4（打印/导出按钮） |
| 修改 | `requirements.txt` | 3/4（openpyxl + reportlab） |

---

### 10.6 V10.11.1 导入导出格式统一 + 页面布局优化 + 海报二维码 + 看板趋势选择器

#### 10.6.1 导入导出格式统一

| 功能点 | 改动 |
|------|------|
| 礼金记录导出（`export_csv`） | 新增 `format=xlsx` 参数，openpyxl 生成 .xlsx（自动列宽）；CSV 保持不变 |
| 宴席台账导出（`banquet_export_excel`） | 修复名不副实：默认输出真实 .xlsx，新增 `format=csv` 选项 |
| 导入模版下载（`download_import_template`） | 新增 `format=xlsx` 参数，Excel 模版（openpyxl） |
| base.html 用户菜单 | 「导出数据(CSV)」→ 拆分为「导出数据(CSV)」+「导出数据(Excel)」 |
| 宴席详情按钮 | 从单个链接升级为下拉按钮组（Excel / CSV 双选项） |

#### 10.6.2 礼金账本按钮区重构

- **合并导入入口**：原「批量导入(CSV)」+「Excel导入」两个按钮合并为统一「导入」下拉菜单（Excel/CSV 字段映射导入 + CSV 快速导入 + 模版下载 + 拍照识别）
- **合并导出入口**：原「导出CSV」按钮组 + 「打印/导出」下拉合并为统一「导出」下拉菜单（全部/筛选/勾选 × CSV/Excel + 打印人情簿 + PDF对账单 + 长图海报）
- **高危操作移位**：「清空所有数据」从最左侧移至最右侧，样式改为 `btn-outline-danger`（暗色边框）
- **按钮排列**：`[新增礼金记录] [导入 ▼] [导出 ▼] [拍照识别] [清空数据]`

#### 10.6.3 导航栏防换行

- CSS 新增 `.navbar-nav .nav-link { white-space: nowrap; font-size: 0.875rem; padding: 0.6rem; }` + `.navbar-nav .nav-item { flex-shrink: 0; }`
- 消除菜单项文字被拆为两行的问题

#### 10.6.4 海报二维码自定义

- `SystemSetting` 新增 `poster_qr_url` 配置项
- 管理员可在「系统管理 > 海报二维码设置」中配置注册 URL
- `poster_template.html` 从静态占位文字升级为真实二维码（qrcode-generator 1.4.4 本地化 `static/vendor/qrcode/1.0.0/`）
- `/api/poster/data` 返回新增 `qr_url` 字段
- 新增 `/api/admin/poster-qr-url` GET/POST 路由

#### 10.6.5 数据分析看板趋势日期选择器

- 月度模式：新增月份范围选择器（`<input type="month">` 起始~结束）
- 年度模式：新增年份范围选择器（数字输入框 起始~结束）
- `/api/dashboard/stats` 新增 `start_month/end_month/start_year/end_year` 可选参数
- 趋势图上方独立日期选择器卡片，含查询/重置按钮

---

### 10.7 V10.11.2 新增菜单同步权限控制与Webhook推送矩阵

#### 10.7.1 菜单权限控制体系补齐

| 位置 | 改动 |
|------|------|
| `app.py` `admin_batch_user_permissions` ALL_MENUS | 补齐 `'dashboard'`/`'family'`（修复批量配置时静默清零 bug） |
| `app.py` `admin_update_user_permissions` ALL_MENUS + MENU_NAMES | 补齐两项 + 中文名映射（修复单用户保存时清零 bug） |
| `routes_ext.py` `TICKET_MENU_OPTIONS` | 补齐 `('dashboard','数据分析')`/`('family','家庭记账')`（工单渠道可申请） |
| `routes_ext.py` `menu_map` | 补充 `api_family_invitable_users`/`api_family_my_perspective_users`/`export_*`/`poster_*` 权限映射 |
| `admin_users.html` 单用户弹窗 | 新增「数据分析」（0~1 级）+「家庭记账」（0~3 级）复选框+下拉 |
| `admin_users.html` 批量配置弹窗 | 同步新增两项 |

#### 10.7.2 Webhook 推送矩阵补齐

| 位置 | 改动 |
|------|------|
| `webhook_utils.py` `PAGE_NAMES` | 新增 `'dashboard':'数据分析'`/`'family':'家庭记账'` |
| `webhook_utils.py` `PAGE_EVENT_MATRIX` | 新增 `'family': ['create','delete','status_change','security']` |
| `routes_ext.py` `api_family_create` | 补充 `trigger_webhook_event('create', ..., page_key='family')` |
| `routes_ext.py` `api_family_invite` | 补充 `trigger_webhook_event('status_change', ..., page_key='family')` |
| `routes_ext.py` `api_family_dissolve` | 补充 `trigger_webhook_event('delete', ..., page_key='family')` |

> `dashboard` 为只读看板，无写入操作，不加入 PAGE_EVENT_MATRIX。

---

### 10.8 V10.11.3 OCR/测试配置 404 修复（Agnes 模型接入指引）

#### 问题根因

用户将图像生成模型的完整端点当 Base URL 填入（`https://apihub.agnes-ai.com/v1/images/generations`），OpenAI SDK 的 chat 接口自动追加 `/chat/completions` 拼出不存在的路径 → 404 `Invalid URL`，且旧错误归类将 404 一律报为“模型名称不存在”，误导排查方向；同时 `agnes-image-2.5-flash` 是图像生成模型（画图），不支持看图识字（OCR）。

#### 修复内容

| 位置 | 改动 |
|------|------|
| `ai_service.py` `normalize_base_url()` | 新增：循环剥除误填的完整端点后缀（/chat/completions、/images/generations、/images/edits、/completions、/messages、/responses、/embeddings）及尾斜杠 |
| `ai_service.py` `_call_openai` / `test_ai_config` / `recognize_gift_image` | 三处创建 OpenAI client 均接入 base_url 清洗 |
| `ai_service.py` `test_ai_config` 错误归类 | 404+`Invalid URL` 改报“Base URL 疑似误填完整接口地址”；图像生成模型附专属提示 |
| `ai_service.py` `_is_image_gen_model()` | 新增：检测 agnes-image-*/DALL-E/Flux 等画图模型，OCR 失败时引导改用图像理解文本模型 |
| `ai_service.py` `recognize_gift_image` 失败信息 | 透出最后 3 条真实错误 + 模型类型/URL 格式针对性引导 |

#### Agnes 官方接入参数（OCR/对话正确配置）

| 项 | 正确值 | 说明 |
|---|---|---|
| 模型名称 | `agnes-2.5-flash` | 官方明确支持图像理解（截图分析/视觉问答/结构化提取），上下文 512K |
| Base URL | `https://apihub.agnes-ai.com/v1` | 根地址，SDK 自动追加 /chat/completions |
| 不可用 | `agnes-image-2.5-flash` | 图像生成模型（文生图/图生图，端点 /v1/images/generations），只能画图不能看图 |

---

### 10.9 V10.11.4 实时天气预报（Open-Meteo 数据源）

#### 功能设计

| 项 | 说明 |
|---|---|
| 数据源 | Open-Meteo（Geocoding + Forecast API），免费、无需 API Key、无需代理 |
| 服务封装 | `weather_service.py`：`geocode_city()` 城市名→经纬度/时区；`fetch_forecast()` 实时+3 日预报（daily 必带 timezone）；`query_weather()` 组合主入口；`WeatherError` 统一异常（中文 message + 建议 HTTP 状态码）；`weather_code_cn()` WMO 码中文映射（未知码兜底） |
| 路由 | `routes_weather.py`：`GET /weather` 页面（login_required）；`GET /api/weather/query?city=` JSON API（login_required，city 非空/≤30 字校验） |
| 前端 | `templates/weather.html`：城市搜索框 + 实时天气卡片（温度/体感/湿度/天气状况/风速）+ 3 天预报卡片（最高最低温/降水概率/天气状况+图标），fetch 携带 CSRF 头，深浅色双主题自适应 |
| 入口 | `base.html` 导航栏新增「天气」菜单（所有登录用户可见，不占用菜单权限体系） |
| 跨域 | 服务端 requests 调用，无 CORS 问题（Open-Meteo 本身亦支持 CORS） |

#### API 调用要点（严格遵循官方约束）

| 接口 | 请求 | 说明 |
|---|---|---|
| 地理编码 | `GET https://geocoding-api.open-meteo.com/v1/search?name={城市}&count=1&language=zh&format=json` | 取 `results[0]` 的 `latitude`/`longitude`/`timezone` |
| 天气预报 | `GET https://api.open-meteo.com/v1/forecast` + `current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m` + `daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max` + `timezone=auto` + `forecast_days=3` | **请求 daily 时必须携带 timezone**（优先地理编码返回值，缺省回落 `auto`），否则接口报错 |
| 错误格式 | `{"error": true, "reason": "..."}` | 服务层检测后透传 reason 为中文提示 |

#### WMO weather_code → 中文映射（weather_service.py 内置）

`0 晴 / 1 基本晴朗 / 2 局部多云 / 3 阴天 / 4 阴天 / 45 雾 / 48 冻雾 / 51·53·55 毛毛雨 / 56·57 冻毛毛雨 / 61 小雨 / 63 中雨 / 65 大雨 / 66·67 冻雨 / 71 小雪 / 73 中雪 / 75 大雪 / 77 米雪 / 80·81·82 阵雨 / 85·86 阵雪 / 95 雷阵雨 / 96 雷暴伴小冰雹 / 99 雷暴伴大冰雹`；未知码兜底「未知天气(N)」。

#### 错误处理矩阵

| 场景 | 返回 |
|---|---|
| 城市名为空 / 超长 | 400「请输入城市名称」/「城市名称过长」 |
| 地理编码无结果 | 404「未找到该城市，请检查城市名称是否正确」 |
| Open-Meteo 返回 error | 透传 `reason`（502） |
| 网络超时 / 连接失败 | 503「…服务超时/暂时不可用，请稍后重试」 |
| 未知异常 | 500「服务器内部错误」，日志记录不泄漏堆栈 |

#### 文件变更清单

| 文件 | 变更 |
|---|---|
| `weather_service.py` | 新增（约 260 行） |
| `routes_weather.py` | 新增（约 45 行） |
| `templates/weather.html` | 新增（约 210 行） |
| `app.py` | 末尾注册 `register_weather_routes(app)` |
| `templates/base.html` | 导航栏新增「天气」入口 |
| `README.md` | 公告 + 功能章节同步 |

#### 验证结论（浏览器实测）

| 场景 | 结果 |
|---|---|
| 默认查询「北京」 | 实时天气 + 3 天预报完整展示 ✅ |
| 查询「上海」 | 正常，weather_code 中文映射正确（毛毛雨/局部多云） ✅ |
| 查询不存在城市 | 提示「未找到该城市，请检查城市名称是否正确」 ✅ |
| 空输入 | 提示「请输入城市名称」 ✅ |
| 黑夜模式 | 页面样式自适应，无回归 ✅ |
| 未登录访问 | 重定向登录页（login_required 生效） ✅ |

---

### 10.10 V10.11.5 AI 配置模型列表 + OCR 识别修复 + PDF 导出修复

#### 功能设计

| 项 | 说明 |
|---|---|
| 模型列表 | `ai_service.fetch_model_list()`：`GET {Base URL}/models`（OpenAI 兼容、`Authorization: Bearer`，连接 5s/读取 15s）；错误分类——超时/连接失败/401/403/非 JSON/空列表均返回中文提示与 detail |
| 后端路由 | `routes_ai.py POST /api/ai/config/models`（仅管理员）：支持 `config_index`（已存配置）或直接传 `api_key/base_url` 两种模式 |
| 前端 | `admin_ai_config.html`：配置卡新增「获取模型列表」按钮 + 模型下拉（选择自动填入模型名）；API Key/Base URL 变更触发防抖 800ms 自动拉取；同一 key+url 组合不重复自动请求（手动按钮可强制刷新） |
| OCR 容错 | `_pick_field()` 中英文键名别名；`_parse_amount()` 金额容错（¥/千分位/中文数字/汉字金额，复用 gift_utils.cn2num）；`_parse_record_type()` 收送类型归一；Prompt 强制英文字段名 + 纯数字金额 + 空数组约定；0 条时透出模型原始返回片段 |
| OCR 前端防御 | 压缩长边 2048→1600px、质量 0.85→0.7→0.55 逐级降级（产物 <700KB）；`startOcrRecognize` 对非 JSON 响应（HTML 413/网关错误页）先查状态码与 Content-Type 再解析，报错信息带 HTTP 状态 |
| PDF 导出修复 | `routes_ext.py export_pdf_statement`：`Content-Disposition` 中文文件名触发 `UnicodeEncodeError`（HTTP 头 latin-1 限制，Werkzeug 真实服务器编码失败 → 浏览器收不到响应 = "点击无反应"）；改 RFC 5987 `filename*=UTF-8''{quote(name)}` + ASCII 兜底 `gift_statement_{date}.pdf` |

#### 验证结论

| 场景 | 结果 |
|---|---|
| 「获取模型列表」真实拉取（agnes apihub） | 成功获取 12 个模型（agnes-2.5-pro-alpha / agnes-3.0-flash 等）✅ |
| 下拉选择模型自动填入 | 选中模型名自动写入输入框 ✅ |
| 自动拉取（改 Base URL 防抖触发） | 自动重新拉取并渲染 ✅ |
| OCR 首次识别（真实 agnes-2.5-flash + 测试礼金簿图） | 张三 500 婚宴 / 李四 300 满月酒 / 王五 600 寿宴 3 条正确 ✅ |
| OCR 二次识别 | 正常返回 JSON，无 SyntaxError/HTML ✅ |
| PDF 导出（真实 HTTP 服务） | 200 + application/pdf + RFC5987 文件名，不再 UnicodeEncodeError ✅ |
| 前端控制台 | 0 报错 ✅ |

### 10.11 V10.11.6 天气权限管控 + Webhook 推送矩阵 + 登记时间自定义

#### 功能设计

| 项 | 说明 |
|---|---|
| 天气权限模型 | 「天气」从"所有登录用户可用"收紧为受控菜单：0=无权限 / 1=可查看实时天气（只读工具菜单，无数据权限维度）；`models.py` 的 `User.get_allowed_menus/get_menu_perm/set_menu_permissions` 与 `app.py` 的 `admin_update_user_permissions` 的 `ALL_MENUS` 均补充 `weather` |
| 权限回填 | `_do_startup_sync()` 启动时幂等追加：非管理员用户 `allowed_menus` 不含 `weather` 则追加（仅追加、幂等、打印回填数量），避免 V10.11.4 开放期老用户权限回退；新注册用户默认无天气权限 |
| 全链路门控 | `routes_ext.py menu_map` 新增 `weather_page`/`api_weather_query → 'weather'`，`menu_names` 补「天气」；`base.html` 导航天气入口改 `current_user.is_admin or can_access_menu('weather')` 条件渲染 |
| 工单申请 | `routes_ext.py` 权限申请清单 `TICKET_MENU_OPTIONS` 新增 `('weather', '天气')`，普通用户可提交天气权限申请 |
| 管理页配置 | `admin_users.html` 单用户权限弹窗 + 批量权限弹窗各新增「天气」复选框 + 0/1 级下拉（无天气访问权限 / 可查看实时天气） |
| Webhook 矩阵 | `webhook_utils.PAGE_NAMES` 新增 `'weather':'天气'`；`PAGE_EVENT_MATRIX` 新增 `weather: []` 只读行（无业务事件，界面展示"—"；同批补 `dashboard: []` 注释说明只读页面不产生事件） |
| 登记时间自定义 | `index.html` 编辑弹窗新增 `edit_created_at`（`datetime-local`，`name=created_at`），编辑按钮 `data-created` 回填原时间；`app.py edit_record` 解析 `%Y-%m-%dT%H:%M`，非法格式返回 400/表单错误，留空保持不变 |

#### 验证结论

| 场景 | 结果 |
|---|---|
| 管理员导航/页面/API | 全部可见可访问 ✅ |
| 无权限用户导航 | 天气入口隐藏，直接访问 `/weather` 跳权限申请页 ✅ |
| 有权限普通用户 | 导航可见、页面正常查询 ✅ |
| 权限回填 | 启动自动为老用户追加 weather，测试用户手动授权后权限准确 ✅ |
| 编辑登记时间 | 新记录编辑 → 改 `2026-03-15T08:45` → 保存成功，列表时间更新 ✅ |
| 非法时间格式 | 返回 400「登记时间格式不正确」✅ |
| Webhook 配置页 | 页面矩阵新增天气行（—），不影响既有推送 ✅ |

#### 文件变更清单

| 文件 | 变更 |
|---|---|
| `app.py` | `_do_startup_sync` 天气权限回填；`admin_update_user_permissions` ALL_MENUS/MENU_NAMES 补 weather；`edit_record` 登记时间解析 |
| `models.py` | `get_allowed_menus`（管理员列表）、`get_menu_perm`、`set_menu_permissions` 的 ALL_MENUS 补 weather |
| `routes_ext.py` | `menu_map`/`menu_names` 补 weather；`TICKET_MENU_OPTIONS` 补天气 |
| `templates/base.html` | 天气导航改为权限条件渲染 |
| `templates/admin_users.html` | 单用户 + 批量权限弹窗新增天气项 |
| `templates/index.html` | 编辑弹窗新增登记时间字段 + `data-created` 回填 |
| `webhook_utils.py` | `PAGE_NAMES`/`PAGE_EVENT_MATRIX` 补 weather（及 dashboard 注释） |
| `README.md` | 公告 + 功能章节 20 同步 |

### 10.12 V10.11.7 表格列宽手动调整 + 天气页面改版

#### 功能一：全平台表格列宽拖拽调整

| 项 | 说明 |
|---|---|
| 启用机制 | `<table data-resizable="表ID">` + 每个 `<th data-col="列key">`；全局脚本 `static/js/table-resizer.js`（base.html 全局引入，零依赖原生 JS）自动初始化 |
| 固化宽度 | 首次进入将各列 auto 布局下的自然宽度固化为显式像素写入 `th.style.width`，同时切 `table-layout: fixed`，拖拽实时生效 |
| 分隔条 | 每个 th 右缘注入 8px 命中区（`.colw-resizer`），hover 高亮 + `col-resize` 光标（Bootstrap CSS 变量双主题适配） |
| 约束 | 默认 min 60px / max 480px；单列可用 `data-col-min/max` 覆盖（checkbox 36、操作列 110+ 等） |
| 横向滚动 | 总宽超容器由 `.table-responsive` 出横向滚动条，不压缩其他列 |
| 双击自适应 | 同帧内切 auto 布局测该列最大内容宽 +16px 余量，再切回 fixed（无闪烁） |
| 持久化 | localStorage 键 `gift_colw_{用户ID}_{表ID}`（按用户+表格隔离），拖动结束保存全部列宽，加载自动恢复 |
| 重置入口 | JS 自动在容器右上角注入「↺ 重置列宽」小按钮，点击清存储恢复默认 |
| 防误选 | 拖动时 body 加 `colw-resizing` 类 → `user-select: none` + 全局 col-resize 光标 |
| 触摸/降级 | Pointer Events 统一；屏宽 <768px 自动 teardown 不拖拽不恢复，回退自然布局；跨断点 resize 防抖自动重绑 |
| title 提示 | 初始化/拖拽后为超宽截断单元格补 `title` 悬停看全文 |
| 覆盖范围 | 21 张主业务表：礼金账本 14 列、人情对账 2 张、用户管理 2 张、Webhook 2 张、备份管理 4 张、宴席列表+详情 2 张、回收站、纪念日、操作日志、权限工单、系统广播、分享台账（`excelPreviewTable` 动态预览小表不启用） |

#### 功能二：天气页面改版（15 天 + 级联选择 + 首页式布局）

| 项 | 说明 |
|---|---|
| 15 天预报 | `weather_service.fetch_forecast` 的 `forecast_days` 参数化（默认 15，1~16）；`/api/weather/query` 新增 `days` 参数 |
| 实时指标扩充 | current 增 surface_pressure/云量/wind_direction_10m（角度→中文方位）/wind_gusts_10m |
| 每日扩充 | daily 增 sunrise/sunset/uv_index_max/precipitation_sum |
| 级联数据 | `static/js/china-regions.js`（144KB）本地内置：阿里云 DataV GeoAtlas（34 省/476 市/2875 区县 + 行政中心坐标）；直辖市市级层显示省名；台湾/省直辖县级市自动补齐三级 |
| 根因说明 | GeoNames 中文库缺中国区县级地名（「双流区」0 候选、仅同名村镇错配），级联改用内置坐标直查 |
| 坐标模式 | `query_weather_by_coords(lat, lon, days, label)`：中国范围粗校验（纬 3~54/经 73~136）+ `timezone=auto` 直查；`/api/weather/query?lat=&lon=&label=` |
| 文本模式 | 保留 `city` 自由输入（Geocoding，兼容旧版）；`province/city2` 可选消歧参数（多候选 admin1/admin2 匹配打分 + 404 去后缀降级重试） |
| 首页式布局 | 大卡片（大温度数字 + 2×4 指标网格，文字不截断）→ 15 天温度趋势双折线图（本地化 ECharts 5.5.0，深浅主题）→ 15 天卡片网格（每行 5 个，今天高亮） |
| 记忆 | localStorage `gift_weather_mode/region/city`：刷新/再次进入自动恢复上次查询方式与地区，首次默认北京 |
| 网络策略修复 | `_http_get`：禁代理直连优先（国内直连可达）+ 失败回落系统代理；修复用户机器开梯子且代理不稳时持续超时 |

#### 验证结论

| 场景 | 结果 |
|---|---|
| 礼金账本 14 列初始化（fixed + 14 resizer + 重置按钮） | ✅ |
| 真实鼠标拖拽 +130px（80→210px） | ✅ |
| 刷新后 210px 恢复 + localStorage 保存 | ✅ |
| 重置按钮恢复默认 80px + 存储清除 | ✅ |
| 拖 -300px 钓到 min 60px | ✅ |
| 双击自适应 100px（内容最大宽） | ✅ |
| 总宽 1214 > 容器 936 → 横向滚动不压列 | ✅ |
| 抽查人情对账/用户管理/工单/操作日志/纪念日 resizer 全就绪 | ✅ |
| 回收站空数据不渲染表格（条件渲染） | ✅ 非缺陷 |
| 天气默认北京自动查询（15 天 + 全部扩充指标） | ✅ |
| 级联四川→成都→双流定位准（气压 961hPa 海拔效应坐标准确） | ✅ |
| 刷新后级联记忆恢复自动查询 | ✅ |
| 黑夜模式视觉（趋势图配色/卡片对比度） | ✅ |
| 指标文字完整无截断 + 趋势图在卡片前布局 | ✅ |

#### 文件变更清单

| 文件 | 变更 |
|---|---|
| `static/js/table-resizer.js` | 新增：全局列宽拖拽脚本 |
| `static/js/china-regions.js` | 新增：行政区划+坐标数据（本地内置） |
| `templates/base.html` | 全局列宽样式 + `data-user-id` 注入 + table-resizer.js 引入 |
| 14 个模板 21 张表 | 补 `data-resizable` / `th data-col` 标记（index/reconciliation/admin_users/admin_webhooks/admin_backups/admin_logs/admin_broadcasts/reminders/recycle_bin/permission_tickets/banquets/banquet_detail/shared_ledger） |
| `weather_service.py` | 15 天参数化 + 指标扩充 + 坐标直查入口 + 级联消歧 + `_http_get` 双路径网络策略 |
| `routes_weather.py` | `days/lat/lon/label/province/city2` 参数 |
| `templates/weather.html` | 重写：级联 + 自由输入双模式、首页式布局、趋势图、记忆恢复 |

### 10.13 V10.11.8 天气页面全面增强 + 告警消息推送（权限联调）

#### 功能一：天气查询交互修复（4 项）

| 项 | 说明 |
|---|---|
| 级联任意级查询 | 省级（未选市）→省会坐标、市级（未选县）→市中心坐标、县级→县坐标；`doCascadeQuery` 放开三级全选限制，label 按所选层级拼接去重 |
| 懒加载逐级展开 | 初始仅显省下拉；选省后显市下拉（`citySelectWrap`）；选市后显县下拉（`districtSelectWrap`）；重选/清空时逐级隐藏 |
| 自由输入本地匹配 | `localMatchCity(text)`：归一化去后缀 + 省/市/县三级匹配（与后端 `_norm_region` 同规则），更具体层级优先（县>市>省）；命中走坐标模式直查（修复「成都市」在线解析 404），未命中回退后端 Geocoding（保留国外城市能力） |
| 双按钮冲突修复 | 每个按钮独立 loading（`btnPending` 计数，只改被点按钮文案），另一按钮保持原状；`reqSeq` 请求序号防竞态（旧响应丢弃不渲染） |
| 页面锁死修复 | ① 前端 `AbortController` 30s 超时（后端直连+代理兑底最坏 26s，超时必恢复按钮，杜绝永久「查询中」）；② 记忆键全部追加用户 ID（`gift_weather_{uid}_*`，同浏览器多账号不串扰，修复退出重进残留他人查询）；③ 新增「重置记忆」按钮一键清空恢复默认北京 |

#### 功能二：天数自定义 + 日历视图 + 对比 + 指数 + 空气质量

| 项 | 说明 |
|---|---|
| 天数控件 | 分段按钮（7/15/16）+ 下拉框（1~16）组合；切换即按当前查询上下文重查，localStorage 记忆 |
| 日历月视图 | 当月网格（周一起始）每日含图标/高低温/降水概率；预报范围外灰置「—」不可点；月份导航不可早于当前月；今日蓝高亮、选中绿描边 |
| 日历周视图 | 今天起 7 天全要素行（天气/温度/降水概率/紫外线/降水总量/日出日落） |
| 点击联动 | 选中日期 → 详情面板（8 项指标）+ 趋势图绿色虚线标记线（markLine）+ 月/周视图同步高亮 |
| 多城对比 | 输入省/市/县名添加（本地匹配、去重、上限 3 个）；主城 + 对比城最高温同图叠加（ECharts 多系列 + 图例）；单城失败跳过并提示；记忆持久化 |
| 生活指数 | 穿衣（体感 6 档）/雨伞（降水概率 3 档）/防晒（紫外线 5 档）/洗车（雨雪码+概率）/出行（风速 3 档）/舒适度（温湿度区间）—— 6 项自研规则 2×3 卡片 |
| 空气质量 | `fetch_air_quality`（Air Quality API `current=pm10,pm2_5,us_aqi`）失败静默降级；PM2.5 按中国 24h 标准分级（0-35 优→>250 严重）配色徽章 + PM10 数值 |

#### 功能三：告警消息推送（管理员菜单权限 ↔ WebDAV 告警配置联调）

| 项 | 说明 |
|---|---|
| 数据模型 | `alert_push_configs`（单行全局配置：总开关/4 类触发/静默期/合并推送/巡检城市/last_push_at JSON）+ `alert_push_grants`（按用户操作授权，user_id 唯一）；`_SCHEMA_VERSION` 1018 → **1019** |
| 巡检线程 | `alert_service.start_alert_inspector`：daemon 线程，首轮延迟 60s 后每 30 分钟一轮；每轮实时判定总开关 + 有效授权（无任何授权用户自动停用推送，配置保留不生效） |
| 天气预警规则 | 巡检城市逐一调 Open-Meteo（8 天窗口）：降温≥8℃ / 日降水概率≥70% / 阵风≥50km/h / 最低温≤0℃ / 最高温≥38℃ |
| 接口异常 | 巡检中天气接口调用失败即事件源（城市 + 错误摘要） |
| 数据完整性 | 关键文件非空校验（china-regions.js/table-resizer.js/echarts/weather.html/base.html/weather_service.py/routes_weather.py/alert_service.py） |
| 定时任务失败 | 扫描 35 分钟回溯窗口内 `scheduled_task_execution_logs` failed 记录（同任务去重） |
| 频控 | 同类型静默期内不重复推（`should_push`/`mark_pushed`，持久化重启后仍有效）；同类型多条合并一条消息（日志分类准确） |
| 推送执行 | 复用 `trigger_webhook_event(force_channels=True)`：企微长连接/钉钉/飞书/pushplus/通用 URL 全支持；邮件本轮不含 |
| 路由 | `routes_alert.py`：config（GET/POST）/test/run/logs/logs-csv/grants（GET/POST）；全部操作级实时校验 + menu_map backups 门控 |
| 前端配置区 | `admin_backups.html` 新增「告警消息推送」卡片：配置区 + 立即巡检 + 测试推送 + 授权管理表（仅超管）+ 日志筛选（类型/结果/分页/CSV 导出）；权限三态渲染（无编辑→置灰+提示条；无测试→隐藏按钮；无日志→隐藏区） |
| 联调规则 | 无 backups 菜单权限 URL 直访被 menu_map 拦截；操作中权限回收 → 403 + 前端提示跳首页；保存失败事务回滚保留原配置；权限全回收 → 巡检自动停用（无孤儿任务）；授权保存立即生效 |

#### 功能四：AI 配置网络策略修复

| 项 | 说明 |
|---|---|
| 问题现象 | AI 配置页「获取模型列表」持续超时；「测试」约 26s 后报 Connection error（API 配置本身正确） |
| 根因 | `requests` 与 OpenAI SDK（httpx）默认 `trust_env` 自动走系统代理；用户机器代理进程存活但出口节点不通时，全部 AI 出网请求挂死在坏代理上直至超时（与 V10.11.7 天气修复前同款问题） |
| 双路径函数 | `_ai_http_get(url)`：requests 禁代理直连优先 + 系统代理兜底，超时 `AI_HTTP_TIMEOUT=(5, 20)`；`_chat_with_fallback`：SDK `httpx.Client(trust_env=False)` 直连优先，仅 `APIConnectionError`（连接类异常含超时）回落系统代理重试一次，鉴权/参数类错误不回落 |
| 覆盖调用链 | `fetch_model_list`（模型列表）/ `test_ai_config`（配置测试，timeout=15）/ `_call_openai`（AI 对话，timeout=30）/ `recognize_gift_image`（OCR，timeout=120）全部 4 条 |
| 验证 | 「获取模型列表」秒回 12 个 Agnes 模型；「测试」`agnes-3.0-flash` 5.1s 返回「测试成功」（修复前 26.3s Connection error）；个别模型返回空内容时提示「接口连通正常但返回内容为空，请检查模型名称」（属模型侧行为非网络问题） |

#### 验证结论（隔离副本库 55 项断言 + 11444 临时实例）

| 场景 | 结果 |
|---|---|
| 6 文件语法编译 + schema 1019 迁移 + 两新表建表 | ✅ |
| 16/7 天预报 + air_quality 真实返回（pm25=43.5） | ✅ |
| 告警配置初始化/授权判定/回收失效/静默期/巡检跳过/开启巡检/完整性/任务失败检测/城市解析 | ✅ |
| admin 全流程（config 保存/越界拒/空城拒/测试无通道提示/手动巡检/日志/筛选/CSV/授权/回收） | ✅ |
| 普通用户 5 个接口全部被拦截（menu_map 门控） | ✅ |
| 副本库运行库隔离确认（运行库仍 1018 无 alert 表） | ✅ |
| AI 网络策略修复（模型列表 12 个秒回 + 配置测试 5.1s 成功） | ✅ |

#### 文件变更清单

| 文件 | 变更 |
|---|---|
| `models.py` | 新增 `AlertPushConfig` / `AlertPushGrant` 两模型 |
| `app.py` | `_SCHEMA_VERSION` 1019 + 两表建表迁移 + 告警路由注册 + 巡检线程启动 |
| `alert_service.py` | 新增：配置/授权/频控/四类检测/巡检线程/测试推送 |
| `routes_alert.py` | 新增：告警 8 个 API（config/test/run/logs/csv/grants） |
| `routes_ext.py` | `menu_map` 补 8 个告警 endpoint（backups 门控） |
| `weather_service.py` | 新增 `fetch_air_quality` + `_build_result` 扩展 air_quality 字段 |
| `templates/weather.html` | 重写：4 bug 修复 + 天数控件 + 日历月/周 + 对比 + 指数 + 空气质量 + 用户级记忆 |
| `templates/admin_backups.html` | 新增「告警消息推送」卡片（配置/授权/日志三区） |
| `ai_service.py` | 新增 `_ai_http_get` / `_chat_with_fallback` 双路径出网函数，改造 4 处调用点（模型列表/测试/对话/OCR） |

---

## 附录：文档元数据

| 属性 | 值 |
|------|-----|
| 文档版本 | V10.11.8 |
| 生成日期 | 2026-10-09（V10.11.8 修订，天气页面全面增强 + 告警消息推送权限联调 + AI 配置网络策略修复；承接 V10.11.7 表格列宽与天气改版） |
| 审计基线 | 代码 commit main 分支 V10.10.29（含 V10.10.16 性能优化同步 + V10.10.17 交互式数据库部署选择 + V10.10.17b run.sh 模块化拆分 + V10.10.18 前端资源本地化与部署链路加固 + V10.10.19 run.sh status 访问信息展示 + V10.10.19b 帮助示例命令名规范化 + V10.10.20 初次部署纯净化 + 独立 PG 镜像策略与 psycopg 驱动修复 + DB_RESET 重选菜单修复与 PG_IMAGE 示例细化 + PG 连接参数全面自定义 + V10.10.21 run.sh 深度模块化拆分 + 配置单点化 + V10.10.22 PG 密码认证修复与 pyzipper 缺失修复与密码固定默认值 + V10.10.23 --reconfig 参数替代 DB_RESET=1 + V10.10.24 Docker 版 PG 默认值差异化隔离 + V10.10.25 共享 PG 状态误判与独立 PG 卷布局崩溃与 peer 认证修复 + V10.10.26 独立 PG unless-stopped 与跨版本共享 PG 检测排除 + V10.10.27 两版首次部署默认数据库差异化 + V10.10.28 独立 PG 版本化数据卷与存量卷自动迁移 + V10.10.29 独立 PG 生命周期闭环（stop 无条件释放与 start 自动重建）） |
| 代码审计范围 | 10 个根目录 Python 文件（12,371 行；另有 aibot/ 官方 SDK 副本 9 个文件不计入）+ 21 个 HTML 模板（11,990 行，V10.10.13 主题改造后）+ run.sh + nginx_ssl.conf + requirements.txt + .gitignore |
| 文档审计范围 | README.md、Project_Survey.md、AI_ASSISTANT_DESIGN.md、V8_修复设计方案.md（后三者已于 PSD 定稿后归档移除） |
| 漂移项总数 | 10（2 高影响 → D-03 已于 V10.10.18 清偿，余 D-02 待治理 / 1 中影响 / 4 低影响 / 3 一致） |
| 技术债总数 | 21（6 代码质量 / 4 性能 / 3 扩展性 / 4 安全 / 4 运维） |
| 治理路线 | P0（2 项 → CDN 本地化已于 V10.10.18 完成，余 Gunicorn 待治理）/ P1（4 项 1-2 周）/ P2（5 项 1-2 月） |
| 最终结论 | 不建议替换框架，仅局部治理 |

> 本文档由星辰超级智能体（TeleAgent）基于代码全量审计与历史文档交叉核验生成，所有架构事实均标注具体代码依据（`相对路径:行号` 或 `函数名`），遵循"代码是实现真相、文档是意图真相、显式揭露漂移、证据链闭环"四大核心准则。