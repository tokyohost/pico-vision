"""Web 界面的应用、固件和 SDK 在线更新接口。"""

from i18n import t

import logging
import sys
import threading

from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from sdk_flash import inspect_sdk_image
from desktop.common.release import ReleaseUpdater

from .config import SDK_RELEASE_REPOSITORY


LOGGER = logging.getLogger("pico-monitor.web-ui")


def _inspect_sdk_image(path):
    """调用 SDK 镜像检查器，并兼容旧入口上的测试替换。"""
    facade_name = "win.ui_web"
    facade = sys.modules.get(facade_name)
    checker = getattr(facade, "inspect_sdk_image", inspect_sdk_image)
    return checker(path)


class UpdateApiMixin:
    """处理在线版本检查、下载、安装和进度查询。"""

    __slots__ = ()

    def _release_updater(self, repository, current_version, include_preview=False):
        """通过宿主平台创建应用更新器，设备发布查询仍使用公共实现。"""
        factory = getattr(self._application, "_create_release_updater", ReleaseUpdater)
        return factory(repository, current_version, include_preview=include_preview)

    @staticmethod
    def _find_release_asset(assets, expected_name):
        """按不区分大小写的完整文件名查找发布资源。"""
        expected = str(expected_name or "").lower()
        return next(
            (
                item for item in assets
                if str(item.get("name") or "").lower() == expected
            ),
            None,
        )

    def _check_update(self, payload):
        """按类别检查设备固件、设备 SDK 或 OmniWatch 应用更新。"""
        category = str(payload.get("category") or "").strip()
        connection = self._application._get_device_connection()
        if category == "firmware":
            if not connection.get("connected"):
                raise RuntimeError(t('message.device_disconnected_cannot_check_firmware_version'))
            current_version = str(connection.get("firmware_version") or t('ui.unknown'))
            updater = self._release_updater(GITHUB_REPOSITORY, current_version, include_preview=bool(self._application.settings.get("developer_plan", False)))
            latest_version, assets, notes = updater.latest_release(
                self._application.settings.get("update_url") or None,
                include_notes=True,
            )
            board_model = str(connection.get("board_model") or "").strip()
            lcd_type = str(connection.get("lcd_device_type") or "").strip()
            asset_name = "OmniWatch-pico-full-v{}-{}-{}.zip".format(
                latest_version, board_model, lcd_type,
            )
            asset = self._find_release_asset(assets, asset_name)
            return {
                "category": category,
                "currentVersion": current_version,
                "latestVersion": latest_version,
                "updateAvailable": updater.firmware_update_available(
                    current_version, latest_version
                ),
                "applicable": True,
                "assetAvailable": asset is not None,
                "assetName": asset.get("name") if asset else asset_name,
                "notes": notes,
            }
        if category == "sdk":
            if not connection.get("connected"):
                raise RuntimeError(t('message.device_disconnected_cannot_check_sdk_version'))
            current_version = str(connection.get("sdk_version") or t('ui.unknown'))
            board_model = str(connection.get("board_model") or "").lower().replace("_", "-")
            if "esp32-s3" not in board_model:
                return {
                    "category": category,
                    "currentVersion": current_version,
                    "latestVersion": t('message.not_applicable'),
                    "updateAvailable": False,
                    "applicable": False,
                    "assetAvailable": False,
                    "assetName": "",
                    "notes": t('message.this_board_does_not_use_an_esp32_s3_micropython'),
                }
            updater = self._release_updater(SDK_RELEASE_REPOSITORY, current_version, include_preview=bool(self._application.settings.get("developer_plan", False)))
            latest_version, assets, notes = updater.latest_release(include_notes=True)
            asset_name = "micropython-ESP32_GENERIC_S3-N8R8-v{}.bin".format(
                latest_version
            )
            asset = self._find_release_asset(assets, asset_name)
            return {
                "category": category,
                "currentVersion": current_version,
                "latestVersion": latest_version,
                "updateAvailable": (
                    current_version.lstrip("v") != latest_version.lstrip("v")
                ),
                "applicable": True,
                "assetAvailable": asset is not None,
                "assetName": asset.get("name") if asset else asset_name,
                "notes": notes,
            }
        if category == "application":
            updater = self._release_updater(GITHUB_REPOSITORY, MONITOR_VERSION, include_preview=bool(self._application.settings.get("developer_plan", False)))
            latest_version, assets, notes = updater.latest_release(
                self._application.settings.get("update_url") or None,
                include_notes=True,
            )
            try:
                asset = updater.select_monitor_asset(assets, latest_version)
            except RuntimeError:
                asset = None
            return {
                "category": category,
                "currentVersion": MONITOR_VERSION,
                "latestVersion": latest_version,
                "updateAvailable": updater.update_available(latest_version),
                "applicable": True,
                "assetAvailable": asset is not None,
                "assetName": asset.get("name") if asset else "",
                "notes": notes,
            }
        raise ValueError(t('message.unsupported_update_category').format(category))

    def _run_firmware_release_update(self, updater, asset, latest_version, port):
        """下载并增量安装设备全量固件包，结束后恢复常驻监控。"""
        package_path = None
        try:
            self._set_update_state(
                "firmware", "running", 10, t('message.downloading_device_firmware'), True
            )
            package_path = updater.download(asset, ".zip")
            self._set_update_state("firmware", "running", 45, t('message.firmware_downloaded_pausing_monitor'))
            self._application._stop_worker()
            self._set_update_state("firmware", "running", 50, t('message.updating_device_firmware_with_mpremote'))

            def report_progress(message, percent):
                """把 mpremote 的逐行输出和字节进度同步到 Web 更新页。"""
                progress = None if percent is None else 50 + int(percent * 0.45)
                self._set_update_state("firmware", "running", progress, message)

            self._application._install_pico_firmware_archive(
                package_path, port, report_progress
            )
            self._set_update_state(
                "firmware",
                "success",
                100,
                t('message.device_firmware_updated_to').format(latest_version),
            )
            LOGGER.info("设备固件已立即更新至 %s", latest_version)
        except Exception as error:
            self._set_update_state(
                "firmware",
                "error",
                None,
                t('message.device_firmware_update_failed').format(error),
            )
            LOGGER.exception("设备固件立即更新失败：%s", error)
        finally:
            if package_path is not None:
                updater.remove_file(package_path)
            try:
                if not self._application.stopping.is_set() and (
                    self._application.worker_process is None
                    or self._application.worker_process.poll() is not None
                ):
                    self._application._start_worker()
            except Exception as error:
                LOGGER.exception("在线固件更新后恢复后台监控失败：%s", error)
                self._set_update_state(
                    "firmware",
                    "error",
                    None,
                    t('message.firmware_update_ended_but_monitor_could_not_resume').format(error),
                )
            finally:
                self._application.update_lock.release()

    def _run_sdk_release_update(self, updater, asset, connection):
        """下载 SDK 发布镜像并通过受控 USB 模式立即刷写。"""
        image_path = None
        delegated = False
        try:
            self._set_update_state("sdk", "running", 10, t('message.downloading_sdk_image'), True)
            image_path = updater.download(asset, ".bin")
            self._set_update_state("sdk", "running", 30, t('message.sdk_image_downloaded_validating'))
            information = _inspect_sdk_image(image_path)
            # 在线下载可能持续数秒，期间后台监控可能重连并更换 COM 号。
            # 必须丢弃点击“立即更新”时的旧快照，使用刷写前的当前 USB 身份。
            connection = self._current_sdk_usb_connection()
            with self._sdk_lock:
                self._sdk_state.update({
                    "busy": True,
                    "status": "running",
                    "message": t('message.downloading_and_flashing_the_latest_sdk_do_not_power'),
                    "image_path": image_path,
                    "image": self._sdk_image_payload(information),
                    "logs": [],
                })
            delegated = True
            self._run_sdk_flash_task(information, connection, False, "")
        except Exception as error:
            self._set_update_state(
                "sdk", "error", None, t('message.sdk_update_failed').format(error)
            )
            LOGGER.exception("SDK 立即更新失败：%s", error)
            with self._sdk_lock:
                self._sdk_state.update({
                    "busy": False,
                    "status": "error",
                    "message": t('message.sdk_update_failed').format(error),
                })
        finally:
            if image_path is not None:
                updater.remove_file(image_path)
                with self._sdk_lock:
                    if self._sdk_state.get("image_path") == image_path:
                        self._sdk_state["image_path"] = None
            if not delegated:
                self._application.update_lock.release()

    @staticmethod
    def _format_download_size(byte_count):
        """把下载字节数格式化为适合实时日志展示的短文本。"""
        size = max(0, int(byte_count or 0))
        units = ("B", "KB", "MB", "GB")
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return "{:.1f} {}".format(value, unit)
            value /= 1024

    def _run_application_release_update(self, updater):
        """在 Web 更新页内下载应用安装包，完整呈现下载进度后启动安装器。"""
        monitor_path = None
        try:
            self._set_update_state(
                "application", "running", 2, t('message.checking_application_update_assets'), True
            )
            latest_version, assets = updater.latest_release(
                self._application.settings.get("update_url") or None
            )
            if not updater.update_available(latest_version):
                raise RuntimeError(t('message.omniwatch_is_up_to_date'))
            asset = updater.select_monitor_asset(assets, latest_version)
            self._set_update_state(
                "application",
                "running",
                5,
                t('message.preparing_installer_download').format(asset.get("name") or latest_version),
            )
            last_percent = [-1]
            last_unknown_megabyte = [-1]

            def report_download_progress(downloaded_bytes, total_bytes):
                """将安装包字节进度换算为页面进度，并避免重复写入相同日志。"""
                if total_bytes:
                    percent = min(100, int(downloaded_bytes * 100 / total_bytes))
                    if percent == last_percent[0]:
                        return
                    last_percent[0] = percent
                    message = t('message.downloading_installer').format(
                        percent,
                        self._format_download_size(downloaded_bytes),
                        self._format_download_size(total_bytes),
                    )
                    self._set_update_state(
                        "application", "running", 5 + int(percent * 0.85), message
                    )
                    return
                downloaded_megabyte = downloaded_bytes // (1024 * 1024)
                if downloaded_megabyte == last_unknown_megabyte[0]:
                    return
                last_unknown_megabyte[0] = downloaded_megabyte
                self._set_update_state(
                    "application",
                    "running",
                    None,
                    t('message.downloading_installer_downloaded').format(
                        self._format_download_size(downloaded_bytes)
                    ),
                )

            monitor_path = updater.download(
                asset, self._application.application_asset_suffix, progress_callback=report_download_progress
            )
            self._set_update_state(
                "application", "running", 95, t('message.installer_downloaded_starting_installation')
            )
            self._application._schedule_monitor_installer(monitor_path, version=latest_version)
            monitor_path = None
            self._set_update_state(
                "application", "success", 100, t('message.installer_started_omniwatch_will_exit')
            )
            LOGGER.info("OmniWatch 应用安装包已下载，准备更新至 %s", latest_version)
            self._application._exit(self._application.icon, None)
        except Exception as error:
            self._set_update_state(
                "application", "error", None, t('message.application_update_failed').format(error)
            )
            LOGGER.exception("应用立即更新失败：%s", error)
        finally:
            if monitor_path is not None:
                updater.remove_file(monitor_path)
            self._application.update_lock.release()

    def _install_update(self, payload):
        """按更新类别立即启动应用、设备固件或 SDK 更新。"""
        category = str(payload.get("category") or "").strip()
        if not self._application.update_lock.acquire(blocking=False):
            raise RuntimeError(t('message.another_update_is_running_please_wait'))
        try:
            if category == "application":
                updater = self._release_updater(
                    GITHUB_REPOSITORY,
                    MONITOR_VERSION,
                    include_preview=bool(
                        self._application.settings.get("developer_plan", False)
                    ),
                )
                target = self._run_application_release_update
                arguments = (updater,)
            else:
                connection = self._application._get_device_connection()
                if not connection.get("connected"):
                    raise RuntimeError(t('message.device_disconnected_cannot_update_now'))
            if category == "application":
                pass
            elif category == "firmware":
                port = self._application._mpremote_repl_port(connection)
                current_version = str(connection.get("firmware_version") or t('ui.unknown'))
                updater = self._release_updater(GITHUB_REPOSITORY, current_version, include_preview=bool(self._application.settings.get("developer_plan", False)))
                latest_version, assets = updater.latest_release(
                    self._application.settings.get("update_url") or None
                )
                if not updater.firmware_update_available(current_version, latest_version):
                    raise RuntimeError(t('message.device_firmware_is_up_to_date'))
                board_model = str(connection.get("board_model") or "").strip()
                lcd_type = str(connection.get("lcd_device_type") or "").strip()
                asset_name = "OmniWatch-pico-full-v{}-{}-{}.zip".format(
                    latest_version, board_model, lcd_type,
                )
                asset = self._find_release_asset(assets, asset_name)
                if asset is None:
                    raise RuntimeError(t('message.no_compatible_firmware_in_this_release').format(asset_name))
                target = self._run_firmware_release_update
                arguments = (updater, asset, latest_version, port)
            elif category == "sdk":
                if not self._sdk_flash_allowed(connection):
                    raise RuntimeError(t('message.this_connection_does_not_support_managed_esp32_s3_sdk'))
                current_version = str(connection.get("sdk_version") or t('ui.unknown'))
                updater = self._release_updater(SDK_RELEASE_REPOSITORY, current_version, include_preview=bool(self._application.settings.get("developer_plan", False)))
                latest_version, assets = updater.latest_release()
                if current_version.lstrip("v") == latest_version.lstrip("v"):
                    raise RuntimeError(t('message.device_sdk_is_up_to_date'))
                asset_name = "micropython-ESP32_GENERIC_S3-N8R8-v{}.bin".format(
                    latest_version
                )
                asset = self._find_release_asset(assets, asset_name)
                if asset is None:
                    raise RuntimeError(t('message.no_compatible_sdk_image_in_this_release').format(asset_name))
                target = self._run_sdk_release_update
                arguments = (updater, asset, connection)
            else:
                raise ValueError(t('message.unsupported_update_category_2').format(category))
            self._set_update_state(
                category, "running", 1, t('message.update_started_preparing'), True
            )
            threading.Thread(
                target=target,
                args=arguments,
                name="Web 立即更新-{}".format(category),
                daemon=True,
            ).start()
            return {"category": category, "started": True}
        except Exception:
            self._application.update_lock.release()
            raise

    def _set_update_state(
        self, category, status, progress, message, reset_logs=False
    ):
        """更新指定在线更新任务的进度，并把阶段消息追加到实时日志。"""
        with self._sdk_lock:
            state = self._update_states[category]
            if reset_logs:
                state["logs"] = []
            state["status"] = status
            state["busy"] = status == "running"
            if progress is not None:
                state["progress"] = max(0, min(100, int(progress)))
            state["message"] = str(message)
            if message:
                state["logs"].append(str(message))
                del state["logs"][:-1000]

    def _update_status(self, payload):
        """返回全部或指定类别在线更新任务的进度与实时日志快照。"""
        category = str(payload.get("category") or "").strip()
        with self._sdk_lock:
            categories = (category,) if category else tuple(self._update_states)
            result = {}
            for name in categories:
                if name not in self._update_states:
                    raise ValueError(t('message.unsupported_update_status_category').format(name))
                state = self._update_states[name]
                result[name] = {
                    "busy": state["busy"],
                    "status": state["status"],
                    "message": state["message"],
                    "progress": state["progress"],
                    "logs": "\n".join(state["logs"]),
                }
            return result[category] if category else result
