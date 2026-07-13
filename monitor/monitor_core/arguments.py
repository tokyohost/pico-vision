"""监控程序命令行参数定义与校验。"""

import argparse
import os

from .config import config_flag, config_value, load_monitor_config, parse_collection_task_intervals
from .console import MonitorVersionAction

def create_argument_parser(config=None):
    """创建监控程序统一命令行参数解析器。"""
    config = config or {}
    parser = argparse.ArgumentParser(description="Pico LCD 系统硬件监控程序")
    parser.add_argument(
        "--version",
        action=MonitorVersionAction,
        nargs=0,
        help="显示 Monitor 版本号并退出",
    )
    parser.add_argument("--config", default=None, help="YAML 配置文件路径，Linux 服务默认使用 /etc/pico-monitor.conf")
    parser.add_argument("--port", default=config_value(config, "PICO_MONITOR_PORT") or None, help="固定串口名称，留空时自动发现")
    parser.add_argument("--websocket-url", default=config_value(config, "PICO_MONITOR_WEBSOCKET_URL") or None, help="固定 WebSocket 地址，例如 ws://192.168.1.20:8765/pv1；设置后使用 Wi-Fi 模式")
    parser.add_argument("--ping-target", default=config_value(config, "PICO_MONITOR_PING_TARGET", "www.baidu.com"), help="网络延迟检测目标")
    parser.add_argument("--interval", type=float, default=float(config_value(config, "PICO_MONITOR_INTERVAL", "0.5")), help="采集和发送间隔，单位为秒")
    adaptive_group = parser.add_mutually_exclusive_group()
    adaptive_group.add_argument("--adaptive-transmit", dest="adaptive_transmit", action="store_true", help="等待 Pico JSON ACK 后再发送下一帧，并在拥塞时合并为最新快照")
    adaptive_group.add_argument("--no-adaptive-transmit", dest="adaptive_transmit", action="store_false", help="关闭 JSON ACK 背压，沿用写完即返回的发送策略")
    parser.set_defaults(adaptive_transmit=config_flag(config, "PICO_MONITOR_ADAPTIVE_TRANSMIT", False))
    parser.add_argument("--collection-task-intervals", type=parse_collection_task_intervals, default=parse_collection_task_intervals(config_value(config, "PICO_MONITOR_COLLECTION_TASK_INTERVALS")), help="各系统采集任务频率 JSON 或 YAML 对象，键为英文任务标识，值为秒数")
    parser.add_argument("--reconnect-interval", type=float, default=float(config_value(config, "PICO_MONITOR_RECONNECT_INTERVAL", "3.0")), help="设备断线后的重连间隔，单位为秒")
    parser.add_argument("--serial-probe-interval", type=float, default=float(config_value(config, "PICO_MONITOR_SERIAL_PROBE_INTERVAL", "3.0")), help="串口探测 PING 的发送间隔，单位为秒")
    parser.add_argument("--screen-rotation", type=int, choices=(0, 180), default=int(config_value(config, "PICO_MONITOR_SCREEN_ROTATION", "0")), help="Pico 屏幕旋转角度，可选 0 或 180")
    parser.add_argument("--lcd-brightness", type=int, choices=range(1, 101), default=int(config_value(config, "PICO_MONITOR_LCD_BRIGHTNESS", "50")), help="Pico LCD 背光亮度百分比，范围为 1 至 100")
    parser.add_argument("--network-unit", choices=("MB", "Mbps"), default=config_value(config, "PICO_MONITOR_NETWORK_UNIT", "MB"), help="网络速率模式：MB 自动使用 B/KB/MB/GB，Mbps 自动使用 bps/Kbps/Mbps/Gbps")
    parser.add_argument("--lcd-style", default=config_value(config, "PICO_MONITOR_LCD_STYLE", "horizontal_disk4x"), help="Pico LCD 界面样式名称")
    parser.add_argument("--log-level", type=lambda value: str(value).upper(), choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), default=str(config_value(config, "PICO_MONITOR_LOG_LEVEL", "INFO")).upper(), help="日志输出级别，默认 INFO；排障时可设为 DEBUG")
    parser.add_argument("--thread-diagnostics", action="store_true", default=config_flag(config, "PICO_MONITOR_THREAD_DIAGNOSTICS", False), help="开启线程诊断，周期输出 threading.enumerate() 摘要和 faulthandler 全线程栈")
    parser.add_argument("--thread-diagnostics-interval", type=float, default=float(config_value(config, "PICO_MONITOR_THREAD_DIAGNOSTICS_INTERVAL", "10.0")), help="线程诊断输出间隔，单位为秒")
    sensor_host_group = parser.add_mutually_exclusive_group()
    sensor_host_group.add_argument("--sensor-host-enabled", dest="sensor_host_enabled", action="store_true", help="开启 Windows SensorHost 外置硬件传感器采集")
    sensor_host_group.add_argument("--no-sensor-host", dest="sensor_host_enabled", action="store_false", help="关闭 Windows SensorHost 外置硬件传感器采集")
    parser.set_defaults(sensor_host_enabled=config_flag(config, "PICO_MONITOR_SENSOR_HOST_ENABLED", True))
    parser.add_argument("--sensor-host-path", default=config_value(config, "PICO_MONITOR_SENSOR_HOST_PATH") or None, help="SensorHost 可执行文件路径，留空时自动从打包目录查找")
    parser.add_argument("--sensor-host-pipe", default=config_value(config, "PICO_MONITOR_SENSOR_HOST_PIPE", "omniwatch.sensorhost"), help="SensorHost Named Pipe 名称")
    qbittorrent_group = parser.add_mutually_exclusive_group()
    qbittorrent_group.add_argument("--qbittorrent-enabled", dest="qbittorrent_enabled", action="store_true", help="开启 qBittorrent 指标采集")
    qbittorrent_group.add_argument("--no-qbittorrent", dest="qbittorrent_enabled", action="store_false", help="关闭 qBittorrent 指标采集")
    parser.set_defaults(qbittorrent_enabled=config_flag(config, "PICO_MONITOR_QBITTORRENT_ENABLED"))
    parser.add_argument("--qbittorrent-address", default=config_value(config, "PICO_MONITOR_QBITTORRENT_ADDRESS") or None, help="qBittorrent Web UI 地址")
    parser.add_argument("--qbittorrent-username", default=config_value(config, "PICO_MONITOR_QBITTORRENT_USERNAME") or None, help="qBittorrent Web UI 账号")
    parser.add_argument("--qbittorrent-password", default=config_value(config, "PICO_MONITOR_QBITTORRENT_PASSWORD") or None, help="qBittorrent Web UI 密码")
    parser.add_argument("--qbittorrent-interval", type=float, default=float(config_value(config, "PICO_MONITOR_QBITTORRENT_INTERVAL", "2.0")), help="qBittorrent 指标采集间隔，单位为秒")
    parser.add_argument("--dev", action="store_true", default=config_flag(config, "PICO_MONITOR_DEV", False), help="开发模式：未发现 Pico 时仍打印待发送的 JSON 协议行")
    parser.add_argument("--disk-health-test-index", type=int, default=int(config_value(config, "PICO_MONITOR_DISK_HEALTH_TEST_INDEX", "0")), help="磁盘健康显示测试：指定从 1 开始的磁盘序号，0 表示关闭")
    parser.add_argument("--disk-health-test-level", type=int, choices=range(6), default=int(config_value(config, "PICO_MONITOR_DISK_HEALTH_TEST_LEVEL", "3")), help="磁盘健康显示测试等级，范围为 0 至 5，默认 3")
    parser.add_argument("--once", action="store_true", help="仅成功发送一次数据")
    parser.add_argument("--pico-info", action="store_true", help="连接 Pico，显示开发板型号、屏幕方案和固件版本后退出")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--upgrade-pico", action="store_true", help="下载当前 Monitor 版本的 Pico 升级包并执行升级")
    parser.add_argument("--upgrade-url", default=config_value(config, "PICO_MONITOR_UPGRADE_URL") or None, help="覆盖 Pico 升级包下载地址")
    parser.add_argument("--upgrade-sha256", default=config_value(config, "PICO_MONITOR_UPGRADE_SHA256") or None, help="可选的升级包 SHA-256 摘要")
    parser.add_argument("--update", action="store_true", help="从 GitHub 最新 Release 下载并安装当前架构的 Linux DEB")
    return parser



