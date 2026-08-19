#!/bin/bash

# ===== 确保使用 Bash 解释器运行（防止 sh run.sh 导致的 Bashisms 语法报错） =====
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi

# ===== 配置区域 =====
APP_DIR="/opt/service/gift-bookkeeping-app"
if [ ! -d "$APP_DIR" ]; then
    APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
fi
VENV_DIR="$APP_DIR/venv"
APP_SCRIPT="app.py"
PID_FILE="$APP_DIR/app.pid"
LOG_FILE="$APP_DIR/app.log"

# Nginx 配置文件目录变量（用户可自定义覆盖，如 export NGINX_CONF_DIR=/etc/nginx/conf.d）
NGINX_CONF_DIR="${NGINX_CONF_DIR:-/etc/nginx/conf.d}"

# ===== 环境变量定义（全局有效） =====
export PORT="${PORT:-11443}"
export NGINX_PORT="${NGINX_PORT:-15001}"
export ADMIN_USER="${ADMIN_USER:-admin}"
export ADMIN_PASS="${ADMIN_PASS:-xK9pQ#vL2mNw2}"  # 密码含特殊字符，用单引号括起

# ===== 颜色输出 =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ===== 函数定义 =====

# 检查服务是否正在运行（基于 PID 文件）
check_status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0  # 正在运行
        else
            rm -f "$PID_FILE"  # PID 文件残留，清理
            return 1  # 未运行
        fi
    else
        return 1  # 未运行
    fi
}

# 自动生成/刷新 SSL 证书
ensure_ssl_certs() {
    echo -e "${GREEN}正在生成/更新 SSL 自签名证书...${NC}"
    mkdir -p "$APP_DIR/ssl"
    if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/python3" ]; then
        "$VENV_DIR/bin/python3" "$APP_DIR/generate_ssl_certs.py"
    elif command -v python3 > /dev/null 2>&1; then
        python3 "$APP_DIR/generate_ssl_certs.py"
    else
        echo -e "${RED}警告: 未找到 python3，无法自动生成证书，请手动生成或准备 ssl/server.crt 和 ssl/server.key${NC}"
    fi
}
setup_nginx_config() {
    if [ -d "$NGINX_CONF_DIR" ]; then
        echo -e "${GREEN}正在处理 Nginx 配置文件 ($NGINX_CONF_DIR)...${NC}"
        if [ -f "$NGINX_CONF_DIR/gift_app_docker.conf" ]; then
            mv "$NGINX_CONF_DIR/gift_app_docker.conf" "$NGINX_CONF_DIR/gift_app_docker.conf.disabled" 2>/dev/null || true
            echo -e "${YELLOW}已禁用冲突的 Docker 版本 Nginx 配置: gift_app_docker.conf${NC}"
        fi
        if [ -f "$APP_DIR/nginx_ssl.conf" ]; then
            # 动态替换后端 PORT 和 NGINX_PORT
            sed -e "s/server 127.0.0.1:[0-9]*/server 127.0.0.1:$PORT/g" \
                -e "s/listen [0-9]* ssl;/listen $NGINX_PORT ssl;/g" \
                "$APP_DIR/nginx_ssl.conf" > "$NGINX_CONF_DIR/gift_app_native.conf" 2>/dev/null && \
            echo -e "${GREEN}✅ 已动态更新并同步 Nginx 配置到 $NGINX_CONF_DIR/gift_app_native.conf (后端端口: $PORT, Nginx监听端口: $NGINX_PORT)${NC}" || true
        fi
        if command -v nginx > /dev/null 2>&1; then
            if nginx -t >/dev/null 2>&1; then
                (nginx -s reload >/dev/null 2>&1 || systemctl reload nginx >/dev/null 2>&1) && \
                echo -e "${GREEN}✅ Nginx 配置热重载成功!${NC}" || echo -e "${YELLOW}⚠️ Nginx 热重载跳过 (需 root 权限)${NC}"
            else
                echo -e "${YELLOW}⚠️ Nginx 配置语法校验未通过，跳过 reload${NC}"
            fi
        fi
    fi
}

# 清理缓存及 .git 本地冗余垃圾数据，释放服务器磁盘空间
cleanup_cache() {
    echo -e "${GREEN}正在清理本地缓存与 .git 冗余垃圾...${NC}"
    cd "$APP_DIR" || return
    if [ -d ".git" ] && command -v git > /dev/null 2>&1; then
        git reflog expire --expire=now --all 2>/dev/null || true
        git gc --prune=now 2>/dev/null || true
        echo -e "${GREEN}✅ .git 冗余垃圾清理完成! 当前 .git 体积: $(du -sh .git 2>/dev/null | cut -f1)${NC}"
    fi
    find "$APP_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$APP_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    rm -rf /tmp/gift-backup 2>/dev/null || true
}

