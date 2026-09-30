#!/bin/sh
# config.sh (传统版) — 全部可自定义变量的唯一权威定义处（V10.10.21 自 run.sh 拆出）
# 依赖：run.sh 先定义 SCRIPT_DIR 再 source 本文件；本文件必须最先加载（其余模块全部依赖这里的变量）
#
# ── 服务器专属持久配置（推荐）──────────────────────────────
# 每台服务器的差异化配置（账密/SNI 域名/端口等）建议写入 bin/config.local.sh
# （已被 .gitignore 忽略，git pull 永不冲突），本文件开头自动加载；
# 三层优先级：命令行环境变量 > bin/config.local.sh > 本文件内置默认值
# local 文件建议沿用 ${变量:-值} 写法使命令行环境变量仍可临时覆盖，示例：
#   ADMIN_USER="${ADMIN_USER:-myadmin}"
#   ADMIN_PASS="${ADMIN_PASS:-MyStrongPass2026}"
#   SNI_DOMAIN="${SNI_DOMAIN:-gift.example.com}"
#   NGINX_PORT="${NGINX_PORT:-8443}"

# ===== 服务器专属持久配置（最先加载，使下方 ${VAR:-默认} 守卫保留其值） =====
if [ -f "$SCRIPT_DIR/bin/config.local.sh" ]; then
    . "$SCRIPT_DIR/bin/config.local.sh"
fi

# ===== 部署目录与运行文件（按部署位置自动判定，无需手工配置） =====
# 服务器正式部署路径；git clone 到其他位置时自动回退为脚本所在目录
APP_DIR="/opt/service/gift-bookkeeping-app"
if [ ! -d "$APP_DIR" ]; then
    APP_DIR="$SCRIPT_DIR"
fi
VENV_DIR="$APP_DIR/venv"
APP_SCRIPT="app.py"
PID_FILE="$APP_DIR/app.pid"
LOG_FILE="$APP_DIR/app.log"

# ===== SNI 多项目共用端口配置 =====
PROJECT_NAME="${PROJECT_NAME:-gift_app}"
SNI_DOMAIN="${SNI_DOMAIN:-localhost}"
SSL_CERT="${SSL_CERT:-$APP_DIR/ssl/server.crt}"
SSL_KEY="${SSL_KEY:-$APP_DIR/ssl/server.key}"
SNI_DEFAULT_SERVER="${SNI_DEFAULT_SERVER:-1}"
NGINX_CONF_DIR="${NGINX_CONF_DIR:-/opt/service/nginx/conf.d}"

# ===== 文件覆盖策略 =====
SSL_FORCE_UPDATE="${SSL_FORCE_UPDATE:-}"
NGINX_CONF_FORCE_UPDATE="${NGINX_CONF_FORCE_UPDATE:-}"

# ===== 环境变量定义（全局有效） =====
export PORT="${PORT:-11443}"
export NGINX_PORT="${NGINX_PORT:-443}"
export ADMIN_USER="${ADMIN_USER:-admin}"
export ADMIN_PASS="${ADMIN_PASS:-admin123}"

# ===== PostgreSQL 默认值（bin/db_setup.sh 与交互菜单引用；运行时仍可被 PG_USER/PG_PASSWORD/PG_DB/PG_PORT/PG_IMAGE 环境变量覆盖） =====
PG_USER_DEFAULT="${PG_USER_DEFAULT:-gift_user}"            # 默认数据库账号
PG_DB_DEFAULT="${PG_DB_DEFAULT:-gift_bookkeeping}"         # 默认数据库名
PG_PORT_DEFAULT="${PG_PORT_DEFAULT:-5432}"                 # 共享 PG 默认宿主机连接端口（独立模式默认从 15432 起扫描）
PG_IMAGE_DEFAULT="${PG_IMAGE_DEFAULT:-postgres:16-alpine}" # 独立 PG 默认镜像（本地无任何 PG 镜像时自动下载）
