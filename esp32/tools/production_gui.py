"""提供 ESP32-S3 USB 自动量产界面，串行完成 SDK 刷写和代码部署。"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


TOOLS = Path(__file__).resolve().parent
PROJECT = TOOLS.parents[1]
COPY_SCRIPT = PROJECT / "tools" / "mpremote_stream_copy.py"
USB_VIDS = {0x303A, 0x10C4, 0x1A86, 0x0403}
PROBE_PREFIX = "PRODUCTION_DEVICE:"
PROBE_CODE = (
    "import sys, os, json, machine\n"
    "d={'platform':sys.platform,'machine':os.uname().machine,"
    "'version':os.uname().release,'id':machine.unique_id().hex(),'sdk':False}\n"
    "try:\n"
    " import fn_protocol\n"
    " d['sdk']=fn_protocol.api_version()==1 and callable(fn_protocol.parse_frame)\n"
    "except (ImportError,AttributeError):\n"
    " pass\n"
    "print('PRODUCTION_DEVICE:'+json.dumps(d))\n"
)


def select_sdk(script: Path) -> tuple[Path, str, int, str]:
    """读取最后一条刷写命令，并按同系列数字版本选择最新 SDK。"""
    commands = []
    for line in script.read_text(encoding="utf-8-sig").splitlines():
        tokens = [item.strip('\"\'') for item in shlex.split(line, posix=False)]
        if "esptool" in tokens and any(item in tokens for item in ("write_flash", "write-flash")):
            commands.append(tokens)
    if not commands:
        raise ValueError("flash.sh 中没有可识别的 esptool 刷写命令")
    tokens = commands[-1]
    index = next(i for i, token in enumerate(tokens) if token in ("write_flash", "write-flash"))
    # 当前项目使用一个完整合并镜像；拒绝静默丢弃其他地址或镜像。
    if len(tokens[index + 1:]) != 2:
        raise ValueError("量产入口仅支持 flash.sh 中单个地址、单个合并镜像的命令")
    chip = tokens[tokens.index("--chip") + 1]
    baud = int(tokens[tokens.index("--baud") + 1])
    address = tokens[index + 1]
    if chip != "esp32s3" or int(address, 0) != 0:
        raise ValueError("当前量产代码库仅支持 ESP32-S3、0x0 合并镜像")
    name = tokens[index + 2].replace("\\", "/").rsplit("/", 1)[-1]
    match = re.fullmatch(r"(.+)-v(\d+(?:\.\d+)+)(.*\.bin)", name)
    if not match:
        raise ValueError("SDK 文件名必须包含 -v数字版本，例如 -v1.0.69")
    pattern = re.compile(re.escape(match[1]) + r"-v(\d+(?:\.\d+)+)" + re.escape(match[3]))
    candidates = []
    for path in script.parent.glob("*.bin"):
        found = pattern.fullmatch(path.name)
        if found:
            candidates.append((tuple(map(int, found[1].split("."))), path))
    if not candidates:
        raise ValueError("flash.sh 同目录没有相同硬件规格和固件系列的 SDK")
    return max(candidates)[1], chip, baud, address


def port_key(port) -> str:
    """优先按 USB 物理位置合并双 CDC 接口，兼容串口号变化。"""
    location = str(port.location or "").lower().split(":", 1)[0]
    return "usb:" + location if location else "serial:" + str(port.serial_number) if port.serial_number else "port:" + port.device


def candidate_groups(ports) -> dict[str, list]:
    """筛选 USB 串口候选，VID 只用于发现，真实型号由后续握手确认。"""
    result = {}
    for port in ports:
        if port.vid in USB_VIDS:
            result.setdefault(port_key(port), []).append(port)
    return result


class ProductionWorker:
    """在后台线程中监测 USB，并确保一块设备处理完成后才处理下一块。"""

    def __init__(self, source: Path, events: queue.Queue):
        """保存不可变批次配置及线程通信队列。"""
        self.source = source
        self.events = events
        self.stop = threading.Event()
        self.log_file = None
        self.progress_range = (0, 0)
        self.progress = 0.0

    def stage(self, start: float, end: float):
        """设置当前阶段占用的流程进度区间，完成校验前不显示百分之百。"""
        self.progress_range = (start, end)
        self.progress = start
        self.emit("progress", str(start))

    def update_progress(self, line: str):
        """从 SDK 写入、代码同步和校验输出提取百分比，映射为单板流程进度。"""
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)
        if not any(marker in text.lower() for marker in ("writing", "校验进度", "production_verify:")):
            return
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if match:
            start, end = self.progress_range
            value = start + (end - start) * min(100, float(match[1])) / 100
            if value > self.progress:
                self.progress = value
                self.emit("progress", str(value))

    def emit(self, kind: str, value: str):
        """发送界面事件，并把日志逐行保存到本地批次文件。"""
        self.events.put((kind, value))
        if kind == "log" and self.log_file and not self.log_file.closed:
            self.log_file.write(time.strftime("%H:%M:%S ") + value + "\n")
            self.log_file.flush()

    def command(self, args: list[str], timeout: float = 30, quiet: bool = False) -> str:
        """执行隔离子进程，实时读取输出，并在超时后结束进程。"""
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        output = []
        lines = queue.Queue()
        process = subprocess.Popen(
            [sys.executable, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        def read_output():
            """持续排空子进程输出，避免管道阻塞，并发送结束哨兵。"""
            try:
                for line in process.stdout:
                    lines.put(line.rstrip())
            finally:
                process.stdout.close()
                lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"命令超时（{timeout:g} 秒）")
                try:
                    line = lines.get(timeout=min(0.2, remaining))
                except queue.Empty:
                    continue
                if line is None:
                    break
                output.append(line)
                if not quiet:
                    self.emit("log", line)
                    self.update_progress(line)
            code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
            if code:
                raise RuntimeError(f"命令退出码 {code}：" + "\n".join(output[-12:]))
            return "\n".join(output)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            reader.join(timeout=2)

    def probe(self, port: str) -> dict | None:
        """读取真实设备运行环境，区别定制 SDK、普通固件及无法进入 REPL 的设备。"""
        try:
            output = self.command(["-m", "mpremote", "connect", port, "exec", PROBE_CODE], 10, True)
            for line in output.splitlines():
                if line.startswith(PROBE_PREFIX):
                    return json.loads(line[len(PROBE_PREFIX):])
        except (OSError, RuntimeError, TimeoutError, ValueError) as error:
            self.emit("log", f"{port} REPL 暂不可用：{error}")
        return None

    def ports(self, key: str) -> list:
        """仅返回当前目标物理设备的串口，防止重枚举后误选其他板卡。"""
        from serial.tools import list_ports
        return candidate_groups(list_ports.comports()).get(key, [])

    def wait_runtime(self, key: str, expected_id: str | None = None) -> tuple[str, dict]:
        """等待刷机后目标重新枚举，并验证定制 SDK 与设备身份。"""
        deadline = time.monotonic() + 65
        time.sleep(2)
        while time.monotonic() < deadline:
            for port in self.ports(key):
                info = self.probe(port.device)
                if info and info.get("sdk") and self.is_s3(info):
                    if expected_id and info["id"] != expected_id:
                        raise RuntimeError("设备身份变化，已停止代码部署")
                    return port.device, info
            time.sleep(1)
        raise RuntimeError("未找到同一 USB 位置的定制 SDK REPL；请检查 USB、驱动或按 RESET 后重新插入")

    @staticmethod
    def is_s3(info: dict) -> bool:
        """通过设备返回的平台及芯片名称确认 ESP32-S3。"""
        return info.get("platform") == "esp32" and "ESP32S3" in re.sub(r"[^A-Z0-9]", "", info.get("machine", "").upper())

    def process(self, key: str, ports: list, config: tuple):
        """先识别已有 SDK，否则验证 ROM 芯片和容量后刷写，再同步代码。"""
        image, chip, baud, address = config
        self.emit("activity", "busy")
        self.stage(0, 10)
        self.emit("status", "识别设备 / " + ", ".join(port.device for port in ports))
        runtime = None
        selected = None
        for port in ports:
            info = self.probe(port.device)
            if info:
                if not self.is_s3(info):
                    raise RuntimeError("检测到非 ESP32-S3 设备，已跳过")
                runtime, selected = info, port.device
                break
        if runtime and runtime.get("sdk"):
            self.emit("log", f"{selected} 已安装定制 SDK {runtime['version']}，直接同步 Python 代码")
        else:
            if runtime:
                # 普通 MicroPython 的原生 USB 需要先主动切换 ROM 下载模式。
                try:
                    self.command(["-m", "mpremote", "connect", selected, "exec", "import machine; machine.bootloader()"], 10, True)
                except (RuntimeError, TimeoutError):
                    pass  # 切换下载模式造成当前串口断开，随后仍必须通过 ROM 握手。
                time.sleep(3)
            self.emit("status", "确认 ROM 芯片与 Flash 容量")
            selected = None
            deadline = time.monotonic() + 25
            errors = []
            while time.monotonic() < deadline and selected is None:
                for port in self.ports(key):
                    try:
                        output = self.command(["-m", "esptool", "--chip", chip, "--port", port.device, "flash-id"], 15)
                        capacity = re.search(r"Detected flash size:\s*(\d+)\s*MB", output, re.I)
                        required = re.search(r"-N(\d+)R", image.name)
                        if not capacity or (required and int(capacity[1]) < int(required[1])):
                            raise ValueError("Flash 容量无法确认或小于 SDK 所需容量")
                        selected = port.device
                        break
                    except (OSError, RuntimeError, TimeoutError) as error:
                        errors.append(str(error))
                if selected is None:
                    time.sleep(1)
            if selected is None:
                raise RuntimeError("ROM 握手失败；请按住 BOOT 接入 USB，检查驱动或关闭占用串口的软件。\n" + "\n".join(errors[-1:]))
            self.emit("status", "正在刷入 SDK / " + image.name)
            self.stage(10, 55)
            # 使用现有受控刷写器处理原生 USB watchdog 复位断连，同时保留镜像校验。
            self.command([str(Path(__file__).resolve()), "--flash", selected, str(image), str(baud)], 180)
            self.emit("status", "SDK 写入完成，等待重新枚举")
            self.stage(55, 60)
            selected, runtime = self.wait_runtime(key, runtime["id"] if runtime else None)
        self.emit("log", f"目标设备：{runtime['id']} / {selected}")
        self.emit("status", "正在同步 Python 代码 / " + selected)
        self.stage(60, 90)
        self.command([str(COPY_SCRIPT), selected, "--source", str(self.source), "--no-reset"], 1800)
        self.emit("status", "正在校验代码文件 SHA-256")
        self.stage(90, 98)
        self.command([str(Path(__file__).resolve()), "--verify-code", selected, str(self.source)], 600)
        # 只有复制成功且设备仍能响应，才执行最终复位并统计成功。
        verified = self.probe(selected)
        if not verified or verified.get("id") != runtime["id"] or not verified.get("sdk"):
            raise RuntimeError("代码同步后设备身份或 SDK 校验失败")
        self.stage(98, 99)
        self.emit("status", "校验通过，正在复位设备")
        self.command(["-m", "mpremote", "connect", selected, "reset"], 15)
        self.emit("log", f"量产成功：{runtime['id']}；可拔出设备并插入下一块")

    def run(self):
        """锁定批次固件并监测插拔；成功或失败的设备均需拔出后才再次处理。"""
        try:
            from serial.tools import list_ports
            config = select_sdk(TOOLS / "flash.sh")
            load_flasher().inspect_sdk_image(config[0])
            if not self.source.is_dir() or not (self.source / "main.py").is_file():
                raise ValueError("代码目录必须存在且包含 main.py")
            if not COPY_SCRIPT.is_file():
                raise ValueError(f"找不到代码复制脚本：{COPY_SCRIPT}")
            for module in ("serial", "esptool", "mpremote"):
                if importlib.util.find_spec(module) is None:
                    raise ValueError(f"缺少依赖：{module}")
            logs = TOOLS / "production_logs"
            logs.mkdir(exist_ok=True)
            with (logs / time.strftime("%Y%m%d-%H%M%S.log")).open("a", encoding="utf-8") as self.log_file:
                self.emit("log", f"本批 SDK：{config[0]}；代码库：{self.source}")
                self.emit("log", "停止按钮会等待当前设备完成；不支持自动下载的板卡请按住 BOOT 插入 USB。")
                handled = {}
                first_seen = {}
                result_key = None
                self.emit("activity", "waiting")
                self.emit("status", "监测中 · 等待下一块设备")
                while not self.stop.is_set():
                    groups = candidate_groups(list_ports.comports())
                    now = time.monotonic()
                    for key in list(handled):
                        if key in groups:
                            handled[key] = now
                        elif now - handled[key] > 2:
                            del handled[key]
                    # 成功绿灯保留到该设备确认拔出，不能被普通监测轮询立即覆盖。
                    if result_key is not None and result_key not in handled:
                        result_key = None
                        self.emit("activity", "waiting")
                        self.emit("progress", "0")
                        self.emit("status", "监测中 · 等待下一块设备")
                    first_seen = {key: first_seen.get(key, now) for key in groups}
                    for key, ports in groups.items():
                        if self.stop.is_set():
                            break
                        if key in handled or now - first_seen[key] < 1.5:
                            continue
                        try:
                            self.process(key, ports, config)
                            self.emit("success", "1")
                            self.emit("progress", "100")
                            self.emit("activity", "complete")
                            self.emit("status", "写入完毕 · 可拔出设备（拔出至少 3 秒后插入下一块）")
                        except Exception as error:
                            self.emit("log", "处理失败：" + str(error))
                            self.emit("failure", "1")
                            self.emit("activity", "failed")
                            self.emit("status", "写入失败 · 请查看日志，拔出设备后重试")
                        handled[key] = time.monotonic()
                        result_key = key
                        # 完成一次设备事务后重新枚举，避免处理排队期间已拔出的旧 COM。
                        break
                    self.stop.wait(0.5)
        except Exception as error:
            self.emit("log", "启动失败：" + str(error))
            self.emit("activity", "failed")
        finally:
            self.log_file = None
            self.emit("stopped", "已停止")


def load_flasher():
    """加载已有 SDK 校验与刷写模块，避免复制项目内的底层刷机逻辑。"""
    spec = importlib.util.spec_from_file_location("production_sdk_flash", PROJECT / "monitor" / "sdk_flash.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_code(port: str, source: Path):
    """复用同步器的过滤和清单协议，逐文件核对设备端大小及 SHA-256。"""
    spec = importlib.util.spec_from_file_location("production_copy", COPY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    copier = module.MpremoteStreamCopier(port, source)
    files = [item for item in copier.source.rglob("*") if item.is_file() and copier._should_copy(item)]
    manifest = copier._read_remote_manifest(files)
    for index, item in enumerate(files, 1):
        if manifest.get(copier._remote_path(item)[1:]) != copier._local_fingerprint(item):
            raise RuntimeError(f"设备端代码校验失败：{item.relative_to(copier.source)}")
        print(f"PRODUCTION_VERIFY:{index / len(files) * 100:.1f}%", flush=True)
    print(f"代码校验通过：{len(files)} 个文件", flush=True)


def configure_tk():
    """补齐 Windows 虚拟环境未自动定位到的 Tcl/Tk 标准库目录。"""
    for variable, folder, marker in (("TCL_LIBRARY", "tcl8.6", "init.tcl"), ("TK_LIBRARY", "tk8.6", "tk.tcl")):
        path = Path(sys.base_prefix) / "tcl" / folder
        if variable not in os.environ and (path / marker).is_file():
            os.environ[variable] = str(path)


class ProductionApp:
    """提供简洁中文量产界面，通过事件队列保持 Tk 主线程响应。"""

    def __init__(self, root: tk.Tk):
        """创建 SDK 摘要、目录选择、量产按钮、统计和日志区域。"""
        self.root = root
        self.worker = None
        self.events = queue.Queue()
        self.success = self.failure = 0
        self.activity = "stopped"
        root.title("ESP32-S3 量产工具")
        root.geometry("850x640")
        root.minsize(700, 520)
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        body = ttk.Frame(root, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="ESP32-S3 自动量产", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        ttk.Label(body, text="插入 USB → 识别 SDK → 自动刷写 → 同步代码", foreground="#666666").pack(anchor="w", pady=(5, 15))
        self.sdk = tk.StringVar()
        ttk.Label(body, textvariable=self.sdk, wraplength=790).pack(anchor="w")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=12)
        ttk.Label(row, text="代码目录").pack(side="left")
        self.source = tk.StringVar(value=str(PROJECT / "esp32-s3"))
        self.entry = ttk.Entry(row, textvariable=self.source)
        self.entry.pack(side="left", fill="x", expand=True, padx=8)
        self.browse = ttk.Button(row, text="选择…", command=self.choose_source)
        self.browse.pack(side="left")
        controls = ttk.Frame(body)
        controls.pack(fill="x")
        self.start = ttk.Button(controls, text="开始量产", command=self.start_work)
        self.start.pack(side="left")
        self.stop_button = ttk.Button(controls, text="停止", command=self.stop_work, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        self.count = tk.StringVar(value="成功 0    失败 0")
        ttk.Label(controls, textvariable=self.count).pack(side="right")
        indicator = ttk.Frame(body)
        indicator.pack(fill="x", pady=(14, 0))
        self.lamp = tk.Canvas(indicator, width=30, height=30, highlightthickness=0,
                              background=style.lookup("TFrame", "background") or root.cget("background"))
        self.lamp_circle = self.lamp.create_oval(4, 4, 26, 26, fill="#94a3b8", outline="")
        self.lamp.pack(side="left")
        self.lamp_text = tk.StringVar(value="已停止")
        ttk.Label(indicator, textvariable=self.lamp_text, font=("Microsoft YaHei UI", 12, "bold")).pack(side="left", padx=6)
        ttk.Label(indicator, text="绿：完成可拔出   黄：等待下一块   红：正在写入", foreground="#666666").pack(side="right")
        progress_row = ttk.Frame(body)
        progress_row.pack(fill="x", pady=(8, 0))
        self.progress_value = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_row, maximum=100, variable=self.progress_value)
        self.progress_bar.pack(side="left", fill="x", expand=True)
        self.progress_text = tk.StringVar(value="流程进度 0%")
        ttk.Label(progress_row, textvariable=self.progress_text, width=16, anchor="e").pack(side="right")
        self.status = tk.StringVar(value="就绪 · 点击开始量产后自动监测 USB")
        ttk.Label(body, textvariable=self.status, wraplength=790).pack(anchor="w", pady=12)
        self.log = scrolledtext.ScrolledText(body, state="disabled", font=("Microsoft YaHei UI", 9), relief="solid", borderwidth=1)
        self.log.pack(fill="both", expand=True)
        self.refresh_sdk()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.pump)

    def refresh_sdk(self):
        """预览当前将被选中的固件，启动批次时再次解析配置。"""
        try:
            self.sdk.set("SDK：" + select_sdk(TOOLS / "flash.sh")[0].name)
        except Exception as error:
            self.sdk.set("SDK 配置错误：" + str(error))

    def set_activity(self, activity: str):
        """同时更新状态灯颜色和中文含义，失败时不会显示成功绿灯。"""
        colors = {
            "busy": ("#dc2626", "正在写入 · 请勿拔出"),
            "waiting": ("#eab308", "等待下一块"),
            "complete": ("#16a34a", "写入完毕 · 可拔出"),
            "failed": ("#eab308", "本块失败 · 等待重试"),
            "stopped": ("#94a3b8", "已停止"),
        }
        color, label = colors[activity]
        self.activity = activity
        self.lamp.itemconfigure(self.lamp_circle, fill=color)
        self.lamp_text.set(label)

    def choose_source(self):
        """选择待刷入的本地 Python 工程目录。"""
        folder = filedialog.askdirectory(initialdir=self.source.get())
        if folder:
            self.source.set(folder)

    def start_work(self):
        """启动后台量产线程并锁定当前配置。"""
        if self.worker is not None:
            return
        self.refresh_sdk()
        self.set_activity("waiting")
        self.progress_value.set(0)
        self.progress_text.set("流程进度 0%")
        self.worker = ProductionWorker(Path(self.source.get()), self.events)
        for widget in (self.start, self.browse, self.entry):
            widget.configure(state="disabled")
        self.stop_button.configure(state="normal")
        threading.Thread(target=self.worker.run, daemon=True).start()

    def stop_work(self):
        """停止接收新设备，允许当前刷写事务完整结束。"""
        if self.worker:
            self.worker.stop.set()
            self.status.set("正在停止 · 等待当前设备处理结束")
            self.stop_button.configure(state="disabled")

    def pump(self):
        """批量消费后台事件并限制可见日志大小，避免长时间量产占满内存。"""
        for _ in range(150):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log.configure(state="normal")
                self.log.insert("end", time.strftime("%H:%M:%S ") + value + "\n")
                if int(self.log.index("end-1c").split(".")[0]) > 1500:
                    self.log.delete("1.0", "300.0")
                self.log.see("end")
                self.log.configure(state="disabled")
            elif kind == "activity":
                self.set_activity(value)
            elif kind == "progress":
                percent = max(0, min(100, float(value)))
                self.progress_value.set(percent)
                self.progress_text.set(f"流程进度 {percent:.0f}%")
            elif kind in ("success", "failure"):
                if kind == "success":
                    self.success += 1
                else:
                    self.failure += 1
                self.count.set(f"成功 {self.success}    失败 {self.failure}")
            elif kind == "stopped":
                self.worker = None
                for widget in (self.start, self.browse, self.entry):
                    widget.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.status.set(value)
                if self.activity not in ("complete", "failed"):
                    self.set_activity("stopped")
            elif kind == "status" and not (self.worker and self.worker.stop.is_set()):
                self.status.set(value)
        self.root.after(100, self.pump)

    def close(self):
        """要求活动批次先平稳停止，避免关闭窗口造成半途刷写。"""
        if self.worker:
            self.stop_work()
            messagebox.showinfo("正在停止", "将完成当前设备后停止，请看到“已停止”后关闭窗口。")
        else:
            self.root.destroy()


def main():
    """区分后台 SDK 刷写入口与桌面 GUI 入口。"""
    if len(sys.argv) > 1 and sys.argv[1] == "--flash":
        return load_flasher().run_esptool_flash(sys.argv[2], sys.argv[3], int(sys.argv[4]), before="default-reset")
    if len(sys.argv) > 1 and sys.argv[1] == "--verify-code":
        verify_code(sys.argv[2], Path(sys.argv[3]))
        return 0
    configure_tk()
    root = tk.Tk()
    ProductionApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
