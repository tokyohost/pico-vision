# Windows FPS 采集

主后端使用 PresentMon 的 ETW 事件，AMD ADLX 是可选回退。采集器只统计前台进程最活跃的 SwapChain，不写 CSV、不采集 GPU 时序和输入延迟。

## 部署 PresentMon

仓库已包含官方 PresentMon 2.4.1 64 位控制台程序（SHA-256：`D74183E7AE630F72CD3690BE0373ECBFDC6CBB86578148AAB8FA2A7166068F34`）。也可以通过环境变量 `PICO_MONITOR_PRESENTMON` 指定其他版本，或把它加入 `PATH`。未安装时 JSON 中 `fps.source` 为 `unavailable`，不会影响其他指标。

PresentMon ETW 会持续接收帧事件；JSON 和 history 每秒更新一次。部分 Windows 账户需要管理员权限或加入 `Performance Log Users` 用户组才能启动 ETW 会话。

## 可选 AMD ADLX

Python 端使用稳定的三函数 C ABI，桥接库应导出：

```c
int adlx_fps_initialize(void);
int adlx_fps_current(int* fps);
void adlx_fps_shutdown(void);
```

仓库的 `bridge/adlx_fps_bridge.cpp` 已实现该接口。安装 Visual Studio C++ 和 CMake 后，在 `bridge` 目录执行：

```text
cmake -S . -B build -A x64 -DADLX_SDK_ROOT=D:/SDK/ADLX/SDK
cmake --build build --config Release
```

产物会进入 `monitor/win/fps/bin`，也可以通过 `PICO_MONITOR_ADLX_BRIDGE` 指定其他位置。桥接库及 ADLX 运行库必须按照 AMD ADLX SDK 的许可要求分发。

## JSON

```json
"fps": {
  "value": 60.0,
  "history": [0, 0, 59.0, 60.0],
  "source": "presentmon_etw",
  "process_id": 1234,
  "process_name": "game.exe"
}
```
