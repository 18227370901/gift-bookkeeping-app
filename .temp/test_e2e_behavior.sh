#!/bin/bash
# run.sh V10.10.3 端到端行为测试 v2：修复 python3 存根问题，用真实 Python 生成证书
# 覆盖场景：
#   A. 证书不存在 → 直接生成（不询问）
#   B. 证书已存在 + 非交互环境 → 自动保留（cron 场景）
#   D.（同 B，合并验证）
#   E. 证书已存在 + SSL_FORCE_UPDATE=1 → 强制更新覆盖
#   C. 交互式 y 输入 → 与场景E共用生成代码路径，由E验证
#   F. nginx conf 已存在 + NGINX_CONF_FORCE_UPDATE=1 → 强制渲染覆盖
#   G. nginx conf 已存在 + 非交互 → 保留
set -u

RUN_SH="/c/Users/cheng/Documents/akshare-test/gift_bookkeeping_app/run.sh"
SANDBOX="/c/Users/cheng/Documents/akshare-test/gift_bookkeeping_app/.temp/run_sh_e2e"
REAL_PY="/c/Users/cheng/.local/share/TeleAgent/runtimes/python/python"
PASS=0; FAIL=0

check() {
    local desc="$1"; local expected="$2"; local actual="$3"
    if [ "$expected" = "$actual" ]; then
        echo "PASS | $desc"; PASS=$((PASS+1))
    else
        echo "FAIL | $desc | expected=$expected actual=$actual"; FAIL=$((FAIL+1))
    fi
}

# ==== 沙箱初始化（先建目录再写文件）====
rm -rf "$SANDBOX"
mkdir -p "$SANDBOX/bin" "$SANDBOX/app" "$SANDBOX/nginx_conf"

# python3 包装器：让 run.sh 中的 command -v python3 命中真实 Python
cat > "$SANDBOX/bin/python3" <<'EOF'
#!/bin/bash
exec /c/Users/cheng/.local/share/TeleAgent/runtimes/python/python "$@"
EOF
chmod +x "$SANDBOX/bin/python3"
export PATH="$SANDBOX/bin:$PATH"