# 启动服务
start_service() {
    if check_status; then
        PID=$(cat "$PID_FILE")
        echo -e "${YELLOW}服务已在运行中 (PID: $PID)${NC}"
        return 1
    fi

    # 启动前自动生成最新 SSL 证书、配置 Nginx 与清理缓存垃圾
    ensure_ssl_certs
    setup_nginx_config
    cleanup_cache

    echo -e "${GREEN}正在启动服务...${NC}"
    
    cd "$APP_DIR" || {
        echo -e "${RED}错误: 无法进入目录 $APP_DIR${NC}"
        return 1
    }

    # 自动创建虚拟环境及安装依赖库
    if [ ! -d "$VENV_DIR" ]; then
        echo -e "${YELLOW}检测到虚拟环境不存在，正在自动创建虚拟环境 $VENV_DIR ...${NC}"
        python3 -m venv "$VENV_DIR" || {
            echo -e "${RED}错误: 创建虚拟环境失败，请确认系统已安装 python3-venv${NC}"
            return 1
        }
    fi

    # 检查核心依赖库是否存在，若缺失则强制安装
    if ! "$VENV_DIR/bin/python3" -c "import flask, flask_sqlalchemy, flask_wtf, flask_login" >/dev/null 2>&1; then
        echo -e "${GREEN}正在检查/补全项目依赖库...${NC}"
        "$VENV_DIR/bin/pip" install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple || true
        if [ -f "$APP_DIR/requirements.txt" ]; then
            "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple || {
                echo -e "${RED}错误: 依赖库安装失败，请检查网络或 requirements.txt${NC}"
                return 1
            }
        else
            "$VENV_DIR/bin/pip" install flask flask-sqlalchemy flask-wtf flask-login -i https://pypi.tuna.tsinghua.edu.cn/simple || {
                echo -e "${RED}错误: 依赖库安装失败${NC}"
                return 1
            }
        fi
        echo -e "${GREEN}✅ 依赖库检查/安装完成!${NC}"
    fi

    # 使用进程组方式启动，便于后续统一管理
    setsid bash -c "
        export ADMIN_USER='$ADMIN_USER'
        export ADMIN_PASS='$ADMIN_PASS'
        export PORT='$PORT'
        source $VENV_DIR/bin/activate
        python3 $APP_SCRIPT
    " >> "$LOG_FILE" 2>&1 &

    # 保存 PID
    local PID=$!
    echo "$PID" > "$PID_FILE"
    
    sleep 2
    if check_status; then
        echo -e "${GREEN}✅ 服务启动成功!${NC}"
        echo -e "   PID: $(cat $PID_FILE)"
        echo -e "   访问地址: http://127.0.0.1:$PORT"
        echo -e "   日志文件: $LOG_FILE"
    else
        echo -e "${RED}❌ 服务启动失败，请查看日志: $LOG_FILE${NC}"
        rm -f "$PID_FILE"
        return 1
    fi
}

# 停止服务（进程组 + 端口检查双重保障）
stop_service() {
    # 第一步：先通过 PID 文件处理
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        echo -e "${YELLOW}正在停止服务 (PID: $PID)...${NC}"
        
        # 获取进程组ID
        PGID=$(ps -o pgid= -p "$PID" 2>/dev/null | tr -d ' ')
        if [ -n "$PGID" ]; then
            echo -e "${YELLOW}终止进程组 PGID: $PGID${NC}"
            kill -TERM -"$PGID" 2>/dev/null
        else
            # 如果无法获取PGID，杀死所有子进程
            pkill -P "$PID" 2>/dev/null
            kill "$PID" 2>/dev/null
        fi
        
        # 等待主进程结束
        local wait_time=0
        while ps -p "$PID" > /dev/null 2>&1; do
            if [ $wait_time -ge 10 ]; then
                break
            fi
            sleep 1
            ((wait_time++))
        done

        # 如果主进程还在，强制杀死
        if ps -p "$PID" > /dev/null 2>&1; then
            echo -e "${YELLOW}进程未响应，强制终止...${NC}"
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
        echo -e "${YELLOW}未找到 PID 文件，尝试通过端口清理...${NC}"
    fi

    # 第二步：双重保险 —— 根据端口清理任何残留进程
    echo -e "${YELLOW}检查端口 $PORT 是否被占用...${NC}"
    local fuser_pid=$(lsof -ti :$PORT 2>/dev/null)
    if [ -n "$fuser_pid" ]; then
        echo -e "${YELLOW}发现端口 $PORT 被进程 $fuser_pid 占用，强制终止...${NC}"
        kill -9 "$fuser_pid" 2>/dev/null
        sleep 1
    fi

    # 最终确认
    if lsof -ti :$PORT > /dev/null 2>&1; then
        echo -e "${RED}❌ 端口 $PORT 仍被占用，请手动检查${NC}"
        echo -e "   执行: sudo lsof -i :$PORT"
        return 1
    else
        echo -e "${GREEN}✅ 服务已完全停止${NC}"
        return 0
    fi
}

# 查看状态
status_service() {
    # 先检查 PID 文件对应的进程
    if check_status; then
        PID=$(cat "$PID_FILE")
        echo -e "${GREEN}✅ 服务正在运行 (基于 PID 文件)${NC}"
        echo -e "   PID: $PID"
        echo -e "   端口: $PORT"
        echo -e "   日志文件: $LOG_FILE"
        ps -p "$PID" -o pid,ppid,cmd,etime
        return 0
    fi

    # 如果 PID 文件无效，但端口被占用，提示异常状态
    local port_pid=$(lsof -ti :$PORT 2>/dev/null)
    if [ -n "$port_pid" ]; then
        echo -e "${YELLOW}⚠️ 端口 $PORT 被进程 $port_pid 占用，但 PID 文件无效${NC}"
        echo -e "   请执行 './service.sh stop' 清理残留进程"
        return 1
    else
        echo -e "${RED}❌ 服务未运行${NC}"
        return 1
    fi
}

# 重启服务
restart_service() {
    echo -e "${YELLOW}正在重启服务...${NC}"
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
        echo "  start   - 启动服务 (自动配置 Nginx 与清理缓存)"
        echo "  stop    - 停止服务"
        echo "  status  - 查看服务状态"
        echo "  restart - 重启服务 (自动清理垃圾数据并生效新代码)"
        echo "  clean   - 仅手动清理垃圾缓存与压缩 .git"
        exit 1
        ;;
esac

exit 0

