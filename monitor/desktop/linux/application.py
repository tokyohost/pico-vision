"""可选 Linux GTK 桌面，不替换现有 systemd 与 HTTP 管理入口。"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from desktop.common.constants import MONITOR_DIRECTORY
from desktop.common.posix_application import PosixDesktopApplication
from desktop.common.release import ReleaseUpdater
from monitor_update import LinuxDebUpdater


class LinuxAutostart:
    """通过用户 XDG autostart 文件管理桌面登录启动。"""

    def __init__(self, command):
        """保存命令和当前用户的启动项位置。"""
        self.command = [str(value) for value in command]
        self.path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart" / "omniwatch.desktop"

    def is_enabled(self):
        """只读取当前应用对应的启动项文件。"""
        return self.path.is_file()

    def set_enabled(self, enabled):
        """写入标准 Desktop Entry，参数独立转义，不启动 shell。"""
        if not enabled:
            self.path.unlink(missing_ok=True)
            return
        if any("\n" in value or "\r" in value for value in self.command):
            raise ValueError("启动命令不能包含换行")
        quoted = ['"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("`", "\\`").replace("$", "\\$") + '"' for value in self.command]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise RuntimeError("启动项路径是符号链接，拒绝覆盖")
        self.path.write_text("[Desktop Entry]\nType=Application\nName=OmniWatch\nTerminal=false\nExec={}\n".format(" ".join(quoted)), encoding="utf-8")


class LinuxDesktopReleaseUpdater(ReleaseUpdater):
    """复用 Linux DEB 的架构与资源选择规则。"""

    def select_monitor_asset(self, assets, version):
        """选择与 dpkg 当前架构一致的唯一 DEB 包。"""
        del version
        return LinuxDebUpdater._find_package_asset(assets, LinuxDebUpdater._architecture())


class LinuxDesktopApplication(PosixDesktopApplication):
    """显式 --desktop 启用 GTK 控制中心，默认 Linux 仍运行无界面服务。"""

    application_asset_suffix = ".deb"

    def __init__(self, worker_arguments):
        """初始化公共应用、XDG 启动项和低开销休眠检测状态。"""
        super().__init__(worker_arguments)
        command = [str(Path(sys.executable).resolve())]
        if not getattr(sys, "frozen", False):
            command.append(str(MONITOR_DIRECTORY / "pico_monitor.py"))
        self.autostart = LinuxAutostart([*command, "--desktop"])
        self._wake_stop = threading.Event()
        self._wake_thread = None

    def _start_webview_loop(self):
        """运行 GTK/WebKit 主循环，与 Linux 托盘后端共用 GTK 调度。"""
        import webview
        webview.start(gui="gtk", debug=False, private_mode=False,
                      storage_path=str(self.data_directory / "webview"))

    def _start_platform_services(self):
        """启用非特权唤醒检测，不给既有 Linux 服务增加 D-Bus 依赖。"""
        self._wake_thread = threading.Thread(target=self._watch_resume, name="桌面唤醒检测", daemon=True)
        self._wake_thread.start()

    def _watch_resume(self):
        """比较墙钟与不计休眠的单调时钟，恢复后通知 worker 重新探测。"""
        difference = time.time() - time.monotonic()
        while not self._wake_stop.wait(5):
            current = time.time() - time.monotonic()
            if current - difference > 5 and not self.stopping.is_set():
                self._write_worker_command("RESUME_PROBE\n")
            difference = current

    def _stop_platform_services(self):
        """停止唤醒检测线程，退出最长等待一秒。"""
        self._wake_stop.set()
        if self._wake_thread is not None:
            self._wake_thread.join(timeout=1)

    @staticmethod
    def _create_release_updater(repository, current_version, include_preview=False):
        """创建与现有 DEB 发布格式一致的桌面更新器。"""
        return LinuxDesktopReleaseUpdater(repository, current_version, include_preview=include_preview)

    @staticmethod
    def _schedule_monitor_installer(download_path, version=None):
        """使用既有 APT 安装逻辑，由 pkexec 显式请求安装授权。"""
        del version
        subprocess.run(["pkexec", "apt-get", "install", "--yes", str(Path(download_path).resolve())], check=True)
        Path(download_path).unlink(missing_ok=True)
