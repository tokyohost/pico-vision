"""Render the firmware boot and monitor connection screen."""

from config import BLACK, BLUE, DARK, GRAY, WHITE
from styles.style_plugins import register_style


# Compact 2:1 downsample of the supplied 72 px SVG. Seven indexed RGB565
# colors preserve its heart, face, paws and curled tail without storing a PNG.
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
    """Pixel-art splash screen shown until the first monitor snapshot arrives."""

    name = "boot"
    font_name = "native"
    width = 320
    height = 240
    landscape = True

    @staticmethod
    def create_dirty_regions():
        # Dirty views must fit the renderer's 40-line strip buffer.
        return [
            ("boot_{}".format(y), 0, y, 320, min(40, 240 - y))
            for y in range(0, 240, 40)
        ]

    @staticmethod
    def _draw_cat(canvas):
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
        progress = max(0, min(100, int(progress or 0)))
        x, y, width, height = 12, 216, 296, 10
        canvas.fill_rect(x, y, width, height, DARK)
        canvas.fill_rect(x + 2, y + 2, (width - 4) * progress // 100, height - 4, BLUE)
        canvas.text(12, 230, "{:3d}%".format(progress), GRAY)

    @classmethod
    def _draw(cls, canvas, snapshot):
        boot = snapshot.get("boot", {})
        canvas.clear(BLACK)
        canvas.text(12, 14, "OmniWatch", WHITE, 2)
        canvas.text(12, 38, "SYSTEM BOOT", GRAY)
        cls._draw_cat(canvas)
        logs = boot.get("logs") or ("BOOT:STARTING",)
        for index, log in enumerate(logs[-4:]):
            canvas.text(12, 141 + index * 13, str(log)[:49], GRAY)
        canvas.text(12, 198, str(boot.get("status", "loading..."))[:49], WHITE)
        cls._draw_progress(canvas, boot.get("progress", 0))

    @classmethod
    def draw_visible(cls, canvas, snapshot):
        cls._draw(canvas, snapshot)

    @classmethod
    def draw_dirty(cls, canvas, key, snapshot):
        cls._draw(canvas, snapshot)


def create_boot_style():
    return BootStyle()


register_style(BootStyle.name, create_boot_style)
