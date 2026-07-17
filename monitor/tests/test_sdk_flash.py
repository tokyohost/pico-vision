"""验证 ESP32-S3 SDK 镜像校验和 ROM USB 端口选择。"""

import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sdk_flash import (
    ESP32_S3_APPLICATION_OFFSET,
    ESP32_S3_PARTITION_TABLE_OFFSET,
    inspect_sdk_image,
    is_espressif_usb_port,
    run_esptool_flash,
    select_esp32s3_bootloader_port,
    serial_port_signature,
)


def build_sdk_image(chip_id=9, include_factory=True):
    """构造满足测试所需最小结构的 ESP32-S3 合并镜像。"""
    content = bytearray(b"\xff" * (ESP32_S3_APPLICATION_OFFSET + 64))
    for offset in (0, ESP32_S3_APPLICATION_OFFSET):
        content[offset] = 0xE9
        struct.pack_into("<H", content, offset + 12, chip_id)
    entries = [
        (0x50AA, 1, 2, 0x9000, 0x6000, b"nvs", 0),
    ]
    if include_factory:
        entries.append((
            0x50AA,
            0,
            0,
            ESP32_S3_APPLICATION_OFFSET,
            0x3F0000,
            b"factory",
            0,
        ))
    table_offset = ESP32_S3_PARTITION_TABLE_OFFSET
    for index, entry in enumerate(entries):
        magic, partition_type, subtype, offset, size, label, flags = entry
        struct.pack_into(
            "<HBBII16sI",
            content,
            table_offset + index * 32,
            magic,
            partition_type,
            subtype,
            offset,
            size,
            label.ljust(16, b"\0"),
            flags,
        )
    version = b"MPY version : v1.0.61-fnProcotolV1 on 2026-07-15\0"
    content[0x200:0x200 + len(version)] = version
    return bytes(content)


class SdkImageValidationTest(unittest.TestCase):
    """确认只有完整 ESP32-S3 合并镜像能够进入刷写阶段。"""

    def setUp(self):
        """创建每项测试独占的临时目录。"""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

    def write_image(self, content, name="sdk.bin"):
        """把指定镜像内容写入临时 bin 并返回路径。"""
        path = Path(self.temporary_directory.name) / name
        path.write_bytes(content)
        return path

    def test_valid_merged_image_reports_version_hash_and_partitions(self):
        """合法镜像应返回版本、摘要及 factory 分区信息。"""
        information = inspect_sdk_image(self.write_image(build_sdk_image()))

        self.assertEqual("v1.0.61-fnProcotolV1", information.sdk_version)
        self.assertEqual(64, len(information.sha256))
        self.assertIn("factory", [item.label for item in information.partitions])

    def test_wrong_chip_image_is_rejected(self):
        """目标芯片不是 ESP32-S3 时必须在连接设备前拒绝。"""
        with self.assertRaisesRegex(ValueError, "不是 ESP32-S3"):
            inspect_sdk_image(self.write_image(build_sdk_image(chip_id=5)))

    def test_image_without_factory_partition_is_rejected(self):
        """缺少 factory 应用的普通片段不能按 0x0 整包刷写。"""
        with self.assertRaisesRegex(ValueError, "缺少 factory"):
            inspect_sdk_image(self.write_image(build_sdk_image(include_factory=False)))

    def test_non_bin_file_is_rejected(self):
        """非 bin 扩展名不能进入受控 SDK 刷写流程。"""
        with self.assertRaisesRegex(ValueError, "只能选择"):
            inspect_sdk_image(self.write_image(build_sdk_image(), "sdk.uf2"))

    def test_esptool_uses_fixed_chip_address_and_controlled_reset_policy(self):
        """刷写器必须固定 ESP32-S3、0x0 地址并禁止再次切换启动引脚。"""
        image = self.write_image(build_sdk_image())
        esptool = SimpleNamespace(main=mock.Mock())

        with mock.patch.dict(sys.modules, {"esptool": esptool}):
            self.assertEqual(0, run_esptool_flash("COM11", image))

        arguments = esptool.main.call_args.args[0]
        self.assertEqual("esp32s3", arguments[arguments.index("--chip") + 1])
        self.assertEqual("no-reset", arguments[arguments.index("--before") + 1])
        self.assertEqual("watchdog-reset", arguments[arguments.index("--after") + 1])
        self.assertEqual(["write-flash", "0x0"], arguments[-3:-1])

    def test_esptool_can_use_default_reset_for_manual_force_flash(self):
        """手动强刷入口可让 esptool 控制所选串口进入下载模式。"""
        image = self.write_image(build_sdk_image())
        esptool = SimpleNamespace(main=mock.Mock())

        with mock.patch.dict(sys.modules, {"esptool": esptool}):
            self.assertEqual(0, run_esptool_flash("COM11", image, before="default-reset"))

        arguments = esptool.main.call_args.args[0]
        self.assertEqual("default-reset", arguments[arguments.index("--before") + 1])

    def test_esptool_rejects_unknown_reset_policy(self):
        """未知进入下载模式策略必须在调用 esptool 前失败。"""
        image = self.write_image(build_sdk_image())

        with self.assertRaisesRegex(ValueError, "不支持"):
            run_esptool_flash("COM11", image, before="unsafe-reset")


