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
