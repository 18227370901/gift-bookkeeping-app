#!/bin/sh

# ===== 配置区域 =====
APP_DIR="/opt/service/gift-bookkeeping-app"
if [ ! -d "$APP_DIR" ]; then
    APP_DIR="$(cd "$(dirname "$0")" && pwd)"
fi
VENV_DIR="$APP_DIR/venv"
APP_SCRIPT="app.py"
PID_FILE="$APP_DIR/app.pid"
LOG_FILE="$APP_DIR/app.log"

# ===== SNI 多项目共用端口配置（全部支持环境变量覆盖，多项目部署时各项目设不同值即可） =====
PROJECT_NAME="${PROJECT_NAME:-gift_app}"        # 项目标识：决定 Nginx 配置文件名($PROJECT_NAME.conf)与 upstream 名(${PROJECT_NAME}_backend)
SNI_DOMAIN="${SNI_DOMAIN:-localhost}"            # SNI 域名：写入 server_name 与自签证书 CN/SAN，多项目各设一个域名
SSL_CERT="${SSL_CERT:-$APP_DIR/ssl/server.crt}" # SSL 证书路径（可指向正式证书）
SSL_KEY="${SSL_KEY:-$APP_DIR/ssl/server.key}"   # SSL 私钥路径
SNI_DEFAULT_SERVER="${SNI_DEFAULT_SERVER:-1}"   # 是否作为该监听端口的兑底 default_server（1=是 0=否，多项目共端口时只应有一个项目为 1）

# Nginx 配置文件目录变量（用户可自定义覆盖，如 export NGINX_CONF_DIR=/etc/nginx/conf.d）
# 默认指向 /opt/service/nginx/conf.d；其他部署环境如使用 /etc/nginx/conf.d，可通过环境变量覆盖
NGINX_CONF_DIR="${NGINX_CONF_DIR:-/opt/service/nginx/conf.d}"

# ===== 文件覆盖策略（V10.10.3 新增：保护已存在的证书与 Nginx 配置，防止重启时被自签证书/模板渲染静默覆盖） =====
# SSL_FORCE_UPDATE / NGINX_CONF_FORCE_UPDATE: 文件已存在时是否强制覆盖更新
#   1 = 强制更新（不询问，直接覆盖）；未设置 = 交互式终端弹出 y/n 询问，非交互场景（cron/CI/管道）默认跳过保留旧文件
SSL_FORCE_UPDATE="${SSL_FORCE_UPDATE:-}"
NGINX_CONF_FORCE_UPDATE="${NGINX_CONF_FORCE_UPDATE:-}"

# ===== 环境变量定义（全局有效） =====
export PORT="${PORT:-11443}"
export NGINX_PORT="${NGINX_PORT:-443}"
export ADMIN_USER="${ADMIN_USER:-admin}"
export ADMIN_PASS="${ADMIN_PASS:-admin123}"  # 密码含特殊字符，用单引号括起

# ===== 颜色输出 =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# POSIX 兼容的彩色输出函数（替代 echo -e，兼容 dash/sh）
echo_e() {
    printf '%b\n' "$*"
}

# ===== 函数定义 =====

