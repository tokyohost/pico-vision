"""验证自定义数据脚本的任务封装和命名规范。"""

import tempfile
import unittest
from pathlib import Path

import custom_data


class CustomDataTaskTest(unittest.TestCase):
    """覆盖自定义数据脚本到采集任务的转换。"""

    def test_script_definition_exposes_task_name_and_zh_name(self):
        """确认脚本声明的英文标识和中文名会形成稳定任务配置 key。"""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "demo.py"
            script.write_text(
                "\n".join((
                    'CUSTOM_DATA_KEY = "demo_json"',
                    'CUSTOM_DATA_NAME = "demo_task"',
                    'CUSTOM_DATA_ZH_NAME = "演示数据"',
                    "CUSTOM_DATA_INTERVAL = 7",
                    "def collect():",
                    "    return {'value': 1}",
                )),
                encoding="utf-8",
                newline="\n",
            )

            manager = custom_data.CustomDataManager(directory)
            definitions = manager.task_definitions()

        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0].task_name, "custom_data.demo_task")
        self.assertEqual(definitions[0].zh_name, "演示数据")
        self.assertEqual(definitions[0].interval, 7.0)

    def test_collect_task_data_runs_single_script(self):
        """确认按任务名执行单个脚本时只返回该脚本的 ext 子字段。"""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "demo.py"
            script.write_text(
                "\n".join((
                    'CUSTOM_DATA_KEY = "demo_json"',
                    'CUSTOM_DATA_NAME = "demo_task"',
                    'CUSTOM_DATA_ZH_NAME = "演示数据"',
                    "CUSTOM_DATA_INTERVAL = 7",
                    "def collect():",
                    "    return {'value': 2}",
                )),
                encoding="utf-8",
                newline="\n",
            )

            manager = custom_data.CustomDataManager(directory)
            result = manager.collect_task_data("demo_task")

        self.assertEqual(result, {"demo_json": {"value": 2}})


if __name__ == "__main__":
    unittest.main()
