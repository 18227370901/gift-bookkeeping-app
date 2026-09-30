#!/bin/sh

# ============================================================
# run.sh (传统版) — 仅保留配置区 + source bin/ 模块 + 启停操作
# 函数已拆分到 bin/ 目录，本文件仅负责编排调用
# ============================================================

# ===== 配置区域 =====
APP_DIR="/opt/service/gift-bookkeeping-app"
if [ ! -d "$APP_DIR" ]; then
    APP_DIR="$(cd "$(dirname "$0")" && pwd)"
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

# ===== 加载 bin/ 模块（按依赖顺序） =====
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/bin/common.sh"
. "$SCRIPT_DIR/bin/cleanup.sh"
. "$SCRIPT_DIR/bin/ssl_certs.sh"
. "$SCRIPT_DIR/bin/nginx_config.sh"
. "$SCRIPT_DIR/bin/port_conflict.sh"
. "$SCRIPT_DIR/bin/db_setup.sh"
. "$SCRIPT_DIR/bin/db_select.sh"

# ===== 启停操作函数 =====

# V10.10.18: 部署环境预检（Python 版本 / venv 模块 / 常用工具提示）
preflight_check() {
    if ! command -v python3 > /dev/null 2>&1; then
        echo_e "${RED}❌ 环境预检失败：未找到 python3，请先安装 Python 3.8+${NC}"
        echo_e "${YELLOW}   Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip${NC}"
        return 1
    fi
    # 识别“命令存在但无法执行”的占位程序（如 Windows Microsoft Store 的 python3 存根）
    if ! python3 -c 'print("ok")' > /dev/null 2>&1; then
        echo_e "${RED}❌ 环境预检失败：python3 无法正常执行（可能为系统占位程序），请安装真正的 Python 3.8+${NC}"
        return 1
    fi
    _py_ok=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 8) else 0)' 2>/dev/null)
    if [ "$_py_ok" != "1" ]; then
        _py_ver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
        echo_e "${RED}❌ 环境预检失败：需要 Python 3.8+，当前版本为 ${_py_ver}，请升级 Python${NC}"
        return 1
    fi
    _py_ver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
    echo_e "${GREEN}✅ 环境预检通过：python3 $_py_ver${NC}"
    if ! python3 -c 'import venv' > /dev/null 2>&1; then
        echo_e "${YELLOW}⚠️ 预检提示：缺少 python3-venv 模块（Debian/Ubuntu: sudo apt install python3-venv），创建虚拟环境可能失败${NC}"
    fi
    if ! command -v lsof > /dev/null 2>&1; then
        echo_e "${YELLOW}⚠️ 预检提示：缺少 lsof（Debian/Ubuntu: sudo apt install lsof），端口占用检测与停止清理功能受限${NC}"
    fi
    return 0
}

# V10.10.18: pip 安装镜像源自动兜底（清华源 → 阿里云 → 官方源，任一成功即返回）
# 入参 $1: pip 子命令与参数（不含 -i 镜像参数）；$2 可选: requirements 文件路径（含空格路径安全）
pip_install_fb() {
    _pip_args="$1"
    _pip_req="${2:-}"
    _mirror_list="https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.aliyun.com/pypi/simple/ https://pypi.org/simple"
    _mi_total=$(echo $_mirror_list | wc -w)
    _mi_idx=0
    for _mirror in $_mirror_list; do
        _mi_idx=$((_mi_idx + 1))
        echo_e "${YELLOW}   使用 pip 源: ${_mirror}${NC}"
        if [ -n "$_pip_req" ]; then
            if "$VENV_DIR/bin/pip" $_pip_args -r "$_pip_req" -i "$_mirror"; then
                return 0
            fi
        else
            if "$VENV_DIR/bin/pip" $_pip_args -i "$_mirror"; then
                return 0
            fi
        fi
        # 仅在还有下一个镜像源时提示切换，最后一个源失败后直接汇总
        if [ "$_mi_idx" -lt "$_mi_total" ]; then
            echo_e "${YELLOW}   该源安装失败，自动切换下一个镜像源...${NC}"
        fi
    done
    echo_e "${RED}   三个镜像源均安装失败，请检查服务器网络连通性${NC}"
    return 1
}

