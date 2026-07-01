# Pico RP2040 系统监控屏

项目包含电脑端数据采集程序和 Pico RP2040 显示程序，实现两个独立功能：

1. 非阻塞控制 GPIO22 上的 WS2812 状态灯；绿色表示运行，蓝色表示收到有效 JSON。
2. 通过 USB 串口增量接收 JSON，并将 ST7789 LCD 按 48 行条带异步刷新。

## 设计约束

- 不使用 RP2040 第二核心，规避 MicroPython 线程、USB 和 SPI 之间的互锁风险。
- 串口通过 `uselect.poll()` 检查后逐字节读取，主循环中不存在无限阻塞读取。
- LCD 不申请 240×320 的整帧缓冲，仅使用 240×48×2，即 23,040 字节条带缓冲。
- LED、串口接收和 LCD 刷新均由单核协作式主循环调度。
- JSON 最大长度为 16 KiB，超限数据包会被拒绝。

## Pico 端文件

将 `picoRP2040/` 内全部 `.py` 文件复制到 Pico 根目录：

- `main.py`：应用入口和协作式主循环。
- `ledController.py`：WS2812 非阻塞状态机。
- `protocol.py`：USB 握手及 JSON 增量接收状态机。
- `data_receiver.py`：最新 JSON 快照缓存。
- `lcd.py`：ST7789 初始化和区域写屏。
- `canvas.py`：带条带裁剪的 RGB565 绘图。
- `dashboard.py`：仪表盘布局和分段刷新。
- `config.py`：引脚、周期、协议和颜色配置。

## 通信协议

数据包采用纯 ASCII 行协议，避免 MicroPython 将二进制 `0x03` 解释为 Ctrl+C：

```text
JSON: + 单行 UTF-8 JSON + 换行符
```

设备发现命令为 `PING:PICO_LCD?\n`，有效 JSON 接收完成后返回 `ACK:JSON\n`。

## 启动方式

```powershell
python -m pip install -r requirements.txt
python send_frame.py
```

固定串口时可增加 `--port COM3` 参数。
