"""桌面应用公共状态、设备操作和菜单业务逻辑。"""

import base64
import json
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from pico_upgrade import PicoFirmwareArchive
from .constants import APPLICATION_NAME, MONITOR_DIRECTORY
from .settings import TraySettingsStore, settings_from_arguments, normalize_style_catalog, style_label, style_names
from .worker_controller import WorkerControllerMixin
from .log_service import LogServiceMixin
from .ui_api.webview import WebUiMixin
from .platform import data_directory, subprocess_flags

LOGGER = logging.getLogger("pico-monitor.desktop")


class DesktopApplication(WorkerControllerMixin, LogServiceMixin, WebUiMixin):
    """统一维护配置、设备命令、窗口状态与采集子进程。"""

    @staticmethod
    def _data_directory():
        """返回当前平台的用户数据目录，不写入应用安装位置。"""
        return data_directory()

    def _migrate_legacy_autostart(self):
        """默认无需迁移旧启动项，Windows 适配层保留原有迁移实现。"""
        return None

    def __init__(self, worker_arguments):
        """初始化托盘状态、窗口互斥量、配置存储和后台进程参数。"""
        self.worker_arguments = list(worker_arguments)
        self.worker_process = None
        self.log_file_lock = threading.Lock()
        self.log_window_lock = threading.Lock()
        self.log_window_open = False
        self.stopping = threading.Event()
        self.icon = None
        self.mutex = None
        self.settings_window = None
        self.settings_window_lock = threading.Lock()
        self.settings_window_open = False
        self.settings_window_restore_requested = threading.Event()
        self.about_window_lock = threading.Lock()
        self.about_window_open = False
        self.device_probe_window_lock = threading.Lock()
        self.device_probe_window_open = False
        self.device_management_messages = queue.Queue()
        self.sdk_flash_messages = queue.Queue()
        self.device_connection_messages = queue.Queue()
        self.wifi_messages = queue.Queue()
        self.websocket_client_messages = queue.Queue()
        self.runtime_config_messages = queue.Queue()
        self.device_connection_lock = threading.Lock()
        self.current_device_connection = {"connected": None}
        self.custom_style_messages = queue.Queue()
        self.custom_style_upload_messages = queue.Queue()
        self.custom_style_upload_logs = queue.Queue()
        self.custom_style_upload_active = threading.Event()
        self.custom_style_delete_messages = queue.Queue()
        self.update_lock = threading.Lock()
        self.crash_dialog_lock = threading.Lock()
        data_directory = self._data_directory()
        data_directory.mkdir(parents=True, exist_ok=True)
        self.data_directory = data_directory
        if sys.platform != "win32":
            os.environ.setdefault("PICO_MONITOR_DATA_ROOT", str(data_directory))
        self.screenshot_directory = data_directory / "screenshot"
        self.log_path = data_directory / "pico-monitor.log"
        self._configure_error_logging()
        try:
            self._migrate_legacy_autostart()
        except (OSError, RuntimeError):
            # 迁移失败时保留旧注册表项，方便用户查看日志后重新切换自启动配置。
            LOGGER.exception("迁移旧版开机自动启动配置失败")
        self.settings_store = TraySettingsStore(data_directory / "settings.json")
        settings_existed = self.settings_store.path.exists()
        self.settings = self.settings_store.load()
        # 新增随机 Auth 等默认配置必须在首次读取后落盘，确保重启后保持稳定。
        self.settings_store.save(self.settings)
        if not settings_existed:
            self.settings = settings_from_arguments(self.worker_arguments, self.settings)
            self.settings_store.save(self.settings)

    def _is_dev_mode(self, item=None):
        """返回托盘配置中的开发模式开关状态。"""
        del item
        return bool(self.settings.get("dev"))

    def _toggle_dev_mode(self, icon, item):
        """切换开发模式并通知后台监控进程即时生效。"""
        del item
        self.settings["dev"] = not self._is_dev_mode()
        self.settings_store.save(self.settings)
        applied = self._apply_dev_settings()
        icon.update_menu()
        state = "开启" if self.settings["dev"] else "关闭"
        if applied:
            self.icon.notify("开发模式已{}".format(state), APPLICATION_NAME)
        else:
            self.icon.notify(
                "开发模式已{}，后台监控下次启动时生效".format(state),
                APPLICATION_NAME,
            )

    def _install_pico_firmware_archive(
        self, package_path, port, progress_callback=None, force=False
    ):
        """校验并解压全量固件包，再通过 mpremote 增量或强制复制。"""
        package = PicoFirmwareArchive(package_path)
        try:
            with tempfile.TemporaryDirectory(prefix="omniwatch-firmware-") as directory:
                source_directory = Path(directory)
                package.extract_to(source_directory)

                if getattr(sys, "frozen", False):
                    command = [sys.executable, "--mpremote-stream-copy"]
                else:
                    command = [
                        sys.executable,
                        str(MONITOR_DIRECTORY.parent / "tools" / "mpremote_stream_copy.py"),
                    ]
                command.extend((str(port), "--source", str(source_directory)))
                if force:
                    command.append("--force")
                environment = os.environ.copy()
                environment.update({
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                    "PYTHONUNBUFFERED": "1",
                })
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=subprocess_flags(),
                    env=environment,
                )
                recent_output = []
                try:
                    for output_line in process.stdout:
                        line = output_line.rstrip("\r\n")
                        if not line:
                            continue
                        recent_output.append(line)
                        del recent_output[:-30]
                        percent_match = re.search(r"（([0-9]+(?:\.[0-9]+)?)%）", line)
                        percent = float(percent_match.group(1)) if percent_match else None
                        if progress_callback is not None:
                            progress_callback(line, percent)
                finally:
                    if process.stdout is not None:
                        process.stdout.close()
                return_code = process.wait(timeout=10)
                if return_code != 0:
                    details = "\n".join(recent_output).strip()
                    raise RuntimeError(
                        details[-2000:] if details else
                        "mpremote 固件更新进程异常退出：{}".format(return_code)
                    )
        finally:
            package.close()

    def _select_style(self, style):
        """创建切换指定屏幕样式的托盘回调。"""
        def select(icon, item):
            """保存选中样式并通知后台进程即时应用。"""
            del item
            self.settings["lcd_style"] = style
            self.settings_store.save(self.settings)
            self._apply_display_settings()
            icon.update_menu()
            self.icon.notify("已切换为{}".format(style_names(self.settings, idle=False)[style]), APPLICATION_NAME)
        return select

    def _style_checked(self, style):
        """创建判断指定屏幕样式是否选中的回调。"""
        return lambda item: self.settings["lcd_style"] == style

    def _exit(self, icon, item):
        """退出桌面 Monitor，不向设备发送重启指令。"""
        del item
        self.stopping.set()
        self._stop_worker()
        icon.stop()
        window = getattr(self, "webview_window", None)
        if window is not None:
            try:
                window.destroy()
            except Exception:
                # 原生窗口尚未完成启动时 destroy 会抛错，托盘仍应正常退出。
                LOGGER.exception("销毁 WebView 窗口失败")

    def _create_image(self):
        """从统一应用图标路径加载托盘菜单栏图标。"""
        from PIL import Image

        with Image.open(self._resource_path("icon", "icon.png")) as image:
            return image.convert("RGBA")

    @staticmethod
    def _resource_path(*parts):
        """返回开发目录或单文件程序解包目录中的资源绝对路径。"""
        base_directory = Path(getattr(sys, "_MEIPASS", MONITOR_DIRECTORY))
        return base_directory.joinpath(*parts)

    def _build_menu(self):
        """构建托盘主菜单，样式子菜单在每次展开时动态读取最新清单。"""
        import pystray

        style_menu = pystray.Menu(self._style_menu_items)
        return pystray.Menu(
            pystray.MenuItem("配置...", self._show_settings, default=pystray.Icon.HAS_DEFAULT_ACTION),
            pystray.MenuItem("界面样式", style_menu),
            pystray.MenuItem("自定义屏幕", self._show_custom_style),
            pystray.MenuItem("自定义数据", self._show_custom_data),
            pystray.MenuItem("屏幕旋转", pystray.Menu(
                pystray.MenuItem("0°", self._set_rotation(0), checked=lambda item: self.settings["screen_rotation"] == 0, radio=pystray.Icon.HAS_MENU_RADIO),
                pystray.MenuItem("180°", self._set_rotation(180), checked=lambda item: self.settings["screen_rotation"] == 180, radio=pystray.Icon.HAS_MENU_RADIO),
            )),
            pystray.MenuItem("屏幕截图", self._take_screenshot),
            pystray.MenuItem("打开日志", self._show_log),
            pystray.MenuItem("设备管理", self._show_device_probe),
            pystray.MenuItem("日志导出", self._export_log),
            pystray.MenuItem("检查更新", self._check_for_updates),
            pystray.MenuItem("关于应用", self._show_about),
            pystray.MenuItem("Dev 模式", self._toggle_dev_mode, checked=self._is_dev_mode),
            pystray.MenuItem("开机自动启动", self._toggle_autostart, checked=self._is_autostart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._exit),
        )

    def request_custom_style_catalog(self):
        """向工作进程发送自定义样式清单查询请求。"""
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        try:
            process.stdin.write("CUSTOM_STYLE_LIST\n")
            process.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def request_custom_style_upload(self, path, existing_style_names, overwrite=False):
        """校验本地样式文件、检查重名并交给 Monitor 工作进程上传。"""
        from style_validator import StyleFileValidator

        validated = StyleFileValidator().validate(path)
        existing_filenames = {
            "style_{}.py".format(name) for name in existing_style_names
        }
        if validated.filename in existing_filenames and not overwrite:
            raise FileExistsError(
                "OmniWatch 中已存在样式名 {} 和文件 {}".format(
                    validated.name, validated.filename,
                )
            )
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            raise RuntimeError("OmniWatch 未运行，无法上传样式")
        payload = {
            "filename": validated.filename,
            "style_name": validated.name,
            "content": base64.b64encode(validated.source).decode("ascii"),
            "overwrite": bool(overwrite),
        }
        upload_active = getattr(self, "custom_style_upload_active", None)
        if upload_active is not None:
            upload_active.set()
        try:
            process.stdin.write(
                "CUSTOM_STYLE_UPLOAD:{}\n".format(
                    json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
                )
            )
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            if upload_active is not None:
                upload_active.clear()
            raise RuntimeError("自定义样式上传请求发送失败") from error
        return validated

    def request_custom_style_delete(self, style_name, filename):
        """向工作进程发送自定义样式删除请求。"""
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            raise RuntimeError("OmniWatch 未运行，无法删除样式")
        payload = {"style_name": style_name, "filename": filename}
        try:
            process.stdin.write(
                "CUSTOM_STYLE_DELETE:{}\n".format(
                    json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
                )
            )
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise RuntimeError("自定义样式删除请求发送失败") from error

    def _reload_style_catalog(self):
        """从配置文件同步 Pico 样式清单及当前选择。"""
        latest_settings = self.settings_store.load()
        self.settings["styles"] = normalize_style_catalog(latest_settings["styles"])
        self.settings["lcd_style"] = latest_settings["lcd_style"]
        self.settings["idle_style"] = latest_settings["idle_style"]

    def _style_menu_items(self):
        """生成最新的样式菜单项，避免托盘长期持有启动时的静态清单。"""
        import pystray

        self._reload_style_catalog()
        return tuple(
            pystray.MenuItem(style_label(name, self.settings), self._select_style(name), checked=self._style_checked(name), radio=pystray.Icon.HAS_MENU_RADIO)
            for name in style_names(self.settings, idle=False)
        )

    def _set_rotation(self, rotation):
        """创建设置指定屏幕旋转角度的托盘回调。"""
        def select(icon, item):
            """保存屏幕旋转角度并通知后台进程即时应用。"""
            del item
            self.settings["screen_rotation"] = rotation
            self.settings_store.save(self.settings)
            self._apply_display_settings()
            icon.update_menu()
        return select
