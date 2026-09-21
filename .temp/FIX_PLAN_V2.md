# 人情记账宝 — 14 项修复与优化设计方案（V2）

> 分支：`feature/ai-assistant` | 日期：2026-09-10 | 状态：**待用户审批**

---

## 一、问题总览

| # | 类型 | 问题 | 涉及文件 |
|---|------|------|----------|
| 1 | 优化 | 权限申请页已申请菜单可重复勾选 | `permission_tickets.html` `routes_ext.py` |
| 2 | 修复 | Webhook 新增 Modal 缺少保存按钮 | `admin_webhooks.html` |
| 3 | 修复 | Webhook 编辑按钮无反应 | `admin_webhooks.html` |
| 4 | 修复 | pyzipper 未安装提示 | `requirements.txt` |
| 5 | 修复 | 普通用户看到管理员 WebDAV 配置 | `admin_backups.html` `routes_ext.py` |
| 6 | 修复 | 普通用户看不到定时备份任务 | `admin_backups.html` |
| 7 | 修复 | 本地上传仅支持 .db | `admin_backups.html` `routes_ext.py` |
| 8 | 修复 | WebDAV 上传 HTTP 404 | `webdav_utils.py` `admin_backups.html` |
| 9 | 优化 | 备份页排版重构 + 定时任务改造 | `admin_backups.html` `routes_ext.py` `models.py` |
| 10 | 修复 | 恢复 .db 后数据未生效 | `routes_ext.py` |
| 11 | 优化 | Webhook 日志缺用户列 + 记录完善 | `admin_webhooks.html` `webhook_utils.py` |
| 12 | 优化 | 备份操作审计日志缺失 | `routes_ext.py` |
| 13 | 修复 | Webhook 操作日志写入审计日志 | `webhook_utils.py` `routes_ext.py` |
| 14 | 确认 | 设计方案需用户过审后执行 | — |

---

## 二、逐项修复方案

### 问题 1：权限申请页已申请菜单可重复勾选

**现状**：新建工单 Modal 中所有菜单 checkbox 均可勾选，不检查用户是否已有 pending 工单包含对应菜单或已拥有该权限。

**修复方案**：

- **后端** (`routes_ext.py` — `permission_ticket_create` 路由)：
  - 查询当前用户所有 `status='pending'` 的工单，提取已申请菜单集合
  - 查询当前用户 `allowed_menus` 已拥有的菜单集合
  - 将两个集合合并为 `already_requested` 传给模板

- **前端** (`permission_tickets.html`)：
  - 菜单 checkbox 渲染时，如果 `key in already_requested`，添加 `disabled` 属性 + `checked` 状态
  - 在 label 旁显示小标签提示"申请中"或"已有权限"
  - 后端提交时也做校验：如果提交的菜单已在 pending 工单中，flash 提示并拒绝

**影响范围**：`routes_ext.py` 修改 1 个路由，`permission_tickets.html` 修改 checkbox 渲染部分

---

### 问题 2：Webhook 新增 Modal 缺少保存按钮

**现状**：`#newWebhookModal` 的 modal-body 结束后直接关闭 modal，缺少 modal-footer，无保存/提交按钮。

**修复方案**：

- **前端** (`admin_webhooks.html`)：
  - 在 `#newWebhookModal` 的 `</div>` (modal-body 结束) 后、modal-content 关闭前，插入标准 modal-footer：
    ```html
    <div class="modal-footer border-light">
      <button type="button" class="btn btn-light rounded-pill px-4" data-bs-dismiss="modal">取消</button>
      <button type="submit" class="btn btn-primary rounded-pill px-4 shadow-sm">保存配置</button>
    </div>
    ```
  - 注意 form 标签需包裹到 footer 内（当前 form 在 modal-body 内开始，需要确保提交按钮也在 form 内）

**影响范围**：`admin_webhooks.html` 插入约 5 行 HTML，调整 form 闭合标签位置

---

### 问题 3：Webhook 编辑按钮无反应

**现状**：`.btn-edit-webhook` 的 click 事件监听器代码完整（行 779-843），逻辑正确。可能原因：

