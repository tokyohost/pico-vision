"""验证标准自定义数据插件的扫描、导入、执行和删除。"""

import tempfile
import unittest
import zipfile
import os
import sys
from pathlib import Path
from unittest import mock

import custom_data
import collectTask.system_tasks as system_tasks


class CustomDataTaskTest(unittest.TestCase):
    """覆盖标准目录插件和 ZIP 插件包的完整管理流程。"""

    def _create_plugin(self, root, name="demo", key="demo_json", task="demo_task", zh_name="演示数据", value=2):
        """创建包含清单和入口文件的标准测试插件目录。"""
        plugin = Path(root) / name
        plugin.mkdir(parents=True)
        (plugin / "plugin.json").write_text(
            (
                '{{"protocol":1,"key":"{}","name":"{}","zh_name":"{}","interval":7}}'
            ).format(key, task, zh_name),
            encoding="utf-8",
            newline="\n",
        )
        (plugin / "main.py").write_text(
            'def collect():\n    """返回标准插件测试数据。"""\n    return {{"value": {}}}\n'.format(value),
            encoding="utf-8",
            newline="\n",
        )
        return plugin

    def _create_test_environment(self, definition):
        """创建指向当前解释器的轻量测试环境，避免测试依赖系统 venv 包。"""
        executable = custom_data._environment_python(definition.environment_directory)
        executable.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(sys.executable, executable)
        (definition.environment_directory / ".dependencies-ready").write_text(
            "无第三方依赖", encoding="utf-8", newline="\n"
        )

    def test_data_root_prefers_explicit_environment(self):
        """确认 Linux systemd 服务可把用户数据写入显式状态目录。"""
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"PICO_MONITOR_DATA_ROOT": directory},
        ):
            self.assertEqual(Path(directory), custom_data.get_data_root())

    def test_plugin_definition_exposes_task_name_and_zh_name(self):
        """确认插件清单的英文标识和中文名会形成稳定任务配置 key。"""
        with tempfile.TemporaryDirectory() as directory:
            self._create_plugin(directory)
            manager = custom_data.CustomDataManager(directory, Path(directory) / "envs")
            definitions = manager.task_definitions()

        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0].task_name, "custom_data.demo_task")
        self.assertEqual(definitions[0].zh_name, "演示数据")
        self.assertEqual(definitions[0].interval, 7.0)

    def test_collect_task_data_runs_single_plugin(self):
        """确认按任务名执行单个插件时只返回该插件的 ext 子字段。"""
        with tempfile.TemporaryDirectory() as directory:
            self._create_plugin(directory)
            manager = custom_data.CustomDataManager(directory, Path(directory) / "envs")
            self._create_test_environment(manager.task_definitions()[0])
            result = manager.collect_task_data("demo_task")
            manager.close()

        self.assertEqual(result, {"demo_json": {"value": 2}})

    def test_collect_task_data_returns_placeholder_before_environment_ready(self):
        """确认独立环境尚未创建成功前返回固定占位数据。"""
        with tempfile.TemporaryDirectory() as directory:
            self._create_plugin(directory)
            manager = custom_data.CustomDataManager(directory, Path(directory) / "envs")
            result = manager.collect_task_data("demo_task")
            manager.close()

        self.assertEqual(result, {"demo_json": custom_data.CUSTOM_DATA_PLACEHOLDER})

    def test_custom_data_collection_coordinator_uses_independent_pool(self):
        """确认每个自定义数据插件会封装为独立任务并使用专用线程池。"""
        with tempfile.TemporaryDirectory() as directory:
            self._create_plugin(directory)
            manager = custom_data.CustomDataManager(directory, Path(directory) / "envs")
            store = type("Store", (), {"publish": lambda self, fragment: None})()
            with mock.patch.object(manager, "prepare_environments_async"):
                coordinator = custom_data.CustomDataCollectionCoordinator(manager, store)
            try:
                self.assertEqual(coordinator.executor.core_workers, 1)
                self.assertEqual(coordinator.executor.max_workers, 5)
                self.assertEqual(coordinator.executor.queue_capacity, 100)
                self.assertEqual(len(coordinator.tasks), 1)
                self.assertIsInstance(coordinator.tasks[0], custom_data.CustomDataCollectionTask)
            finally:
                coordinator.close()
                manager.close()

    def test_custom_data_task_is_not_registered_as_system_task(self):
        """确认自定义数据任务子类不会被系统任务自动发现误注册。"""
        with mock.patch.object(system_tasks, "_import_task_modules"):
            self.assertNotIn(custom_data.CustomDataCollectionTask, system_tasks.system_task_classes())

    def test_custom_data_task_normal_completion_uses_debug_log(self):
        """确认普通自定义数据采集完成不再产生 INFO 级别运行日志。"""
        coordinator = custom_data.CustomDataCollectionCoordinator.__new__(
            custom_data.CustomDataCollectionCoordinator
        )
        coordinator.result_transform = None
        coordinator.result_store = mock.Mock()
        coordinator.task_logs_enabled = True
        coordinator.executor = mock.Mock()
        coordinator.executor.state.return_value = {
            "core_workers": 1,
            "max_workers": 5,
            "workers": 1,
            "active": 1,
            "idle": 0,
            "queued": 0,
            "queue_capacity": 100,
        }
        task = mock.Mock()
        task.name = "custom_data.demo"
        task.zh_name = "演示数据"
        task.collect.return_value = {"ext": {"demo": 1}}

        with mock.patch("custom_data.time.monotonic", side_effect=[0.0, 0.2]):
            with self.assertLogs("pico-monitor.custom-data", level="DEBUG") as logs:
                coordinator._execute_and_publish(task)

        self.assertIn("DEBUG:pico-monitor.custom-data:自定义数据任务完成", "\n".join(logs.output))
        self.assertNotIn("INFO:pico-monitor.custom-data:自定义数据任务完成", "\n".join(logs.output))

    def test_custom_data_task_slow_completion_keeps_warning_log(self):
        """确认慢自定义数据采集仍会保留可见告警日志。"""
        coordinator = custom_data.CustomDataCollectionCoordinator.__new__(
            custom_data.CustomDataCollectionCoordinator
        )
        coordinator.result_transform = None
        coordinator.result_store = mock.Mock()
        coordinator.task_logs_enabled = True
        coordinator.executor = mock.Mock()
        coordinator.executor.state.return_value = {
            "core_workers": 1,
            "max_workers": 5,
            "workers": 1,
            "active": 1,
            "idle": 0,
            "queued": 0,
            "queue_capacity": 100,
        }
        task = mock.Mock()
        task.name = "custom_data.demo"
        task.zh_name = "演示数据"
        task.collect.return_value = {"ext": {"demo": 1}}

        with mock.patch("custom_data.time.monotonic", side_effect=[0.0, 1.2]):
            with self.assertLogs("pico-monitor.custom-data", level="WARNING") as logs:
                coordinator._execute_and_publish(task)

        self.assertIn("WARNING:pico-monitor.custom-data:自定义数据任务完成", "\n".join(logs.output))

    def test_high_frequency_collection_reuses_plugin_process(self):
        """确认连续采集复用同一个插件进程，避免反复启动解释器。"""
        with tempfile.TemporaryDirectory() as directory:
            plugin = self._create_plugin(directory)
            (plugin / "main.py").write_text(
                'import os\n\ndef collect():\n    """返回当前插件进程编号。"""\n    return {"pid": os.getpid()}\n',
                encoding="utf-8",
                newline="\n",
            )
            manager = custom_data.CustomDataManager(directory, Path(directory) / "envs")
            self._create_test_environment(manager.task_definitions()[0])

            first = manager.collect_task_data("demo_task")
            second = manager.collect_task_data("demo_task")
            manager.close()

        self.assertEqual(first["demo_json"]["pid"], second["demo_json"]["pid"])

    def test_single_python_file_is_ignored_and_rejected_for_import(self):
        """确认旧版单文件不会被扫描，也不能再通过导入接口加载。"""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "legacy.py"
            script.write_text("CUSTOM_DATA_KEY = 'legacy'\n", encoding="utf-8", newline="\n")
            manager = custom_data.CustomDataManager(directory, Path(directory) / "envs")

            self.assertEqual(manager.task_definitions(), ())
            with self.assertRaisesRegex(custom_data.CustomDataError, "不再支持单文件"):
                manager.import_plugin(script)

    def test_plugin_template_uses_standard_directory_structure(self):
        """确认首次初始化生成目录模板，且模板不会被当成已安装插件扫描。"""
        with tempfile.TemporaryDirectory() as directory:
            custom_data._create_plugin_template(directory)
            template = Path(directory) / custom_data.CUSTOM_DATA_TEMPLATE_DIRECTORY_NAME
            manager = custom_data.CustomDataManager(directory, Path(directory) / "envs")

            self.assertTrue((template / "plugin.json").is_file())
            self.assertTrue((template / "main.py").is_file())
            self.assertTrue((template / "requirements.txt").is_file())
            self.assertEqual(manager.task_definitions(), ())

    def test_zip_plugin_import_and_subprocess_execution(self):
        """确认 ZIP 插件包可导入、创建独立环境并通过子进程执行。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "plugin.json").write_text(
                '{"protocol":1,"key":"zip_data","name":"zip_task","zh_name":"压缩包插件","interval":3}',
                encoding="utf-8",
                newline="\n",
            )
            (source / "main.py").write_text(
                'from helper import SOURCE\n\ndef collect():\n    """返回压缩包插件测试数据。"""\n    return {"source": SOURCE}\n',
                encoding="utf-8",
                newline="\n",
            )
            (source / "helper.py").write_text('SOURCE = "zip"\n', encoding="utf-8", newline="\n")
            archive = root / "plugin.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.write(source / "plugin.json", "weather/plugin.json")
                package.write(source / "main.py", "weather/main.py")
                package.write(source / "helper.py", "weather/helper.py")
            manager = custom_data.CustomDataManager(root / "customData", root / "envs")
            definition = manager.import_plugin(archive)
            self._create_test_environment(definition)
            manager.reload_scripts()
            manager.activate_plugin(definition.name)

            result = manager.collect_task_data(definition.name)
            manager.close()

        self.assertEqual(definition.zh_name, "压缩包插件")
        self.assertEqual(result, {"zip_data": {"source": "zip"}})

    def test_imported_plugin_stays_not_running_until_activated(self):
        """确认运行中导入的新插件默认不进入采集任务，激活后才参与调度。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._create_plugin(root / "source")
            manager = custom_data.CustomDataManager(root / "customData", root / "envs")

            definition = manager.import_plugin(source)
            items, _ = manager.list_items()

            self.assertEqual(manager.task_definitions(), ())
            self.assertFalse(items[0].runtime_enabled)
            self.assertEqual(manager.collect_task_data(definition.name), {})

            with mock.patch.object(manager, "prepare_environments_async"):
                activated = manager.activate_plugin(definition.name)

            self.assertEqual(activated.name, definition.name)
            self.assertEqual(manager.task_definitions()[0].name, definition.name)
            self.assertTrue(manager.list_items()[0][0].runtime_enabled)

    def test_newly_discovered_plugin_is_not_running_until_activated(self):
        """确认后台进程运行中扫描到的新插件默认显示未运行。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custom_root = root / "customData"
            manager = custom_data.CustomDataManager(custom_root, root / "envs")

            self._create_plugin(custom_root)
            manager.reload_if_changed()
            items, _ = manager.list_items()

            self.assertEqual(manager.task_definitions(), ())
            self.assertEqual(len(items), 1)
            self.assertFalse(items[0].runtime_enabled)

            with mock.patch.object(manager, "prepare_environments_async"):
                manager.activate_plugin(items[0].definition.name)

            self.assertEqual(manager.task_definitions()[0].name, "demo_task")

    def test_zip_plugin_rejects_path_traversal(self):
        """确认 ZIP 插件包不能通过路径穿越写出解压目录。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("../plugin.json", "{}")
            manager = custom_data.CustomDataManager(root / "customData", root / "envs")

            with self.assertRaises(custom_data.CustomDataError):
                manager.import_plugin(archive)

    def test_duplicate_plugin_import_reports_overwritable_conflict(self):
        """确认重复 key 的插件导入会返回可供窗口确认覆盖的冲突信息。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._create_plugin(root / "first")
            second = self._create_plugin(root / "second", task="other_task", zh_name="重复数据")
            manager = custom_data.CustomDataManager(root / "customData", root / "envs")
            manager.import_plugin(first)

            with self.assertRaises(custom_data.CustomDataDuplicateError) as context:
                manager.import_plugin(second)

            self.assertIn("插件重复", str(context.exception))
            self.assertEqual(context.exception.definition.name, "other_task")
            self.assertEqual(context.exception.conflicts[0].name, "demo_task")

    def test_duplicate_plugin_import_can_overwrite_existing_plugin(self):
        """确认用户确认覆盖后会替换旧插件目录和独立环境。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._create_plugin(root / "first", value=2)
            second = self._create_plugin(root / "second", task="other_task", zh_name="覆盖数据", value=9)
            manager = custom_data.CustomDataManager(root / "customData", root / "envs")
            original = manager.import_plugin(first)
            original.environment_directory.mkdir(parents=True)
            (original.environment_directory / "old.txt").write_text("old", encoding="utf-8", newline="\n")

            replacement = manager.import_plugin(second, overwrite=True)
            self._create_test_environment(replacement)
            manager.reload_scripts()
            manager.activate_plugin(replacement.name)
            result = manager.collect_task_data(replacement.name)
            manager.close()

            self.assertFalse(original.plugin_directory.exists())
            self.assertFalse(original.environment_directory.exists())
            self.assertEqual(replacement.name, "other_task")
            self.assertEqual(result, {"demo_json": {"value": 9}})

    def test_import_reports_orphan_target_directory_as_overwritable(self):
        """确认目标目录残留但未加载时仍提示用户可覆盖恢复。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._create_plugin(root / "source")
            custom_root = root / "customData"
            orphan = custom_root / "demo_task"
            orphan.mkdir(parents=True)
            (orphan / "stale.txt").write_text("残留目录", encoding="utf-8", newline="\n")
            manager = custom_data.CustomDataManager(custom_root, root / "envs")

            with self.assertRaises(custom_data.CustomDataDuplicateError) as context:
                manager.import_plugin(source)
            definition = manager.import_plugin(source, overwrite=True)

            self.assertIn("目标目录已存在但当前未加载", str(context.exception))
            self.assertEqual(context.exception.conflicts, ())
            self.assertEqual(definition.name, "demo_task")
            self.assertTrue((definition.plugin_directory / "plugin.json").is_file())
            self.assertFalse((definition.plugin_directory / "stale.txt").exists())

    def test_remove_directory_retries_when_temporarily_busy(self):
        """确认 Windows 短暂占用目录时删除操作会自动重试。"""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "busy"
            target.mkdir()
            with mock.patch("custom_data.shutil.rmtree", side_effect=[PermissionError("busy"), None]) as remove:
                with mock.patch("custom_data.time.sleep") as sleep:
                    custom_data._rmtree_with_retry(target, "测试目录")

            self.assertEqual(remove.call_count, 2)
            sleep.assert_called_once_with(custom_data.CUSTOM_DATA_REMOVE_RETRY_DELAY_SECONDS)

    def test_delete_plugin_removes_directory_and_environment(self):
        """确认删除操作按插件目录执行，并同步清理对应独立环境。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._create_plugin(root / "source")
            manager = custom_data.CustomDataManager(root / "customData", root / "envs")
            definition = manager.import_plugin(source)
            definition.environment_directory.mkdir(parents=True)

            manager.delete_plugin(definition.plugin_directory)

            self.assertFalse(definition.plugin_directory.exists())
            self.assertFalse(definition.environment_directory.exists())


if __name__ == "__main__":
    unittest.main()