# V10.10.19: 统一访问信息展示（start 成功提示与 status 巡检共用，输出格式保持一致）
print_access_info() {
    local domain_count
    domain_count=$(echo "$SNI_DOMAIN" | wc -w)
    if [ "$domain_count" -gt 1 ]; then
        echo_e "   访问地址 (共 ${domain_count} 个域名):"
        for domain in $SNI_DOMAIN; do
            if [ "$NGINX_PORT" = "443" ]; then
                echo_e "     - https://$domain/"
            else
                echo_e "     - https://$domain:$NGINX_PORT/"
            fi
        done
    else
        local primary_domain="${SNI_DOMAIN%% *}"
        local access_url="https://$primary_domain/"
        if [ "$NGINX_PORT" != "443" ]; then
            access_url="https://$primary_domain:$NGINX_PORT/"
        fi
        echo_e "   访问地址: $access_url"
    fi
    echo_e "   后端本地直连: http://127.0.0.1:$PORT"
    echo_e "   日志文件: $LOG_FILE"
}

# V10.10.19: 展示当前持久化的数据库部署模式（status 巡检用；不展示 DATABASE_URL 以免泄露数据库密码）
print_db_mode_info() {
    if [ -f "$DB_ENV_FILE" ]; then
        load_db_env
        if [ -n "${DB_MODE:-}" ]; then
            echo_e "   数据库模式: ${DB_MODE} (配置于 .temp/.db.env，DB_RESET=1 ./$(basename "$0") start 可重新选择)"
        else
            echo_e "   数据库模式: 配置文件为空或已损坏 (.temp/.db.env)，建议 DB_RESET=1 ./$(basename "$0") start 重新选择"
        fi
    else
        echo_e "   数据库模式: 未持久化配置（可能由 DB_MODE 环境变量指定或非交互默认 SQLite）"
    fi
}

