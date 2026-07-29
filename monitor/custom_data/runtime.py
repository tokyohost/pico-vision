#!/usr/bin/env python3
"""负责自定义数据插件的隔离进程执行与采集任务调度。"""

import json
import logging
import os
import subprocess
import threading
import time
import uuid

from collectTask.executor import BoundedElasticThreadPool, TaskRejectedError
from collectTask.system_tasks import CollectionTask
from .support import (
    CUSTOM_DATA_COLLECTION_POOL_CORE_WORKERS,
    CUSTOM_DATA_COLLECTION_POOL_MAX_WORKERS,
    CUSTOM_DATA_COLLECTION_QUEUE_CAPACITY,
    CUSTOM_DATA_SLOW_TASK_WARNING_SECONDS,
    DEFAULT_SCRIPT_TIMEOUT_SECONDS,
    CustomDataError,
    _environment_python,
    _runner_path,
)


class CustomDataWorker:
    """维护单个插件的常驻隔离进程，避免高频采集反复启动解释器。"""

    def __init__(self, definition):
        """保存插件定义并初始化尚未启动的进程状态。"""
        self.definition = definition
        self.process = None
        self.lock = threading.RLock()

    def _start(self):
        """启动插件常驻进程并建立行式 JSON 通信管道。"""
        python_path = _environment_python(self.definition.environment_directory)
        if not python_path.is_file():
            raise CustomDataError("插件环境尚未安装，请先在自定义数据窗口安装依赖")
        process_environment = os.environ.copy()
        process_environment["PYTHONIOENCODING"] = "utf-8"
        process_environment["PYTHONUTF8"] = "1"
        self.process = subprocess.Popen(
            [str(python_path), str(_runner_path()), str(self.definition.path)],
            cwd=str(self.definition.plugin_directory), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1,
            env=process_environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _request(self, command, payload=None, timeout=DEFAULT_SCRIPT_TIMEOUT_SECONDS):
        """向常驻插件进程发送一条命令并等待匹配的结构化响应。"""
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.stop()
                self._start()
            try:
                request_id = uuid.uuid4().hex
                request = {
                    "command": command,
                    "request_id": request_id,
                    **(payload or {}),
                }
                self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
                result = []
                reader = threading.Thread(target=lambda: result.append(self.process.stdout.readline()), daemon=True)
                reader.start()
                reader.join(timeout)
                if reader.is_alive():
                    self.stop()
                    raise CustomDataError("{} 执行超过 {:g} 秒，已重启插件进程".format(command, timeout))
                if not result or not result[0]:
                    self.stop()
                    raise CustomDataError("插件进程异常退出")
                envelope = json.loads(result[0])
            except (OSError, ValueError) as error:
                self.stop()
                raise CustomDataError("插件进程通信失败：{}".format(error)) from error
            if not envelope.get("ok"):
                raise CustomDataError(envelope.get("error", "插件执行失败"))
            if envelope.get("request_id") != request_id:
                self.stop()
                raise CustomDataError("插件进程响应标识不匹配")
            return envelope.get("data")

    def collect(self, config=None, timeout=DEFAULT_SCRIPT_TIMEOUT_SECONDS):
        """请求常驻进程执行一次采集。"""
        return self._request(
            "collect",
            {"config": json.dumps(config or {}, ensure_ascii=False)},
            timeout,
        )

    def invoke(self, method_name, context=None, timeout=DEFAULT_SCRIPT_TIMEOUT_SECONDS):
        """请求插件执行一个由清单授权的方法。"""
        return self._request(
            "invoke",
            {"method": str(method_name), "context": dict(context or {})},
            timeout,
        )

    def uninstall(self, context=None, timeout=DEFAULT_SCRIPT_TIMEOUT_SECONDS):
        """请求插件执行固定名称的卸载清理钩子。"""
        return self._request(
            "uninstall",
            {"context": dict(context or {})},
            timeout,
        )

    def stop(self):
        """终止插件进程并关闭通信管道。"""
        with self.lock:
            process, self.process = self.process, None
            if process is None:
                return
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()


class CustomDataCollectionTask(CollectionTask):
    """把单个自定义数据插件封装为标准采集任务。"""

    order = 2000

    def __init__(self, manager, definition):
        """保存插件管理器和插件定义，并设置任务标识、中文名和频率。"""
        super().__init__(manager)
        self.manager = manager
        self.definition = definition
        self.plugin_name = definition.name
        self.name = definition.task_name
        self.zh_name = definition.zh_name
        self.default_interval = float(definition.interval)
        self.interval = float(definition.interval)

    def update_definition(self, definition):
        """更新插件定义，并同步默认采集频率和中文名称。"""
        self.definition = definition
        self.plugin_name = definition.name
        self.name = definition.task_name
        self.zh_name = definition.zh_name
        self.default_interval = float(definition.interval)
        self.interval = float(definition.interval)

    def collect(self):
        """执行插件采集并返回可合并到完整快照的 ext 片段。"""
        return {"ext": self.manager.collect_task_data(self.plugin_name)}


class CustomDataCollectionCoordinator:
    """使用独立线程池调度全部自定义数据采集任务。"""

    def __init__(
        self,
        manager,
        result_store,
        result_transform=None,
        task_intervals=None,
        task_logs_enabled=True,
        plugin_configs=None,
        plugin_enabled=None,
    ):
        """创建核心 1、最大 5、队列 100 的自定义数据采集协调器。"""
        self.manager = manager
        self.result_store = result_store
        self.result_transform = result_transform
        self.task_logs_enabled = bool(task_logs_enabled)
        self.task_intervals = dict(task_intervals or {})
        self.plugin_configs = dict(plugin_configs or {})
        self.manager.update_plugin_configs(self.plugin_configs)
        self.plugin_enabled = dict(plugin_enabled or {})
        self.manager.update_plugin_enabled(self.plugin_enabled)
        self.tasks = ()
        self.executor = BoundedElasticThreadPool(
            core_workers=CUSTOM_DATA_COLLECTION_POOL_CORE_WORKERS,
            max_workers=CUSTOM_DATA_COLLECTION_POOL_MAX_WORKERS,
            queue_capacity=CUSTOM_DATA_COLLECTION_QUEUE_CAPACITY,
        )
        self._sync_tasks()
        self.manager.prepare_environments_async()
        LOGGER = logging.getLogger("pico-monitor.custom-data")
        if self.task_logs_enabled:
            LOGGER.info("自定义数据采集线程池已初始化：%s", self._pool_state_text())
            LOGGER.info("自定义数据采集任务频率：%s", self._task_interval_text() or "无")

    def schedule(self):
        """提交当前到期且未在执行的自定义数据任务，队列饱和时丢弃。"""
        self._sync_tasks()
        self.manager.prepare_environments_async()
        now = time.monotonic()
        logger = logging.getLogger("pico-monitor.custom-data")
        for task in self.tasks:
            if not task.is_due(now):
                continue
            task.mark_scheduled(now)
            try:
                self.executor.submit(self._execute_and_publish, task)
                if self.task_logs_enabled:
                    logger.debug(
                        "自定义数据任务已提交：任务=%s，频率=%.3f秒，%s",
                        self._task_label(task),
                        task.interval,
                        self._pool_state_text(),
                    )
            except TaskRejectedError:
                task.mark_finished()
                logger.warning("自定义数据任务被丢弃：任务=%s，%s", self._task_label(task), self._pool_state_text())

    def activate_plugin(self, name):
        """将指定插件加入当前协调器，并把首次采集时间提前到现在。"""
        definition = self.manager.activate_plugin(name)
        self._sync_tasks()
        for task in self.tasks:
            if task.plugin_name == definition.name:
                task.next_run_time = 0.0
                break
        return definition

    def next_schedule_delay(self):
        """返回下一次自定义数据任务到期前需要等待的秒数。"""
        now = time.monotonic()
        due_times = [task.next_run_time for task in self.tasks if not task.scheduled]
        if not due_times:
            return min((task.interval for task in self.tasks), default=1.0)
        return max(0.0, min(due_times) - now)

    def close(self, wait=True):
        """关闭自定义数据采集线程池。"""
        if self.task_logs_enabled:
            logging.getLogger("pico-monitor.custom-data").info("自定义数据采集线程池准备关闭：%s", self._pool_state_text())
        self.executor.shutdown(wait=wait)
        if self.task_logs_enabled:
            logging.getLogger("pico-monitor.custom-data").info("自定义数据采集线程池已关闭：%s", self._pool_state_text())

    def update_runtime_settings(
        self,
        task_intervals,
        plugin_configs,
        task_logs_enabled,
        plugin_enabled=None,
    ):
        """热更新自定义数据任务频率和常规日志开关。"""
        self.task_intervals = dict(task_intervals or {})
        self.plugin_configs = dict(plugin_configs or {})
        self.manager.update_plugin_configs(self.plugin_configs)
        self.plugin_enabled = dict(plugin_enabled or {})
        self.manager.update_plugin_enabled(self.plugin_enabled)
        self.task_logs_enabled = bool(task_logs_enabled)
        self._sync_tasks()
        logging.getLogger("pico-monitor.custom-data").info(
            "自定义数据运行时配置已更新：日志=%s，频率=%s",
            "开启" if self.task_logs_enabled else "关闭",
            self._task_interval_text() or "无",
        )

    def _sync_tasks(self):
        """根据插件目录最新定义同步采集任务列表。"""
        existing = {task.plugin_name: task for task in self.tasks}
        tasks = []
        for definition in self.manager.task_definitions():
            task = existing.get(definition.name)
            if task is None:
                task = CustomDataCollectionTask(self.manager, definition)
            else:
                task.update_definition(definition)
            configured_interval = self.plugin_configs.get(task.plugin_name, {}).get("interval")
            if configured_interval is None:
                configured_interval = self.task_intervals.get(task.name)
            if configured_interval is not None:
                try:
                    task.configure_interval(configured_interval)
                except (TypeError, ValueError):
                    logging.getLogger("pico-monitor.custom-data").warning(
                        "忽略无效自定义数据采集频率配置：任务=%s，频率=%s",
                        task.name,
                        configured_interval,
                    )
            tasks.append(task)
        self.tasks = tuple(tasks)

    def _execute_and_publish(self, task):
        """执行单个自定义数据任务并发布快照片段。"""
        started = time.monotonic()
        task_label = self._task_label(task)
        logger = logging.getLogger("pico-monitor.custom-data")
        if self.task_logs_enabled:
            logger.debug("自定义数据任务开始：任务=%s，%s", task_label, self._pool_state_text())
        try:
            fragment = task.collect()
            if self.result_transform is not None:
                fragment = self.result_transform(fragment)
            self.result_store.publish(fragment)
            elapsed = time.monotonic() - started
            is_slow_task = elapsed >= CUSTOM_DATA_SLOW_TASK_WARNING_SECONDS
            if self.task_logs_enabled or is_slow_task:
                log_method = logger.warning if is_slow_task else logger.debug
                log_method(
                    "自定义数据任务完成：任务=%s，耗时=%.3f秒，更新字段=%s，%s",
                    task_label,
                    elapsed,
                    "、".join(fragment.keys()) or "无",
                    self._pool_state_text(),
                )
        except Exception as error:
            logger.exception(
                "自定义数据任务失败：任务=%s，耗时=%.3f秒，错误=%s，%s",
                task_label,
                time.monotonic() - started,
                error,
                self._pool_state_text(),
            )
        finally:
            task.mark_finished()
            task.scheduled = False

    def _task_interval_text(self):
        """把所有自定义数据任务当前采集频率格式化为日志文本。"""
        return "、".join("{}={}秒".format(self._task_label(task), task.interval) for task in self.tasks)

    def _pool_state_text(self):
        """把自定义数据采集线程池状态格式化为中文日志文本。"""
        state = self.executor.state()
        return (
            "线程池[核心={core_workers}，最大={max_workers}，已创建={workers}，"
            "活跃={active}，空闲={idle}，排队={queued}/{queue_capacity}]"
        ).format(**state)

    @staticmethod
    def _task_label(task):
        """返回日志中使用的自定义数据任务中文名称和英文标识。"""
        return "{}({})".format(task.zh_name, task.name) if task.zh_name != task.name else task.name
