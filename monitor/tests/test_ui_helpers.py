"""跨平台管理界面共享数据处理测试。"""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from monitor_core.ui_helpers import (
    DEFAULT_STYLE_CATALOG,
    extract_style_package,
    merge_wifi_networks,
    normalize_style_catalog,
    wifi_security_label,
    wifi_state_label,
)


class UiHelpersTest(unittest.TestCase):
    """验证共享逻辑脱离 Windows 模块后保持原有行为。"""

    def test_normalize_style_catalog_merges_valid_custom_style(self):
        """确认样式规范化会保留内置样式并合并合法自定义样式。"""
        catalog = normalize_style_catalog([
            {
                "name": "custom_demo",
                "chinese_name": "演示样式",
                "type": "custom",
                "idle": True,
            },
            {"name": "invalid", "type": "custom"},
        ])

        self.assertEqual(len(DEFAULT_STYLE_CATALOG) + 1, len(catalog))
        self.assertEqual("custom_demo", catalog[-1]["name"])
        self.assertTrue(catalog[-1]["idle"])

    def test_wifi_helpers_merge_and_label_networks(self):
        """确认 Wi-Fi 合并、排序及中文标签保持一致。"""
        networks = merge_wifi_networks(
            [
                {"ssid": "Guest", "rssi": -70, "security": 0},
                {"ssid": "Office", "rssi": -80, "security": 3},
                {"ssid": "Office", "rssi": -40, "security": 3},
            ],
            {"ssid": "Office", "connected": True, "rssi": -42},
        )

        self.assertEqual(["Office", "Guest"], [item["ssid"] for item in networks])
        self.assertEqual(-40, networks[0]["rssi"])
        self.assertEqual("已连接", wifi_state_label(networks[0]))
        self.assertEqual("开放", wifi_security_label(networks[1]["security"]))

    def test_extract_style_package_reads_valid_manifest(self):
        """确认平台无关的样式包解析器能够安全读取合法 ZIP。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_path = root / "style.zip"
            target = root / "target"
            target.mkdir()
            manifest = {"type": "style", "style": "style_demo.py"}
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr("plugin.json", json.dumps(manifest))
                archive.writestr("style_demo.py", "def draw():\n    pass\n")

            package = extract_style_package(package_path, target)

        self.assertEqual("style_demo.py", package["style"].name)
        self.assertIsNone(package["detail"])
        self.assertIsNone(package["preview"])


if __name__ == "__main__":
    unittest.main()
