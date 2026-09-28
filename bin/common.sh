#!/bin/sh
# common.sh — 两版完全一致的公共函数（颜色输出 + 文件覆盖决策）
# 被 run.sh source，不要单独执行

# ===== 颜色输出 =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# POSIX 兼容的彩色输出函数（替代 echo -e，兼容 dash/sh）
echo_e() {
    printf '%b\n' "$*"
}

# ===== 判断是否覆盖已存在文件：交互环境弹 y/n 询问；非交互环境（cron/CI）不能卡死在 read，默认保留旧文件 =====
# 入参 $1: 已存在文件路径（提示语用）；$2: 对应策略环境变量当前值（1=强制覆盖 0=强制保留 空=询问）；$3: 策略变量名（非交互提示文案用）
# 返回值: 0=允许覆盖更新 1=保留旧文件不覆盖
should_overwrite() {
    local target_file="$1"
    local force_value="$2"
    local hint_var="$3"
    if [ "$force_value" = "1" ]; then
        return 0
    fi
    if [ "$force_value" = "0" ]; then
        return 1
    fi
    if [ ! -t 0 ]; then
        echo_e "${YELLOW}检测到已存在 $target_file，非交互环境自动保留旧文件（如需强制更新请设置 $hint_var=1）${NC}"
        return 1
    fi
    printf '检测到已存在 %s，是否覆盖更新? (y/n) [默认 n]: ' "$target_file" >&2
    read -r answer
    case "$answer" in
        y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}
