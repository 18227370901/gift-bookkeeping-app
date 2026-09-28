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

start_service() {
    if check_status; then
        PID=$(cat "$PID_FILE")
        echo_e "${YELLOW}服务已在运行中 (PID: $PID)${NC}"
        return 1
    fi

    ensure_ssl_certs
    check_port_conflict "$PORT" || return 1
    setup_nginx_config || {
        echo_e "${RED}❌ Nginx SNI 配置失败，服务启动中止，请检查 SNI_DOMAIN 环境变量${NC}"
        return 1
    }
    cleanup_cache

    # V10.10.17: 数据库部署选择（修正：从 clean 分支移到 start_service 内）
    select_db_mode

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

    # 检查核心依赖库是否存在，若缺失则强制安装
    if ! "$VENV_DIR/bin/python3" -c "import flask, flask_sqlalchemy, flask_wtf, flask_login" >/dev/null 2>&1; then
        echo_e "${GREEN}正在检查/补全项目依赖库...${NC}"
        "$VENV_DIR/bin/pip" install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple || true
        if [ -f "$APP_DIR/requirements.txt" ]; then
            "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple || {
                echo_e "${RED}错误: 依赖库安装失败，请检查网络或 requirements.txt${NC}"
                return 1
            }
        else
            "$VENV_DIR/bin/pip" install flask flask-sqlalchemy flask-wtf flask-login -i https://pypi.tuna.tsinghua.edu.cn/simple || {
                echo_e "${RED}错误: 依赖库安装失败${NC}"
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
        local domain_count
        domain_count=$(echo "$SNI_DOMAIN" | wc -w)
        echo_e "${GREEN}✅ 服务启动成功!${NC}"
        echo_e "   PID: $(cat $PID_FILE)"
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
        echo_e "   日志文件: $LOG_FILE"
        ps -p "$PID" -o pid,ppid,cmd,etime
        return 0
    fi

    local port_pid=$(lsof -ti :$PORT 2>/dev/null)
    if [ -n "$port_pid" ]; then
        echo_e "${YELLOW}⚠️ 端口 $PORT 被进程 $port_pid 占用，但 PID 文件无效${NC}"
        echo_e "   请执行 './service.sh stop' 清理残留进程"
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
        echo "  status  - 查看服务状态"
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
        echo "  示例: PROJECT_NAME=mengyao SNI_DOMAIN=mengyao.example.com ./$0 start"
        echo "  多域名示例: SNI_DOMAIN=\"gift.example.com gift2.example.com\" ./$0 start"
        echo "  示例: SSL_FORCE_UPDATE=1 NGINX_CONF_FORCE_UPDATE=1 ./$0 restart  # cron/自动化场景强制更新"
        exit 1
        ;;
esac

exit 0
