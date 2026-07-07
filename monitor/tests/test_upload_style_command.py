"""验证 Pico 样式上传命令的 Flash 临时文件分块流程。"""

import base64
import os
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PICO_ROOT = os.path.join(PROJECT_ROOT, "picoRP2040")
if PICO_ROOT not in sys.path:
    sys.path.insert(0, PICO_ROOT)

from command.base import CommandError
from command.upload_style import UploadStyleCommand
from command.style_list import StyleListCommand
from command.style_delete import StyleDeleteCommand
from styles.style_plugins import _scan_style_directory


class TestableUploadStyleCommand(UploadStyleCommand):
    """把固件自定义样式目录替换为测试临时目录。"""

    directory = None

    @classmethod
    def _custom_style_directory(cls):
        """返回当前测试用临时目录。"""
        return cls.directory


class TestableStyleDeleteCommand(StyleDeleteCommand):
    """使用测试文件路径并阻止真实设备重启。"""

    path = None
    restarted = False

    @classmethod
    def _custom_style_path(cls, filename):
        """返回测试创建的样式文件路径。"""
        del filename
        return cls.path

    @classmethod
    def _restart(cls):
        """记录重启请求而不终止测试进程。"""
        cls.restarted = True


class RecordingCommandContext:
    """记录固件命令主动发送的响应。"""

    def __init__(self):
        """初始化请求标识和响应列表。"""
        self.request_id = "delete-1"
        self.responses = []

    def respond(self, status, command, data=None, request_id=None):
        """保存命令响应参数供测试断言。"""
        self.responses.append((status, command, data, request_id))


class UploadStyleCommandTest(unittest.TestCase):
    """覆盖临时文件创建、分块追加及异常清理。"""

    def setUp(self):
        """创建独立临时目录和上传命令实例。"""
        self.temporary_directory = tempfile.TemporaryDirectory()
        TestableUploadStyleCommand.directory = self.temporary_directory.name
        self.command = TestableUploadStyleCommand()

    def tearDown(self):
        """释放测试临时目录。"""
        self.temporary_directory.cleanup()

    def test_chunks_are_written_directly_to_temporary_file(self):
        """确认源码块仅落入 Flash 临时文件且接收顺序受校验。"""
        content = b"print('clock')\n" * 80
        self.command._begin({
            "filename": "style_clock.py",
            "style_name": "clock",
            "size": len(content),
        })

        for sequence, offset in enumerate(range(0, len(content), 256)):
            chunk = content[offset:offset + 256]
            self.command._append({
                "upload_id": "style_clock.py",
                "sequence": sequence,
                "content": base64.b64encode(chunk).decode("ascii"),
            })

        temporary_path = os.path.join(self.temporary_directory.name, "style_clock.py.uploading")
        with open(temporary_path, "rb") as source:
            self.assertEqual(source.read(), content)
        self.assertEqual(self.command._session["written"], len(content))

    def test_invalid_sequence_does_not_append_data(self):
        """确认乱序数据块不会写入临时文件。"""
        self.command._begin({
            "filename": "style_clock.py",
            "style_name": "clock",
            "size": 3,
        })

        with self.assertRaisesRegex(CommandError, "INVALID_STYLE_SEQUENCE"):
            self.command._append({
                "upload_id": "style_clock.py",
                "sequence": 1,
                "content": base64.b64encode(b"abc").decode("ascii"),
            })

        temporary_path = os.path.join(self.temporary_directory.name, "style_clock.py.uploading")
        self.assertEqual(os.path.getsize(temporary_path), 0)

    def test_begin_removes_all_invalid_temporary_files(self):
        """确认每次开始上传都会清理目录内遗留的无效临时文件。"""
        stale_paths = (
            os.path.join(self.temporary_directory.name, "style_old.py.uploading"),
            os.path.join(self.temporary_directory.name, "broken.uploading"),
        )
        for stale_path in stale_paths:
            with open(stale_path, "wb") as output:
                output.write(b"stale")
        valid_path = os.path.join(self.temporary_directory.name, "style_valid.py")
        with open(valid_path, "wb") as output:
            output.write(b"valid")
        backup_path = os.path.join(
            self.temporary_directory.name, "style_recover.py.backup",
        )
        with open(backup_path, "wb") as output:
            output.write(b"backup")

        self.command._begin({
            "filename": "style_clock.py",
            "style_name": "clock",
            "size": 3,
        })

        self.assertTrue(all(not os.path.exists(path) for path in stale_paths))
        self.assertTrue(os.path.exists(valid_path))
        recovered_path = os.path.join(
            self.temporary_directory.name, "style_recover.py",
        )
        with open(recovered_path, "rb") as source:
            self.assertEqual(source.read(), b"backup")
        self.assertTrue(os.path.exists(
            os.path.join(self.temporary_directory.name, "style_clock.py.uploading")
        ))

    @mock.patch("styles.style_plugins.release_style")
    @mock.patch("styles.style_plugins.create_style")
    def test_confirmed_overwrite_replaces_existing_style(self, create_style, _release):
        """确认覆盖上传校验成功后替换旧文件并删除备份。"""
        create_style.return_value = SimpleNamespace(name="clock")
        target_path = os.path.join(self.temporary_directory.name, "style_clock.py")
        with open(target_path, "wb") as output:
            output.write(b"old")
        self.command._begin({
            "filename": "style_clock.py", "style_name": "clock",
            "size": 3, "overwrite": True,
        })
        self.command._append({
            "upload_id": "style_clock.py", "sequence": 0,
            "content": base64.b64encode(b"new").decode("ascii"),
        })

        self.command._finish({"upload_id": "style_clock.py"})

        with open(target_path, "rb") as source:
            self.assertEqual(source.read(), b"new")
        self.assertFalse(os.path.exists(target_path + ".backup"))

    @mock.patch("styles.style_plugins.release_style")
    @mock.patch("styles.style_plugins.create_style", side_effect=ValueError("坏样式"))
    def test_failed_overwrite_restores_previous_style(self, _create_style, _release):
        """确认新样式校验失败时恢复原有 Flash 文件。"""
        target_path = os.path.join(self.temporary_directory.name, "style_clock.py")
        with open(target_path, "wb") as output:
            output.write(b"old")
        self.command._begin({
            "filename": "style_clock.py", "style_name": "clock",
            "size": 3, "overwrite": True,
        })
        self.command._append({
            "upload_id": "style_clock.py", "sequence": 0,
            "content": base64.b64encode(b"bad").decode("ascii"),
        })

        with self.assertRaisesRegex(CommandError, "STYLE_VALIDATION_FAILED"):
            self.command._finish({"upload_id": "style_clock.py"})

        with open(target_path, "rb") as source:
            self.assertEqual(source.read(), b"old")


