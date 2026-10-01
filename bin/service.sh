#!/bin/sh
# service.sh (传统版) — 启停操作函数（V10.10.21 自 run.sh 拆出）
# 依赖：bin/config.sh（变量）、bin/common.sh（echo_e）、bin/cleanup.sh（cleanup_cache）、
#       bin/python_env.sh（preflight_check/ensure_python_env）、bin/db_select.sh（select_db_mode/load_db_env）、
#       bin/db_setup.sh（ensure_sqlite_runtime_db/PG 模式函数）、bin/ssl_certs.sh、bin/nginx_config.sh、bin/port_conflict.sh
#
# V10.10.29: 独立 PG 生命周期闭环 ——
#   ① stop 无条件释放 PG 容器（docker rm -f 容器删除、数据卷保留，对齐 Docker 版 compose down），
#      此前释放逻辑嵌在端口检查成功分支内，端口清理失败 return 1 时 PG 容器完全不会被释放；
#   ② start 检测容器未运行时自动重建（V10.10.28 版本化数据卷自动接回原数据），running 则幂等跳过，
#      此前 start 走 .db.env 复用分支时从不重建 PG 容器，stop 释放后服务将无法连接 PG；
#   ③ 独立 PG 容器名/镜像/挂载路径/连接参数持久化至 .db.env（对齐 Docker 版做法），供 stop 释放与 start 重建使用

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
            echo_e "   数据库模式: ${DB_MODE} (配置于 .temp/.db.env，./$(basename "$0") --reconfig 可重新选择)"
        else
            echo_e "   数据库模式: 配置文件为空或已损坏 (.temp/.db.env)，建议 ./$(basename "$0") --reconfig 重新选择"
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

    # V10.10.29: 独立 PG 生命周期闭环 —— stop 已改为释放容器（docker rm -f，数据卷保留），
    # start 需检测容器未运行时自动重建（V10.10.28 版本化数据卷自动接回原数据），running 则幂等跳过。
    # 背景：此前 start 走 .db.env 复用分支时从不重建 PG 容器，stop 释放后服务将无法连接 PG。
    if [ "${DB_MODE:-}" = "independent" ]; then
        # 容器名：优先读 .db.env 持久化值（V10.10.29 起 start 时写入），兜底当前 PROJECT_NAME 拼接
        load_db_env
        _pg_ct="${PG_CONTAINER_NAME:-${PROJECT_NAME}-pg}"
        _pg_ct_state=$(docker inspect --format '{{.State.Status}}' "$_pg_ct" 2>/dev/null)
        if [ "$_pg_ct_state" != "running" ]; then
            echo_e "${YELLOW}独立 PG 容器未运行（状态: ${_pg_ct_state:-不存在}），正在重建（数据卷保留，自动接回原数据）...${NC}"
            # PROJECT_NAME 已变更时先清理旧名容器，避免泄漏（容器名与卷名均随 PROJECT_NAME 变化）
            if [ -n "${PG_CONTAINER_NAME:-}" ] && [ "$PG_CONTAINER_NAME" != "${PROJECT_NAME}-pg" ]; then
                docker rm -f "$PG_CONTAINER_NAME" > /dev/null 2>&1 || true
                echo_e "${YELLOW}已清理旧名独立 PG 容器 ${PG_CONTAINER_NAME}（PROJECT_NAME 已变更）${NC}"
            fi
            # 镜像兜底链：.db.env 持久化 PG_LOCAL_IMAGE > 本地镜像扫描（detect_pg_environment）
            # > setup_independent_pg 内下载默认镜像；存量老部署无持久化字段时靠本地扫描
            if [ -z "${PG_LOCAL_IMAGE:-}" ]; then
                detect_pg_environment
            fi
            setup_independent_pg
            # setup 内部失败会降级 SQLite——已有 PG 数据的场景绝不能静默切库，中止启动
            if [ "${DB_MODE:-}" != "independent" ]; then
                echo_e "${RED}❌ 独立 PG 容器重建失败（已降级 SQLite），为避免数据混淆中止启动；请检查 Docker 状态后重试${NC}"
                return 1
            fi
            # 重建后端口可能变化（15432 起重扫），同步更新 .db.env 供后续 stop/无参 restart 复用
            save_db_env
        fi
        # V10.10.29: 独立 PG 模式持久化容器名/镜像/挂载路径/连接参数至 .db.env（对齐 Docker 版做法，
        # 用 grep -v 剥旧字段再追加，避免 save_db_env 整体重写时丢失）；空值不写入（存量老部署兼容）
        mkdir -p "$APP_DIR/.temp"
        [ -f "$DB_ENV_FILE" ] || touch "$DB_ENV_FILE"
        grep -v -E '^(PG_CONTAINER_NAME|PG_LOCAL_IMAGE|PG_DATA_DIR|PG_USER|PG_PASSWORD|PG_DB|PG_MAJOR)=' "$DB_ENV_FILE" 2>/dev/null > "$DB_ENV_FILE.tmp" || true
        [ -n "${PG_CONTAINER_NAME:-}" ] && echo "PG_CONTAINER_NAME=$PG_CONTAINER_NAME" >> "$DB_ENV_FILE.tmp"
        [ -n "${PG_LOCAL_IMAGE:-}" ] && echo "PG_LOCAL_IMAGE=$PG_LOCAL_IMAGE" >> "$DB_ENV_FILE.tmp"
        [ -n "${PG_DATA_DIR:-}" ] && echo "PG_DATA_DIR=$PG_DATA_DIR" >> "$DB_ENV_FILE.tmp"
        [ -n "${PG_USER:-}" ] && echo "PG_USER=$PG_USER" >> "$DB_ENV_FILE.tmp"
        [ -n "${PG_PASSWORD:-}" ] && echo "PG_PASSWORD=$PG_PASSWORD" >> "$DB_ENV_FILE.tmp"
        [ -n "${PG_DB:-}" ] && echo "PG_DB=$PG_DB" >> "$DB_ENV_FILE.tmp"
        [ -n "${PG_MAJOR:-}" ] && echo "PG_MAJOR=$PG_MAJOR" >> "$DB_ENV_FILE.tmp"
        mv "$DB_ENV_FILE.tmp" "$DB_ENV_FILE"
        chmod 600 "$DB_ENV_FILE" 2>/dev/null || true
    fi

    # V10.10.20: SQLite 模式下确保运行库位于 data/ 目录（首次部署仅就绪目录，由应用创建纯净空库）
    if [ -z "${DATABASE_URL:-}" ]; then
        ensure_sqlite_runtime_db || return 1
    fi

    echo_e "${GREEN}正在启动服务...${NC}"

    cd "$APP_DIR" || {
        echo_e "${RED}错误: 无法进入目录 $APP_DIR${NC}"
        return 1
    }

    # V10.10.21: venv 就绪 + 依赖检查/安装（自本函数抽取至 bin/python_env.sh 的 ensure_python_env）
    ensure_python_env || return 1

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

    # V10.10.29: 独立 PG 容器无条件释放 —— 此前嵌在端口检查成功分支内，端口清理失败 return 1 时
    # PG 容器完全不会被释放；现移到端口检查之前，无论端口清理结果如何都执行释放。
    # 释放方式对齐 Docker 版 compose down：docker rm -f 容器删除、数据卷保留（start 时自动重建接回数据）。
    # 容器名：independent 用 .db.env 持久化值（兜底 PROJECT_NAME 拼接）；
    # 非 independent 模式（sqlite/shared/配置未持久化的存量直通部署）按本版命名约定识别遗留容器兜底清理；
    # shared 模式的实际数据库在外部容器 DB_PG_CONTAINER，设计上保留运行，仅输出提示。
    if [ -f "$DB_ENV_FILE" ]; then
        load_db_env
    fi
    if [ "${DB_MODE:-}" = "independent" ]; then
        _pg_container="${PG_CONTAINER_NAME:-${PROJECT_NAME}-pg}"
    else
        _pg_container="${PROJECT_NAME}-pg"
        if [ "${DB_MODE:-}" = "shared" ] && [ -n "${DB_PG_CONTAINER:-}" ]; then
            echo_e "${GREEN}共享 PG 容器 ${DB_PG_CONTAINER} 为外部容器，保留运行不做操作${NC}"
        fi
    fi
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${_pg_container}$"; then
        echo_e "${YELLOW}正在释放独立 PG 容器 (${_pg_container})（容器移除、数据卷保留）...${NC}"
        if docker rm -f "$_pg_container" > /dev/null 2>&1; then
            echo_e "${GREEN}✅ 独立 PG 容器已停止并移除（数据卷保留，下次 start 自动重建）${NC}"
        else
            echo_e "${YELLOW}⚠️ 独立 PG 容器 ${_pg_container} 移除失败，请手动处理: docker rm -f ${_pg_container}${NC}"
        fi
    fi

    # 最终确认（端口检查只影响返回码，不再影响 PG 释放）
    if lsof -ti :$PORT > /dev/null 2>&1; then
        echo_e "${RED}❌ 端口 $PORT 仍被占用，请手动检查${NC}"
        echo_e "   执行: sudo lsof -i :$PORT"
        return 1
    else
        echo_e "${GREEN}✅ 服务已完全停止${NC}"
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
