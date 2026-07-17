"""绘制像素终端风格的系统待机时钟页面。"""

from config import BLACK, WHITE
from styles.style_plugins import register_style


SCREEN_WIDTH = 320
SCREEN_HEIGHT = 240
ACCENT = 0x27DC
IDLE_GREEN = 0x47F5
PANEL_BORDER = 0x31A8
DIM_TEXT = 0x632C
GHOST_TEXT = 0x18E4
WEEKDAYS = ("星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六")


class IdleStyle:
    """展示最后一次接收时间，未接收过 JSON 时展示连接等待提示。"""

    name = "idle"
    zh_name = "像素待机时钟"
    type = "builtin"
    idle = True
    font_name = "screen_2inch"
    width = SCREEN_WIDTH
    height = SCREEN_HEIGHT
    landscape = True

    @staticmethod
    def create_dirty_regions():
        """创建覆盖整屏条带的待机刷新区域。"""
        return [
            ("idle_{}".format(y), 0, y, SCREEN_WIDTH, min(40, SCREEN_HEIGHT - y))
            for y in range(0, SCREEN_HEIGHT, 40)
        ]

    @staticmethod
    def _timestamp_parts(snapshot):
        """从快照中读取合法的日期和秒级时间。"""
        timestamp = str((snapshot or {}).get("timestamp") or "")
        if len(timestamp) < 16:
            return None
        try:
            year = int(timestamp[0:4])
            month = int(timestamp[5:7])
            day = int(timestamp[8:10])
            hour = int(timestamp[11:13])
            minute = int(timestamp[14:16])
            second = int(timestamp[17:19]) if len(timestamp) >= 19 else 0
        except (TypeError, ValueError):
            return None
        if not (
            1 <= month <= 12
            and 1 <= day <= 31
            and 0 <= hour <= 23
            and 0 <= minute <= 59
            and 0 <= second <= 59
        ):
            return None
        return year, month, day, hour, minute, second, "{:02d}:{:02d}:{:02d}".format(hour, minute, second)

    @staticmethod
    def _weekday(year, month, day):
        """使用公历日期计算中文星期文本。"""
        offsets = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
        adjusted_year = year - 1 if month < 3 else year
        index = (
            adjusted_year
            + adjusted_year // 4
            - adjusted_year // 100
            + adjusted_year // 400
            + offsets[month - 1]
            + day
        ) % 7
        return WEEKDAYS[index]

    @staticmethod
    def _center_text(canvas, y, value, color, scale=1, font_name=None):
        """在横向中心绘制指定文字。"""
        width = canvas.text_width(value, scale, font_name=font_name)
        canvas.text((SCREEN_WIDTH - width) // 2, y, value, color, scale, font_name=font_name)

    @staticmethod
    def _clip_text(canvas, value, max_width, scale=1, font_name=None):
        """将文本裁剪到指定像素宽度，避免右上角状态溢出。"""
        text = str(value or "")
        while text and canvas.text_width(text, scale, font_name=font_name) > max_width:
            text = text[:-1]
        return text

    @staticmethod
    def _wifi_status(snapshot):
        """从待机快照中提取 Wi-Fi 连接状态。"""
        if not isinstance(snapshot, dict):
            return {}
        wifi = snapshot.get("wifi")
        if isinstance(wifi, dict):
            return wifi
        boot = snapshot.get("boot")
        if isinstance(boot, dict) and isinstance(boot.get("wifi"), dict):
            return boot.get("wifi")
        return {}

    @classmethod
    def _draw_header(cls, canvas, snapshot):
        """绘制品牌和右上角 Wi-Fi 状态。"""
        canvas.text(8, 8, "OMNIWATCH", WHITE)
        wifi = cls._wifi_status(snapshot)
        connected = bool(wifi.get("connected"))
        color = IDLE_GREEN if connected else DIM_TEXT
        if connected:
            rssi = wifi.get("rssi")
            ssid = wifi.get("ssid") or "ON"
            label = "WIFI {}dBm {}".format(rssi, ssid) if rssi is not None else "WIFI {}".format(ssid)
        else:
            label = "WIFI OFF"
        label = cls._clip_text(canvas, label.strip(), 208)
        text_x = SCREEN_WIDTH - 8 - canvas.text_width(label)
        canvas.fill_rect(max(104, text_x - 12), 9, 7, 7, color)
        canvas.text(text_x, 8, label, WHITE if connected else DIM_TEXT)

    @classmethod
    def _draw_clock(cls, canvas, parts):
        """绘制大时钟、日期、中文星期和分钟内秒进度。"""
        year, month, day, hour, minute, second, clock_with_seconds = parts
        clock = "{:02d}:{:02d}".format(hour, minute)
        canvas.text(197, 34, "{:02d}".format(minute), GHOST_TEXT, 7)
        cls._center_text(canvas, 43, clock, WHITE, 5)
        canvas.text(12, 121, "{:04d} / {:02d} / {:02d}".format(year, month, day), WHITE)
        weekday = cls._weekday(year, month, day)
        canvas.text(244, 117, weekday, WHITE, font_name="wqy_8x16")
        canvas.text(12, 143, "0", DIM_TEXT)
        canvas.text(292, 143, "60", DIM_TEXT)
        canvas.fill_rect(31, 147, 260, 2, PANEL_BORDER)
        canvas.fill_rect(31, 147, 260 * second // 60, 2, ACCENT)
        return clock_with_seconds or clock

    @classmethod
    def _draw_waiting(cls, canvas):
        """在没有任何 JSON 时间基准时绘制连接等待提示。"""
        cls._center_text(canvas, 66, "WAITTING CONNECT", WHITE, 2)
        cls._center_text(canvas, 104, "NO TIME DATA", DIM_TEXT)
        canvas.fill_rect(31, 147, 260, 2, PANEL_BORDER)
        return "--:--:--"

    @staticmethod
    def _draw_log_panel(canvas, has_time, clock):
        """绘制参考图底部的三行待机状态日志。"""
        top = 164
        canvas.fill_rect(0, top, SCREEN_WIDTH, SCREEN_HEIGHT - top, 0x0022)
        canvas.line(0, top, SCREEN_WIDTH - 1, top, PANEL_BORDER)
        canvas.line(0, SCREEN_HEIGHT - 1, SCREEN_WIDTH - 1, SCREEN_HEIGHT - 1, PANEL_BORDER)
        canvas.line(0, top, 0, SCREEN_HEIGHT - 1, PANEL_BORDER)
        canvas.line(SCREEN_WIDTH - 1, top, SCREEN_WIDTH - 1, SCREEN_HEIGHT - 1, PANEL_BORDER)
        canvas.text(12, 169, "SYSTEM LOG", DIM_TEXT)
        if has_time:
            rows = (
                (IDLE_GREEN, clock + "  Snapshot received", WHITE),
                (IDLE_GREEN, "Clock running locally", DIM_TEXT),
                (IDLE_GREEN, "Waiting next JSON", DIM_TEXT),
            )
        else:
            rows = (
                (IDLE_GREEN, "NO SNAPSHOT RECEIVED", WHITE),
                (IDLE_GREEN, "USB / WIFI STANDBY", DIM_TEXT),
                (IDLE_GREEN, "WAITING FOR MONITOR", DIM_TEXT),
            )
        for index, (bullet_color, text, text_color) in enumerate(rows):
            y = 187 + index * 16
            canvas.fill_rect(12, y + 2, 6, 6, bullet_color)
            canvas.text(25, y, text, text_color)
        canvas.text(286, 224, "IDLE", IDLE_GREEN)

    @classmethod
    def _draw(cls, canvas, snapshot):
        """完整绘制待机页面。"""
        canvas.clear(BLACK)
        cls._draw_header(canvas, snapshot)
        parts = cls._timestamp_parts(snapshot)
        clock = cls._draw_clock(canvas, parts) if parts else cls._draw_waiting(canvas)
        cls._draw_log_panel(canvas, parts is not None, clock)

    @classmethod
    def draw_visible(cls, canvas, snapshot):
        """绘制当前可见条带中的待机页面内容。"""
        cls._draw(canvas, snapshot)

    @classmethod
    def draw_dirty(cls, canvas, key, snapshot):
        """刷新指定待机条带。"""
        del key
        cls._draw(canvas, snapshot)


def create_idle_style():
    """创建像素待机时钟样式实例。"""
    return IdleStyle()


register_style(IdleStyle.name, create_idle_style)
