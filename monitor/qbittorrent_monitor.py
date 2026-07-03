#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.



"""通过 qBittorrent Web API 异步采集传输和种子状态指标。"""


import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from http.cookiejar import CookieJar


LOGGER = logging.getLogger("pico-monitor")
QBITTORRENT_HISTORY_LENGTH = 24


class QbittorrentApiClient:
    """封装 qBittorrent Web API 的认证和 JSON 请求。"""

    def __init__(self, address, username="", password="", timeout=5.0):
        """保存连接参数，并创建能够维持登录 Cookie 的请求器。"""
        self.address = str(address or "").strip().rstrip("/")
        self.username = str(username or "")
        self.password = str(password or "")
        self.timeout = max(0.1, float(timeout))
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )
        self.authenticated = False

    def _request(self, path, data=None):
        """请求指定 API 路径，并返回响应正文。"""
        encoded_data = None
        if data is not None:
            encoded_data = urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(
            self.address + path,
            data=encoded_data,
            headers={"Referer": self.address + "/"},
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8")

    def login(self):
        """使用配置的账号密码登录 qBittorrent Web API。"""
        try:
            result = self._request(
                "/api/v2/auth/login",
                {"username": self.username, "password": self.password},
            ).strip()
        except urllib.error.HTTPError as error:
            try:
                response_text = error.read().decode("utf-8", errors="replace")
            except (AttributeError, OSError):
                response_text = ""
            response_text = " ".join(response_text.split())[:200] or "无响应正文"
            raise RuntimeError(
                "qBittorrent Web API 登录失败：地址={}，账号={}，HTTP={} {}，响应={}".format(
                    self.address, self.username, error.code, error.reason, response_text
                )
            ) from error
        if not result:
            try:
                version = self._request("/api/v2/app/version").strip()
            except (OSError, urllib.error.URLError) as error:
                raise RuntimeError(
                    "qBittorrent Web API 登录返回空响应，且会话验证失败：地址={}，账号={}，原因={}".format(
                        self.address, self.username, error
                    )
                ) from error
            if version:
                LOGGER.info(
                    "qBittorrent 登录接口返回空响应，但 API 会话验证成功：版本=%s；可能已配置来源地址免登录",
                    version,
                )
                self.authenticated = True
                return
            raise RuntimeError(
                "qBittorrent Web API 登录返回空响应，且版本接口仍为空：地址={}，账号={}；请检查反向代理和 Web UI 身份验证设置".format(
                    self.address, self.username
                )
            )
        if result != "Ok.":
            response_text = " ".join(result.split())[:200] or "空响应"
            raise RuntimeError(
                "qBittorrent Web API 登录失败：地址={}，账号={}，服务器响应={}".format(
                    self.address, self.username, response_text
                )
            )
        self.authenticated = True

    def get_json(self, path):
        """读取 JSON 接口；会话失效时重新登录并重试一次。"""
        if not self.authenticated:
            self.login()
        for attempt in range(2):
            try:
                return json.loads(self._request(path))
            except urllib.error.HTTPError as error:
                if error.code not in (401, 403) or attempt:
                    raise
                self.authenticated = False
                self.login()
        return None

    def collect(self):
        """读取全局传输信息、用户统计和全部种子列表。"""
        transfer = self.get_json("/api/v2/transfer/info")
        main_data = self.get_json("/api/v2/sync/maindata?rid=0") or {}
        torrents = self.get_json("/api/v2/torrents/info?filter=all")
        return transfer, main_data.get("server_state", {}), torrents


class QbittorrentMonitor:
    """在后台定时采集 qBittorrent 指标，并提供线程安全快照。"""

    def __init__(self, address, username="", password="", interval=2.0, timeout=5.0):
        """初始化 API 客户端、速率历史和离线默认快照。"""
        self.client = QbittorrentApiClient(address, username, password, timeout)
        self.interval = max(0.5, float(interval))
        self.upload_history = deque([0] * QBITTORRENT_HISTORY_LENGTH, maxlen=QBITTORRENT_HISTORY_LENGTH)
        self.download_history = deque([0] * QBITTORRENT_HISTORY_LENGTH, maxlen=QBITTORRENT_HISTORY_LENGTH)
        self.lock = threading.Lock()
        self.value = self._empty_snapshot()
        self.started = False

    @staticmethod
    def _empty_snapshot():
        """创建尚未成功连接时使用的完整指标结构。"""
        return {
            "enabled": True, "online": False, "error": None,
            "connection_status": "disconnected",
            "upload_bps": 0, "download_bps": 0,
            "upload_history": [], "download_history": [],
            "uploaded_bytes": 0, "downloaded_bytes": 0,
            "free_space_bytes": 0,
            "user_statistics": {
                "alltime_uploaded_bytes": 0, "alltime_downloaded_bytes": 0,
                "alltime_share_ratio": 0, "session_wasted_bytes": 0,
                "connected_users": 0,
            },
            "torrents": {
                "all": 0, "downloading": 0, "seeding": 0, "completed": 0,
                "resumed": 0, "paused": 0, "active": 0, "inactive": 0,
                "paused_uploading": 0, "stalled_uploading": 0,
                "checking": 0, "errored": 0,
            },
        }

    def start(self):
        """启动唯一的守护采集线程。"""
        if self.started:
            return
        self.started = True
        threading.Thread(
            target=self._run, name="qBittorrent 指标采集", daemon=True
        ).start()

    def snapshot(self):
        """返回最近一次 qBittorrent 指标的独立副本。"""
        with self.lock:
            return json.loads(json.dumps(self.value))

    @classmethod
    def _torrent_counts(cls, torrents):
        """按照 qBittorrent 状态和进度汇总各类种子数量。"""
        counts = cls._empty_snapshot()["torrents"]
        counts["all"] = len(torrents)
        for torrent in torrents:
            state = str(torrent.get("state") or "")
            state_lower = state.lower()
            progress = float(torrent.get("progress") or 0)
            downloading = state in ("downloading", "metaDL", "forcedDL")
            # qBittorrent 的“做种”包含正在上传、等待连接、排队及强制上传。
            seeding = state in (
                "uploading", "stalledUP", "queuedUP", "forcedUP"
            )
            paused = state in ("pausedDL", "pausedUP", "stoppedDL", "stoppedUP")
            active = int(torrent.get("dlspeed") or 0) > 0 or int(torrent.get("upspeed") or 0) > 0
            counts["downloading"] += int(downloading)
            counts["seeding"] += int(seeding)
            counts["completed"] += int(progress >= 1)
            counts["paused"] += int(paused)
            counts["resumed"] += int(not paused)
            counts["active"] += int(active)
            counts["inactive"] += int(not active)
            counts["paused_uploading"] += int(state in ("pausedUP", "stoppedUP"))
            counts["stalled_uploading"] += int(state == "stalledUP")
            counts["checking"] += int("check" in state_lower)
            counts["errored"] += int(state in ("error", "missingFiles", "unknown"))
        return counts

    def _build_snapshot(self, transfer, server_state, torrents):
        """将 API 原始数据转换为稳定的监控协议字段。"""
        upload_bps = max(0, int(transfer.get("up_info_speed") or 0))
        download_bps = max(0, int(transfer.get("dl_info_speed") or 0))
        self.upload_history.append(upload_bps)
        self.download_history.append(download_bps)
        return {
            "enabled": True, "online": True, "error": None,
            "connection_status": str(
                server_state.get("connection_status") or "disconnected"
            ).lower(),
            "upload_bps": upload_bps, "download_bps": download_bps,
            "upload_history": list(self.upload_history),
            "download_history": list(self.download_history),
            "uploaded_bytes": max(0, int(transfer.get("up_info_data") or 0)),
            "downloaded_bytes": max(0, int(transfer.get("dl_info_data") or 0)),
            "free_space_bytes": max(0, int(transfer.get("free_space_on_disk") or 0)),
            "user_statistics": {
                "alltime_uploaded_bytes": max(0, int(server_state.get("alltime_ul") or 0)),
                "alltime_downloaded_bytes": max(0, int(server_state.get("alltime_dl") or 0)),
                "alltime_share_ratio": max(0, float(server_state.get("global_ratio") or 0)),
                "session_wasted_bytes": max(0, int(server_state.get("total_wasted_session") or 0)),
                "connected_users": max(0, int(server_state.get("total_peer_connections") or 0)),
            },
            "torrents": self._torrent_counts(torrents),
        }

    def _run(self):
        """循环采集 API，异常时发布离线状态并按周期重试。"""
        while True:
            started = time.monotonic()
            try:
                transfer, server_state, torrents = self.client.collect()
                value = self._build_snapshot(
                    transfer or {}, server_state or {}, torrents or []
                )
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
                LOGGER.warning("qBittorrent 指标采集失败：%s", error)
                with self.lock:
                    value = dict(self.value)
                value["online"] = False
                value["error"] = str(error)[:160]
            with self.lock:
                self.value = value
            time.sleep(max(0.1, self.interval - (time.monotonic() - started)))