1. 新增 Modal 的 HTML 结构错误（缺 footer 导致 DOM 层级异常），可能影响 JS 解析
2. 某处 JS 语法错误导致后续事件绑定失败

**修复方案**：

- 先修复问题 2（补全 Modal HTML 结构）
- 在 JS 中为编辑按钮事件添加 **错误调试日志**：
  - 在 click 回调第一行加 `console.log('edit clicked', this.dataset.id)`
  - 如果仍无反应，检查是否有 JS 运行时错误（通过 `playwright_browser_console_messages`）
- 如果确实是 JS 错误导致，定位并修复对应语法问题

**影响范围**：修复问题 2 后大概率自动修复；如仍有问题则排查 JS 控制台错误

---

### 问题 4：pyzipper 未安装提示

**现状**：`requirements.txt` 已声明 `pyzipper>=0.3.1`，但环境中未安装，模板显示警告。

**修复方案**：

- 执行 `pip install pyzipper` 安装依赖
- 安装后 `HAS_PYZIPPER` 标志自动变为 `True`，模板警告自动消失
- **无需修改代码**

**影响范围**：仅环境操作，不修改代码文件

---

### 问题 5：普通用户看到管理员 WebDAV 配置

**现状**：`BackupConfig.get_config()` 返回全局唯一配置记录，普通用户能看到管理员的 WebDAV 地址、用户名、密码（可明文查看）。

**修复方案**：

采用"管理员配置、授权用户只读使用"模式：

- **模板** (`admin_backups.html`)：
  - WebDAV 配置区域增加 `{% if current_user.is_admin %}` 条件：
    - **管理员**：完整配置表单（可编辑 URL/用户名/密码/加密密码）
    - **普通用户**：只读信息卡片，显示"已由管理员配置 WebDAV 备份"状态，**不显示地址/密码等敏感信息**
    - 普通用户如需独立配置，可提交"申请备份权限"工单

- **后端** (`routes_ext.py`)：
  - `admin_save_webdav_config` 路由增加 `if not current_user.is_admin: abort(403)` 限制
  - `admin_test_webdav` 路由保持管理员和授权用户均可测试（测试时使用全局配置，不传明文给前端）

- **不修改 `models.py`** — 保持 BackupConfig 全局单例，通过权限控制隔离

**影响范围**：`admin_backups.html` 重构配置区域，`routes_ext.py` 保存配置路由加权限限制

---

### 问题 6：普通用户看不到定时备份任务

**现状**：行 76 `{% if current_user.is_admin %}` 包裹定时任务卡片和授权管理卡片，普通用户不可见。

**修复方案**：

- **模板** (`admin_backups.html`)：
  - 定时任务卡片条件改为 `{% if current_user.is_admin or current_user.can_use_backup() %}`
  - 卡片内容区分权限：
    - 管理员：完整 CRUD（创建/编辑/删除/启停定时任务）
    - 授权用户：只读查看定时任务列表和执行状态
  - 授权管理卡片保持 `{% if current_user.is_admin %}`（仅管理员可管理授权）

**影响范围**：`admin_backups.html` 修改条件判断 + 卡片内容分权限渲染

---

### 问题 7：本地上传仅支持 .db

**现状**：文件选择器 `accept=".db"`，后端仅校验 `.db` 后缀，不支持其他类型文件恢复。

**修复方案**：

- **模板** (`admin_backups.html`)：
  - 将上传区域拆分为两个独立卡片：
    1. **数据库恢复**：`accept=".db"`，用于恢复 .db 文件
    2. **附件恢复**：`accept=".json,.csv,.txt,.xlsx,.docx,.zip"`，用于恢复其他备份文件
  - 两个卡片分别有独立的上传表单和提交按钮

- **后端** (`routes_ext.py`)：
  - 保留 `admin_upload_local_backup` 处理 .db 文件
  - 新增 `admin_upload_attachment` 路由处理其他类型文件，保存到指定目录

**影响范围**：`admin_backups.html` 新增上传卡片，`routes_ext.py` 新增 1 个路由

---

