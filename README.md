# 人情礼金记账系统 (Gift Bookkeeping App)

> **最新更新说明**：
> - 👑 **管理员用户管理增强**：管理员可实时启用/禁用/删除普通用户，被禁用账号无法登录并显示“联系管理员处理”提示，已登录用户在被禁用或删除后将被即时拦截强制下线。
> - 🛠️ **自动化运维与依赖管理**：启动脚本 `run.sh` 自动判断并创建 Python 虚拟环境（`venv`）及安装 `requirements.txt` 依赖库，免除手动执行命令；支持通过环境变量自定义 admin 账号与密码。
> - 🧹 **冗余清理**：项目已彻底清理打包 exe/apk 等不必要文件及历史构件，精简项目体积。

# 人情礼金记账系统 (Gift Bookkeeping App)

一个基于 **Python Flask + SQLite/PostgreSQL + Bootstrap 5** 开发的简洁、高效的人情往来与礼金记账管理系统。支持多用户管理、礼金收支记录、多维度统计图表、Excel/CSV 批量导入导出、高级多字段模糊搜索。

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
  - 提供红色的“清空所有数据”安全操作（带有二次确认弹窗）。
- 🔒 **完善的用户与安全体系**：
  - 支持注册、登录、记住账密（Browser Autocomplete + Persistent Session）。
  - 支持忘记密码与安全问题找回、修改密码。
  - 👑 **用户状态管理与权限控制**：管理员可管理所有普通用户的启用/禁用状态以及删除用户；禁用账号无法登录并友好提示“联系管理员处理”，已被禁用的在线用户将在操作或页面刷新时即时下线。
- 🛡️ **安全增强与管理员控制**：
  - **注册邀请码限制与管理**：支持自定义邀请码使用次数限制（如1次、5次或无限制），并可实时删除无效或过期的邀请链接。
  - **重置密保问题**：管理员可为任何用户重置安全保护问题与答案。
  - **全站操作审计**：记录用户登录、注册、删改记录、修改密码以及全站浏览与搜索操作，支持按关键词检索、多维排序、自定义每页条数及勾选批量删除日志。
  - **日志自动清理机制**：内置 90 天自动过期日志清理逻辑，防止日志数据无上限膨胀。

---

## 📂 项目结构

```text
gift_bookkeeping_app/
├── app.py                      # Flask 核心路由与主程序
├── models.py                   # SQLAlchemy 数据库模型 (User, GiftRecord)
├── gift_bookkeeping.db         # SQLite 数据库文件
├── run.sh                      # Linux 后台服务管理与虚拟环境自动创建/启动脚本
├── nginx_ssl.conf              # Nginx 自定义 HTTPS 端口反向代理配置文件
├── generate_ssl_certs.py       # 自签名 SSL 证书快速生成脚本
├── .gitignore                  # Git 忽略文件配置
└── templates/                  # HTML 模板目录
    ├── base.html               # 基础模板 (Bootstrap 5 + FontAwesome)
    ├── index.html              # 首页 (数据列表、搜索、筛选、统计图表)
    ├── login.html              # 登录页面
    ├── register.html           # 注册页面
    ├── forgot_password.html    # 忘记密码 / 重置密码页面
    ├── change_password.html    # 修改密码页面
    ├── admin_users.html        # 管理员用户管理页面 (含账号禁用/启用/重置/删除)
    └── admin_logs.html         # 操作审计日志管理页面 (含搜索排序与批量删除)
```

---

## 🚀 本地与服务器运行指南

### 使用运行脚本 `run.sh`（推荐 Linux / 云服务器环境）

根目录下提供了服务管理脚本 `run.sh`。运行 `start` 指令时，脚本会**自动判断并创建 Python 虚拟环境（`venv`）**，并**自动安装 `requirements.txt` 中所需依赖**，无需手动执行繁琐命令。

```bash
# 1. 赋予可执行权限
chmod +x run.sh

# 2. 启动服务（自动创建 venv + 自动 install 依赖 + 后台启动 Flask）
./run.sh start

# 3. 其他常用服务管理指令
./run.sh status   # 查看服务运行状态与 PID
./run.sh stop     # 停止服务
./run.sh restart  # 重启服务
```

> 💡 **自定义管理员账号密码与端口**：
> 可在 `run.sh` 脚本头的环境变量配置区域修改 `ADMIN_USER` 和 `ADMIN_PASS`（支持特殊字符），程序默认监听端口为 `11443`（例如配合 Nginx 宿主机 `15001` 端口代理映射至后端 `11443` 端口）。启动时系统将自动初始化或更新该管理员账号。

---

## 🔒 SSL / HTTPS 部署说明

项目已提供全套 SSL/TLS 安全部署方案：

### 1. 生成测试 / 内网自签名证书（可选）
若在本地或内网环境没有域名证书，直接运行：
```bash
python generate_ssl_certs.py
```
将在当前目录生成 `server.crt` 与 `server.key` 文件。

