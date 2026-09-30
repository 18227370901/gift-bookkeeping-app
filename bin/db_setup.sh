#!/bin/sh
# db_setup.sh (传统版) — 数据库模式配置函数（SQLite/共享PG/独立PG，通过环境变量传递 DATABASE_URL）
# V10.10.22: ALTER USER 密码同步改为可靠模式（不再静默吞错），独立 PG 容器就绪后强制 ALTER USER

# V10.10.22: 可靠的 PG 密码同步（ALTER USER），两种连接方式兑底
# 入参 $1: 容器名, $2: 超级用户名（可选，默认 postgres）, $3: 目标用户, $4: 新密码
# 返回 0=成功 1=失败
pg_sync_password() {
    _psc="$1"
    _pss="${2:-postgres}"
    _psu="$3"
    _psp="$4"
    # 方式 1: 通过本地 socket + 超级用户（Docker 默认 trust 认证）
    if docker exec "$_psc" psql -U "$_pss" -tAc "SELECT 1" >/dev/null 2>&1; then
        docker exec "$_psc" psql -U "$_pss" -c "ALTER USER $_psu WITH PASSWORD '$_psp';" >/dev/null 2>&1
        return $?
    fi
    # 方式 2: 通过 OS 级 peer 认证（docker exec -u postgres，无需密码）
    if docker exec -u postgres "$_psc" psql -tAc "SELECT 1" >/dev/null 2>&1; then
        docker exec -u postgres "$_psc" psql -c "ALTER USER $_psu WITH PASSWORD '$_psp';" >/dev/null 2>&1
        return $?
    fi
    echo_e "${RED}❌ ALTER USER 密码同步失败：无法连接容器 $_psc 的 PostgreSQL（尝试了超级用户 $_pss 与 peer 认证）${NC}"
    return 1
}

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
    # V10.10.20: 连接参数解析（PG_USER/PG_PASSWORD/PG_DB 可自定义，未指定用默认值）
    resolve_pg_conn_params
    # 幂等创建/更新账号与库（已有部署时 ALTER 同步密码、保留数据）
    # V10.10.22: ALTER USER 不再静默吞错——失败则报错终止，避免 DATABASE_URL 密码与 PG 实际密码不匹配
    if docker exec "$DB_PG_CONTAINER" psql -U "$PG_SUPERUSER" -tAc "SELECT 1 FROM pg_roles WHERE rolname='$PG_USER'" 2>/dev/null | grep -q 1; then
        if ! pg_sync_password "$DB_PG_CONTAINER" "$PG_SUPERUSER" "$PG_USER" "$PG_PASSWORD"; then
            echo_e "${RED}❌ 共享 PG 密码同步失败，请检查容器 $DB_PG_CONTAINER 的超级用户权限${NC}"
            return 1
        fi
    else
        docker exec "$DB_PG_CONTAINER" psql -U "$PG_SUPERUSER" -c "CREATE USER $PG_USER WITH PASSWORD '$PG_PASSWORD';" >/dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo_e "${RED}❌ CREATE USER $PG_USER 失败，请检查容器 $DB_PG_CONTAINER 的超级用户权限${NC}"
            return 1
        fi
    fi
    docker exec "$DB_PG_CONTAINER" psql -U "$PG_SUPERUSER" -tAc "SELECT 1 FROM pg_database WHERE datname='$PG_DB'" 2>/dev/null | grep -q 1 || \
        docker exec "$DB_PG_CONTAINER" psql -U "$PG_SUPERUSER" -c "CREATE DATABASE $PG_DB OWNER $PG_USER;" >/dev/null 2>&1 || true
    docker exec "$DB_PG_CONTAINER" psql -U "$PG_SUPERUSER" -c "GRANT ALL ON DATABASE $PG_DB TO $PG_USER;" >/dev/null 2>&1 || true
    # V10.10.20: PG_PORT 可自定义宿主机连接端口（优先于容器端口映射自动检测；默认 PG_PORT_DEFAULT，定义于 bin/config.sh）
    if [ -n "${PG_PORT:-}" ]; then
        PG_HOST_PORT="$PG_PORT"
    else
        PG_HOST_PORT=$(docker inspect --format '{{range $p, $conf := .NetworkSettings.Ports}}{{range $conf}}{{.HostPort}} {{end}}{{end}}' "$DB_PG_CONTAINER" 2>/dev/null | awk '{print $1}')
        PG_HOST_PORT="${PG_HOST_PORT:-$PG_PORT_DEFAULT}"
    fi
    DATABASE_URL="postgresql://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_HOST_PORT}/${PG_DB}"
    export DATABASE_URL
    echo_e "${GREEN}数据库模式: 共享 PostgreSQL (${DB_PG_CONTAINER}, 端口 ${PG_HOST_PORT}, 库 ${PG_DB}/账号 ${PG_USER})${NC}"
}

