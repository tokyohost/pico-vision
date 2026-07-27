"""验证 ESP32-S3 eFuse MAC 派生设备 UUID 的稳定性与格式。"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ESP32_ROOT = Path(__file__).resolve().parents[1]
if str(ESP32_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_ROOT))

import device_identity  # noqa: E402


class DeviceIdentityTest(unittest.TestCase):
    """验证设备 UUID 仅由芯片 eFuse MAC 稳定派生。"""

    def setUp(self):
        """清空模块缓存，确保每个用例独立验证首次生成过程。"""
        device_identity._DEVICE_UUID = None

    def test_device_uuid_uses_sha256_and_rfc_uuid_v8_format(self):
        """确认固定 eFuse MAC 生成确定的 UUID v8 且不暴露原始 MAC。"""
        machine = types.SimpleNamespace(
            unique_id=mock.Mock(return_value=bytes.fromhex("aabbccddeeff"))
        )

        with mock.patch.dict(sys.modules, {"machine": machine}):
            value = device_identity.device_uuid()

        self.assertEqual("17226b1f-68ae-8acd-af07-46450f642874", value)
        self.assertNotIn("aabbccddeeff", value.replace("-", ""))
        machine.unique_id.assert_called_once_with()

    def test_device_uuid_is_cached_after_first_efuse_read(self):
        """确认重复握手复用 UUID，不重复读取芯片唯一标识。"""
        machine = types.SimpleNamespace(unique_id=mock.Mock(return_value=b"\x01\x02\x03\x04\x05\x06"))

        with mock.patch.dict(sys.modules, {"machine": machine}):
            first = device_identity.device_uuid()
            second = device_identity.device_uuid()

        self.assertEqual(first, second)
        machine.unique_id.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
