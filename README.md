# Pico 系统监控屏

本项目将系统信息采集与图像渲染彻底分离：电脑只负责采集系统参数并通过 JSON 发送，Pico 负责生成 RGB565 图像，并固定每 0.5 秒刷新一次 ST7789 屏幕。

## 文件职责

Pico 端文件位于 `pico/`，需要将该目录中的全部文件复制到 Pico 根目录：

- `pico/main.py`：启动入口，只负责编排 JSON 接收和 0.5 秒渲染循环。
- `pico/config.py`：屏幕、引脚、协议和颜色配置。
- `pico/lcd.py`：ST7789 初始化与整帧输出驱动。
- `pico/canvas.py`：RGB565 帧缓冲基础绘图。
- `pico/font_5x7.py`：紧凑型 ASCII 点阵字体。
- `pico/dashboard.py`：系统监控仪表盘布局和渲染。
- `pico/protocol.py`：USB 握手、轮询和 JSON 数据包解析。

电脑端文件位于项目根目录：

- `send_frame.py`：电脑端启动入口和发送周期编排。
- `system_monitor.py`：CPU、内存、磁盘、网络、温度与 Ping 数据采集。
- `pico_client.py`：Pico 串口发现、握手和 JSON 发送。

## 通信协议

每个数据包由三部分连续组成：

```text
JSN0 + 4 字节大端 JSON 长度 + UTF-8 JSON
```

握手命令保持为 `PING:PICO_LCD?\n`，支持自动发现串口。Pico 只缓存最新 JSON；即使电脑发送间隔发生抖动，LCD 仍由 Pico 自身时钟每 500 ms 重绘。

## 使用方法

1. 将 `pico/` 目录内的全部 `.py` 文件保存到 Pico 根目录并重启。
2. 在电脑端安装依赖：`python -m pip install -r requirements.txt`。
3. 启动采集程序：`python send_frame.py`。

可使用 `--port COM3` 固定串口，使用 `--ping-target 1.1.1.1` 修改 Ping 目标。