### 问题 8：WebDAV 上传 HTTP 404

**现状**：`ensure_remote_dir()` 只做单层 MKCOL，不支持递归创建多级目录；坚果云等对 `/dav/` 根目录写保护，直接上传返回 404。

**修复方案**：

- **`webdav_utils.py`**：
  1. 新增 `_resolve_target_dir_url(base_url)` 函数：
     - 如果 URL 以 `/dav` 或 `/dav/` 结尾，自动追加 `/gift_backups/`
     - 如果 URL 以其他路径结尾，保持原样但确保以 `/` 结尾
     - 返回标准化后的目标目录 URL

  2. 改造 `ensure_remote_dir()` 支持递归创建：
     - 先调用 `_resolve_target_dir_url()` 标准化 URL
     - 解析 URL 路径为多级目录段
     - 从根目录开始逐级 PROPFIND 检查 → MKCOL 创建
     - 每级创建成功后继续下一级，确保完整路径可用

  3. 上传函数 `upload_to_webdav()` 调用改造后的 `ensure_remote_dir()`

- **模板** (`admin_backups.html`)：
  - WebDAV 配置区增加"备份存储子目录"输入框（可选），默认值 `gift_backups`
  - 后端将子目录路径存入 `BackupConfig.backup_subdir` 字段

- **`models.py`**：
  - `BackupConfig` 新增 `backup_subdir` 字段（String, default='gift_backups'）

**影响范围**：`webdav_utils.py` 新增 1 个函数 + 改造 1 个函数，`admin_backups.html` 新增输入框，`models.py` 新增 1 字段，`app.py` 追加迁移 SQL

---

### 问题 9：备份页排版重构 + 定时任务改造

**现状**：备份页面排版混乱，.db 文件和其他文件上传混在一起；定时备份任务仅支持数据库备份，用户希望改为"定时任务"支持选择备份内容或自定义脚本。

**修复方案**：

分两个部分：

**A. 页面排版重构** (`admin_backups.html`)：

重新组织页面布局为以下顺序：
1. **WebDAV 配置**（管理员可编辑 / 普通用户只读状态卡片）
2. **定时任务管理**（管理员 CRUD / 授权用户只读）
3. **数据库备份与恢复**（备份 + .db 上传恢复 + WebDAV 远程恢复）
4. **附件文件恢复**（其他文件上传）
5. **备份功能授权管理**（仅管理员）

**B. 定时任务改造** (`models.py` + `routes_ext.py` + `admin_backups.html`)：

- `ScheduledBackupTask` 模型扩展字段：
  - `task_type` (String, default='db_backup')：任务类型 — `db_backup`(数据库备份) / `file_backup`(文件备份) / `custom`(自定义脚本)
  - `target_files` (Text, nullable)：目标文件列表（JSON 数组），用于 file_backup 类型
  - `custom_script` (Text, nullable)：自定义脚本内容，用于 custom 类型

- 路由扩展：
  - 创建/编辑定时任务时接收 `task_type`、`target_files`、`custom_script` 参数
  - `_backup_scheduler_worker` 根据 `task_type` 执行不同逻辑：
    - `db_backup`：备份数据库文件（现有逻辑）
    - `file_backup`：打包指定文件上传到 WebDAV
    - `custom`：执行自定义脚本命令（需管理员权限，有安全提示）

- 模板更新：
  - 定时任务 Modal 增加任务类型选择下拉框
  - 根据任务类型动态显示对应配置区域
  - 卡片标题从"定时备份任务"改为"定时任务"

**影响范围**：`admin_backups.html` 全页面重构，`models.py` 新增 3 字段，`routes_ext.py` 改造定时任务 CRUD + 调度逻辑，`app.py` 追加迁移 SQL

---

### 问题 10：恢复 .db 后数据未生效

**现状**：`admin_upload_local_backup` 直接 `file.save(db_path)` 覆盖数据库文件，但 SQLAlchemy 连接池仍持有旧句柄，后续操作可能读取旧数据或报错。

**修复方案**：

