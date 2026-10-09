"""验证量产版本选择、设备分组、分支决策与失败时的禁止写入行为。"""

import importlib.util
from pathlib import Path
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile


SPEC = importlib.util.spec_from_file_location("production_gui", Path(__file__).resolve().parents[1] / "production_gui.py")
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)


def make_port(device="COM7", location="1-3:1.0", vid=0x303A):
    """构造无需真实串口的 USB 枚举对象。"""
    return SimpleNamespace(device=device, location=location, serial_number="abc", vid=vid)


class ProductionTests(unittest.TestCase):
    """覆盖量产中可能误选固件或误刷设备的重要边界。"""

    def setUp(self):
        """为每项测试创建独立配置和设备响应。"""
        self.worker = APP.ProductionWorker(Path("source"), queue.Queue())
        self.info = {"platform": "esp32", "machine": "ESP32S3", "sdk": True, "id": "a1", "version": "1.0.69"}
        self.config = (Path("sdk-N16R8-v1.0.69.bin"), "esp32s3", 460800, "0x0")

    def test_numeric_version_and_hardware_family(self):
        """最高版本按数字选择，忽略其他内存规格和官方固件。"""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            names = ["sdk-N16R8-v1.0.9.bin", "sdk-N16R8-v1.0.100.bin", "sdk-N8R8-v9.9.9.bin", "official-v99.0.0.bin"]
            for name in names:
                (root / name).touch()
            script = root / "flash.sh"
            script.write_text('py -m esptool --chip esp32s3 --port COM37 --baud 460800 write_flash 0x0 "N:\\old path\\sdk-N16R8-v1.0.9.bin"', encoding="utf-8-sig")
            self.assertEqual(APP.select_sdk(script)[0].name, names[1])

    def test_unsupported_chip_rejected(self):
        """其他 ESP32 型号不能复用 S3 的固件与代码库。"""
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "flash.sh"
            script.write_text("py -m esptool --chip esp32 --baud 460800 write_flash 0x0 sdk-v1.0.bin", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ESP32-S3"):
                APP.select_sdk(script)

    def test_manual_sdk_keeps_flash_parameters(self):
        """手动 SDK 应覆盖自动版本，同时继续沿用已审核的芯片、波特率和地址。"""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            selected = root / "manual.bin"
            selected.touch()
            script = root / "flash.sh"
            script.write_text(
                "py -m esptool --chip esp32s3 --baud 921600 write_flash 0x0 default-v1.0.0.bin",
                encoding="utf-8",
            )
            self.assertEqual(
                APP.select_sdk(script, selected),
                (selected.resolve(), "esp32s3", 921600, "0x0"),
            )

    def test_release_zip_is_prepared_and_cleaned(self):
        """发版全量 ZIP 应解压为同步目录，并在批次退出后清理临时文件。"""
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "OmniWatch-pico-full-v1.2.3.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("main.py", "print('ready')\n")
                archive.writestr("command/demo.py", "VALUE = 1\n")
            with APP.prepared_code_source(package) as source:
                extracted = source
                self.assertEqual((source / "main.py").read_text(encoding="utf-8"), "print('ready')\n")
                self.assertTrue((source / "command" / "demo.py").is_file())
            self.assertFalse(extracted.exists())

    def test_release_zip_requires_root_main(self):
        """多包一层目录的 ZIP 不能静默部署到设备错误路径。"""
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "wrapped.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("firmware/main.py", "")
            with self.assertRaisesRegex(ValueError, "根目录"):
                with APP.prepared_code_source(package):
                    pass

    def test_release_zip_rejects_unsafe_path(self):
        """全量 ZIP 在解压前必须拒绝父目录跳转。"""
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "unsafe.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("main.py", "")
                archive.writestr("../outside.py", "")
            with self.assertRaisesRegex(ValueError, "不安全路径"):
                with APP.prepared_code_source(package):
                    pass

    def test_dual_cdc_grouping_and_non_usb_filter(self):
        """同板双 CDC 只排队一次，普通串口不会被探测。"""
        groups = APP.candidate_groups([make_port(), make_port("COM8", "1-3:1.2"), make_port("COM1", None, None)])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups["usb:1-3"]), 2)

    def test_existing_sdk_skips_flash_and_verifies_copy(self):
        """已有兼容 SDK 只复制、校验和复位，不调用 esptool。"""
        with patch.object(self.worker, "probe", return_value=self.info), patch.object(self.worker, "command", return_value="") as command:
            self.worker.process("usb:1-3", [make_port()], self.config)
            calls = [call.args[0] for call in command.call_args_list]
            self.assertEqual(len(calls), 3)
            self.assertIn("--verify-code", calls[1])
            self.assertFalse(any("esptool" in args or "--flash" in args for args in calls))

    def test_wrong_chip_never_writes(self):
        """非 S3 的有效 REPL 响应直接阻止所有写入。"""
        with patch.object(self.worker, "probe", return_value=dict(self.info, machine="ESP32C3")), patch.object(self.worker, "command") as command:
            with self.assertRaisesRegex(RuntimeError, "非 ESP32-S3"):
                self.worker.process("usb:1-3", [make_port()], self.config)
            command.assert_not_called()

    def test_blank_board_flash_then_copy(self):
        """空板必须先通过容量检查和刷后运行验证，再开始代码复制。"""
        with patch.object(self.worker, "probe", side_effect=[None, self.info]), patch.object(self.worker, "ports", return_value=[make_port()]), patch.object(self.worker, "wait_runtime", return_value=("COM9", self.info)), patch.object(self.worker, "command", return_value="Detected flash size: 16MB") as command:
            self.worker.process("usb:1-3", [make_port()], self.config)
            calls = [call.args[0] for call in command.call_args_list]
            self.assertIn("flash-id", calls[0])
            self.assertIn("--flash", calls[1])
            self.assertEqual(calls[2][1], "COM9")

    def test_small_flash_never_writes(self):
        """N16 固件不能写入仅有 8 MB Flash 的候选板卡。"""
        with patch.object(self.worker, "probe", return_value=None), patch.object(self.worker, "ports", return_value=[make_port()]), patch.object(self.worker, "command", return_value="Detected flash size: 8MB") as command:
            with self.assertRaisesRegex(ValueError, "容量"):
                self.worker.process("usb:1-3", [make_port()], self.config)
            self.assertEqual(command.call_count, 1)

    def test_flash_failure_never_copies(self):
        """SDK 写入失败后不继续部署代码。"""
        with patch.object(self.worker, "probe", return_value=None), patch.object(self.worker, "ports", return_value=[make_port()]), patch.object(self.worker, "command", side_effect=["Detected flash size: 16MB", RuntimeError("flash failed")]) as command:
            with self.assertRaisesRegex(RuntimeError, "flash failed"):
                self.worker.process("usb:1-3", [make_port()], self.config)
            self.assertEqual(command.call_count, 2)

    def test_device_swap_fails_final_check(self):
        """复制后设备身份不同，不复位且不报告成功。"""
        with patch.object(self.worker, "probe", side_effect=[self.info, dict(self.info, id="other")]), patch.object(self.worker, "command", return_value="") as command:
            with self.assertRaisesRegex(RuntimeError, "身份"):
                self.worker.process("usb:1-3", [make_port()], self.config)
            self.assertEqual(command.call_count, 2)

    def test_command_timeout(self):
        """子进程无响应时能够超时退出，不让量产线程永久卡住。"""
        with self.assertRaises(TimeoutError):
            self.worker.command(["-c", "import time; time.sleep(10)"], timeout=0.15)

    def test_command_failure(self):
        """子进程非零返回码不会被当作成功。"""
        with self.assertRaisesRegex(RuntimeError, "退出码 3"):
            self.worker.command(["-c", "raise SystemExit(3)"])

    def test_progress_waits_for_final_verification(self):
        """SDK 或代码阶段百分之百不能提前代表整块设备量产成功。"""
        self.worker.stage(10, 55)
        self.worker.update_progress("Writing at 0x00010000... (100 %)")
        self.assertEqual(self.worker.progress, 55)
        self.worker.stage(60, 90)
        self.worker.update_progress("校验进度：50/100 字节（50.0%）")
        self.assertEqual(self.worker.progress, 75)
        self.worker.update_progress("校验进度：30/100 字节（30.0%）")
        self.assertEqual(self.worker.progress, 75)
        self.worker.stage(90, 98)
        self.worker.update_progress("PRODUCTION_VERIFY:100.0%")
        self.assertEqual(self.worker.progress, 98)

    def test_reenumeration_never_selects_another_board(self):
        """目标 USB 位置消失时，不能把其他板卡当成刷机后重新枚举的设备。"""
        with patch("serial.tools.list_ports.comports", return_value=[make_port("COM20", "1-9:1.0")]):
            self.assertEqual(self.worker.ports("usb:1-3"), [])

    def test_watcher_requires_unplug_before_retry(self):
        """持续连接期间仅处理一次，充分拔出后同一位置可以再次量产。"""
        clock = [0]

        def advance(_seconds):
            """推进虚拟时钟，避免测试真实等待 USB 防抖时间。"""
            clock[0] += 1

        def enumerate_ports():
            """模拟连接、拔出四秒、重新连接的设备序列。"""
            return [] if 5 <= clock[0] < 9 else [make_port()]

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "main.py").touch()
            self.worker.source = root
            with patch.object(APP, "TOOLS", root), patch.object(APP, "select_sdk", return_value=self.config), patch.object(APP, "load_flasher"), patch("serial.tools.list_ports.comports", side_effect=enumerate_ports), patch.object(APP.time, "monotonic", side_effect=lambda: clock[0]), patch.object(self.worker.stop, "wait", side_effect=advance), patch.object(self.worker.stop, "is_set", side_effect=lambda: clock[0] >= 15), patch.object(self.worker, "process") as process:
                self.worker.run()
                self.assertEqual(process.call_count, 2)
                events = list(self.worker.events.queue)
                activities = [value for kind, value in events if kind == "activity"]
                # 连接期间的多轮轮询不能把完成绿灯覆盖为等待黄灯。
                self.assertEqual(activities, ["waiting", "complete", "waiting", "complete"])


if __name__ == "__main__":
    unittest.main()
