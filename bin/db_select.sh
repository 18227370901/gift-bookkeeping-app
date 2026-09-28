#!/bin/sh
# db_select.sh — 两版完全一致的数据库选择逻辑（交互式三选一 + Cron安全 + 智能推荐）
# 被 run.sh source，依赖 bin/common.sh（echo_e）和 bin/db_setup.sh（setup_sqlite/setup_shared_pg/setup_independent_pg）
# DB_ENV_FILE / DB_OVERRIDE 在此定义，run.sh 中的 start_service/stop_service 也可读取

DB_ENV_FILE="$APP_DIR/.temp/.db.env"
DB_OVERRIDE="$APP_DIR/.temp/docker-compose.db-override.yml"

# 检测服务器 PG 环境与可用内存
detect_pg_environment() {
    PG_RUNNING_NAME=""
    PG_RUNNING_IMAGE=""
    PG_LOCAL_IMAGE=""
    AVAIL_MEM=0
    if command -v docker > /dev/null 2>&1; then
        _pg_info=$(docker ps --format '{{.Names}} {{.Image}}' 2>/dev/null | grep -iE 'postgres|pgvector' | head -1)
        if [ -n "$_pg_info" ]; then
            PG_RUNNING_NAME=$(echo "$_pg_info" | awk '{print $1}')
            PG_RUNNING_IMAGE=$(echo "$_pg_info" | awk '{print $2}')
        fi
        PG_LOCAL_IMAGE=$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -iE 'postgres|pgvector' | head -1)
    fi
    if command -v free > /dev/null 2>&1; then
        AVAIL_MEM=$(free -m 2>/dev/null | awk '/^Mem:/{print $7}')
        AVAIL_MEM="${AVAIL_MEM:-0}"
    fi
}

# 保存数据库配置
save_db_env() {
    mkdir -p "$APP_DIR/.temp"
    cat > "$DB_ENV_FILE" << ENVEOF
# 人情记账本数据库部署配置（首次交互选择后自动生成，后续重启自动读取）
# 生成时间: $(date '+%Y-%m-%d %H:%M:%S')
DB_MODE=$DB_MODE
DB_PG_CONTAINER=$DB_PG_CONTAINER
DATABASE_URL=$DATABASE_URL
ENVEOF
    chmod 600 "$DB_ENV_FILE" 2>/dev/null || true
}

# 从 .temp/.db.env 读取数据库配置
load_db_env() {
    if [ -f "$DB_ENV_FILE" ]; then
        . "$DB_ENV_FILE"
    fi
}

# 交互式数据库选择主逻辑（cron 安全）
select_db_mode() {
    if [ "$DB_RESET" = "1" ] && [ -f "$DB_ENV_FILE" ]; then
        rm -f "$DB_ENV_FILE"
        [ -n "$DB_OVERRIDE" ] && rm -f "$DB_OVERRIDE"
        echo_e "${YELLOW}已清除旧数据库配置，将重新选择${NC}"
    fi

    # ① DB_MODE 环境变量直通（cron/CI 首选方式）
    if [ -n "$DB_MODE" ]; then
        case "$DB_MODE" in
            sqlite) setup_sqlite ;;
            shared) setup_shared_pg ;;
            independent) detect_pg_environment; setup_independent_pg ;;
            *) echo_e "${RED}无效的 DB_MODE: $DB_MODE${NC}"; exit 1 ;;
        esac
        if [ -t 0 ] && [ "$DB_MODE" != "independent" ]; then
            save_db_env
        fi
        return
    fi

    # ② 配置文件存在，直接读取（日常 restart 场景）
    if [ -f "$DB_ENV_FILE" ]; then
        load_db_env
        export DATABASE_URL
        echo_e "${GREEN}数据库模式: ${DB_MODE} (从配置文件读取)${NC}"
        return
    fi

    # ③ 交互式终端：显示三选一菜单
    if [ -t 0 ]; then
        detect_pg_environment
        echo_e ""
        echo_e "${GREEN}🔍 检测服务器环境...${NC}"
        [ -n "$PG_RUNNING_NAME" ] && echo_e "   运行中的 PG 容器: ${PG_RUNNING_NAME} (${PG_RUNNING_IMAGE})" || echo_e "   运行中的 PG 容器: 无"
        [ -n "$PG_LOCAL_IMAGE" ] && echo_e "   本地 PG 镜像: ${PG_LOCAL_IMAGE}" || echo_e "   本地 PG 镜像: 无"
        echo_e "   可用内存: ${AVAIL_MEM}MB"
        echo_e ""

        _recommend=1
        if [ -n "$PG_RUNNING_NAME" ] && [ "$AVAIL_MEM" -ge 400 ]; then
            _recommend=2
        elif [ -n "$PG_LOCAL_IMAGE" ] && [ "$AVAIL_MEM" -ge 700 ]; then
            _recommend=3
        fi

        echo_e "  ┌─────────────────────────────────────────────────┐"
        echo_e "  │  请选择数据库部署方式                              │"
        echo_e "  ├─────────────────────────────────────────────────┤"
        echo_e "  │  1) SQLite 本地文件                               │"
        echo_e "  │     零依赖、内存占用最低、适合单机轻量场景           │"
        if [ -n "$PG_RUNNING_NAME" ]; then
            echo_e "  │  2) 共享 PostgreSQL 实例$([ $_recommend -eq 2 ] && echo ' ⭐ 推荐')"
            echo_e "  │     复用已有 PG 容器 ${PG_RUNNING_NAME}"
            echo_e "  │     自动创建应用专属库 + 账号，互不干扰              │"
        else
            echo_e "  │  2) 共享 PostgreSQL 实例 (未检测到运行中的 PG 容器)"
        fi
        if [ -n "$PG_LOCAL_IMAGE" ]; then
            echo_e "  │  3) 独立 PostgreSQL 容器$([ $_recommend -eq 3 ] && echo ' ⭐ 推荐')"
            echo_e "  │     新起 pg 服务，应用独占"
            echo_e "  │     使用本地镜像 ${PG_LOCAL_IMAGE}"
        else
            echo_e "  │  3) 独立 PostgreSQL 容器 (本地无 PG 镜像，需下载)"
        fi
        echo_e "  └─────────────────────────────────────────────────┘"

        printf '请选择 [1/2/3，默认 %d]: ' "$_recommend" >&2
        read -r _db_choice
        _db_choice="${_db_choice:-$_recommend}"

        case "$_db_choice" in
            1) DB_MODE=sqlite ;;
            2) DB_MODE=shared; DB_PG_CONTAINER="$PG_RUNNING_NAME" ;;
            3) DB_MODE=independent ;;
            *) echo_e "${RED}无效选择${NC}"; exit 1 ;;
        esac

        case "$DB_MODE" in
            sqlite) setup_sqlite ;;
            shared) setup_shared_pg ;;
            independent) setup_independent_pg ;;
        esac
        save_db_env
    else
        # ④ 非交互环境：默认 SQLite（cron/管道安全降级）
        echo_e "${YELLOW}非交互环境，默认使用 SQLite。如需配置 PostgreSQL，请设置 DB_MODE 环境变量或交互式运行 ./run.sh start${NC}"
        DB_MODE=sqlite
        DATABASE_URL=""
        export DATABASE_URL
    fi
}
