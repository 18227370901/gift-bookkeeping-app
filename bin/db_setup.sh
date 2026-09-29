#!/bin/sh
# db_setup.sh (传统版) — 数据库模式配置函数（SQLite/共享PG/独立PG，通过环境变量传递 DATABASE_URL）

# 配置 SQLite 模式
setup_sqlite() {
    DATABASE_URL=""
    export DATABASE_URL
    echo_e "${GREEN}数据库模式: SQLite 本地文件${NC}"
}

# V10.10.18: 首次部署自动初始化运行库（仅 SQLite 模式调用，由 run.sh 的 start_service 触发）
# 背景：全新 clone 后 data/ 目录不存在时，app.py 会把运行库落在仓库根目录的样例库上，
#       运行数据污染 git 工作区（git pull 覆盖丢数据，与 V10.10.12 事故同源）。
# 此函数确保 data/ 目录存在并复制样例库为运行库，实现运行数据与样例库彻底分离；
# 已有运行库时不做任何改动（幂等，不影响存量部署）。
ensure_sqlite_runtime_db() {
    _rt_dir="$APP_DIR/data"
    _rt_db="$_rt_dir/gift_bookkeeping.db"
    _sample_db="$APP_DIR/gift_bookkeeping.db"
    if [ ! -f "$_rt_db" ]; then
        mkdir -p "$_rt_dir" || {
            echo_e "${RED}❌ 创建数据目录 $_rt_dir 失败，请检查目录权限${NC}"
            return 1
        }
        if [ -f "$_sample_db" ]; then
            cp "$_sample_db" "$_rt_db" || {
                echo_e "${RED}❌ 复制样例库到 $_rt_db 失败，请检查磁盘空间与权限${NC}"
                return 1
            }
            echo_e "${GREEN}✅ 首次部署：已复制样例库为运行库 data/gift_bookkeeping.db（运行数据与样例库彻底分离）${NC}"
        else
            echo_e "${YELLOW}⚠️ 未找到样例库 $_sample_db，应用启动后将自动创建全新空库 data/gift_bookkeeping.db${NC}"
        fi
    fi
    return 0
}

# 配置共享 PostgreSQL 模式（传统版：通过 127.0.0.1:暴露端口 连接）
setup_shared_pg() {
    if [ -z "$DB_PG_CONTAINER" ]; then
        echo_e "${RED}共享 PG 模式需要指定 DB_PG_CONTAINER 环境变量${NC}"
        exit 1
    fi
    PG_SUPERUSER=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$DB_PG_CONTAINER" 2>/dev/null | grep '^POSTGRES_USER=' | cut -d= -f2)
    PG_SUPERUSER="${PG_SUPERUSER:-postgres}"
    PG_PASSWORD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 16)
    docker exec "$DB_PG_CONTAINER" psql -U "$PG_SUPERUSER" -c "CREATE USER gift_user WITH PASSWORD '$PG_PASSWORD';" 2>/dev/null || true
    docker exec "$DB_PG_CONTAINER" psql -U "$PG_SUPERUSER" -c "CREATE DATABASE gift_bookkeeping OWNER gift_user;" 2>/dev/null || true
    docker exec "$DB_PG_CONTAINER" psql -U "$PG_SUPERUSER" -c "GRANT ALL ON DATABASE gift_bookkeeping TO gift_user;" 2>/dev/null || true
    PG_HOST_PORT=$(docker inspect --format '{{range $p, $conf := .NetworkSettings.Ports}}{{range $conf}}{{.HostPort}} {{end}}{{end}}' "$DB_PG_CONTAINER" 2>/dev/null | awk '{print $1}')
    PG_HOST_PORT="${PG_HOST_PORT:-5432}"
    DATABASE_URL="postgresql://gift_user:${PG_PASSWORD}@127.0.0.1:${PG_HOST_PORT}/gift_bookkeeping"
    export DATABASE_URL
    echo_e "${GREEN}数据库模式: 共享 PostgreSQL (${DB_PG_CONTAINER}, 端口 ${PG_HOST_PORT})${NC}"
}

# 配置独立 PostgreSQL 模式（传统版：docker run -d 启动独立容器）
setup_independent_pg() {
    if [ -z "$PG_LOCAL_IMAGE" ]; then
        echo_e "${YELLOW}本地未找到 PostgreSQL 镜像。${NC}"
        if [ -t 0 ]; then
            printf '是否允许下载 postgres:16-alpine (约40MB)? (y/n) [默认 n]: ' >&2
            read -r _dl_answer
            case "$_dl_answer" in
                y|Y|yes|YES) PG_LOCAL_IMAGE="postgres:16-alpine" ;;
                *) echo_e "${YELLOW}用户取消下载，降级为 SQLite 模式${NC}"; DB_MODE=sqlite; setup_sqlite; return ;;
            esac
        else
            echo_e "${YELLOW}非交互环境无法下载，降级为 SQLite 模式${NC}"
            DB_MODE=sqlite; setup_sqlite; return
        fi
    fi
    PG_PASSWORD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 16)
    PG_CONTAINER_NAME="${PROJECT_NAME}-pg"
    PG_HOST_PORT=15432
    while lsof -ti :$PG_HOST_PORT > /dev/null 2>&1; do
        PG_HOST_PORT=$((PG_HOST_PORT + 1))
    done
    docker rm -f "$PG_CONTAINER_NAME" 2>/dev/null || true
    echo_e "${GREEN}正在启动独立 PostgreSQL 容器 (${PG_LOCAL_IMAGE})...${NC}"
    docker run -d \
        --name "$PG_CONTAINER_NAME" \
        -e POSTGRES_DB=gift_bookkeeping \
        -e POSTGRES_USER=gift_user \
        -e POSTGRES_PASSWORD="$PG_PASSWORD" \
        -p "127.0.0.1:${PG_HOST_PORT}:5432" \
        -v "${PROJECT_NAME}_pg_data:/var/lib/postgresql/data" \
        "$PG_LOCAL_IMAGE" > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo_e "${RED}独立 PG 容器启动失败，降级为 SQLite 模式${NC}"
        DB_MODE=sqlite; setup_sqlite; return
    fi
    echo_e "${YELLOW}等待 PostgreSQL 就绪...${NC}"
    _pg_wait=0
    while [ $_pg_wait -lt 30 ]; do
        if docker exec "$PG_CONTAINER_NAME" pg_isready -U gift_user > /dev/null 2>&1; then
            break
        fi
        sleep 1
        _pg_wait=$((_pg_wait + 1))
    done
    DATABASE_URL="postgresql://gift_user:${PG_PASSWORD}@127.0.0.1:${PG_HOST_PORT}/gift_bookkeeping"
    export DATABASE_URL
    echo_e "${GREEN}数据库模式: 独立 PostgreSQL (${PG_CONTAINER_NAME}, 端口 ${PG_HOST_PORT})${NC}"
}
