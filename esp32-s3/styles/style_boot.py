"""绘制固件启动和 Monitor 连接等待页面。"""

from config import BLACK, BLUE, DARK, GRAY, WHITE
from styles.style_plugins import register_style


# 使用紧凑字符矩阵保存猫咪像素图，避免在固件内存中加载 PNG。
CAT = (
    "..........OPPP................",
    "..........PPPP................",
    "...RBBB...PPP...RBB...........",
    "..BBCCBB.......BBCCB..........",
    "..BBPPCB......BLCPLB..........",
    "..BBPPPCBBBBBBCCPPLB..........",
    "..BBPPPCCCOCCOCCPPLBBBB.......",
    "..BBPPCCCOCOCOCCCPLBRRRBB.....",
    "..BBCCCCCCCCCCCCCCCBCCCCOBB...",
    "..BCCCCCCCCLCCCCCCCLCCOOOOBB..",
    ".BBCCCCCCCCCCCCCCCCCBCOOOCCB..",
    "RBCCCCBBBCCCCBBCCLPCBCCCCCCOB.",
    "BBPPPPBBWWWWWBBPPOPPBCCCCOOOBB",
    ".BPPPPPWWWWBWWOOPOPWBBCCCOOOOB",
    "BBWWOOWWWWWWWWWWOWCBCCCCCCLLLB",
    "BPBBWWWWWWWWWWWWLBBCCCCCLLLLLL",
    "BOCCBBLLBBBLLBBBBBCCCCCCLLLLLL",
    "BCCCCOBBWWWBBWWWWBCCCCLLLLLLLB",
    "BCCCCCOBWBBBBBBWLBCCCCLLLLOOPB",
    "BCCCLOOCBBBCCBBBBBBLLLLLLOOORR",
    "BOCCCCCCCCCCCCCCCCCCBBROPPORRR",
    "BBOCCCCCCCCCCCCCCCCLLLLLOPPRBB",
    "BBOOCCCCCCCCLCCOOLLLLLLLLORRBB",
    ".BOOCCCCOOOOLLOOOOLLPPLLLRRRB.",
    "..BOOPOOOOOOOOOOOOOOPPPPPRRB..",
    "...BOOOPPPPPPPPRRPPPRRRPPPB...",
    "...OBBBBPPPPPPPPPPPPRRBBBB....",
    ".......PBBBBBBBBBBBBBB........",
)

BROWN = 0xA244
CREAM = 0xFFBA
LIGHT_CREAM = 0xFF76
ORANGE = 0xFE31
PEACH = 0xFDCF
RUST = 0xE48C
CAT_COLORS = {
    "B": BROWN, "C": CREAM, "L": LIGHT_CREAM, "O": ORANGE,
    "P": PEACH, "R": RUST, "W": WHITE,
}


class BootStyle:
    """在收到首份 Monitor 快照前展示像素风格系统启动页。"""

    name = "boot"
    zh_name = "系统启动页"
    type = "builtin"
    idle = False
    font_name = "native"
    width = 320
    height = 240
    landscape = True

    @staticmethod
    def create_dirty_regions():
        """创建适配四十行条带缓冲区的启动页脏区。"""
        return [
            ("boot_{}".format(y), 0, y, 320, min(40, 240 - y))
            for y in range(0, 240, 40)
        ]

    @staticmethod
    def _draw_cat(canvas):
        """在启动页右上角绘制猫咪像素图。"""
        pixel = 2
        left = 248
        top = 8
        for row, line in enumerate(CAT):
            for column, value in enumerate(line):
                color = CAT_COLORS.get(value)
                if color is not None:
                    canvas.fill_rect(
                        left + column * pixel,
                        top + row * pixel,
                        pixel,
                        pixel,
                        color,
                    )

    @staticmethod
    def _draw_progress(canvas, progress):
        """绘制启动进度条和百分比。"""
        progress = max(0, min(100, int(progress or 0)))
        x, y, width, height = 12, 216, 296, 10
        canvas.fill_rect(x, y, width, height, DARK)
        canvas.fill_rect(x + 2, y + 2, (width - 4) * progress // 100, height - 4, BLUE)
        canvas.text(12, 230, "{:3d}%".format(progress), GRAY)

    @staticmethod
    def _wifi_lines(wifi):
        """把 Wi-Fi 状态转换为固定展示的四行英文信息。"""
        if not isinstance(wifi, dict) or not wifi.get("enabled"):
            return ()
        available = bool(wifi.get("available"))
        connected = bool(wifi.get("connected"))
        ssid = wifi.get("ssid") or "NOT SET"
        error = wifi.get("error")
        if not available:
            state = "UNAVAILABLE"
        elif connected:
            state = "CONNECTED"
        elif error:
            state = "ERROR"
        elif wifi.get("ssid"):
            state = "CONNECTING"
        else:
            state = "CONFIG REQUIRED"
        rssi = wifi.get("rssi")
        if connected and rssi is not None:
            state += "  RSSI:{}".format(rssi)
        ip = wifi.get("ip") or ("ACQUIRING" if wifi.get("ssid") else "NOT CONNECTED")
        port = wifi.get("websocket_port") or 8765
        path = wifi.get("websocket_path") or "/pv1"
        websocket_state = "CLIENT" if wifi.get("websocket_connected") else "WAITING"
        websocket = "{}:{}{} {}".format(ip, port, path, websocket_state)
        detail = str(error) if error else "IP: {}".format(ip)
        return (
            "WIFI: " + state,
            "SSID: " + str(ssid),
            detail,
            "WS: " + websocket,
        )

    @classmethod
    def _draw(cls, canvas, snapshot):
        """完整绘制启动页、固定 Wi-Fi 区域和滚动日志区域。"""
        boot = snapshot.get("boot", {})
        canvas.clear(BLACK)
        canvas.text(12, 14, "OmniWatch", WHITE, 2)
        canvas.text(12, 38, "SYSTEM BOOT", GRAY)
        cls._draw_cat(canvas)
        for index, line in enumerate(cls._wifi_lines(boot.get("wifi"))):
            canvas.text(12, 76 + index * 13, str(line)[:49], WHITE if index == 0 else GRAY)
        logs = boot.get("logs") or ("BOOT:STARTING",)
        for index, log in enumerate(logs[-4:]):
            canvas.text(12, 141 + index * 13, str(log)[:49], GRAY)
        canvas.text(12, 198, str(boot.get("status", "loading..."))[:49], WHITE)
        cls._draw_progress(canvas, boot.get("progress", 0))

    @classmethod
    def draw_visible(cls, canvas, snapshot):
        """绘制当前可见的完整启动页面。"""
        cls._draw(canvas, snapshot)

    @classmethod
    def draw_dirty(cls, canvas, key, snapshot):
        """脏区刷新时重绘完整启动页面内容。"""
        cls._draw(canvas, snapshot)


def create_boot_style():
    """创建系统启动页样式实例。"""
    return BootStyle()


register_style(BootStyle.name, create_boot_style)