class SdkBootloaderPortSelectionTest(unittest.TestCase):
    """验证多串口环境按物理位置选择目标 ROM USB 端口。"""

    @staticmethod
    def port(device, vid, pid, location="", serial_number=""):
        """构造 pyserial 串口枚举结果的轻量测试替身。"""
        return SimpleNamespace(
            device=device,
            vid=vid,
            pid=pid,
            location=location,
            serial_number=serial_number,
        )

    def test_same_usb_location_has_priority_over_other_espressif_devices(self):
        """多个 Espressif 设备存在时应匹配刷写前的物理 USB 位置。"""
        source = self.port("COM7", 0x1209, 1, location="1-3")
        other = self.port("COM10", 0x303A, 0x1001, location="1-4")
        target = self.port("COM11", 0x303A, 0x1001, location="1-3")

        selected = select_esp32s3_bootloader_port(
            [other, target],
            source,
            [serial_port_signature(source)],
        )

        self.assertEqual("COM11", selected.device)

    def test_only_espressif_native_usb_port_is_eligible(self):
        """CH343 等 USB-UART 串口不能进入仅支持原生 USB 的刷写流程。"""
        native = self.port("COM7", 0x303A, 0x1001, location="1-3")
        uart = self.port("COM8", 0x1A86, 0x55D4, location="1-4")

        self.assertTrue(is_espressif_usb_port("com7", [native, uart]))
        self.assertFalse(is_espressif_usb_port("COM8", [native, uart]))

    def test_ambiguous_existing_espressif_ports_are_not_guessed(self):
        """无法关联目标的多个旧端口必须返回空，避免刷错设备。"""
        first = self.port("COM10", 0x303A, 0x1001, location="1-4")
        second = self.port("COM11", 0x303A, 0x1001, location="1-5")
        previous = [serial_port_signature(first), serial_port_signature(second)]

        self.assertIsNone(
            select_esp32s3_bootloader_port([first, second], None, previous)
        )

    def test_unchanged_single_espressif_port_is_not_reused(self):
        """唯一候选未发生重枚举时也不能把其他设备或旧端口当作目标。"""
        existing = self.port("COM10", 0x303A, 0x1001, location="1-4")

        self.assertIsNone(
            select_esp32s3_bootloader_port(
                [existing],
                None,
                [serial_port_signature(existing)],
            )
        )

    def test_multiple_new_espressif_ports_without_identity_are_rejected(self):
        """多个同时出现的新 ROM 端口缺少目标特征时必须拒绝猜测。"""
        first = self.port("COM10", 0x303A, 0x1001, location="1-4")
        second = self.port("COM11", 0x303A, 0x1001, location="1-5")

        self.assertIsNone(
            select_esp32s3_bootloader_port([first, second], None, ())
        )


if __name__ == "__main__":
    unittest.main()
