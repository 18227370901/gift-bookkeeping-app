#!/bin/sh
# port_conflict.sh (传统版) — PID 状态检查 + 端口冲突检测（含 PID 自检）

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

# 检测端口是否被占用，被占用时提示用户选择处理方式
check_port_conflict() {
    local check_port="$1"
    local port_pid=$(lsof -ti :"$check_port" 2>/dev/null)

    if [ -z "$port_pid" ]; then
        return 0  # 端口空闲，可正常启动
    fi

    # 端口被占用，判断是否为自身服务（PID 文件匹配）
    if [ -f "$PID_FILE" ]; then
        local my_pid=$(cat "$PID_FILE")
        if [ "$port_pid" = "$my_pid" ]; then
            return 0  # 是自己的进程，正常
        fi
    fi

    local proc_info=$(ps -p "$port_pid" -o cmd= 2>/dev/null | head -c 200)
    echo_e "${RED}❌ 端口 $check_port 已被占用！${NC}"
    echo_e "   占用进程 PID: $port_pid"
    echo_e "   进程信息: $proc_info"

    if [ ! -t 0 ]; then
        echo_e "${RED}非交互环境无法选择，服务启动中止。请更换端口后重试。${NC}"
        echo_e "   传统版: PORT=新端口 ./$0 start"
        echo_e "   Docker版: HOST_PORT=新端口 ./$0 start"
        return 1
    fi

    while true; do
        echo_e "${YELLOW}请选择处理方式：${NC}"
        echo_e "  1) 修改本服务端口后重新启动（推荐）"
        echo_e "  2) 停用另一个服务的 Nginx 配置后继续"
        echo_e "  3) 中止启动"
        printf '请输入选项 [1/2/3]: '
        read -r choice
        case "$choice" in
            1)
                echo_e "${GREEN}请修改端口后重新启动：${NC}"
                echo_e "   传统版: PORT=新端口 ./$0 start"
                echo_e "   Docker版: HOST_PORT=新端口 ./$0 start"
                return 1
                ;;
            2)
                echo_e "${YELLOW}当前 $NGINX_CONF_DIR 中的 Nginx 配置文件：${NC}"
                local conf_files=$(ls "$NGINX_CONF_DIR"/*.conf 2>/dev/null)
                if [ -z "$conf_files" ]; then
                    echo_e "${RED}未找到任何 .conf 配置文件${NC}"
                    return 1
                fi
                local ci=1
                for f in $conf_files; do
                    echo_e "  $ci) $(basename "$f")"
                    ci=$((ci + 1))
                done
                printf '请输入要停用的配置编号: '
                read -r conf_choice
                local selected=$(echo "$conf_files" | sed -n "${conf_choice}p")
                if [ -n "$selected" ]; then
                    mv "$selected" "${selected}.disabled" 2>/dev/null
                    echo_e "${GREEN}已停用: $(basename "$selected")${NC}"
                    if command -v nginx > /dev/null 2>&1; then
                        if nginx -t >/dev/null 2>&1; then
                            nginx -s reload 2>/dev/null || systemctl reload nginx 2>/dev/null
                        fi
                    fi
                    local recheck_pid=$(lsof -ti :"$check_port" 2>/dev/null)
                    if [ -n "$recheck_pid" ]; then
                        echo_e "${RED}停用 Nginx 配置后端口 $check_port 仍被占用，可能后端进程仍在运行${NC}"
                        echo_e "   请手动停止占用端口的进程: kill $recheck_pid"
                        return 1
                    fi
                    return 0
                else
                    echo_e "${RED}无效的选择${NC}"
                    return 1
                fi
                ;;
            3)
                echo_e "${YELLOW}已中止启动${NC}"
                return 1
                ;;
            *)
                echo_e "${RED}无效选项，请重新选择${NC}"
                ;;
        esac
    done
}
