#!/bin/sh
# nginx_config.sh (传统版) — Nginx SNI 反向代理配置渲染（__BACKEND_PORT__ 替换为 $PORT）

setup_nginx_config() {
    if [ -z "$SNI_DOMAIN" ]; then
        echo_e "${RED}错误: SNI_DOMAIN 为空，无法配置 Nginx SNI 分流，已中止。请通过环境变量指定，例如: SNI_DOMAIN=gift.example.com PROJECT_NAME=gift_app ./$0 start${NC}"
        return 1
    fi

    if [ ! -d "$NGINX_CONF_DIR" ]; then
        echo_e "${RED}错误: Nginx 配置目录不存在: $NGINX_CONF_DIR${NC}"
        echo_e "${YELLOW}请手动创建该目录后重试: sudo mkdir -p $NGINX_CONF_DIR${NC}"
        echo_e "${YELLOW}（其他部署环境如使用 /etc/nginx/conf.d，可通过环境变量覆盖: export NGINX_CONF_DIR=/etc/nginx/conf.d）${NC}"
        return 1
    fi

    if [ -d "$NGINX_CONF_DIR" ]; then
        echo_e "${GREEN}正在处理 Nginx 配置文件 ($NGINX_CONF_DIR)...${NC}"
        local target_conf="$NGINX_CONF_DIR/$PROJECT_NAME.conf"
        if [ "$SNI_DEFAULT_SERVER" = "1" ]; then
            for f in "$NGINX_CONF_DIR"/*.conf; do
                [ -f "$f" ] || continue
                [ "$f" = "$target_conf" ] && continue
                if grep -q "default_server" "$f" 2>/dev/null; then
                    echo_e "${YELLOW}⚠️ 检测到 $(basename "$f") 已设为 default_server，本项目将自动改为非兜底模式${NC}"
                    SNI_DEFAULT_SERVER=0
                    break
                fi
            done
        fi
        if [ -f "$target_conf" ] && ! should_overwrite "$target_conf" "$NGINX_CONF_FORCE_UPDATE" "NGINX_CONF_FORCE_UPDATE"; then
            echo_e "${YELLOW}保留现有 Nginx 配置文件，未重新渲染: $target_conf${NC}"
        elif [ -f "$APP_DIR/nginx_ssl.conf" ]; then
            local listen_value="$NGINX_PORT"
            local default_flag="否"
            if [ "$SNI_DEFAULT_SERVER" = "1" ]; then
                listen_value="${NGINX_PORT} default_server"
                default_flag="是"
            fi
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