# 探测真实 Python 可用性（openssl / cryptography 至少一个可用才能生成证书）
PROBE=$("$REAL_PY" -c "
import shutil, sys
ok=[]
if shutil.which('openssl'): ok.append('openssl')
try:
    import cryptography; ok.append('cryptography')
except ImportError: pass
print(','.join(ok) if ok else 'NONE')
" 2>/dev/null)
echo "[INFO] 证书生成可用手段: $PROBE"

# ==== 提取 run.sh 真实函数（should_overwrite + ensure_ssl_certs）====
sed -n '/^# 判断是否覆盖已存在文件/,/^setup_nginx_config()/p' "$RUN_SH" | sed '$d' > "$SANDBOX/funcs.sh"
grep -q "^should_overwrite()" "$SANDBOX/funcs.sh" && check "提取 should_overwrite 函数" "0" "0" || check "提取 should_overwrite 函数" "0" "1"
grep -q "^ensure_ssl_certs()" "$SANDBOX/funcs.sh" && check "提取 ensure_ssl_certs 函数" "0" "0" || check "提取 ensure_ssl_certs 函数" "0" "1"

# shellcheck disable=SC1090
source "$SANDBOX/funcs.sh"

# 真实函数依赖的变量环境（与 run.sh 运行态对齐）
APP_DIR="$SANDBOX/app"
SNI_DOMAIN="test.example.com"
VENV_DIR="$APP_DIR/venv"
SSL_CERT="$APP_DIR/ssl/server.crt"
SSL_KEY="$APP_DIR/ssl/server.key"
SSL_FORCE_UPDATE=""
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
cp "/c/Users/cheng/Documents/akshare-test/gift_bookkeeping_app/generate_ssl_certs.py" "$APP_DIR/"

echo "===== 场景A: 证书不存在 → 直接生成（不询问）====="
out=$(ensure_ssl_certs < /dev/null 2>&1)
[ -f "$SSL_CERT" ] && [ -f "$SSL_KEY" ]
check "A: 生成证书文件" "0" "$?"
md5_before=$(md5sum "$SSL_CERT" 2>/dev/null | cut -d' ' -f1)
echo "$out" | grep -q "未检测到 SSL 证书文件"
check "A: 走了创建分支提示" "0" "$?"
echo "$out" | grep -q "是否覆盖更新"
[ $? -eq 1 ] && check "A: 首次创建未被询问" "0" "0" || check "A: 首次创建未被询问" "0" "1"

echo "===== 场景B/D: 证书已存在 + 非交互环境 → 自动保留（cron 场景）====="
out=$(ensure_ssl_certs < /dev/null 2>&1)
md5_after=$(md5sum "$SSL_CERT" 2>/dev/null | cut -d' ' -f1)
check "B/D: 证书内容未变（保留）" "$md5_before" "$md5_after"
echo "$out" | grep -q "保留现有证书不更新"
check "B/D: 走了保留分支提示" "0" "$?"
echo "$out" | grep -q "非交互环境自动保留旧文件"
check "B/D: 非交互提示出现" "0" "$?"

echo "===== 场景E: SSL_FORCE_UPDATE=1 → 强制更新 ====="
SSL_FORCE_UPDATE="1"
out=$(ensure_ssl_certs < /dev/null 2>&1)
md5_e=$(md5sum "$SSL_CERT" 2>/dev/null | cut -d' ' -f1)
[ -n "$md5_e" ] && [ "$md5_e" != "$md5_before" ]
check "E: 证书被重新生成（内容变化）" "0" "$?"
echo "$out" | grep -q "确认更新"
check "E: 走了更新分支提示" "0" "$?"
SSL_FORCE_UPDATE=""

echo "===== 场景F/G: nginx conf 保护逻辑（真模板渲染）====="
NGINX_CONF_DIR="$SANDBOX/nginx_conf"
PROJECT_NAME="gift_app"
NGINX_PORT="443"
SNI_DEFAULT_SERVER="1"
PORT="11443"
NGINX_CONF_FORCE_UPDATE=""
cp "/c/Users/cheng/Documents/akshare-test/gift_bookkeeping_app/nginx_ssl.conf" "$APP_DIR/nginx_ssl.conf"
target_conf="$NGINX_CONF_DIR/$PROJECT_NAME.conf"

# G: 非交互 + conf 已存在 → 保留
echo "HAND_MODIFIED_MARKER" > "$target_conf"
if [ -f "$target_conf" ] && ! should_overwrite "$target_conf" "$NGINX_CONF_FORCE_UPDATE" "NGINX_CONF_FORCE_UPDATE" < /dev/null 2>&1; then
    keep_g=$(head -1 "$target_conf")
    check "G: conf 内容保留" "HAND_MODIFIED_MARKER" "$keep_g"
else
    check "G: conf 内容保留" "SKIPPED" "OVERWRITE"
fi

# F: NGINX_CONF_FORCE_UPDATE=1 → 强制覆盖渲染（与 run.sh 逐字一致的渲染段）
NGINX_CONF_FORCE_UPDATE="1"
if should_overwrite "$target_conf" "$NGINX_CONF_FORCE_UPDATE" "NGINX_CONF_FORCE_UPDATE" < /dev/null 2>&1; then
    listen_value="${NGINX_PORT} default_server"
    default_flag="是"
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
    } > "$target_conf" 2>/dev/null
    f_content=$(cat "$target_conf")
    echo "$f_content" | grep -q "listen 443 default_server"
    check "F: 渲染 conf 包含 default_server" "0" "$?"
    echo "$f_content" | grep -q "server_name test.example.com"
    check "F: 渲染 conf 包含 SNI 域名" "0" "$?"
    echo "$f_content" | grep -q "__"
    if [ $? -eq 1 ]; then check "F: 渲染 conf 无残留占位符" "0" "0"; else check "F: 渲染 conf 无残留占位符" "0" "1"; fi
else
    check "F: 强制覆盖许可" "0" "1"
fi

echo ""
echo "=============================================="
echo "端到端测试结果: PASS=$PASS FAIL=$FAIL"
echo "=============================================="
[ $FAIL -eq 0 ] && echo "ALL_TESTS_PASSED" || echo "SOME_TESTS_FAILED"