def validate_arguments(arguments):
    """校验通用间隔以及启用 qBittorrent 后的必填连接参数。"""
    arguments.log_level = str(arguments.log_level).strip().upper()
    exclusive_actions = sum(bool(value) for value in (
        arguments.pico_info, arguments.upgrade_pico, arguments.update,
    ))
    if exclusive_actions > 1:
        raise SystemExit("--pico-info、--upgrade-pico 和 --update 不能同时使用")
    if (arguments.interval <= 0 or arguments.reconnect_interval <= 0
            or arguments.serial_probe_interval <= 0
            or arguments.qbittorrent_interval <= 0
            or arguments.thread_diagnostics_interval <= 0):
        raise SystemExit("采集间隔和重连间隔必须大于 0")
    if any(interval <= 0 for interval in arguments.collection_task_intervals.values()):
        raise SystemExit("采集任务频率必须大于 0")
    if arguments.pico_info:
        return
    if not arguments.qbittorrent_enabled:
        return
    required = (
        ("--qbittorrent-address", arguments.qbittorrent_address),
        ("--qbittorrent-username", arguments.qbittorrent_username),
        ("--qbittorrent-password", arguments.qbittorrent_password),
    )
    missing = [name for name, value in required if not str(value or "").strip()]
    if missing:
        raise SystemExit("开启 qBittorrent 采集后必须配置：" + "、".join(missing))


def parse_monitor_arguments(argv=None):
    """先读取配置文件，再用完整解析器合并命令行参数。"""
    preliminary_parser = argparse.ArgumentParser(add_help=False)
    preliminary_parser.add_argument("--config")
    preliminary_arguments, _ = preliminary_parser.parse_known_args(argv)
    config_path = (
        preliminary_arguments.config
        or os.getenv("PICO_MONITOR_CONFIG")
        or os.getenv("PICO_MONITOR_CONFIG_PATH")
    )
    config = load_monitor_config(config_path)
    arguments = create_argument_parser(config).parse_args(argv)
    arguments.config = config_path
    return arguments
