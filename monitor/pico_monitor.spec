# -*- mode: python ; coding: utf-8 -*-
"""将 Pico 系统监控程序打包为单文件 Windows EXE。"""

from pathlib import Path


optional_fps_binaries = []
for binary_name in ("PresentMon.exe", "adlx_fps_bridge.dll"):
    binary_path = Path("win/fps/bin") / binary_name
    if binary_path.is_file():
        optional_fps_binaries.append((str(binary_path), "win/fps/bin"))

analysis = Analysis(
    ["pico_monitor.py"],
    pathex=[],
    binaries=optional_fps_binaries,
    datas=[("icon/icon.png", "icon"), ("assert/fishQr.png", "assert"), ("win/fps/PRESENTMON_LICENSE.txt", "win/fps")],
    hiddenimports=["psutil", "serial", "serial.tools.list_ports", "pystray._win32", "PIL.Image", "PIL.ImageTk", "pico_upgrade", "build_info", "windows_update"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
python_archive = PYZ(analysis.pure)
executable = EXE(python_archive, analysis.scripts, analysis.binaries, analysis.datas, [], name="pico-monitor", debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=False, uac_admin=False, disable_windowed_traceback=False)
