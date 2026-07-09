# -*- mode: python ; coding: utf-8 -*-
"""将 Pico 系统监控程序打包为单文件 Windows EXE。"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules


MONITOR_ROOT = Path.cwd()
optional_fps_binaries = []
for binary_name in ("PresentMon.exe", "adlx_fps_bridge.dll"):
    binary_path = Path("win/fps/bin") / binary_name
    if binary_path.is_file():
        optional_fps_binaries.append((str(binary_path), "win/fps/bin"))
optional_datas = [("icon/icon.png", "icon"), ("assert/fishQr.png", "assert"), ("win/fps/PRESENTMON_LICENSE.txt", "win/fps"), ("custom_data_runner.py", ".")]
sensor_host_directory = Path("sensorhost")
if sensor_host_directory.is_dir():
    for sensor_host_file in sensor_host_directory.rglob("*"):
        if sensor_host_file.is_file():
            target_directory = Path("sensorhost") / sensor_host_file.relative_to(sensor_host_directory).parent
            optional_datas.append((str(sensor_host_file), str(target_directory)))

analysis = Analysis(
    ["pico_monitor.py"],
    pathex=[],
    binaries=optional_fps_binaries,
    datas=optional_datas,
    hiddenimports=["psutil", "serial", "serial.tools.list_ports", "custom_data", "collectTask", "collectTask.coordinator", "collectTask.executor", "collectTask.result_store", "collectTask.system_tasks", "tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.scrolledtext", "tkinter.ttk", "pystray._win32", "PIL.Image", "PIL.ImageTk", "pico_upgrade", "build_info", "windows_update", "win.sensor_host", "win32api", "win32con", "win32file", "win32job", "win32pipe"] + collect_submodules("collectTask.tasks"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
python_archive = PYZ(analysis.pure)
executable = EXE(
    python_archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="pico-monitor",
    icon=str(MONITOR_ROOT / "icon" / "icon.png"),
    version=str(MONITOR_ROOT / "windows_version_info.txt"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    uac_admin=True,
    disable_windowed_traceback=False,
)
