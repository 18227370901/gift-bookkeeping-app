#!/bin/sh

# ============================================================
# run.sh (传统版) — 模块加载与命令分发（V10.10.21 瘦身；V10.11.34 定时任务 3 大场景优化升级）
# 自定义配置: bin/config.sh（账密/端口/SNI/PG 默认值；支持 bin/config.local.sh 服务器专属覆盖，不入库）
# Python 环境: bin/python_env.sh | 启停操作: bin/service.sh | 帮助文本: bin/help.sh
# 用法: ./run.sh {start|stop|status|restart|clean|add_nginx} [选项...]
# 定时任务 3 大场景:
#   ① 完全自适应: 0 3 * * * cd /opt/mengya-local && ./run.sh restart >> /var/log/cron.log 2>&1
#   ② 显式语义化: 0 3 * * * cd /opt/mengya-local && ./run.sh restart --cron >> /var/log/cron.log 2>&1
#   ③ 按需强制更新: 0 0 1 * * cd /opt/mengya-local && ./run.sh add_nginx --cron --renew-ssl >> /var/log/ssl.log 2>&1
# 可选参数: --cron (等价 --unattended), --renew-ssl, --renew-nginx, --reconfig (--reconfig-db)
# ============================================================

# ===== 加载 bin/ 模块（按依赖顺序） =====
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/bin/config.sh"         # ① 配置（必须最先，其余模块全部依赖这里的变量）
. "$SCRIPT_DIR/bin/common.sh"         # ② 彩色输出 + 文件覆盖决策
. "$SCRIPT_DIR/bin/cleanup.sh"        # ③ 缓存清理
. "$SCRIPT_DIR/bin/ssl_certs.sh"      # ④ SSL 证书
. "$SCRIPT_DIR/bin/nginx_config.sh"   # ⑤ Nginx SNI 配置
. "$SCRIPT_DIR/bin/port_conflict.sh"  # ⑥ 端口冲突检测 + 运行状态检查
. "$SCRIPT_DIR/bin/db_setup.sh"       # ⑦ 数据库模式函数（SQLite/共享PG/独立PG）
. "$SCRIPT_DIR/bin/db_select.sh"     # ⑧ 数据库选择（含 DB_ENV_FILE 定义与交互菜单）
. "$SCRIPT_DIR/bin/python_env.sh"    # ⑨ Python 环境保障（预检/pip 兜底/venv 依赖安装）
. "$SCRIPT_DIR/bin/service.sh"       # ⑩ 启停操作函数
. "$SCRIPT_DIR/bin/help.sh"          # ⑪ 帮助文本

# ===== 主逻辑 =====

SUBCOMMAND="${1:-}"
[ -n "$SUBCOMMAND" ] || { show_help; exit 1; }
shift

# V10.11.34: 多参数循环解析（支持 --cron, --unattended, --renew-ssl, --renew-nginx, --reconfig 任意组合）
# 用法示例: ./run.sh restart --cron
#           ./run.sh add_nginx --cron --renew-ssl
#           ./run.sh restart --reconfig --cron
while [ $# -gt 0 ]; do
    case "$1" in
        --cron|--unattended)
            UNATTENDED=1
            CRON=1
            ;;
        --renew-ssl|--ssl-renew)
            SSL_FORCE_UPDATE=1
            ;;
        --renew-nginx|--nginx-renew)
            NGINX_CONF_FORCE_UPDATE=1
            ;;
        --reconfig|--reconfig-db)
            DB_RESET=1
            ;;
        --local|--front-proxy)
            NGINX_BIND_IP="127.0.0.1"
            ;;
        --public)
            NGINX_BIND_IP=""
            ;;
        --nginx-port)
            shift
            [ $# -gt 0 ] || { echo "错误: --nginx-port 缺少端口参数"; exit 1; }
            NGINX_PORT="$1"
            ;;
        --nginx-port=*)
            NGINX_PORT="${1#*=}"
            ;;
        --bind-ip)
            shift
            [ $# -gt 0 ] || { echo "错误: --bind-ip 缺少 IP 参数"; exit 1; }
            NGINX_BIND_IP="$1"
            ;;
        --bind-ip=*)
            NGINX_BIND_IP="${1#*=}"
            ;;
        *)
            echo "错误: 未知参数 '$1'"
            echo "可用参数: --cron, --unattended, --renew-ssl, --renew-nginx, --reconfig, --local, --public, --nginx-port <端口>, --bind-ip <IP>"
            echo "用法: ./$(basename "$0") {start|stop|status|restart|clean|add_nginx} [选项...]"
            exit 1
            ;;
    esac
    shift
done

case "$SUBCOMMAND" in
    start) start_service ;;
    stop) stop_service ;;
    status) status_service ;;
    restart) restart_service ;;
    clean) cleanup_cache ;;
    add_nginx|setup_nginx) add_nginx_service ;;
    help|--help|-h) show_help ;;
    *) show_help; exit 1 ;;
esac

exit 0
