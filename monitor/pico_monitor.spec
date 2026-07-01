# -*- mode: python ; coding: utf-8 -*-
"""将 Pico 系统监控程序打包为单文件 Windows EXE。"""

analysis = Analysis(
    ["pico_monitor.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["psutil", "serial", "serial.tools.list_ports", "pystray._win32", "PIL.Image", "PIL.ImageDraw"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
python_archive = PYZ(analysis.pure)
executable = EXE(python_archive, analysis.scripts, analysis.binaries, analysis.datas, [], name="pico-monitor", debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=False, uac_admin=False, disable_windowed_traceback=False)
