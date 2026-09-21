#!/bin/bash
# Docker 版 run.sh V10.10.3 提取验证（函数与传统版逐字对齐性 + 非交互行为）
set -u
RUN_SH="/c/Users/cheng/Documents/akshare-test/gift_bookkeeping_app-docker/run.sh"
SANDBOX="/c/Users/cheng/Documents/akshare-test/gift_bookkeeping_app/.temp/run_sh_docker_e2e"
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

rm -rf "$SANDBOX"; mkdir -p "$SANDBOX/bin" "$SANDBOX/app"
cat > "$SANDBOX/bin/python3" <<'EOF'
#!/bin/bash
exec /c/Users/cheng/.local/share/TeleAgent/runtimes/python/python "$@"
EOF
chmod +x "$SANDBOX/bin/python3"
export PATH="$SANDBOX/bin:$PATH"

# 提取 Docker 版函数（should_overwrite 到 setup_nginx_config 前）
sed -n '/^# ===== 判断是否覆盖已存在文件/,/^# ===== 自动配置 Nginx/p' "$RUN_SH" | sed '$d' > "$SANDBOX/funcs.sh"
grep -q "^should_overwrite()" "$SANDBOX/funcs.sh" && check "Docker版: 提取 should_overwrite" "0" "0" || check "Docker版: 提取 should_overwrite" "0" "1"
grep -q "^ensure_ssl_certs()" "$SANDBOX/funcs.sh" && check "Docker版: 提取 ensure_ssl_certs" "0" "0" || check "Docker版: 提取 ensure_ssl_certs" "0" "1"

# 两版 should_overwrite 函数逐字一致性比对
TRAD_FUNC=$(sed -n '/^should_overwrite() {/,/^}/p' "/c/Users/cheng/Documents/akshare-test/gift_bookkeeping_app/run.sh")
DOCKER_FUNC=$(sed -n '/^should_overwrite() {/,/^}/p' "$RUN_SH")
[ "$TRAD_FUNC" = "$DOCKER_FUNC" ]
check "两版 should_overwrite 逐字一致" "0" "$?"

# 两版 should_overwrite 调用点参数一致性（证书部分）
TRAD_CALL=$(grep -o 'should_overwrite "\$SSL_CERT" "[^"]*" "[^"]*"' "/c/Users/cheng/Documents/akshare-test/gift_bookkeeping_app/run.sh")
DOCKER_CALL=$(grep -o 'should_overwrite "\$SSL_CERT" "[^"]*" "[^"]*"' "$RUN_SH")
[ "$TRAD_CALL" = "$DOCKER_CALL" ]
check "两版证书调用点一致" "0" "$?"

# shellcheck disable=SC1090
source "$SANDBOX/funcs.sh"
APP_DIR="$SANDBOX/app"
SNI_DOMAIN="docker.example.com"
SSL_CERT="$APP_DIR/ssl/server.crt"
SSL_KEY="$APP_DIR/ssl/server.key"
SSL_FORCE_UPDATE=""
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
cp "/c/Users/cheng/Documents/akshare-test/gift_bookkeeping_app-docker/generate_ssl_certs.py" "$APP_DIR/"

echo "===== Docker版场景A: 证书不存在 → 直接生成 ====="
out=$(ensure_ssl_certs < /dev/null 2>&1)
[ -f "$SSL_CERT" ] && [ -f "$SSL_KEY" ]
check "A: 生成证书文件" "0" "$?"

echo "===== Docker版场景B: 非交互 → 保留 ====="
md5_before=$(md5sum "$SSL_CERT" 2>/dev/null | cut -d' ' -f1)
out=$(ensure_ssl_certs < /dev/null 2>&1)
md5_after=$(md5sum "$SSL_CERT" 2>/dev/null | cut -d' ' -f1)
check "B: 证书内容未变" "$md5_before" "$md5_after"

echo "===== Docker版场景E: SSL_FORCE_UPDATE=1 → 强制更新 ====="
SSL_FORCE_UPDATE="1"
out=$(ensure_ssl_certs < /dev/null 2>&1)
md5_e=$(md5sum "$SSL_CERT" 2>/dev/null | cut -d' ' -f1)
[ -n "$md5_e" ] && [ "$md5_e" != "$md5_before" ]
check "E: 证书被重新生成" "0" "$?"

echo ""
echo "=============================================="
echo "Docker版验证结果: PASS=$PASS FAIL=$FAIL"
echo "=============================================="
[ $FAIL -eq 0 ] && echo "ALL_TESTS_PASSED" || echo "SOME_TESTS_FAILED"
