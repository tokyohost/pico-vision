"""验证自定义屏幕标准模板符合固件条带画布约束。"""

import importlib.util
import sys
import unittest
from pathlib import Path

from style_validator import MAX_STYLE_FILE_SIZE, StyleFileValidator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PICO_ROOT = PROJECT_ROOT / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))


def _load_template_module():
    """从示例目录加载标准模板模块。"""
    path = PROJECT_ROOT / "monitor" / "example" / "style_template.py"
    specification = importlib.util.spec_from_file_location("tested_style_template", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class StyleTemplateTest(unittest.TestCase):
    """覆盖模板脏矩形容量和图表刷新选择。"""

    @classmethod
    def setUpClass(cls):
        """加载一次模板模块供全部测试复用。"""
        cls.template = _load_template_module().TemplateStyle

    def test_dirty_regions_fit_portrait_strip_canvas(self):
        """确认每个脏矩形均不超过竖屏四十行条带画布容量。"""
        capacity_pixels = 240 * 40
        for key, _x, _y, width, height in self.template.create_dirty_regions():
            self.assertLessEqual(
                width * height,
                capacity_pixels,
                "{} 脏矩形超过画布容量".format(key),
            )

    def test_history_change_refreshes_two_chart_regions(self):
        """确认历史数据变化时会刷新拆分后的上下图表区域。"""
        previous = {"cpu": {"history": [10]}}
        current = {"cpu": {"history": [20]}}

        regions = self.template.select_dirty_regions(previous, current)

        self.assertEqual(
            [region[0] for region in regions],
            ["cpu_history_top", "cpu_history_bottom"],
        )

    def test_template_passes_upload_validation_and_size_limit(self):
        """确认标准模板可直接通过上传校验且未超过统一文件上限。"""
        path = PROJECT_ROOT / "monitor" / "example" / "style_template.py"

        validated = StyleFileValidator().validate(path)

        self.assertEqual(validated.name, "template")
        self.assertLessEqual(len(validated.source), MAX_STYLE_FILE_SIZE)


if __name__ == "__main__":
    unittest.main()
