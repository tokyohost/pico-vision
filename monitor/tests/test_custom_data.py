"""验证标准自定义数据插件的扫描、导入、执行和删除。"""

import tempfile
import unittest
import zipfile
import os
import sys
from pathlib import Path

import custom_data


class CustomDataTaskTest(unittest.TestCase):
    """覆盖标准目录插件和 ZIP 插件包的完整管理流程。"""

    def _create_plugin(self, root, name="demo"):
        """创建包含清单和入口文件的标准测试插件目录。"""
        plugin = Path(root) / name
        plugin.mkdir(parents=True)
        (plugin / "plugin.json").write_text(
            '{"protocol":1,"key":"demo_json","name":"demo_task","zh_name":"演示数据","interval":7}',
            encoding="utf-8",
            newline="\n",
        )
        (plugin / "main.py").write_text(
            'def collect():\n    """返回标准插件测试数据。"""\n    return {"value": 2}\n',
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

        self.assertEqual(result, {"demo_json": {"value": 2}})

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

            result = manager.collect_task_data(definition.name)

        self.assertEqual(definition.zh_name, "压缩包插件")
        self.assertEqual(result, {"zip_data": {"source": "zip"}})

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
