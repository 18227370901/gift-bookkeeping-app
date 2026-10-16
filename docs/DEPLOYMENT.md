# 人情礼金记账系统 部署与运维手册 (Deployment & Operation)

> 本文档详细介绍了系统在本地及各类 Linux 生产服务器上的部署、运维、反向代理、SSL 证书及 Git 更新处理方案。  
> 快速启动请参考主页 [README.md](../README.md)。

---

## 目录
- [一、本地环境快速启动](#一本地环境快速启动)
- [二、使用服务管理脚本 run.sh (推荐生产环境)](#二使用服务管理脚本-runsh-推荐生产环境)
- [三、端口、账密与服务器专属持久配置](#三端口账密与服务器专属持久配置)
- [四、多项目共用 443 端口 SNI 分流配置](#四多项目共用-443-端口-sni-分流配置)
- [五、SSL / HTTPS 部署与证书生成](#五ssl--https-部署与证书生成)
- [六、Nginx 反向代理配置与热重载](#六nginx-反向代理配置与热重载)
- [七、Linux 服务器代码更新与冲突处理最佳实践](#七linux-服务器代码更新与冲突处理最佳实践)
- [八、项目多形态交付矩阵 (Ecosystem)](#八项目多形态交付矩阵-ecosystem)

---

## 一、本地环境快速启动

### 适用场景
适用于开发机本地联调（Windows、macOS 或 Linux 原生 Python 环境）。

### 步骤
```bash
# 1. 克隆代码并进入项目目录
git clone https://github.com/18227370901/gift-bookkeeping-app.git
cd gift_bookkeeping-app

# 2. 安装项目依赖（推荐在 Python 3.10+ 虚拟环境下）
pip install -r requirements.txt

# 3. 直接启动 Flask 应用（默认监听 11443 端口）
python app.py
```
> 访问地址：`http://127.0.0.1:11443`  
> 默认初始管理员：`admin` / `admin123`

---

## 二、使用服务管理脚本 run.sh (推荐生产环境)

根目录下的 `run.sh` 提供了高可用、全自动的后台服务运维管理能力。执行 `start` 指令时，脚本会**自动检测并创建独立虚拟环境（`venv`）**，并**自动增量补齐所需依赖库**。

```bash
# 1. 赋予执行权限
chmod +x run.sh

# 2. 启动服务（自动创建 venv + 自动 install 依赖 + 自动生成 SSL 证书 + 后台启动）
./run.sh start

# 3. 查看服务运行状态（含访问地址、本地直连、日志与数据库模式）
./run.sh status

# 4. 重启服务
./run.sh restart

# 5. 停止服务
./run.sh stop
```

---

## 三、端口、账密与服务器专属持久配置

### 1. 临时环境变量覆盖
可在执行命令时通过命令行临时覆盖端口与凭证：
```bash
PORT=12443 ADMIN_USER=custom_admin ADMIN_PASS=StrongPass2026 ./run.sh start
```

### 2. 服务器专属持久配置（推荐最佳实践）
每台服务器的差异化配置（账密/SNI 域名/监听端口/PG 连接参数等）建议写入 `bin/config.local.sh` 或 `config/config.local.sh`（已被 `.gitignore` 整体忽略，`git pull` 永不冲突）。

示例 `bin/config.local.sh`：
```bash
ADMIN_USER="${ADMIN_USER:-myadmin}"
ADMIN_PASS="${ADMIN_PASS:-MyStrongPass2026}"
SNI_DOMAIN="${SNI_DOMAIN:-gift.example.com}"
NGINX_PORT="${NGINX_PORT:-8443}"
```
配置优先级：**命令行临时环境变量 > config.local.sh > bin/config.sh 内置默认值**。

---

## 四、多项目共用 443 端口 SNI 分流配置

同一台服务器上的多个独立 Web 项目可共用 443 端口，Nginx 依靠 SNI（Server Name Indication）域名特征精准分流各项目流量：

```bash
PROJECT_NAME=gift_app SNI_DOMAIN=gift.example.com SNI_DEFAULT_SERVER=1 ./run.sh start
```

- **`PROJECT_NAME`**：项目唯一标识，决定 Nginx 配置文件名与 Upstream 名（默认 `gift_app`）；
- **`SNI_DOMAIN`**：项目绑定的域名（默认 `localhost`）；支持以空格分隔传入多个域名（如 `SNI_DOMAIN="a.com b.com"`），第一个作为证书 CN，全部自动写入证书 SAN 与 Nginx `server_name`；
- **`SNI_DEFAULT_SERVER`**：是否作为 443 端口默认兑底（单台服务器多项目中仅限一个设为 `1`）；
- **`SSL_CERT` / `SSL_KEY`**：若有权威机构颁发的正式证书，可直接指定证书路径；未指定时自动使用自签名证书。

---

## 五、SSL / HTTPS 部署与证书生成

### 1. 自动生成自签名证书
`run.sh start` 会根据 `$SNI_DOMAIN` 全自动生成自签名证书。

### 2. 手工调用证书生成工具
亦可手动使用内置工具定制生成证书：
```bash
# 生成绑定指定域名的自签名证书
python tools/generate_ssl_certs.py --domain gift.example.com

# 指定有效天数（如 2 年）
python tools/generate_ssl_certs.py --domain gift.example.com --days 730
```
证书文件默认输出至 `ssl/server.crt` 与 `ssl/server.key`。

---

## 六、Nginx 反向代理配置与热重载

1. 位于 `config/nginx_ssl.conf` 的配置文件为**占位符模板**，包含 `__UPSTREAM_NAME__`、`__BACKEND_PORT__`、`__NGINX_PORT__`、`__SNI_DOMAIN__` 等关键占位符。
2. 每次执行 `./run.sh start` 或 `./run.sh restart` 时，脚本会自动将模板渲染并同步到系统的 Nginx 配置目录（如 `/etc/nginx/conf.d/gift_app.conf`）。
3. 渲染完成后脚本会自动尝试执行 `nginx -t` 语法检测及热重载（`nginx -s reload`）。亦可手动检查：
   ```bash
   nginx -t
   nginx -s reload
   ```

---

## 七、Linux 服务器代码更新与冲突处理最佳实践

### 1. 标准平滑更新流程（推荐）
若遵循上述 `bin/config.local.sh` 分离策略，服务器更新时本地无任何被 Git 追踪的文件改动，直接拉取即可：
```bash
cd /opt/service/gift-bookkeeping-app
git pull origin main
./run.sh restart
```

### 2. 存量服务器冲突排查与处理
若早期版本中曾直接修改过 `run.sh` 等跟踪文件导致 `git pull` 冲突，建议采取以下一次性迁移步骤：
```bash
# 1. 将自定义变量迁移至本地私有配置文件
cat > bin/config.local.sh <<'EOF'
ADMIN_USER="${ADMIN_USER:-myadmin}"
ADMIN_PASS="${ADMIN_PASS:-MyStrongPass2026}"
SNI_DOMAIN="${SNI_DOMAIN:-gift.example.com}"
EOF

# 2. 丢弃或暂存跟踪文件的修改
git checkout -- run.sh
# 或
git stash

# 3. 拉取最新代码并重启
git pull origin main
./run.sh restart
```

---

## 八、项目多形态交付矩阵 (Ecosystem)

本套系统提供三种产品交付形态，源码均已同步发布至 GitHub：

| 形态 | GitHub 仓库地址 | 适用场景 |
|:---|:---|:---|
| 🖥️ **Web 原生部署版** | [gift-bookkeeping-app](https://github.com/18227370901/gift-bookkeeping-app.git) | 适合本地 Python 环境、虚拟主机、轻量 VPS 单机运行 |
| 🐳 **Docker Compose 版** | [gift-bookkeeping-app-docker](https://github.com/18227370901/gift-bookkeeping-app-docker.git) | 适合企业生产服务器、一键容器编排、Nginx 反代与 SSL 自动化管理 |
| 📱 **Android 原生 APK 版** | [gift_bookkeeping_apk](https://github.com/18227370901/gift_bookkeeping_apk.git) | 适合安卓手机与平板脱机随身离线使用 |
