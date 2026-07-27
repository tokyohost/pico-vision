"""封装 Monitor 服务中的自定义数据生命周期与采集调度。"""

import logging

from custom_data import CustomDataCollectionCoordinator
from custom_data import get_manager as get_custom_data_manager


LOGGER = logging.getLogger("pico-monitor")


class CustomDataServiceMixin:
    """为 Monitor 服务提供自定义数据初始化、调度和资源释放能力。"""

    def initialize_custom_data(self):
        """初始化自定义数据管理器及独立采集协调器。"""
        self.custom_data_manager = get_custom_data_manager()
        self.custom_data_manager.prepare_environments_async()
        self._custom_data_coordinator = CustomDataCollectionCoordinator(
            self.custom_data_manager,
            self._snapshot_store,
            self._complete_collection_fragment,
            self.arguments.collection_task_intervals,
            self.arguments.collection_task_logs,
        )

    def activate_custom_data_plugin(self, name):
        """将运行中新加载的自定义数据插件实时加入采集任务。"""
        definition = self._custom_data_coordinator.activate_plugin(name)
        LOGGER.info(
            "自定义数据插件实时加入 Monitor 任务：插件=%s，任务=%s",
            definition.name,
            definition.task_name,
        )
        return definition

    def update_custom_data_runtime_settings(self):
        """根据当前运行参数更新自定义数据采集频率和日志开关。"""
        coordinator = getattr(self, "_custom_data_coordinator", None)
        if coordinator is None:
            return
        coordinator.update_runtime_settings(
            self.arguments.collection_task_intervals,
            self.arguments.collection_task_logs,
        )

    def schedule_custom_data_collection(self):
        """调度到期的自定义数据任务并返回下一次调度等待时间。"""
        coordinator = getattr(self, "_custom_data_coordinator", None)
        if coordinator is None:
            return None
        coordinator.schedule()
        return coordinator.next_schedule_delay()

    def close_custom_data(self):
        """依次关闭自定义数据采集协调器和插件管理器。"""
        coordinator = getattr(self, "_custom_data_coordinator", None)
        if coordinator is not None:
            coordinator.close(wait=True)
        manager = getattr(self, "custom_data_manager", None)
        if manager is not None:
            manager.close()

    def custom_data_collection_tasks(self):
        """把当前发现的自定义数据插件转换为兼容的采集任务定义。"""
        tasks = []
        for definition in self.custom_data_manager.task_definitions():
            tasks.append(
                (
                    definition.task_name,
                    self.create_custom_data_collector(definition.name),
                    definition.interval,
                    definition.zh_name,
                )
            )
        return tasks

    def create_custom_data_collector(self, name):
        """创建指定自定义数据插件的兼容采集回调。"""
        def collect():
            """执行一个自定义数据插件并返回扩展字段片段。"""
            return {"ext": self.custom_data_manager.collect_task_data(name)}

        return collect

    def collect_all_custom_data(self):
        """同步采集全部自定义数据插件，供旧版完整快照流程使用。"""
        custom_ext = {}
        for definition in self.custom_data_manager.task_definitions():
            custom_ext.update(
                self.custom_data_manager.collect_task_data(definition.name)
            )
        return custom_ext