start_service() {
    if check_status; then
        PID=$(cat "$PID_FILE")
        echo_e "${YELLOW}服务已在运行中 (PID: $PID)${NC}"
        return 1
    fi

    # V10.10.18: 部署环境预检（Python 版本 / venv / 常用工具）
    preflight_check || return 1

    ensure_ssl_certs
    check_port_conflict "$PORT" || return 1
    setup_nginx_config || {
        echo_e "${RED}❌ Nginx SNI 配置失败，服务启动中止，请检查 SNI_DOMAIN 环境变量${NC}"
        return 1
    }
    cleanup_cache

    # V10.10.17: 数据库部署选择（修正：从 clean 分支移到 start_service 内）
    select_db_mode

    # V10.10.20: SQLite 模式下确保运行库位于 data/ 目录（首次部署仅就绪目录，由应用创建纯净空库）
    if [ -z "${DATABASE_URL:-}" ]; then
        ensure_sqlite_runtime_db || return 1
    fi

    echo_e "${GREEN}正在启动服务...${NC}"

    cd "$APP_DIR" || {
        echo_e "${RED}错误: 无法进入目录 $APP_DIR${NC}"
        return 1
    }

    # 自动创建虚拟环境及安装依赖库
    if [ ! -d "$VENV_DIR" ]; then
        echo_e "${YELLOW}检测到虚拟环境不存在，正在自动创建虚拟环境 $VENV_DIR ...${NC}"
        python3 -m venv "$VENV_DIR" || {
            echo_e "${RED}错误: 创建虚拟环境失败，请确认系统已安装 python3-venv${NC}"
            return 1
        }
    fi

    # 检查核心依赖库是否存在，若缺失则强制安装（V10.10.18：镜像源自动兜底 清华源→阿里云→官方源）
    if ! "$VENV_DIR/bin/python3" -c "import flask, flask_sqlalchemy, flask_wtf, flask_login" >/dev/null 2>&1; then
        echo_e "${GREEN}正在检查/补全项目依赖库...${NC}"
        pip_install_fb "install --upgrade pip" || true
        if [ -f "$APP_DIR/requirements.txt" ]; then
            pip_install_fb "install" "$APP_DIR/requirements.txt" || {
                echo_e "${RED}错误: 依赖库安装失败（已依次尝试清华源/阿里云/官方源），请检查网络或 requirements.txt${NC}"
                return 1
            }
        else
            pip_install_fb "install flask flask-sqlalchemy flask-wtf flask-login" || {
                echo_e "${RED}错误: 依赖库安装失败（已依次尝试清华源/阿里云/官方源）${NC}"
                return 1
            }
        fi
        echo_e "${GREEN}✅ 依赖库检查/安装完成!${NC}"
    fi

    # 使用进程组方式启动，便于后续统一管理
    setsid bash -c "
        export ADMIN_USER='$ADMIN_USER'
        export ADMIN_PASS='$ADMIN_PASS'
        export PORT='$PORT'
        export DATABASE_URL='$DATABASE_URL'
        . $VENV_DIR/bin/activate
        python3 $APP_SCRIPT
    " >> "$LOG_FILE" 2>&1 &

    # 保存 PID
    local PID=$!
    echo "$PID" > "$PID_FILE"

    sleep 2
    if check_status; then
        echo_e "${GREEN}✅ 服务启动成功!${NC}"
        echo_e "   PID: $(cat $PID_FILE)"
        # V10.10.19: 访问信息展示统一由 print_access_info 输出（与 status 命令一致）
        print_access_info
    else
        echo_e "${RED}❌ 服务启动失败，请查看日志: $LOG_FILE${NC}"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_service() {
    # 第一步：先通过 PID 文件处理
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        echo_e "${YELLOW}正在停止服务 (PID: $PID)...${NC}"

        PGID=$(ps -o pgid= -p "$PID" 2>/dev/null | tr -d ' ')
        if [ -n "$PGID" ]; then
            echo_e "${YELLOW}终止进程组 PGID: $PGID${NC}"
            kill -TERM -"$PGID" 2>/dev/null
        else
            pkill -P "$PID" 2>/dev/null
            kill "$PID" 2>/dev/null
        fi

        local wait_time=0
        while ps -p "$PID" > /dev/null 2>&1; do
            if [ $wait_time -ge 10 ]; then
                break
            fi
            sleep 1
            wait_time=$((wait_time + 1))
        done

        if ps -p "$PID" > /dev/null 2>&1; then
            echo_e "${YELLOW}进程未响应，强制终止...${NC}"
            if [ -n "$PGID" ]; then
                kill -9 -"$PGID" 2>/dev/null
            else
                kill -9 "$PID" 2>/dev/null
                pkill -9 -P "$PID" 2>/dev/null
            fi
            sleep 1
        fi

        rm -f "$PID_FILE"
    else
        echo_e "${YELLOW}未找到 PID 文件，尝试通过端口清理...${NC}"
    fi

    # 第二步：双重保险 —— 根据端口清理任何残留进程
    echo_e "${YELLOW}检查端口 $PORT 是否被占用...${NC}"
    local fuser_pid=$(lsof -ti :$PORT 2>/dev/null)
    if [ -n "$fuser_pid" ]; then
        echo_e "${YELLOW}发现端口 $PORT 被进程 $fuser_pid 占用，强制终止...${NC}"
        kill -9 "$fuser_pid" 2>/dev/null
        sleep 1
    fi

    # 最终确认
    if lsof -ti :$PORT > /dev/null 2>&1; then
        echo_e "${RED}❌ 端口 $PORT 仍被占用，请手动检查${NC}"
        echo_e "   执行: sudo lsof -i :$PORT"
        return 1
    else
        echo_e "${GREEN}✅ 服务已完全停止${NC}"
        # V10.10.17: 独立 PG 模式时同步停止 PG 容器
        if [ -f "$DB_ENV_FILE" ]; then
            load_db_env
            if [ "$DB_MODE" = "independent" ]; then
                _pg_container="${PROJECT_NAME}-pg"
                if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${_pg_container}$"; then
                    echo_e "${YELLOW}正在停止独立 PG 容器 (${_pg_container})...${NC}"
                    docker stop "$_pg_container" > /dev/null 2>&1 || true
                    echo_e "${GREEN}✅ 独立 PG 容器已停止${NC}"
                fi
            fi
        fi
        return 0
    fi
}

status_service() {
    if check_status; then
        PID=$(cat "$PID_FILE")
        echo_e "${GREEN}✅ 服务正在运行 (基于 PID 文件)${NC}"
        echo_e "   PID: $PID"
        echo_e "   端口: $PORT"
        # V10.10.19: 与启动成功提示一致，附带访问地址/本地直连/日志/数据库模式，便于日常巡检
        print_access_info
        print_db_mode_info
        ps -p "$PID" -o pid,ppid,cmd,etime
        return 0
    fi

    local port_pid=$(lsof -ti :$PORT 2>/dev/null)
    if [ -n "$port_pid" ]; then
        echo_e "${YELLOW}⚠️ 端口 $PORT 被进程 $port_pid 占用，但 PID 文件无效${NC}"
        echo_e "   请执行 './$(basename "$0") stop' 清理残留进程"
        return 1
    else
        echo_e "${RED}❌ 服务未运行${NC}"
        return 1
    fi
}

restart_service() {
    echo_e "${YELLOW}正在重启服务...${NC}"
    stop_service
    sleep 2
    start_service
}

# ===== 主逻辑 =====

case "$1" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    status)
        status_service
        ;;
    restart)
        restart_service
        ;;
    clean)
        cleanup_cache
        ;;
    *)
        echo "用法: $0 {start|stop|status|restart|clean}"
        echo ""
        echo "  start   - 启动服务 (自动生成证书、配置 Nginx 与清理缓存)"
        echo "  stop    - 停止服务"
        echo "  status  - 查看服务状态 (含访问地址、本地直连、日志与数据库模式)"
        echo "  restart - 重启服务 (自动清理垃圾数据并生效新代码)"
        echo "  clean   - 仅手动清理垃圾缓存与压缩 .git"
        echo ""
        echo "多项目共用 443 端口 SNI 分流的环境变量（均有默认值，可按项目覆盖）:"
        echo "  PROJECT_NAME        项目标识，决定 Nginx 配置文件名与 upstream 名 (默认: gift_app)"
        echo "  SNI_DOMAIN          SNI 域名，写入 server_name 与证书 CN/SAN (默认: localhost)"
        echo "                      支持空格分隔多域名，如 SNI_DOMAIN=\"a.com b.com\"，第一个为证书 CN，全部写入 SAN 与 server_name"
        echo "  NGINX_PORT          Nginx 对外监听端口 (默认: 443)"
        echo "  SSL_CERT/SSL_KEY    证书与私钥路径 (默认: \$APP_DIR/ssl/server.crt|key)"
        echo "  SNI_DEFAULT_SERVER  是否作为兜底 default_server，1=是 0=否 (默认: 1)"
        echo "  SSL_FORCE_UPDATE=1          SSL 证书已存在时强制覆盖更新，不询问 (默认: 询问/非交互时保留)"
        echo "  NGINX_CONF_FORCE_UPDATE=1   Nginx 配置已存在时强制覆盖渲染，不询问 (默认: 询问/非交互时保留)"
        echo ""
        echo "数据库部署选择 (首次 start 交互式三选一，选择结果持久化于 .temp/.db.env，后续 start/restart 自动读取):"
        echo "  DB_MODE             直接指定数据库模式跳过交互: sqlite | shared | independent (shared 需搭配 DB_PG_CONTAINER)"
        echo "  DB_PG_CONTAINER     共享 PG 模式复用的已运行容器名 (与 DB_MODE=shared 搭配)"
        echo "  DB_RESET=1          清除已保存的数据库配置并重新进入交互选择 (无需手动删除 .temp/.db.env)"
        echo "  PG_IMAGE            独立 PG 模式自定义镜像版本"
        echo "                      优先级: PG_IMAGE 指定 > 本地已有 PG 镜像 > 自动下载默认 postgres:16-alpine"
        echo "                      仅独立 PG 模式生效；共享 PG 模式复用已运行容器，不涉及镜像选择"
        echo "  示例: DB_RESET=1 ./$(basename "$0") start                                          # 重新交互选择数据库模式"
        echo "  示例: DB_MODE=independent PG_IMAGE=postgres:16-alpine ./$(basename "$0") start      # 直通独立 PG，指定 16-alpine 镜像"
        echo "  示例: DB_MODE=independent PG_IMAGE=pgvector/pgvector:pg18 ./$(basename "$0") start   # 指定 PG18 镜像(挂载路径自动匹配 /var/lib/postgresql)"
        echo "  示例: DB_RESET=1 DB_MODE=independent PG_IMAGE=postgres:15 ./$(basename "$0") start   # 清除旧配置重选 + 直通独立 PG + 指定 15 版镜像"
        echo "  示例: DB_MODE=sqlite ./$(basename "$0") start   # 直通指定，交互终端下会保存为新配置"
        echo "  示例: PROJECT_NAME=mengyao SNI_DOMAIN=mengyao.example.com ./$(basename "$0") start"
        echo "  多域名示例: SNI_DOMAIN=\"gift.example.com gift2.example.com\" ./$(basename "$0") start"
        echo "  示例: SSL_FORCE_UPDATE=1 NGINX_CONF_FORCE_UPDATE=1 ./$(basename "$0") restart  # cron/自动化场景强制更新"
        exit 1
        ;;
esac

exit 0
