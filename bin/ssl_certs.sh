#!/bin/sh
# ssl_certs.sh (传统版) — SSL 证书自动生成（优先使用 venv 中的 python3）

ensure_ssl_certs() {
    if [ ! -f "$SSL_CERT" ] && [ ! -f "$SSL_KEY" ]; then
        echo_e "${GREEN}未检测到 SSL 证书文件，正在生成自签名证书 (域名: $SNI_DOMAIN)...${NC}"
        mkdir -p "$APP_DIR/ssl"
        local cert_script="$APP_DIR/generate_ssl_certs.py"
        if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/python3" ]; then
            (cd "$APP_DIR" && "$VENV_DIR/bin/python3" "$cert_script" --domain "$SNI_DOMAIN")
        elif command -v python3 > /dev/null 2>&1; then
            (cd "$APP_DIR" && python3 "$cert_script" --domain "$SNI_DOMAIN")
        else
            echo_e "${RED}警告: 未找到 python3，无法自动生成证书，请手动生成或准备 $SSL_CERT 和 $SSL_KEY${NC}"
        fi
    elif should_overwrite "$SSL_CERT" "$SSL_FORCE_UPDATE" "SSL_FORCE_UPDATE"; then
        echo_e "${GREEN}确认更新，正在重新生成 SSL 自签名证书 (域名: $SNI_DOMAIN)...${NC}"
        mkdir -p "$APP_DIR/ssl"
        local cert_script="$APP_DIR/generate_ssl_certs.py"
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
