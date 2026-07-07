"""验证自定义屏幕样式文件的 Monitor 端校验规则。"""

import tempfile
import unittest
from pathlib import Path

from style_validator import StyleFileValidator


VALID_STYLE_SOURCE = '''\
from styles.style_plugins import register_style

class ClockStyle:
    """测试使用的完整自定义样式类。"""
    name = "clock"
    zh_name = "时钟"
    type = "custom"

    def create_dirty_regions(self):
        return []

    def draw_visible(self, canvas, snapshot):
        pass

    def draw_dirty(self, canvas, snapshot, key):
        pass

def create_clock_style():
    return ClockStyle()

register_style(ClockStyle.name, create_clock_style)
'''


class StyleFileValidatorTest(unittest.TestCase):
    """覆盖样式元数据、方法、注册名和编码校验。"""

    def _write_style(self, content=VALID_STYLE_SOURCE, filename="style_clock.py"):
        """在临时目录写入待校验样式并返回路径。"""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / filename
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return path

    def test_valid_class_style_returns_upload_metadata(self):
        """确认完整样式类会返回上传所需的英文样式名和文件名。"""
        result = StyleFileValidator().validate(self._write_style())

        self.assertEqual("clock", result.name)
        self.assertEqual("时钟", result.chinese_name)
        self.assertEqual("style_clock.py", result.filename)

    def test_missing_required_method_is_rejected(self):
        """确认缺少必要绘制方法的样式类会被拒绝。"""
        source = VALID_STYLE_SOURCE.replace(
            "    def draw_dirty(self, canvas, snapshot, key):\n        pass\n",
            "",
        )

        with self.assertRaisesRegex(ValueError, "draw_dirty"):
            StyleFileValidator().validate(self._write_style(source))

    def test_conflicting_registered_style_name_is_rejected(self):
        """确认注册调用不能返回与类元数据冲突的样式名。"""
        source = VALID_STYLE_SOURCE.replace(
            "register_style(ClockStyle.name, create_clock_style)",
            'register_style("other", create_clock_style)',
        )

        with self.assertRaisesRegex(ValueError, "register_style"):
            StyleFileValidator().validate(self._write_style(source))

    def test_filename_must_match_class_style_name(self):
        """确认上传文件名必须遵循 style_样式名.py 约定。"""
        with self.assertRaisesRegex(ValueError, "style_clock.py"):
            StyleFileValidator().validate(self._write_style(filename="style_other.py"))

    def test_utf8_bom_is_rejected(self):
        """确认带 UTF-8 BOM 的样式文件不能进入上传流程。"""
        source = b"\xef\xbb\xbf" + VALID_STYLE_SOURCE.encode("utf-8")

        with self.assertRaisesRegex(ValueError, "BOM"):
            StyleFileValidator().validate(self._write_style(source))


if __name__ == "__main__":
    unittest.main()
