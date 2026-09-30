#!/bin/sh
# db_setup.sh (传统版) — 数据库模式配置函数（SQLite/共享PG/独立PG，通过环境变量传递 DATABASE_URL）

# 配置 SQLite 模式
setup_sqlite() {
    DATABASE_URL=""
    export DATABASE_URL
    echo_e "${GREEN}数据库模式: SQLite 本地文件${NC}"
}

# V10.10.20: 首次部署仅就绪 data/ 目录（不再复制样例库）
# 背景：全新 clone 后 data/ 目录不存在。为确保运行库位于 data/ 且初次部署即为
#       纯净空库 + 单一管理员（与 Docker 版行为一致），仅创建 data/ 目录；
#       库文件由 app.py 首次启动 init_database() 自动全新建库。
#       仓库根目录样例库仅作开发/演示参考，不再参与运行。
# 已有运行库时不做任何改动（幂等，不影响存量部署）。
ensure_sqlite_runtime_db() {
    _rt_dir="$APP_DIR/data"
    _rt_db="$_rt_dir/gift_bookkeeping.db"
    if [ ! -f "$_rt_db" ]; then
        mkdir -p "$_rt_dir" || {
            echo_e "${RED}❌ 创建数据目录 $_rt_dir 失败，请检查目录权限${NC}"
            return 1
        }
        echo_e "${GREEN}✅ 首次部署：data/ 目录已就绪，应用启动将自动创建纯净空库（仅初始管理员）${NC}"
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
# V10.10.20: 智能匹配 PG 镜像数据目录挂载路径（PostgreSQL 18+/pgvector:pg18 → /var/lib/postgresql；15/16/14 及 alpine → /var/lib/postgresql/data）
detect_pg_data_dir() {
    case "$1" in
        *18*|*pg18*) echo "/var/lib/postgresql" ;;
        *15*|*16*|*14*|*alpine*) echo "/var/lib/postgresql/data" ;;
        *) echo "/var/lib/postgresql" ;;
    esac
}

setup_independent_pg() {
    # V10.10.20: 镜像优先级链 —— PG_IMAGE（用户自定义）> 本地已存在镜像（detect_pg_environment）> 默认镜像自动下载（postgres:16-alpine）
    if [ -n "$PG_IMAGE" ]; then
        PG_LOCAL_IMAGE="$PG_IMAGE"
        echo_e "${GREEN} 使用用户自定义 PG 镜像: ${PG_LOCAL_IMAGE}${NC}"
    fi
    if [ -z "$PG_LOCAL_IMAGE" ]; then
        echo_e "${YELLOW}  本地未检测到 PostgreSQL 镜像，自动下载内置默认镜像 postgres:16-alpine ...${NC}"
        PG_LOCAL_IMAGE="postgres:16-alpine"
        if ! docker pull "$PG_LOCAL_IMAGE"; then
            echo_e "${RED}❌ 默认 PG 镜像下载失败，请检查网络，或改用 PG_IMAGE 指定自定义镜像后重试；降级为 SQLite 模式${NC}"
            DB_MODE=sqlite; setup_sqlite; return
        fi
        echo_e "${GREEN}✅ 默认镜像已下载: ${PG_LOCAL_IMAGE}${NC}"
    fi
    PG_PASSWORD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 16)
    PG_CONTAINER_NAME="${PROJECT_NAME}-pg"
    # V10.10.20: 按镜像智能匹配数据目录挂载路径（防止 PG18+ 镜像挂错路径导致数据不落卷）
    PG_DATA_DIR=$(detect_pg_data_dir "$PG_LOCAL_IMAGE")
    PG_HOST_PORT=15432
    while lsof -ti :$PG_HOST_PORT > /dev/null 2>&1; do
        PG_HOST_PORT=$((PG_HOST_PORT + 1))
    done
    docker rm -f "$PG_CONTAINER_NAME" 2>/dev/null || true
    echo_e "${GREEN}正在启动独立 PostgreSQL 容器 (${PG_LOCAL_IMAGE}，挂载 ${PG_DATA_DIR})...${NC}"
    docker run -d \
        --name "$PG_CONTAINER_NAME" \
        -e POSTGRES_DB=gift_bookkeeping \
        -e POSTGRES_USER=gift_user \
        -e POSTGRES_PASSWORD="$PG_PASSWORD" \
        -p "127.0.0.1:${PG_HOST_PORT}:5432" \
        -v "${PROJECT_NAME}_pg_data:${PG_DATA_DIR}" \
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