class StyleListCommandTest(unittest.TestCase):
    """验证样式清单返回的 Pico Flash 空间数据。"""

    @mock.patch("command.style_list.os.statvfs", create=True)
    def test_flash_space_contains_free_and_total_bytes(self, statvfs):
        """确认文件系统块信息会换算成剩余字节数和总字节数。"""
        statvfs.return_value = (4096, 4096, 1000, 240, 240, 0, 0, 0, 0, 255)

        flash = StyleListCommand._flash_space()

        self.assertEqual(flash["free_bytes"], 4096 * 240)
        self.assertEqual(flash["total_bytes"], 4096 * 1000)

    def test_custom_style_contains_template_filename_and_size(self):
        """确认自定义样式清单包含模板文件名和模板文件字节数。"""
        source = (
            'class ClockStyle:\n'
            '    name = "clock"\n'
            '    zh_name = "时钟"\n'
            '    type = "custom"\n'
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "style_clock.py")
            with open(path, "wb") as output:
                output.write(source)

            catalog = _scan_style_directory(directory, "custom")

        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["filename"], "style_clock.py")
        self.assertEqual(catalog[0]["file_size"], len(source))


class StyleDeleteCommandTest(unittest.TestCase):
    """验证自定义样式文件删除和设备重启顺序。"""

    @mock.patch("styles.style_plugins.release_style")
    @mock.patch("styles.style_plugins.custom_style_catalog")
    def test_delete_custom_style_then_restart(self, catalog, release_style):
        """确认清单中的样式文件被删除、响应成功并请求重启。"""
        catalog.return_value = ({
            "name": "clock",
            "filename": "style_clock.py",
            "type": "custom",
        },)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "style_clock.py")
            with open(path, "wb") as output:
                output.write(b"source")
            TestableStyleDeleteCommand.path = path
            TestableStyleDeleteCommand.restarted = False
            context = RecordingCommandContext()

            TestableStyleDeleteCommand().execute({
                "style_name": "clock",
                "filename": "style_clock.py",
            }, context)

            self.assertFalse(os.path.exists(path))
        release_style.assert_called_once_with("clock")
        self.assertEqual(context.responses[0][0:2], ("ok", "style.delete"))
        self.assertTrue(context.responses[0][2]["restarting"])
        self.assertTrue(TestableStyleDeleteCommand.restarted)

    @mock.patch("styles.style_plugins.custom_style_catalog", return_value=())
    def test_delete_rejects_unknown_custom_style(self, _catalog):
        """确认不存在的样式不会触碰 Flash 文件。"""
        with self.assertRaisesRegex(CommandError, "CUSTOM_STYLE_NOT_FOUND"):
            TestableStyleDeleteCommand().execute({
                "style_name": "missing",
                "filename": "style_missing.py",
            }, RecordingCommandContext())


if __name__ == "__main__":
    unittest.main()
