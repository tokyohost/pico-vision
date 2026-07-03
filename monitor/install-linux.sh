#!/bin/sh
# 为主流 systemd Linux 发行版安装 Pico Monitor 通用版本。
set -eu

INSTALL_ROOT="/opt/pico-monitor"
COMMAND_PATH="/usr/local/bin/pico-monitor"
SERVICE_PATH="/etc/systemd/system/pico-monitor.service"
CONFIG_PATH="/etc/pico-monitor.conf"

# 检查安装过程是否具有系统目录写入权限。
require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "请使用 sudo 运行本安装脚本。" >&2
        exit 1
    fi
}

# 根据当前发行版安装 Python、虚拟环境和 Ping 工具。
install_system_dependencies() {
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update
        apt-get install -y python3 python3-venv iputils-ping
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3 python3-pip iputils
    elif command -v zypper >/dev/null 2>&1; then
        zypper --non-interactive install python3 python3-pip iputils
    elif command -v pacman >/dev/null 2>&1; then
        pacman -Sy --needed --noconfirm python python-pip iputils
    else
        echo "未识别包管理器，请先安装 Python 3、venv、pip 和 ping。" >&2
    fi
}

# 安装程序文件并在独立虚拟环境中部署 Python 依赖。
install_application() {
    script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
    install -d -m 0755 "$INSTALL_ROOT"
    install -m 0644 "$script_directory/pico_monitor.py" "$INSTALL_ROOT/"
    install -m 0644 "$script_directory/pico_client.py" "$INSTALL_ROOT/"
    install -m 0644 "$script_directory/qbittorrent_monitor.py" "$INSTALL_ROOT/"
    install -m 0644 "$script_directory/system_monitor.py" "$INSTALL_ROOT/"
    install -m 0644 "$script_directory/requirements.txt" "$INSTALL_ROOT/"
    python3 -m venv "$INSTALL_ROOT/venv"
    "$INSTALL_ROOT/venv/bin/python" -m pip install --upgrade pip
    "$INSTALL_ROOT/venv/bin/python" -m pip install -r "$INSTALL_ROOT/requirements.txt"
    install -m 0755 "$script_directory/packaging/pico-monitor-generic" "$COMMAND_PATH"
}

# 安装配置和 systemd 服务，并立即启用监控程序。
install_service() {
    script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
    if [ ! -f "$CONFIG_PATH" ]; then
        install -m 0644 "$script_directory/debian/pico-monitor.conf" "$CONFIG_PATH"
    fi
    install -m 0644 "$script_directory/packaging/pico-monitor-generic.service" "$SERVICE_PATH"
    systemctl daemon-reload
    systemctl enable --now pico-monitor.service
}

require_root
install_system_dependencies
install_application
install_service
echo "Pico Monitor 安装完成，可运行：systemctl status pico-monitor"
