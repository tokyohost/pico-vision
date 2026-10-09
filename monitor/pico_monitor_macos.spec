# -*- mode: python ; coding: utf-8 -*-
"""分别生成 Intel/Apple Silicon 的 macOS 菜单栏应用。"""

import os
import platform
import re
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from build_info import MONITOR_VERSION


MONITOR_ROOT = Path(SPECPATH).resolve()
target_arch = os.environ.get("MONITOR_MAC_ARCH", platform.machine())
if target_arch not in ("x86_64", "arm64"):
    raise RuntimeError("macOS 打包仅支持 x86_64 和 arm64")
runtime_root = Path(os.environ["MONITOR_MAC_PLUGIN_RUNTIME"]).resolve()
if not (runtime_root / "bin" / "python3").is_file():
    raise RuntimeError("缺少完整可迁移插件 Python Runtime")
identity = os.environ.get("MONITOR_MAC_SIGNING_IDENTITY") or None
entitlements = str(MONITOR_ROOT / "desktop" / "macos" / "entitlements.plist")
matched = re.match(r"^(\d+\.\d+\.\d+)", MONITOR_VERSION)
bundle_version = matched.group(1) if matched else "0.0.0"
datas = [
    (str(MONITOR_ROOT / "win/ui-web/dist"), "win/ui-web/dist"),
    (str(MONITOR_ROOT / "icon/icon.png"), "icon"),
    (str(MONITOR_ROOT / "assert"), "assert"),
    (str(MONITOR_ROOT / "custom_data/runner.py"), "custom_data"),
    (str(MONITOR_ROOT.parent / "tools/mpremote_stream_copy.py"), "tools"),
    (str(runtime_root), "plugin-runtime"),
]
for module in ("webview", "esptool"):
    datas.extend(collect_data_files(module))
analysis = Analysis(
    [str(MONITOR_ROOT / "pico_monitor.py")],
    pathex=[str(MONITOR_ROOT)],
    binaries=[], datas=datas,
    hiddenimports=(
        ["pystray._darwin", "PIL.Image", "AppKit", "Foundation", "WebKit", "UserNotifications", "PyObjCTools.AppHelper", "serial.tools.list_ports"]
        + collect_submodules("desktop.common")
        + collect_submodules("desktop.macos")
        + collect_submodules("collectTask.tasks.mac_os")
        + collect_submodules("esptool")
        + collect_submodules("mpremote")
        + collect_submodules("webview")
        + collect_submodules("aiohttp")
    ),
    excludes=["desktop.win", "desktop.linux.application", "win", "windows_tray", "windows_update", "win32api", "win32con", "win32file", "win32job", "win32pipe", "win32clipboard", "tkinter", "webview.platforms.winforms", "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cef", "webview.platforms.android"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True,
    name="pico-monitor", console=False, upx=False,
    target_arch=target_arch, codesign_identity=identity,
    entitlements_file=entitlements,
)
collection = COLLECT(executable, analysis.binaries, analysis.datas,
                     name="OmniWatch", upx=False)
application = BUNDLE(
    collection, name="OmniWatch.app",
    icon=str(MONITOR_ROOT / "icon/icon.png"),
    bundle_identifier="com.omniwatch.monitor", version=bundle_version,
    info_plist={
        "CFBundleDisplayName": "OmniWatch",
        "CFBundleShortVersionString": bundle_version,
        "OmniWatchReleaseVersion": MONITOR_VERSION,
        "LSMinimumSystemVersion": "12.0",
        "LSUIElement": True,
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
        "NSLocalNetworkUsageDescription": "OmniWatch 需要发现并连接局域网中的 ESP32-S3 或 RP2040 显示设备。",
    },
)