- **`routes_ext.py`** (`admin_upload_local_backup` 和 WebDAV 恢复路由)：
  - 覆盖文件后、redirect 前调用 `db.engine.dispose()` 释放所有连接池连接
  - dispose 后下次访问会自动重建连接，读取新文件
  - 同时 flash 提示"数据库已恢复，建议刷新页面确认数据更新"
  - WebDAV 远程下载恢复路由同样追加 dispose 调用

代码示例：
```python
file.save(db_path)
db.engine.dispose()  # 释放连接池，强制下次访问重新连接
safe_log('上传恢复本地备份', f"成功恢复了数据库文件: {file.filename}")
flash('本地数据库已成功恢复，请刷新页面确认数据更新。', 'success')
```

**影响范围**：`routes_ext.py` 修改 2 个路由（本地上传 + WebDAV 恢复），各加 1 行 `db.engine.dispose()`

---

### 问题 11：Webhook 日志缺用户列 + 记录完善

**现状**：
- 推送日志表格无"发起用户"列
- `record_webhook_log()` 中 `user_id` 取的是 WebhookConfig 的创建者（通道所属用户），非操作发起人
- `user_id` 为空时默认填 1（管理员）

**修复方案**：

- **`webhook_utils.py`**：
  - `trigger_webhook_event()` 增加 `operator_id` 参数（操作发起人 ID）
  - `record_webhook_log()` 增加 `operator_id` 参数，写入新字段
  - `user_id` 仍记录通道所属用户，`operator_id` 记录操作发起人

- **`models.py`**：
  - `WebhookLog` 新增 `operator_id` 字段（Integer, nullable=True, ForeignKey('users.id')）

- **`admin_webhooks.html`**：
  - 日志表格表头新增"发起用户"列（在"触发通道"后）
  - 行模板渲染 operator 用户名（通过关联查询或后端预加载）

- **`routes_ext.py`**：
  - 所有调用 `trigger_webhook_event` 的地方传入 `operator_id=current_user.id`
  - 日志查询路由返回 operator 用户名

**影响范围**：`webhook_utils.py` 修改 2 个函数，`models.py` 新增 1 字段，`admin_webhooks.html` 修改表格，`routes_ext.py` 修改所有 webhook 触发调用点，`app.py` 追加迁移 SQL

---

### 问题 12：备份操作审计日志缺失

**现状**：`admin_test_webdav`、`admin_backups_list_ajax` 等路由未调用 `safe_log`，操作不留审计记录。

**修复方案**：

- **`routes_ext.py`**：全面排查并补充 `safe_log` 调用：
  - `admin_test_webdav`：记录"测试 WebDAV 连接"（成功/失败）
  - `admin_backups_list_ajax`：记录"查看备份文件列表"
  - `admin_download_backup`：确认已有 safe_log（若无则补充）
  - `admin_delete_backup`：确认已有 safe_log（若无则补充）
  - Webhook 测试通知路由：确认 safe_log 覆盖

- 补充原则：
  - 写操作（创建/修改/删除/恢复）→ 必须记录
  - 读操作（查看列表/测试连接）→ 记录但不标记为重要

**影响范围**：`routes_ext.py` 在约 5-8 个路由中补充 `safe_log` 调用

---

### 问题 13：Webhook 操作日志写入审计日志

**现状**：Webhook 推送日志通过 `record_webhook_log()` 写入 `webhook_logs` 表（独立于审计日志），但 Webhook 配置操作（创建/编辑/删除 Webhook 配置）的审计日志可能不完整。

**修复方案**：

- **`routes_ext.py`**：排查 Webhook 配置相关路由的 `safe_log` 调用：
  - `admin_create_webhook`：记录"创建 Webhook 配置"
  - `admin_edit_webhook`：记录"编辑 Webhook 配置"
  - `admin_delete_webhook`：记录"删除 Webhook 配置"
  - `admin_test_webhook`：记录"测试 Webhook 推送"
  - Webhook 启停路由：记录状态变更

- **`webhook_utils.py`**：
  - 推送日志（`record_webhook_log`）保持写入 `webhook_logs` 表不变
  - 确保不与 `safe_log` 混淆：推送日志 = 技术日志，审计日志 = 操作日志
  - 在推送日志记录成功/失败时，不再重复写审计日志

