"""Web 界面的插件市场下载安装接口。"""

from i18n import t

import logging
import os
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from build_info import MONITOR_VERSION


LOGGER = logging.getLogger("pico-monitor.web-ui")
MAXIMUM_MARKET_PACKAGE_SIZE = 20 * 1024 * 1024


def _normalized_url_origin(url):
    """提取 HTTP 地址的标准化来源。"""
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(t('message.plugin_download_url_must_use_http_or_https'))
    default_port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname.lower(), parsed.port or default_port


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """仅允许插件下载请求在市场同源范围内重定向。"""

    def __init__(self, allowed_origin):
        """保存允许的市场来源。"""
        super().__init__()
        self.allowed_origin = allowed_origin

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        """在发起重定向请求前拒绝跨来源目标。"""
        if _normalized_url_origin(new_url) != self.allowed_origin:
            raise ValueError(t('message.plugin_download_redirected_to_another_origin_installation_refused'))
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


class MarketApiMixin:
    """处理插件市场包的受控下载、导入和进度查询。"""

    __slots__ = ()

    @staticmethod
    def _url_origin(url):
        """提取 HTTP 地址的标准化来源，供下载地址白名单校验。"""
        return _normalized_url_origin(url)

    def _market_origin(self):
        """返回当前 Monitor 实际加载的插件市场来源。"""
        market_url = (
            "http://localhost/market"
            if MONITOR_VERSION == "development"
            else str(self._application.settings.get("market_url") or "").strip()
        )
        if not market_url:
            raise RuntimeError(t('message.no_plugin_market_url_configured'))
        return self._url_origin(market_url)

    def _validate_market_download_url(self, download_url):
        """限制下载地址与已配置市场同源，避免页面请求任意网络资源。"""
        if self._url_origin(download_url) != self._market_origin():
            raise ValueError(t('message.plugin_url_differs_from_the_market_origin_installation_refused'))
        return str(download_url).strip()

    def _set_market_state(
        self, status, progress, message, reset_logs=False, result=None
    ):
        """更新市场安装任务状态，并保留有限数量的阶段日志。"""
        with self._market_lock:
            if reset_logs:
                self._market_state["logs"] = []
                self._market_state["result"] = None
            self._market_state["status"] = str(status)
            self._market_state["busy"] = status == "running"
            if progress is not None:
                self._market_state["progress"] = max(
                    0, min(100, int(progress))
                )
            self._market_state["message"] = str(message or "")
            if message:
                self._market_state["logs"].append(str(message))
                del self._market_state["logs"][:-1000]
            if result is not None:
                self._market_state["result"] = result

    def _download_market_package(self, download_url, target_path):
        """流式下载市场 ZIP，并持续更新全局安装进度。"""
        request = urllib.request.Request(
            download_url,
            headers={
                "Accept": "application/zip, application/octet-stream",
                "User-Agent": "OmniWatch-Monitor/{}".format(MONITOR_VERSION),
            },
        )
        opener = urllib.request.build_opener(
            _SameOriginRedirectHandler(self._market_origin())
        )
        with opener.open(request, timeout=30) as response:
            final_url = self._validate_market_download_url(response.geturl())
            total = int(response.headers.get("Content-Length") or 0)
            if total > MAXIMUM_MARKET_PACKAGE_SIZE:
                raise ValueError(t('message.plugin_package_exceeds_the_20_mb_limit'))
            downloaded = 0
            last_reported = -1
            with target_path.open("wb") as output:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAXIMUM_MARKET_PACKAGE_SIZE:
                        raise ValueError(t('message.plugin_package_exceeds_the_20_mb_limit'))
                    output.write(chunk)
                    if total:
                        percentage = min(65, 10 + int(downloaded * 55 / total))
                        if percentage >= last_reported + 5:
                            self._set_market_state(
                                "running",
                                percentage,
                                t('message.downloading_plugin_package').format(
                                    min(100, int(downloaded * 100 / total))
                                ),
                            )
                            last_reported = percentage
            if downloaded == 0:
                raise ValueError(t('message.market_returned_an_empty_plugin_package'))
            LOGGER.info("市场插件包下载完成：地址=%s，字节=%s", final_url, downloaded)

    def _require_connected_device(self):
        """确认当前存在可接收屏幕样式的已连接设备。"""
        getter = getattr(self._application, "_get_device_connection", None)
        connection = getter() if callable(getter) else {}
        if not connection or not connection.get("connected"):
            raise RuntimeError(t('message.connect_a_device_before_installing_a_screen_style'))
        return connection

    def _run_market_install(self, download_url, plugin_name, plugin_type):
        """在后台完成插件包下载、校验和覆盖导入。"""
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="omniwatch-market-", suffix=".zip"
        )
        os.close(descriptor)
        package_path = Path(temporary_name)
        try:
            self._set_market_state(
                "running", 8, t('message.downloading').format(plugin_name)
            )
            self._download_market_package(download_url, package_path)
            self._set_market_state("running", 70, t('message.download_complete_validating_zip_plugin_package'))
            if not zipfile.is_zipfile(package_path):
                raise ValueError(t('message.download_is_not_a_valid_zip_plugin_package'))
            self._set_market_state("running", 82, t('message.validation_passed_installing_market_resource'))
            if plugin_type == "style":
                self._require_connected_device()
                existing_names = {
                    str(item.get("name") or "")
                    for item in self._application.settings.get("styles", ())
                    if isinstance(item, dict) and item.get("type") == "custom"
                }
                result = self._upload_style_source(
                    str(package_path),
                    {"overwrite": True, "existingNames": list(existing_names)},
                )
                result["name"] = result.get("filename", plugin_name)
                result["chineseName"] = plugin_name
            else:
                result = self._import_custom_data_source(
                    str(package_path), {"overwrite": True}
                )
            self._set_market_state(
                "success",
                100,
                t('message.plugin_installed').format(result["chineseName"]),
                result=result,
            )
            LOGGER.info("市场插件安装完成：%s", result["name"])
        except Exception as error:
            self._set_market_state(
                "error", None, t('message.plugin_installation_failed').format(plugin_name, error)
            )
            LOGGER.exception("市场插件安装失败：%s", error)
        finally:
            package_path.unlink(missing_ok=True)

    def _market_install(self, payload):
        """校验市场安装请求并启动唯一后台任务。"""
        download_url = self._validate_market_download_url(
            payload.get("downloadUrl")
        )
        plugin_name = str(payload.get("pluginName") or t('ui.unnamed_plugin')).strip()[:120]
        plugin_type = str(payload.get("pluginType") or "plugin").strip()
        if plugin_type not in ("plugin", "style"):
            raise ValueError(t('message.market_resource_type_must_be_plugin_or_style'))
        if plugin_type == "style":
            self._require_connected_device()
        with self._market_lock:
            if self._market_state["busy"]:
                raise RuntimeError(t('message.another_plugin_is_being_installed_please_wait'))
            self._market_state.update(
                {
                    "busy": True,
                    "status": "running",
                    "progress": 2,
                    "message": t('message.preparing_download_and_installation'),
                    "logs": [t('message.preparing_download_and_installation')],
                    "result": None,
                }
            )
        threading.Thread(
            target=self._run_market_install,
            args=(download_url, plugin_name, plugin_type),
            name="Web 插件市场安装",
            daemon=True,
        ).start()
        return {"started": True}

    def _market_install_status(self, payload):
        """返回市场安装任务的进度、实时日志和最终结果。"""
        del payload
        with self._market_lock:
            return {
                "busy": self._market_state["busy"],
                "status": self._market_state["status"],
                "progress": self._market_state["progress"],
                "message": self._market_state["message"],
                "logs": "\n".join(self._market_state["logs"]),
                "result": self._market_state["result"],
            }
