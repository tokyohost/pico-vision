"""验证 mpremote 工程复制工具的 SHA-256 增量上传行为。"""


import contextlib
import hashlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "tools" / "mpremote_stream_copy.py"
SPEC = importlib.util.spec_from_file_location("mpremote_stream_copy", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MpremoteStreamCopyTest(unittest.TestCase):
    """确认内容一致文件被跳过，变化文件才上传。"""

    def test_remote_manifest_parser_accepts_markers_among_noise(self):
        """设备输出含启动日志时仍应正确解析文件指纹。"""
        remote_path = "/目录/main.py"
        path_hex = remote_path.encode("utf-8").hex()
        digest = hashlib.sha256(b"data").hexdigest()
        output = (
            "BOOT:READY\n"
            f"{MODULE.REMOTE_MANIFEST_PREFIX}{path_hex}:4:{digest}\n"
            "其他输出\n"
        )

        manifest = MODULE.MpremoteStreamCopier._parse_remote_manifest(output)

        self.assertEqual({remote_path: (4, digest)}, manifest)

    def test_copy_uploads_only_missing_or_changed_files(self):
        """增量模式应跳过相同文件并上传内容变化的文件。"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            same_file = source / "same.py"
            changed_file = source / "changed.py"
            same_file.write_bytes(b"same")
            changed_file.write_bytes(b"new")
            copier = MODULE.MpremoteStreamCopier("COM_TEST", source)
            remote_manifest = {
                "/same.py": copier._local_fingerprint(same_file),
                "/changed.py": (3, hashlib.sha256(b"old").hexdigest()),
            }
            with mock.patch.object(copier, "_check_environment"), mock.patch.object(
                copier,
                "_prepare_remote_directories",
            ), mock.patch.object(
                copier,
                "_read_remote_manifest",
                return_value=remote_manifest,
            ), mock.patch.object(copier, "_run_mpremote") as run_mpremote, contextlib.redirect_stdout(
                io.StringIO()
            ):
                copier.copy()

        copy_calls = [
            call
            for call in run_mpremote.call_args_list
            if call.args[0][:2] == ["fs", "cp"]
        ]
        self.assertEqual(1, len(copy_calls))
        self.assertEqual(":/changed.py", copy_calls[0].args[0][-1])
        self.assertEqual(["reset"], run_mpremote.call_args_list[-1].args[0])

    def test_force_mode_uploads_every_file_without_remote_manifest(self):
        """强制模式应跳过远端校验并上传全部本地文件。"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "first.py").write_bytes(b"first")
            (source / "second.py").write_bytes(b"second")
            copier = MODULE.MpremoteStreamCopier("COM_TEST", source)
            with mock.patch.object(copier, "_check_environment"), mock.patch.object(
                copier,
                "_prepare_remote_directories",
            ), mock.patch.object(
                copier,
                "_read_remote_manifest",
            ) as read_manifest, mock.patch.object(
                copier,
                "_run_mpremote",
            ) as run_mpremote, contextlib.redirect_stdout(io.StringIO()):
                copier.copy(force=True, restart=False)

        read_manifest.assert_not_called()
        self.assertEqual(2, run_mpremote.call_count)
        self.assertTrue(all(
            call.args[0][:2] == ["fs", "cp"]
            for call in run_mpremote.call_args_list
        ))

    def test_remote_manifest_requests_are_batched_and_valid_python(self):
        """远端校验代码应分批发送并保持有效 Python 语法。"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            copier = MODULE.MpremoteStreamCopier("COM_TEST", source)
            files = [source / f"file_{index}.py" for index in range(41)]

            def capture(arguments, description):
                """校验生成代码并返回空设备清单。"""
                del description
                self.assertEqual("exec", arguments[0])
                compile(arguments[1], "<remote-manifest>", "exec")
                return ""

            with mock.patch.object(
                copier,
                "_capture_mpremote",
                side_effect=capture,
            ) as capture_mpremote:
                manifest = copier._read_remote_manifest(files)

        self.assertEqual({}, manifest)
        self.assertEqual(2, capture_mpremote.call_count)


if __name__ == "__main__":
    unittest.main()