### 2. Nginx 反向代理配置（15001 端口映射至 11443 端口）
1. 参考项目根目录下的 `nginx_ssl.conf` 配置文件（用于监听 HTTPS 15001 端口并将流量转发至 127.0.0.1:11443）。
2. 将 `nginx_ssl.conf` 拷贝至服务器 Nginx 配置目录（例如 `/etc/nginx/conf.d/gift_app_native.conf`）。
> 💡 **单端口多配置冲突说明**：如果服务器上同时存在 Docker 版本，由于两个配置文件的 Nginx `server` 块均写了 `listen 15001 ssl;`，在 `/etc/nginx/conf.d/` 下同时存在两个 `.conf` 文件时，Nginx 默认会优先命中字母排序在前的 Upstream 配置。
> 当您切换使用**非 Docker 版本**时，请将 Docker 版本的配置文件重命名禁用：
> `mv /etc/nginx/conf.d/gift_app_docker.conf /etc/nginx/conf.d/gift_app_docker.conf.disabled 2>/dev/null || true`
3. 确保 SSL 证书存放于 `/opt/service/gift-bookkeeping-app/ssl/server.crt` 和 `server.key`（或修改为您的实际证书路径）。
4. 检查 Nginx 配置语法并重载生效：
   ```bash
   nginx -t
   nginx -s reload
   ```

---

## 🚀 首次部署指导操作说明

### 1. 克隆代码库到 Linux 服务器
```bash
git clone https://github.com/18227370901/gift-bookkeeping-app.git /opt/service/gift-bookkeeping-app
cd /opt/service/gift-bookkeeping-app
```

### 2. 启动服务应用（推荐通过脚本管理）
```bash
chmod +x run.sh
./run.sh start
```
> 💡 **自动依赖管理机制**：`run.sh` 在启动时会自动校验虚拟环境及依赖。若虚拟环境或核心依赖库（`flask`, `flask-sqlalchemy` 等）缺失，将自动使用清华镜像源全自动安装/补全依赖。

### 3. 配置 Nginx SSL 反向代理（支持 HTTPS 15001 端口暴露）
```bash
# 生成自签名 SSL 证书（用于内网测试环境，若有正式证书直接放入 ssl/ 目录）
python3 generate_ssl_certs.py

# 引入项目自带的 Nginx 配置文件
cp nginx_ssl.conf /etc/nginx/conf.d/gift_app.conf
nginx -t && nginx -s reload
```

---

## 🔄 Linux 服务器更新最新代码指南

针对已经在 Linux 服务器上执行过 `git clone` 的项目，拉取并应用 GitHub 云端最新代码的完整步骤如下：

### 标准更新步骤（本地无未提交修改）
```bash
# 1. 进入服务器上的项目根目录
cd /opt/service/gift-bookkeeping-app  # 请替换为您在服务器上的实际项目路径

# 2. 从 GitHub 云端拉取最新代码
git pull origin main

# 3. 执行重启服务命令
./run.sh restart
```
> 💡 **自动更新防护**：`./run.sh restart` 执行时会自动对比并补全新增的核心依赖包以及自动执行数据库结构无损迁移。

---

### ⚠️ 当本地有修改，拉取最新代码的冲突处理方案

如果在服务器或本地修改了配置文件（如 `nginx_ssl.conf`、`run.sh` 或数据库文件），直接执行 `git pull origin main` 可能会提示冲突。请根据业务需求选择以下处理方案之一：

#### 方案一：保留本地修改并合并（推荐）✅
暂存本地修改，拉取远程更新后再恢复合并：
```bash
# 1. 暂存本地修改
git stash push -m "保存本地配置变更"

# 2. 拉取最新代码
git pull origin main

# 3. 恢复本地修改（如遇到冲突需手动修改）
git stash pop

# 4. 手动解决冲突后提交（如需要）
git add .
git commit -m "fix: 合并远程更新并保留本地配置"

# 5. 重启服务应用最新代码
./run.sh restart
```

#### 方案二：放弃本地修改，使用远程版本
丢弃特定的本地文件改动，直接同步远程代码：
```bash
# 1. 查看具体改动（确认是否要放弃）
git diff gift_bookkeeping.db nginx_ssl.conf run.sh

# 2. 恢复这些文件到远程版本
git checkout -- gift_bookkeeping.db nginx_ssl.conf run.sh

# 3. 拉取最新代码
git pull origin main

# 4. 重启服务
./run.sh restart
```

#### 方案三：仅保留重要文件的本地修改
备份重要配置文件后重置，拉取最新代码再手动比对合并：
```bash
# 1. 备份重要配置文件
cp nginx_ssl.conf nginx_ssl.conf.backup
cp run.sh run.sh.backup

# 2. 放弃这些文件的修改
git checkout -- gift_bookkeeping.db nginx_ssl.conf run.sh

# 3. 拉取最新代码
git pull origin main

# 4. 对比备份文件和最新代码，手动合并配置
diff nginx_ssl.conf.backup nginx_ssl.conf
diff run.sh.backup run.sh

# 5. 合并完成后清理备份文件
rm nginx_ssl.conf.backup run.sh.backup

# 6. 重启服务
./run.sh restart
```

#### 方案四：强制覆盖（谨慎使用）⚠️
直接用远程最新代码强制覆盖本地所有改动（**未提交的本地修改将不可逆丢失**）：
```bash
# 1. 重置到远程最新状态
git fetch origin main
git reset --hard origin/main

# 2. 重启服务
./run.sh restart
```



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
