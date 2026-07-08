"""Windows 托盘共享常量。"""

from pathlib import Path

APPLICATION_NAME = "OmniWatch USB监控屏"
WINDOWS_APP_USER_MODEL_ID = "OmniWatch.USBMonitor.Tray"
AUTOSTART_NAME = "PicoHardwareMonitor"
MONITOR_DIRECTORY = Path(__file__).resolve().parent.parent
LOG_EXPORT_SIZE = 1024 * 1024