**影响范围**：`routes_ext.py` 在 Webhook 配置 CRUD 路由中补充/确认 `safe_log` 调用

---

### 问题 14：设计方案需用户过审

**本方案即为过审文档**，用户确认后立即开始执行。

---

## 三、执行计划

按以下顺序分批执行，每批完成后验证：

| 批次 | 包含问题 | 预估修改文件数 | 说明 |
|------|----------|---------------|------|
| 第 1 批 | #2 #3 #4 | 1 + 环境操作 | Webhook Modal 修复 + pyzipper 安装，快速修复最影响使用的问题 |
| 第 2 批 | #1 #11 #13 | 3 | 权限工单 + Webhook 日志完善，逻辑性修复 |
| 第 3 批 | #5 #6 #7 | 2 | 备份页权限隔离 + 上传分拆，用户权限相关 |
| 第 4 批 | #8 #10 | 3 | WebDAV 上传 404 修复 + 恢复生效，技术性修复 |
| 第 5 批 | #9 #12 | 4 | 页面重构 + 定时任务改造 + 审计日志补全，最大改动 |
| 第 6 批 | 文档更新 | 2 | 更新 AI_ASSISTANT_DESIGN.md 和 README |

每批完成后执行：
1. Python 语法验证（`python -m py_compile`）
2. 关键页面 HTTP 200 检查
3. Git 提交（每批 1 个 commit）

---

## 四、数据模型变更汇总

### 新增字段

| 模型 | 字段 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `BackupConfig` | `backup_subdir` | String(100) | `'gift_backups'` | WebDAV 备份存储子目录 |
| `ScheduledBackupTask` | `task_type` | String(20) | `'db_backup'` | 任务类型 |
| `ScheduledBackupTask` | `target_files` | Text | null | 目标文件列表(JSON) |
| `ScheduledBackupTask` | `custom_script` | Text | null | 自定义脚本 |
| `WebhookLog` | `operator_id` | Integer | null | 操作发起人ID(FK users.id) |

### 迁移 SQL

```sql
-- BackupConfig 新增字段
ALTER TABLE backup_config ADD COLUMN backup_subdir VARCHAR(100) DEFAULT 'gift_backups';

-- ScheduledBackupTask 新增字段
ALTER TABLE scheduled_backup_tasks ADD COLUMN task_type VARCHAR(20) DEFAULT 'db_backup';
ALTER TABLE scheduled_backup_tasks ADD COLUMN target_files TEXT;
ALTER TABLE scheduled_backup_tasks ADD COLUMN custom_script TEXT;

-- WebhookLog 新增字段
ALTER TABLE webhook_logs ADD COLUMN operator_id INTEGER REFERENCES users(id);
```

---

## 五、风险评估

| 风险 | 等级 | 应对措施 |
|------|------|----------|
| 定时任务自定义脚本执行存在安全风险 | 中 | 仅管理员可创建 custom 类型；脚本内容记录审计日志；UI 显示安全警告 |
| db.engine.dispose() 后并发请求可能短暂失败 | 低 | dispose 后立即有新请求自动重建连接；加 flash 提示用户刷新 |
| WebhookLog operator_id 历史数据为空 | 低 | nullable=True，前端渲染时显示"系统"或"未知" |
| 页面重构可能引入样式问题 | 低 | 保持 Bootstrap 5 风格一致，逐卡片验证 |
| 递归创建 WebDAV 目录可能触发限频 | 低 | 每级 PROPFIND+MKCOL 间隔 100ms，最多 5 级 |

---

## 六、不修改的内容

- `BackupConfig` 保持全局单例模式（不拆分为 per-user 配置）
- 推送日志 `record_webhook_log()` 保持独立写入 `webhook_logs` 表（不合并到审计日志）
- 现有 Webhook 推送矩阵功能不变
- AI 助手模块不受本次修改影响

---

> **请确认本方案是否可以开始执行，或需要调整哪些部分。**
