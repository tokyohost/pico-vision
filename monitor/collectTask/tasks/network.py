"""网络采集任务。"""

import time

from history import update_per_second

from ..system_tasks import CollectionTask


class NetworkTask(CollectionTask):
    """采集主通信网卡、速率、累计流量、IP 和网络延迟。"""

    name = "network"
    zh_name = "网络采集"
    default_interval = 1.0
    order = 40

    def collect(self):
        """返回网络顶层指标并维护上传下载历史序列。"""
        local_ip = self.collector._local_ip()
        network = self.collector._network_rates(local_ip)
        now = time.monotonic()
        for name, value in (("upload", network[0]), ("download", network[1])):
            update_per_second(
                self.collector.histories[name],
                round(value, 1),
                self.collector.history_states.setdefault(name, {}),
                now,
            )
        ping, online = self.collector.ping_monitor.snapshot()
        return {
            "network": {
                "upload_bps": network[0],
                "download_bps": network[1],
                "transmit_bytes": network[2],
                "receive_bytes": network[3],
                "link_speed_mbps": self.collector._network_link_speed(local_ip),
                "upload_history": list(self.collector.histories["upload"]),
                "download_history": list(self.collector.histories["download"]),
                "ping_ms": ping,
                "online": online,
                "ip": local_ip,
            }
        }
