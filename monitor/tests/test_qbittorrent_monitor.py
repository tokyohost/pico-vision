"""验证 qBittorrent Web API 指标采集和状态汇总。"""

import sys
import unittest
from pathlib import Path


MONITOR_ROOT = Path(__file__).resolve().parents[1]
if str(MONITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MONITOR_ROOT))

from qbittorrent_monitor import QbittorrentApiClient, QbittorrentMonitor


class QbittorrentMonitorTests(unittest.TestCase):
    """覆盖传输指标转换和主要种子状态计数。"""

    def test_build_snapshot_contains_transfer_and_history_metrics(self):
        """确认实时速率、累计流量、剩余空间和历史被完整输出。"""
        monitor = QbittorrentMonitor("http://127.0.0.1:8080")
        snapshot = monitor._build_snapshot(
            {
                "up_info_speed": 1024,
                "dl_info_speed": 2048,
                "up_info_data": 4096,
                "dl_info_data": 8192,
                "free_space_on_disk": 16384,
            },
            {
                "alltime_ul": 100000,
                "alltime_dl": 200000,
                "global_ratio": "0.5",
                "total_wasted_session": 3000,
                "total_peer_connections": 7,
            },
            [],
        )
        self.assertEqual(snapshot["upload_bps"], 1024)
        self.assertEqual(snapshot["download_bps"], 2048)
        self.assertEqual(snapshot["uploaded_bytes"], 4096)
        self.assertEqual(snapshot["downloaded_bytes"], 8192)
        self.assertEqual(snapshot["free_space_bytes"], 16384)
        self.assertEqual(snapshot["upload_history"][-1], 1024)
        self.assertEqual(snapshot["download_history"][-1], 2048)
        statistics = snapshot["user_statistics"]
        self.assertEqual(statistics["alltime_uploaded_bytes"], 100000)
        self.assertEqual(statistics["alltime_downloaded_bytes"], 200000)
        self.assertEqual(statistics["alltime_share_ratio"], 0.5)
        self.assertEqual(statistics["session_wasted_bytes"], 3000)
        self.assertEqual(statistics["connected_users"], 7)

    def test_torrent_counts_cover_qbittorrent_four_and_five_states(self):
        """确认兼容 qBittorrent 四版 paused 和五版 stopped 状态。"""
        counts = QbittorrentMonitor._torrent_counts([
            {"state": "downloading", "progress": 0.5, "dlspeed": 10, "upspeed": 0},
            {"state": "uploading", "progress": 1, "dlspeed": 0, "upspeed": 20},
            {"state": "pausedUP", "progress": 1},
            {"state": "stoppedDL", "progress": 0.2},
            {"state": "stalledUP", "progress": 1},
            {"state": "checkingDL", "progress": 0.6},
            {"state": "error", "progress": 0.1},
        ])
        self.assertEqual(counts["all"], 7)
        self.assertEqual(counts["downloading"], 1)
        self.assertEqual(counts["seeding"], 1)
        self.assertEqual(counts["completed"], 3)
        self.assertEqual(counts["paused"], 2)
        self.assertEqual(counts["resumed"], 5)
        self.assertEqual(counts["active"], 2)
        self.assertEqual(counts["inactive"], 5)
        self.assertEqual(counts["paused_uploading"], 1)
        self.assertEqual(counts["stalled_uploading"], 1)
        self.assertEqual(counts["checking"], 1)
        self.assertEqual(counts["errored"], 1)

    def test_login_failure_contains_safe_diagnostic_details(self):
        """确认登录失败包含地址、账号和响应，但不会泄露密码。"""
        client = QbittorrentApiClient(
            "http://127.0.0.1:8080", "admin", "secret-password"
        )
        client._request = lambda path, data=None: "Fails."

        with self.assertRaises(RuntimeError) as context:
            client.login()

        message = str(context.exception)
        self.assertIn("http://127.0.0.1:8080", message)
        self.assertIn("admin", message)
        self.assertIn("Fails.", message)
        self.assertNotIn("secret-password", message)

    def test_empty_login_response_accepts_verified_api_session(self):
        """确认免登录来源返回空正文时可通过版本接口验证会话。"""
        client = QbittorrentApiClient(
            "http://127.0.0.1:8080", "admin", "secret-password"
        )
        responses = {
            "/api/v2/auth/login": "",
            "/api/v2/app/version": "v5.0.0",
        }
        client._request = lambda path, data=None: responses[path]

        client.login()

        self.assertTrue(client.authenticated)


if __name__ == "__main__":
    unittest.main()
