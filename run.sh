#!/bin/bash

# ===== 配置区域 =====
APP_DIR="/opt/service/gift-bookkeeping-app-docker"
VENV_DIR="$APP_DIR/venv"
APP_SCRIPT="app.py"
PID_FILE="$APP_DIR/app.pid"
LOG_FILE="$APP_DIR/app.log"

# 环境变量
export PORT=15001
export ADMIN_USER=admin
export ADMIN_PASS=xK9pQ#vL2mNw

# ===== 颜色输出（可选） =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ===== 函数定义 =====

# 检查服务是否正在运行
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

# 启动服务
start_service() {
    if check_status; then
        PID=$(cat "$PID_FILE")
        echo -e "${YELLOW}服务已在运行中 (PID: $PID)${NC}"
        return 1
    fi

    echo -e "${GREEN}正在启动服务...${NC}"
    
    # 切换到应用目录并启动（后台运行）
    cd "$APP_DIR" || {
        echo -e "${RED}错误: 无法进入目录 $APP_DIR${NC}"
        return 1
    }

    # 激活虚拟环境并启动 Flask 应用
    # 使用 nohup 让进程在后台运行，输出重定向到日志文件
    nohup bash -c "
        source $VENV_DIR/bin/activate
        python3 $APP_SCRIPT
    " >> "$LOG_FILE" 2>&1 &

    # 保存 PID
    echo $! > "$PID_FILE"
    
    # 等待一秒确认启动
    sleep 1
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

# 停止服务
stop_service() {
    if ! check_status; then
        echo -e "${YELLOW}服务未运行${NC}"
        return 1
    fi

    PID=$(cat "$PID_FILE")
    echo -e "${YELLOW}正在停止服务 (PID: $PID)...${NC}"
    
    kill "$PID" 2>/dev/null
    
    # 等待进程结束（最多 5 秒）
    for i in {1..5}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done

    # 如果还没结束，强制杀死
    if ps -p "$PID" > /dev/null 2>&1; then
        echo -e "${YELLOW}进程未响应，强制终止...${NC}"
        kill -9 "$PID" 2>/dev/null
    fi

    rm -f "$PID_FILE"
    echo -e "${GREEN}✅ 服务已停止${NC}"
}

# 查看状态
status_service() {
    if check_status; then
        PID=$(cat "$PID_FILE")
        echo -e "${GREEN}✅ 服务正在运行${NC}"
        echo -e "   PID: $PID"
        echo -e "   端口: $PORT"
        # 可选：显示进程详细信息
        ps -p "$PID" -o pid,ppid,cmd,etime
    else
        echo -e "${RED}❌ 服务未运行${NC}"
    fi
}

# 重启服务
restart_service() {
    echo -e "${YELLOW}正在重启服务...${NC}"
    stop_service
    sleep 1
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
    *)
        echo "用法: $0 {start|stop|status|restart}"
        echo ""
        echo "  start   - 启动服务"
        echo "  stop    - 停止服务"
        echo "  status  - 查看服务状态"
        echo "  restart - 重启服务"
        exit 1
        ;;
esac

exit 0
