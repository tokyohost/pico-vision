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


"""在两次 Monitor 校准之间持续推进当前时间与系统运行时间。"""


import time


class TimeIncrease:
    """依据单调时钟推进快照时间，并仅在误差超限时重新校准。"""

    def __init__(self, calibration_snapshots=5, tolerance_seconds=2):
        """初始化校准周期、允许误差和本地时间基准。"""
        self._calibration_snapshots = max(1, int(calibration_snapshots))
        self._tolerance_seconds = max(0, int(tolerance_seconds))
        self.reset()

    def reset(self):
        """清除已有时间基准，使下一份有效快照立即完成校准。"""
        self._snapshot_count = 0
        self._base_ticks = None
        self._timestamp_parts = None
        self._timestamp_suffix = ""
        self._uptime_seconds = None
        self._last_elapsed_seconds = None
        self._last_timestamp = None
        self._last_uptime_seconds = None

    def receive(self, snapshot):
        """接收 Monitor 快照，并在本地推进误差超过阈值时校准。"""
        if not isinstance(snapshot, dict):
            return snapshot
        self._snapshot_count += 1
        should_calibrate = self._base_ticks is None
        if not should_calibrate:
            should_calibrate = self._uptime_error_exceeded(snapshot)
        if should_calibrate:
            self._calibrate(snapshot)
        return self.increase(snapshot)

    def increase(self, snapshot):
        """按照校准后经过的整秒数更新快照中的两个时间字段。"""
        if not isinstance(snapshot, dict) or self._base_ticks is None:
            return snapshot
        elapsed_seconds = max(
            0,
            time.ticks_diff(time.ticks_ms(), self._base_ticks) // 1000,
        )
        if elapsed_seconds == self._last_elapsed_seconds:
            if self._last_timestamp is not None:
                snapshot["timestamp"] = self._last_timestamp
            if self._last_uptime_seconds is not None:
                snapshot["uptime_seconds"] = self._last_uptime_seconds
            return snapshot
        if self._timestamp_parts is not None:
            self._last_timestamp = self._format_timestamp(elapsed_seconds)
            snapshot["timestamp"] = self._last_timestamp
        if self._uptime_seconds is not None:
            self._last_uptime_seconds = self._uptime_seconds + elapsed_seconds
            snapshot["uptime_seconds"] = self._last_uptime_seconds
        self._last_elapsed_seconds = elapsed_seconds
        return snapshot

    def next_refresh_ms(self, interval_ms=1000, now_ms=None):
        """返回相对校准基准对齐的下一次绝对刷新时刻。"""
        interval_ms = max(1, int(interval_ms))
        if now_ms is None:
            now_ms = time.ticks_ms()
        if self._base_ticks is None:
            return time.ticks_add(now_ms, interval_ms)
        elapsed_ms = max(0, time.ticks_diff(now_ms, self._base_ticks))
        next_elapsed_ms = (elapsed_ms // interval_ms + 1) * interval_ms
        return time.ticks_add(self._base_ticks, next_elapsed_ms)

    def _uptime_error_exceeded(self, snapshot):
        """判断主机运行时间与 Pico 单调时钟推进结果是否相差超过阈值。"""
        try:
            received_uptime = max(0, int(snapshot.get("uptime_seconds")))
        except (TypeError, ValueError):
            return (
                self._snapshot_count % self._calibration_snapshots == 0
            )
        if self._uptime_seconds is None:
            return True
        elapsed_seconds = max(
            0,
            time.ticks_diff(time.ticks_ms(), self._base_ticks) // 1000,
        )
        expected_uptime = self._uptime_seconds + elapsed_seconds
        return abs(received_uptime - expected_uptime) > self._tolerance_seconds

    def _calibrate(self, snapshot):
        """从有效 Monitor 字段记录当前时间、运行时间和单调时钟基准。"""
        timestamp_parts, timestamp_suffix = self._parse_timestamp(
            snapshot.get("timestamp")
        )
        try:
            uptime_seconds = max(0, int(snapshot.get("uptime_seconds")))
        except (TypeError, ValueError):
            uptime_seconds = None
        if timestamp_parts is None and uptime_seconds is None:
            return
        self._base_ticks = time.ticks_ms()
        self._last_elapsed_seconds = None
        self._last_timestamp = None
        self._last_uptime_seconds = None
        if timestamp_parts is not None:
            self._timestamp_parts = timestamp_parts
            self._timestamp_suffix = timestamp_suffix
        if uptime_seconds is not None:
            self._uptime_seconds = uptime_seconds

    @staticmethod
    def _parse_timestamp(value):
        """解析 Monitor 的 ISO 时间，返回日历字段及原始时区后缀。"""
        if not isinstance(value, str) or len(value) < 19:
            return None, ""
        try:
            parts = (
                int(value[0:4]),
                int(value[5:7]),
                int(value[8:10]),
                int(value[11:13]),
                int(value[14:16]),
                int(value[17:19]),
            )
        except (TypeError, ValueError):
            return None, ""
        year, month, day, hour, minute, second = parts
        if (
            value[4:5] != "-"
            or value[7:8] != "-"
            or value[10:11] not in ("T", " ")
            or value[13:14] != ":"
            or value[16:17] != ":"
            or month < 1
            or month > 12
            or day < 1
            or day > TimeIncrease._days_in_month(year, month)
            or hour < 0
            or hour > 23
            or minute < 0
            or minute > 59
            or second < 0
            or second > 59
        ):
            return None, ""
        return parts, value[19:]

    def _format_timestamp(self, elapsed_seconds):
        """将经过秒数叠加到校准日历时间并生成 ISO 时间字符串。"""
        year, month, day, hour, minute, second = self._timestamp_parts
        seconds_of_day = hour * 3600 + minute * 60 + second + elapsed_seconds
        day_increment, seconds_of_day = divmod(seconds_of_day, 86400)
        day += day_increment
        while day > self._days_in_month(year, month):
            day -= self._days_in_month(year, month)
            month += 1
            if month > 12:
                month = 1
                year += 1
        hour, remainder = divmod(seconds_of_day, 3600)
        minute, second = divmod(remainder, 60)
        return (
            "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}{}".format(
                year,
                month,
                day,
                hour,
                minute,
                second,
                self._timestamp_suffix,
            )
        )

    @staticmethod
    def _days_in_month(year, month):
        """返回指定年月的天数，并正确处理公历闰年。"""
        if month == 2:
            is_leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
            return 29 if is_leap else 28
        return 30 if month in (4, 6, 9, 11) else 31
