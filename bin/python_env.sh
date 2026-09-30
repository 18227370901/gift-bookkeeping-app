#!/bin/sh
# python_env.sh (传统版) — Python 环境保障（V10.10.21 自 run.sh 拆出）
# 职责：部署环境预检（python3 版本/venv 模块/常用工具）+ pip 镜像源自动兜底 + venv 创建与依赖安装
# 依赖：bin/config.sh（VENV_DIR/APP_DIR）、bin/common.sh（echo_e）

# V10.10.18: 部署环境预检（Python 版本 / venv 模块 / 常用工具提示）
preflight_check() {
    if ! command -v python3 > /dev/null 2>&1; then
        echo_e "${RED}❌ 环境预检失败：未找到 python3，请先安装 Python 3.8+${NC}"
        echo_e "${YELLOW}   Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip${NC}"
        return 1
    fi
    # 识别“命令存在但无法执行”的占位程序（如 Windows Microsoft Store 的 python3 存根）
    if ! python3 -c 'print("ok")' > /dev/null 2>&1; then
        echo_e "${RED}❌ 环境预检失败：python3 无法正常执行（可能为系统占位程序），请安装真正的 Python 3.8+${NC}"
        return 1
    fi
    _py_ok=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 8) else 0)' 2>/dev/null)
    if [ "$_py_ok" != "1" ]; then
        _py_ver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
        echo_e "${RED}❌ 环境预检失败：需要 Python 3.8+，当前版本为 ${_py_ver}，请升级 Python${NC}"
        return 1
    fi
    _py_ver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
    echo_e "${GREEN}✅ 环境预检通过：python3 $_py_ver${NC}"
    if ! python3 -c 'import venv' > /dev/null 2>&1; then
        echo_e "${YELLOW}⚠️ 预检提示：缺少 python3-venv 模块（Debian/Ubuntu: sudo apt install python3-venv），创建虚拟环境可能失败${NC}"
    fi
    if ! command -v lsof > /dev/null 2>&1; then
        echo_e "${YELLOW}⚠️ 预检提示：缺少 lsof（Debian/Ubuntu: sudo apt install lsof），端口占用检测与停止清理功能受限${NC}"
    fi
    return 0
}

# V10.10.18: pip 安装镜像源自动兜底（清华源 → 阿里云 → 官方源，任一成功即返回）
# 入参 $1: pip 子命令与参数（不含 -i 镜像参数）；$2 可选: requirements 文件路径（含空格路径安全）
pip_install_fb() {
    _pip_args="$1"
    _pip_req="${2:-}"
    _mirror_list="https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.aliyun.com/pypi/simple/ https://pypi.org/simple"
    _mi_total=$(echo $_mirror_list | wc -w)
    _mi_idx=0
    for _mirror in $_mirror_list; do
        _mi_idx=$((_mi_idx + 1))
        echo_e "${YELLOW}   使用 pip 源: ${_mirror}${NC}"
        if [ -n "$_pip_req" ]; then
            if "$VENV_DIR/bin/pip" $_pip_args -r "$_pip_req" -i "$_mirror"; then
                return 0
            fi
        else
            if "$VENV_DIR/bin/pip" $_pip_args -i "$_mirror"; then
                return 0
            fi
        fi
        # 仅在还有下一个镜像源时提示切换，最后一个源失败后直接汇总
        if [ "$_mi_idx" -lt "$_mi_total" ]; then
            echo_e "${YELLOW}   该源安装失败，自动切换下一个镜像源...${NC}"
        fi
    done
    echo_e "${RED}   三个镜像源均安装失败，请检查服务器网络连通性${NC}"
    return 1
}

# V10.10.21: venv 就绪 + 依赖检查/安装（自 start_service 抽取，幂等，可独立维护）
ensure_python_env() {
    # 自动创建虚拟环境及安装依赖库
    if [ ! -d "$VENV_DIR" ]; then
        echo_e "${YELLOW}检测到虚拟环境不存在，正在自动创建虚拟环境 $VENV_DIR ...${NC}"
        python3 -m venv "$VENV_DIR" || {
            echo_e "${RED}错误: 创建虚拟环境失败，请确认系统已安装 python3-venv${NC}"
            return 1
        }
    fi

    # 检查核心依赖库是否存在，若缺失则强制安装（V10.10.18：镜像源自动兜底 清华源→阿里云→官方源）
    # V10.10.22: 增加 pyzipper 检查——此前仅查 flask 四件套，老部署已装时 pip install 整体跳过，
    #            导致后加入 requirements.txt 的 pyzipper/cryptography/psycopg 等永远不被安装
    if ! "$VENV_DIR/bin/python3" -c "import flask, flask_sqlalchemy, flask_wtf, flask_login, pyzipper" >/dev/null 2>&1; then
        echo_e "${GREEN}正在检查/补全项目依赖库...${NC}"
        pip_install_fb "install --upgrade pip" || true
        if [ -f "$APP_DIR/requirements.txt" ]; then
            pip_install_fb "install" "$APP_DIR/requirements.txt" || {
                echo_e "${RED}错误: 依赖库安装失败（已依次尝试清华源/阿里源/官方源），请检查网络或 requirements.txt${NC}"
                return 1
            }
        else
            pip_install_fb "install flask flask-sqlalchemy flask-wtf flask-login" || {
                echo_e "${RED}错误: 依赖库安装失败（已依次尝试清华源/阿里云/官方源）${NC}"
                return 1
            }
        fi
        echo_e "${GREEN}✅ 依赖库检查/安装完成!${NC}"
    fi
    return 0
}