# V10.10.20: PG 连接参数解析（用户自定义 > 默认值；默认值集中定义于 bin/config.sh，V10.10.21 起）
# PG_USER/PG_PASSWORD/PG_DB 环境变量可自定义；未指定时使用默认值（PG_USER_DEFAULT / 随机 16 位 / PG_DB_DEFAULT）
# 密码校验：单引号/空格直接拒绝（无法安全拼入 SQL 与 URL）；URL 特殊字符警告
resolve_pg_conn_params() {
    PG_USER="${PG_USER:-$PG_USER_DEFAULT}"
    PG_DB="${PG_DB:-$PG_DB_DEFAULT}"
    if [ -z "$PG_PASSWORD" ]; then
        PG_PASSWORD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 16)
    else
        case "$PG_PASSWORD" in
            *\'*|*' '*)
                echo_e "${RED}❌ 自定义 PG_PASSWORD 含单引号或空格，无法安全用于数据库与连接 URL，请更换${NC}"
                exit 1
                ;;
            *@*|*:*|*/*|*#*|*\?*)
                echo_e "${YELLOW}⚠️ 自定义 PG_PASSWORD 含 URL 特殊字符（@ : / # ?），如遇连接失败请改用字母数字组合${NC}"
                ;;
        esac
    fi
    export PG_USER PG_PASSWORD PG_DB
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
        echo_e "${YELLOW}  本地未检测到 PostgreSQL 镜像，自动下载内置默认镜像 ${PG_IMAGE_DEFAULT:-postgres:16-alpine} ...${NC}"
        PG_LOCAL_IMAGE="${PG_IMAGE_DEFAULT:-postgres:16-alpine}"
        if ! docker pull "$PG_LOCAL_IMAGE"; then
            echo_e "${RED}❌ 默认 PG 镜像下载失败，请检查网络，或改用 PG_IMAGE 指定自定义镜像后重试；降级为 SQLite 模式${NC}"
            DB_MODE=sqlite; setup_sqlite; return
        fi
        echo_e "${GREEN}✅ 默认镜像已下载: ${PG_LOCAL_IMAGE}${NC}"
    fi
    # V10.10.20: 连接参数解析（PG_USER/PG_PASSWORD/PG_DB 可自定义，未指定用默认值）
    resolve_pg_conn_params
    PG_CONTAINER_NAME="${PROJECT_NAME}-pg"
    # V10.10.20: 按镜像智能匹配数据目录挂载路径（防止 PG18+ 镜像挂错路径导致数据不落卷）
    PG_DATA_DIR=$(detect_pg_data_dir "$PG_LOCAL_IMAGE")
    # V10.10.20: PG_PORT 可自定义宿主机映射端口（未指定时从 15432 起自动扫描可用端口）
    if [ -n "${PG_PORT:-}" ]; then
        PG_HOST_PORT="$PG_PORT"
    else
        PG_HOST_PORT=15432
        while lsof -ti :$PG_HOST_PORT > /dev/null 2>&1; do
            PG_HOST_PORT=$((PG_HOST_PORT + 1))
        done
    fi
    docker rm -f "$PG_CONTAINER_NAME" 2>/dev/null || true
    echo_e "${GREEN}正在启动独立 PostgreSQL 容器 (${PG_LOCAL_IMAGE}，挂载 ${PG_DATA_DIR}，库 ${PG_DB}/账号 ${PG_USER})...${NC}"
    docker run -d \
        --name "$PG_CONTAINER_NAME" \
        -e POSTGRES_DB="$PG_DB" \
        -e POSTGRES_USER="$PG_USER" \
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
        if docker exec "$PG_CONTAINER_NAME" pg_isready -U "$PG_USER" > /dev/null 2>&1; then
            break
        fi
        sleep 1
        _pg_wait=$((_pg_wait + 1))
    done
    DATABASE_URL="postgresql://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_HOST_PORT}/${PG_DB}"
    export DATABASE_URL
    echo_e "${GREEN}数据库模式: 独立 PostgreSQL (${PG_CONTAINER_NAME}, 端口 ${PG_HOST_PORT}, 库 ${PG_DB}/账号 ${PG_USER})...${NC}"
    # V10.10.22: 容器就绪后强制 ALTER USER 同步密码——
    # Docker 卷已存在时 POSTGRES_PASSWORD 环境变量被忽略（PG 只在首次初始化时读取），
    # 需 ALTER USER 兑底确保密码与 DATABASE_URL 一致
    if pg_sync_password "$PG_CONTAINER_NAME" "$PG_USER" "$PG_USER" "$PG_PASSWORD"; then
        echo_e "${GREEN}✅ 独立 PG 密码已同步${NC}"
    elif pg_sync_password "$PG_CONTAINER_NAME" "postgres" "$PG_USER" "$PG_PASSWORD"; then
        echo_e "${GREEN}✅ 独立 PG 密码已同步（via postgres 超级用户）${NC}"
    else
        echo_e "${YELLOW}⚠️ 独立 PG 密码同步未成功，如遇连接失败请手动检查容器 $PG_CONTAINER_NAME${NC}"
    fi
}