# 判断是否覆盖已存在文件：交互环境弹 y/n 询问；非交互环境（cron/CI）不能卡死在 read，默认保留旧文件
# 入参 $1: 已存在文件路径（提示语用）；$2: 对应策略环境变量当前值（1=强制覆盖 0=强制保留 空=询问）；$3: 策略变量名（非交互提示文案用）
# 返回值: 0=允许覆盖更新 1=保留旧文件不覆盖
should_overwrite() {
    local target_file="$1"
    local force_value="$2"
    local hint_var="$3"
    # 环境变量已显式指定策略时，直接按策略执行，不再询问（兼容 cron 定时重启等非交互场景）
    if [ "$force_value" = "1" ]; then
        return 0
    fi
    if [ "$force_value" = "0" ]; then
        return 1
    fi
    # [ -t 0 ] 检测 stdin 是否为终端：非交互场景（cron、管道、CI）无人应答，默认保留旧文件，避免脚本卡死
    if [ ! -t 0 ]; then
        echo_e "${YELLOW}检测到已存在 $target_file，非交互环境自动保留旧文件（如需强制更新请设置 $hint_var=1）${NC}"
        return 1
    fi
    # 交互式终端：弹出确认，输入 y/Y 确认覆盖，其余任意输入（含直接回车）均视为保留旧文件（默认安全）
    printf '检测到已存在 %s，是否覆盖更新? (y/n) [默认 n]: ' "$target_file" >&2
    read -r answer
    case "$answer" in
        y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

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

# 自动生成 SSL 证书：文件不存在则直接创建；已存在时先询问是否更新，防止自定义/正式证书被自签证书覆盖
ensure_ssl_certs() {
    # 两份证书文件均不存在时，无需询问，直接创建（首次部署场景）
    if [ ! -f "$SSL_CERT" ] && [ ! -f "$SSL_KEY" ]; then
        echo_e "${GREEN}未检测到 SSL 证书文件，正在生成自签名证书 (域名: $SNI_DOMAIN)...${NC}"
        mkdir -p "$APP_DIR/ssl"
        local cert_script="$APP_DIR/generate_ssl_certs.py"
        # 固定在 APP_DIR 下执行，确保证书始终输出到 $APP_DIR/ssl（不依赖调用时所在目录）
        if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/python3" ]; then
            (cd "$APP_DIR" && "$VENV_DIR/bin/python3" "$cert_script" --domain "$SNI_DOMAIN")
        elif command -v python3 > /dev/null 2>&1; then
            (cd "$APP_DIR" && python3 "$cert_script" --domain "$SNI_DOMAIN")
        else
            echo_e "${RED}警告: 未找到 python3，无法自动生成证书，请手动生成或准备 $SSL_CERT 和 $SSL_KEY${NC}"
        fi
    # 文件已存在：必须先取得用户/环境变量许可，才允许覆盖更新（保护自定义证书、正式证书）
    elif should_overwrite "$SSL_CERT" "$SSL_FORCE_UPDATE" "SSL_FORCE_UPDATE"; then
        echo_e "${GREEN}确认更新，正在重新生成 SSL 自签名证书 (域名: $SNI_DOMAIN)...${NC}"
        mkdir -p "$APP_DIR/ssl"
        local cert_script="$APP_DIR/generate_ssl_certs.py"
        # 固定在 APP_DIR 下执行，确保证书始终输出到 $APP_DIR/ssl（不依赖调用时所在目录）
        if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/python3" ]; then
            (cd "$APP_DIR" && "$VENV_DIR/bin/python3" "$cert_script" --domain "$SNI_DOMAIN")
        elif command -v python3 > /dev/null 2>&1; then
            (cd "$APP_DIR" && python3 "$cert_script" --domain "$SNI_DOMAIN")
        else
            echo_e "${RED}警告: 未找到 python3，无法自动生成证书，请手动生成或准备 $SSL_CERT 和 $SSL_KEY${NC}"
        fi
    else
        echo_e "${GREEN}✅ 检测到已存在 SSL 证书文件，保留现有证书不更新: $SSL_CERT / $SSL_KEY${NC}"
    fi
    if [ ! -f "$SSL_CERT" ] || [ ! -f "$SSL_KEY" ]; then
        echo_e "${YELLOW}⚠️ 证书文件缺失: $SSL_CERT / $SSL_KEY，Nginx 配置校验将无法通过${NC}"
    fi
}
setup_nginx_config() {
    # SNI 域名必填：server_name 为空会导致 Nginx 配置无效，且多项目无法区分流量
    if [ -z "$SNI_DOMAIN" ]; then
        echo_e "${RED}错误: SNI_DOMAIN 为空，无法配置 Nginx SNI 分流，已中止。请通过环境变量指定，例如: SNI_DOMAIN=gift.example.com PROJECT_NAME=gift_app ./$0 start${NC}"
        return 1
    fi

    # Nginx 配置目录不存在时：提示用户手动创建，不自动创建、不跳过
    if [ ! -d "$NGINX_CONF_DIR" ]; then
        echo_e "${RED}错误: Nginx 配置目录不存在: $NGINX_CONF_DIR${NC}"
        echo_e "${YELLOW}请手动创建该目录后重试: sudo mkdir -p $NGINX_CONF_DIR${NC}"
        echo_e "${YELLOW}（其他部署环境如使用 /etc/nginx/conf.d，可通过环境变量覆盖: export NGINX_CONF_DIR=/etc/nginx/conf.d）${NC}"
        return 1
    fi

    if [ -d "$NGINX_CONF_DIR" ]; then
        echo_e "${GREEN}正在处理 Nginx 配置文件 ($NGINX_CONF_DIR)...${NC}"
        if [ -f "$NGINX_CONF_DIR/gift_app_docker.conf" ]; then
            mv "$NGINX_CONF_DIR/gift_app_docker.conf" "$NGINX_CONF_DIR/gift_app_docker.conf.disabled" 2>/dev/null || true
            echo_e "${YELLOW}已禁用冲突的 Docker 版本 Nginx 配置: gift_app_docker.conf${NC}"
        fi
        # 禁用本项目旧版硬编码命名的配置文件（防止新旧配置共存导致 server_name 冲突）
        if [ "$PROJECT_NAME" = "gift_app" ] && [ -f "$NGINX_CONF_DIR/gift_app_native.conf" ]; then
            mv "$NGINX_CONF_DIR/gift_app_native.conf" "$NGINX_CONF_DIR/gift_app_native.conf.disabled" 2>/dev/null || true
            echo_e "${YELLOW}已禁用旧版 Nginx 配置: gift_app_native.conf${NC}"
        fi
        local target_conf="$NGINX_CONF_DIR/$PROJECT_NAME.conf"
        # 已存在的项目配置文件先取得许可再覆盖渲染，防止用户手改过的 conf 被模板静默重置
        # （首次部署文件不存在时无需询问，直接渲染创建）
        if [ -f "$target_conf" ] && ! should_overwrite "$target_conf" "$NGINX_CONF_FORCE_UPDATE" "NGINX_CONF_FORCE_UPDATE"; then
            echo_e "${YELLOW}保留现有 Nginx 配置文件，未重新渲染: $target_conf${NC}"
        elif [ -f "$APP_DIR/nginx_ssl.conf" ]; then
            # 按 SNI_DEFAULT_SERVER 决定 listen 行是否追加 default_server（兜底 server）
            local listen_value="$NGINX_PORT"
            local default_flag="否"
            if [ "$SNI_DEFAULT_SERVER" = "1" ]; then
                listen_value="${NGINX_PORT} default_server"
                default_flag="是"
            fi
            # 渲染占位符模板，输出为当前项目专属配置文件（每个项目一份，互不覆盖）
            # 模板顶部的占位符说明注释不带入生成文件（其占位符已被替换，保留会误导阅读者）
            {
                echo "# 本文件由 run.sh 依据 nginx_ssl.conf 模板自动生成，请勿手工修改（改模板请编辑源文件后重跑 start）"
                echo "# 项目: $PROJECT_NAME | SNI域名: $SNI_DOMAIN | 监听端口: $NGINX_PORT | default_server: $default_flag | 生成时间: $(date '+%Y-%m-%d %H:%M:%S')"
                sed -e '1,/^#   __SSL_KEY__/d' \
                    -e "s|__UPSTREAM_NAME__|${PROJECT_NAME}_backend|g" \
                    -e "s|__BACKEND_PORT__|$PORT|g" \
                    -e "s|__NGINX_PORT__|$listen_value|g" \
                    -e "s|__SNI_DOMAIN__|$SNI_DOMAIN|g" \
                    -e "s|__SSL_CERT__|$SSL_CERT|g" \
                    -e "s|__SSL_KEY__|$SSL_KEY|g" \
                    "$APP_DIR/nginx_ssl.conf"
            } > "$target_conf" 2>/dev/null && \
            echo_e "${GREEN}✅ 已动态更新并同步 Nginx 配置到 $target_conf (项目: $PROJECT_NAME, 后端端口: $PORT, Nginx监听端口: $NGINX_PORT, SNI域名: $SNI_DOMAIN, default_server: $default_flag)${NC}" || true
        fi
        if command -v nginx > /dev/null 2>&1; then
            if nginx -t >/dev/null 2>&1; then
                (nginx -s reload >/dev/null 2>&1 || systemctl reload nginx >/dev/null 2>&1) && \
                echo_e "${GREEN}✅ Nginx 配置热重载成功!${NC}" || echo_e "${YELLOW}⚠️ Nginx 热重载跳过 (需 root 权限)${NC}"
            else
                echo_e "${YELLOW}⚠️ Nginx 配置语法校验未通过，跳过 reload${NC}"
            fi
        fi
    fi
}

# 清理缓存及 .git 本地冗余垃圾数据，释放服务器磁盘空间
cleanup_cache() {
    echo_e "${GREEN}正在清理本地缓存与 .git 冗余垃圾...${NC}"
    cd "$APP_DIR" || return
    if [ -d ".git" ] && command -v git > /dev/null 2>&1; then
        git reflog expire --expire=now --all 2>/dev/null || true
        git gc --prune=now 2>/dev/null || true
        echo_e "${GREEN}✅ .git 冗余垃圾清理完成! 当前 .git 体积: $(du -sh .git 2>/dev/null | cut -f1)${NC}"
    fi
    find "$APP_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$APP_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    rm -rf /tmp/gift-backup 2>/dev/null || true
}

# 启动服务
start_service() {
    if check_status; then
        PID=$(cat "$PID_FILE")
        echo_e "${YELLOW}服务已在运行中 (PID: $PID)${NC}"
        return 1
    fi

    # 启动前自动生成最新 SSL 证书、配置 Nginx 与清理缓存垃圾（SNI 配置失败则中止启动）
    ensure_ssl_certs
    setup_nginx_config || {
        echo_e "${RED}❌ Nginx SNI 配置失败，服务启动中止，请检查 SNI_DOMAIN 环境变量${NC}"
        return 1
    }
    cleanup_cache

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
        . $VENV_DIR/bin/activate
        python3 $APP_SCRIPT
    " >> "$LOG_FILE" 2>&1 &

    # 保存 PID
    local PID=$!
    echo "$PID" > "$PID_FILE"
    
    sleep 2
    if check_status; then
        # 标准端口(443)不附加端口号；非标准端口则以 域名:端口 形式提示
        local access_url="https://$SNI_DOMAIN/"
        if [ "$NGINX_PORT" != "443" ]; then
            access_url="https://$SNI_DOMAIN:$NGINX_PORT/"
        fi
        echo_e "${GREEN}✅ 服务启动成功!${NC}"
        echo_e "   PID: $(cat $PID_FILE)"
        echo_e "   访问地址: $access_url"
        echo_e "   后端本地直连: http://127.0.0.1:$PORT"
        echo_e "   日志文件: $LOG_FILE"
    else
        echo_e "${RED}❌ 服务启动失败，请查看日志: $LOG_FILE${NC}"
        rm -f "$PID_FILE"
        return 1
    fi
}

# 停止服务（进程组 + 端口检查双重保障）
stop_service() {
    # 第一步：先通过 PID 文件处理
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        echo_e "${YELLOW}正在停止服务 (PID: $PID)...${NC}"
        
        # 获取进程组ID
        PGID=$(ps -o pgid= -p "$PID" 2>/dev/null | tr -d ' ')
        if [ -n "$PGID" ]; then
            echo_e "${YELLOW}终止进程组 PGID: $PGID${NC}"
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
            wait_time=$((wait_time + 1))
        done

        # 如果主进程还在，强制杀死
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
        return 0
    fi
}

# 查看状态
status_service() {
    # 先检查 PID 文件对应的进程
    if check_status; then
        PID=$(cat "$PID_FILE")
        echo_e "${GREEN}✅ 服务正在运行 (基于 PID 文件)${NC}"
        echo_e "   PID: $PID"
        echo_e "   端口: $PORT"
        echo_e "   日志文件: $LOG_FILE"
        ps -p "$PID" -o pid,ppid,cmd,etime
        return 0
    fi

    # 如果 PID 文件无效，但端口被占用，提示异常状态
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

# 重启服务
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
        echo "  NGINX_PORT          Nginx 对外监听端口 (默认: 443)"
        echo "  SSL_CERT/SSL_KEY    证书与私钥路径 (默认: \$APP_DIR/ssl/server.crt|key)"
        echo "  SNI_DEFAULT_SERVER  是否作为兜底 default_server，1=是 0=否 (默认: 1)"
        echo "  SSL_FORCE_UPDATE=1          SSL 证书已存在时强制覆盖更新，不询问 (默认: 询问/非交互时保留)"
        echo "  NGINX_CONF_FORCE_UPDATE=1   Nginx 配置已存在时强制覆盖渲染，不询问 (默认: 询问/非交互时保留)"
        echo "  示例: PROJECT_NAME=mengyao SNI_DOMAIN=mengyao.example.com ./$0 start"
        echo "  示例: SSL_FORCE_UPDATE=1 NGINX_CONF_FORCE_UPDATE=1 ./$0 restart  # cron/自动化场景强制更新"
        exit 1
        ;;
esac

exit 0

