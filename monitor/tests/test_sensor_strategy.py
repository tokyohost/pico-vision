"""LibreHardwareMonitor 原始数据解析策略测试。"""

import unittest
from unittest import mock

from collectTask.strategy import LibreHardwareMonitorSnapshotAdapter
from collectTask.strategy.base import SensorValueStrategy, StrategyChain
from collectTask.strategy.cpu import registry as cpu_registry
from collectTask.strategy.disk import registry as disk_registry
from collectTask.strategy.gpu import registry as gpu_registry


class StrategyChainTest(unittest.TestCase):
    """验证字段策略链的短路语义。"""

    def test_first_non_none_value_skips_remaining_strategies(self):
        """确认前一策略获得值后不会调用后续策略。"""
        first = mock.Mock(spec=SensorValueStrategy)
        second = mock.Mock(spec=SensorValueStrategy)
        first.parse.return_value = 0

        value = StrategyChain(first, second).parse([], {})

        self.assertEqual(value, 0)
        first.parse.assert_called_once_with([], {})
        second.parse.assert_not_called()

    def test_none_value_continues_with_next_strategy(self):
        """确认空值会继续交给下一策略解析。"""
        first = mock.Mock(spec=SensorValueStrategy)
        second = mock.Mock(spec=SensorValueStrategy)
        first.parse.return_value = None
        second.parse.return_value = 42

        value = StrategyChain(first, second).parse([], {})

        self.assertEqual(value, 42)
        second.parse.assert_called_once_with([], {})


class CategoryStrategyRegistryTest(unittest.TestCase):
    """验证 CPU、GPU 和磁盘均支持设备专属策略扩展。"""

    def test_device_strategy_precedes_each_category_default_strategy(self):
        """确认三个类别的专属策略有值时都会跳过对应默认策略。"""
        cases = (
            (cpu_registry.DEVICE_CPU_STRATEGIES, cpu_registry.create_cpu_strategy_chains, "cpu"),
            (gpu_registry.DEVICE_GPU_STRATEGIES, gpu_registry.create_gpu_strategy_chains, "gpu"),
            (disk_registry.DEVICE_DISK_STRATEGIES, disk_registry.create_disk_strategy_chains, "disk"),
        )
        for device_strategies, chain_factory, section in cases:
            with self.subTest(section=section):
                device_strategy = mock.Mock(spec=SensorValueStrategy)
                device_strategy.parse.return_value = 66
                context = {section: {"temperature_c": 55}}
                with mock.patch.dict(device_strategies, {"temperature_c": (device_strategy,)}):
                    value = chain_factory()["temperature_c"].parse([], context)

                self.assertEqual(value, 66)
                device_strategy.parse.assert_called_once_with([], context)


class LibreHardwareMonitorSnapshotAdapterTest(unittest.TestCase):
    """验证分类字段解析和客户设备 CPU 温度兼容规则。"""

    def test_cpu_temperature_falls_back_to_mainboard_sensor(self):
        """确认 CPU 节点缺温度时可读取 SuperIO 的 PECI CPU 温度。"""
        raw_data = [{
            "name": "Nuvoton NCT6798D",
            "type": "SuperIO",
            "sensors": [
                {"name": "System", "type": "Temperature", "value": 31, "unit": "°C"},
                {"name": "PECI Agent 0", "type": "Temperature", "value": 57, "unit": "°C"},
            ],
        }]
        context = {"cpu": {"percent": 12.5, "frequency_ghz": 4.8, "temperature_c": None}}

        parsed = LibreHardwareMonitorSnapshotAdapter().parse(raw_data, context)

        self.assertEqual(parsed["cpu"]["temperature_c"], 57.0)

    def test_snapshot_cpu_temperature_has_priority_over_raw_fallback(self):
        """确认现有默认字段有值时不会被原始传感器覆盖。"""
        raw_data = [{
            "type": "Cpu",
            "sensors": [{"name": "CPU Package", "type": "Temperature", "value": 70}],
        }]
        context = {"cpu": {"temperature_c": 55}}

        parsed = LibreHardwareMonitorSnapshotAdapter().parse(raw_data, context)

        self.assertEqual(parsed["cpu"]["temperature_c"], 55.0)

    def test_existing_snapshot_fields_are_parsed_by_default_strategies(self):
        """确认 CPU、内存、GPU、功耗和磁盘旧字段保持兼容。"""
        context = {
            "cpu": {"percent": 10, "frequency_ghz": 4.2, "temperature_c": 50},
            "memory": {"physical": {"percent": 60, "used_bytes": 600, "available_bytes": 400}},
            "gpu": {"name": "GPU", "percent": 30, "temperature_c": 45},
            "power": {"watts": 80, "source": "librehardwaremonitor", "scope": "cpu_gpu"},
            "disks": [{"name": "Disk0", "temperature_c": 35, "health_percent": 99}],
        }

        parsed = LibreHardwareMonitorSnapshotAdapter().parse([], context)

        self.assertEqual(parsed["cpu"]["frequency_ghz"], 4.2)
        self.assertEqual(parsed["memory"]["total_bytes"], 1000)
        self.assertEqual(parsed["gpu"]["temperature_c"], 45.0)
        self.assertEqual(parsed["power"]["watts"], 80.0)
        self.assertEqual(parsed["disks"][0]["health"], 1)


if __name__ == "__main__":
    unittest.main()
