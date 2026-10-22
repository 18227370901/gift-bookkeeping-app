#!/bin/sh

# ============================================================
# run.sh (传统版) — 模块加载与命令分发（V10.10.21 瘦身：399 → 约 40 行；V10.11.33 参数解析扩展）
# 自定义配置: bin/config.sh（账密/端口/SNI/PG 默认值；支持 bin/config.local.sh 服务器专属覆盖，不入库）
# Python 环境: bin/python_env.sh | 启停操作: bin/service.sh | 帮助文本: bin/help.sh
# 用法: ./run.sh {start|stop|status|restart|clean}
#       ./run.sh {start|restart} --reconfig      重选数据库模式后执行
#       ./run.sh {start|restart} --reconfig-db   同上（完整别名）
#       ./run.sh {start|restart} --unattended    无人值守模式（等价 UNATTENDED=1，定时任务/cron 场景）
#       ./run.sh {start|restart} --reconfig --unattended   组合：重选数据库模式 + 无人值守
# 无人值守语义：证书/Nginx 覆盖询问、数据库菜单、端口冲突处理一律使用默认参数，不阻塞等待输入；
# 数据库沿用 .temp/.db.env 已持久化的用户选择（无配置时默认 SQLite）；显式环境变量策略仍优先
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

# V10.10.23: --reconfig / --reconfig-db 后缀参数解析（替代 DB_RESET=1 环境变量，更直观）
# V10.11.33: 新增 --unattended（等价 UNATTENDED=1 环境变量）；$2/$3 支持任意顺序组合
# 用法: ./run.sh restart --reconfig 或 ./run.sh restart --unattended 或 ./run.sh restart --reconfig --unattended
# $1=子命令，$2/$3 可选参数；DB_RESET=1 / UNATTENDED=1 环境变量仍保留兼容（cron/CI 场景）
for _arg in "$2" "$3"; do
    [ -n "$_arg" ] || continue
    case "$_arg" in
        --reconfig|--reconfig-db)
            DB_RESET=1
            ;;
        --unattended)
            UNATTENDED=1
            ;;
        *)
            echo "错误: 未知参数 '$_arg'"
            echo "可用参数: --reconfig, --reconfig-db, --unattended"
            echo "用法: ./$(basename "$0") {start|restart} [--reconfig] [--unattended]"
            exit 1
            ;;
    esac
done

case "$1" in
    start) start_service ;;
    stop) stop_service ;;
    status) status_service ;;
    restart) restart_service ;;
    clean) cleanup_cache ;;
    *) show_help; exit 1 ;;
esac

exit 0
