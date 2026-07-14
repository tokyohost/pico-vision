# ESP32-S3 设备端代码

本目录是从 `picoRP2040` 独立出来的 ESP32-S3 专用实现，不包含 RP2040 硬件档案、Pico USB Device 驱动或跨开发板选择逻辑。

## 固定硬件配置

- 开发板：ESP32-S3
- 状态灯：GPIO48 板载 WS2812，单灯珠
- LCD 总线：SPI2，SCK GPIO12，MOSI GPIO11，保留 MISO GPIO15
- LCD 控制：CS GPIO10，DC GPIO9，RST GPIO14，背光 PWM GPIO13
- 按键：GPIO1、GPIO2、GPIO3，低电平有效并启用内部上拉
- 通信：ESP32-S3 内置 USB 控制台和可选 Wi-Fi WebSocket

## 固件要求

推荐使用仓库 `esp32/driver` 中带原生 PV1 加速模块的 ESP32-S3 MicroPython 固件。标准固件缺少原生模块时，协议与画布会自动使用纯 Python 后端，但必须提供 `network`、`neopixel`、`machine.SPI`、`machine.PWM` 和内置 USB 控制台能力。

部署时将本目录中的 Python 文件及子目录复制到 ESP32-S3 文件系统根目录，并以 `main.py` 作为启动入口。

## 第二阶段渲染服务

ESP32-S3 专用入口已经使用 `render_service.py` 隔离通信主循环与渲染状态：

- 通信主线程只解析 USB/WIFI 数据并发布最新快照。
- Python 渲染工作线程独占 `DashboardRenderer`、Canvas、LCD 和 SPI。
- 两个固定快照槽采用最新帧覆盖策略，避免渲染落后时积压旧画面。
- 样式切换、旋转、背光和截图通过八项固定控制队列在渲染线程执行。
- 线程模块不可用或线程创建失败时，自动回退到相同接口的同步渲染服务。
- 启动日志通过 `BOOT:RENDER_SERVICE:THREAD` 或 `SYNC_FALLBACK` 标明实际模式。

该阶段可以在 SPI DMA 等待释放 GIL 时让通信主线程继续运行，但所有 MicroPython 线程仍受 GIL 和 CPU1 亲和性限制。真正把绘制计算固定到 CPU0 需要继续实施原生 C 渲染任务。
