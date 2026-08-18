# 人情礼金记账系统 (Gift Bookkeeping App)

> **最新更新说明**：优化账号安全与退出登录逻辑，修复包含静态页面与退出路由在内的 Session 超时无感知处理，全局配置浏览器 `Cache-Control` 防缓存响应头，解决回退页面/登出报错 500 问题；更新并完善全站 CSRF 防护机制与安全审计功能。


# 人情礼金记账系统 (Gift Bookkeeping App)

一个基于 **Python Flask + SQLite + Bootstrap 5** 开发的简洁、高效的人情往来与礼金记账管理系统。支持多用户管理、礼金收支记录、多维度统计图表、Excel/CSV 批量导入导出、高级多字段模糊搜索，并配置了 **Android APK 自动化构建流水线**。

---

## 🌟 核心功能特色

- 📊 **数据统计与可视化**：
  - 汇总统计收礼/送礼总金额、总笔数及净收支。
  - 提供月度趋势图表与办事缘由比例分布图（基于 Chart.js）。
- 🔍 **多字段模糊搜索与智能转换**：
  - 支持按姓名、电话、地址、办事缘由、备注、年龄等字段进行模糊匹配。
  - 内置中文大写数字转换（`cn2num`），例如搜索“贰佰”或“200”均可自动精准匹配金额。
- 📁 **CSV/Excel 批量导入与导出**：
  - 支持从 CSV 文件批量导入礼金记录，智能兼容列名，自动保留自定义办事缘由（如“儿子结婚”、“开业大吉”等）。
  - 支持一键导出筛选后的记录为标准 CSV 文件。
- 🗑️ **数据管理与批量操作**：
  - 支持多选记录一键批量删除。
  - 提供红色的“清空所有数据”安全操作（带有二次二次二次确认弹窗）。
- 🔒 **完善的用户与安全体系**：
  - 支持注册、登录、记住账密（Browser Autocomplete + Persistent Session）。
  - 支持忘记密码与安全问题找回、修改密码。
  - 支持管理员（Admin）角色，可管理所有用户及全局数据。
- 🛡️ **安全增强与管理员控制**：
  - **注册邀请码限制与管理**：支持自定义邀请码使用次数限制（如1次、5次或无限制），并可实时删除无效或过期的邀请链接。
  - **重置密保问题**：管理员可为任何用户重置安全保护问题与答案。
  - **全站操作审计**：记录用户登录、注册、删改记录、修改密码以及全站浏览与搜索操作，支持按关键词检索、多维排序、自定义每页条数及勾选批量删除日志。
  - **日志自动清理机制**：内置 90 天自动过期日志清理逻辑，防止日志数据无上限膨胀。
- 📱 **跨平台与 Android 打包**：
  - 响应式 UI 布局，完美适配 PC、平板与手机浏览器。
  - 内置 Buildozer 与 GitHub Actions 配置文件，一键云端打包为 Android 原生 `.apk` 安装包（内置 SQLite 初始数据）。

---

## 📂 项目结构

```text
gift_bookkeeping_app/
├── app.py                      # Flask 核心路由与主程序
├── models.py                   # SQLAlchemy 数据库模型 (User, GiftRecord)
├── gift_bookkeeping.db         # SQLite 数据库文件 (包含初始样例数据)
├── main.py                     # Android 平台嵌入式启动入口
├── buildozer.spec              # Buildozer Android 打包配置文件
├── nginx_ssl.conf              # Nginx 自定义 HTTPS 端口反向代理配置文件
├── generate_ssl_certs.py       # 自签名 SSL 证书快速生成脚本
├── .gitignore                  # Git 忽略文件配置
├── .github/
│   └── workflows/
│       └── build_apk.yml       # GitHub Actions 自动化打包 APK 流水线
└── templates/                  # HTML 模板目录
    ├── base.html               # 基础模板 (Bootstrap 5 + FontAwesome)
    ├── index.html              # 首页 (数据列表、搜索、筛选、统计图表)
    ├── login.html              # 登录页面
    ├── register.html           # 注册页面
    ├── forgot_password.html    # 忘记密码 / 重置密码页面
    ├── change_password.html    # 修改密码页面
    └── admin_users.html        # 管理员用户管理页面
     └── admin_logs.html         # 操作审计日志管理页面 (含搜索排序与批量删除)
```

---

## 🚀 本地运行指南

### 1. 环境准备
确保您的电脑已安装 Python 3.8+。

### 2. 安装依赖包
在终端/命令行中运行：
```bash
pip install flask flask-sqlalchemy flask-login cn2num
```

### 3. 启动应用
进入 `gift_bookkeeping_app` 目录并运行 `app.py`：
```bash
cd gift_bookkeeping_app
python app.py
```

### 4. 访问系统
打开浏览器访问：`http://127.0.0.1:5000`
- **默认管理员账号**：`admin`
- **默认管理员密码**：`admin123`

---
## 🔒 SSL / HTTPS 部署说明

项目已提供全套 SSL/TLS 安全部署方案：

### 1. 生成测试 / 内网自签名证书（可选）
若在本地或内网环境没有域名证书，直接运行：
```bash
python generate_ssl_certs.py
```
将在当前目录生成 `server.crt` 与 `server.key` 文件。

### 2. Nginx 反向代理配置（支持自定义端口如 1443）
1. 参考项目根目录下的 `nginx_ssl.conf` 配置文件。
2. 将 `listen 1443 ssl http2;` 中的 `1443` 修改为您所需的任意 HTTPS 端口。
3. 修改 `ssl_certificate` 和 `ssl_certificate_key` 的具体文件路径。
4. 加载 Nginx 配置后重载 Nginx 服务：`nginx -s reload`。

### 3. 应用安全配置与环境变量
如果通过 HTTPS 域名或 Nginx SSL 端口部署，建议设置环境变量：
- `SESSION_COOKIE_SECURE=true` ：开启后将强制 Cookie 仅在 HTTPS 安全连接下传输。

---


## 📱 打包为 Android APK (通过 GitHub Actions)

本仓库已配置好 GitHub Actions 自动化打包流程：

1. 提交并推送代码到您的 GitHub 仓库。
2. 在 GitHub 仓库页面进入 **Actions** 标签页。
3. 选择 **Build and Release Android APK** 工作流，点击 **Run workflow** 运行。
4. 编译完成后，在 **Artifacts** 或 **Releases** 区域即可下载 `.apk` 文件安装到手机使用。

---

## 📄 开源许可

本项目基于 MIT 许可证开源。
