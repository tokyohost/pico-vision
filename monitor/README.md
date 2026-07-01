# Pico LCD 系统硬件监控程序

本目录提供独立电脑端监控程序，兼容 `pico-project/picoRP2040` 固件的 `JSON:` 行协议。程序通过操作系统内核公开接口采集 CPU、内存、磁盘、网络、运行时间和可用温度传感器数据，经 USB 串口持续发送给 Pico RP2040。

本程序不安装自定义内核驱动：Windows 使用系统性能接口和串口驱动，Linux 使用 `/proc`、`/sys` 及系统串口驱动。这样无需驱动签名，也不会绑定特定内核版本。

## 主要功能

- 自动发现并握手识别 Pico LCD，也可固定串口。
- 设备拔插、休眠唤醒或通信失败后自动重连。
- 完整记录握手、JSON 原文、数据块数量、Pico 响应、异常和超时。
- Windows 单文件 EXE、托盘运行、日志查看和当前用户自启动。
- Debian/Ubuntu DEB、systemd 守护、异常自动重启和开机启动。
- 全部源码采用无 BOM UTF-8，类和方法包含规范中文注释。

## 源码运行

```powershell
python -m pip install -r requirements.txt
python pico_monitor.py
```

常用参数：

```text
--port COM3                 固定 Windows 串口
--port /dev/ttyACM0         固定 Linux 串口
--ping-target 1.1.1.1       指定延迟探测目标
--interval 1.0              指定采集发送间隔
--reconnect-interval 3.0    指定断线重连间隔
--screen-rotation 180       将 Pico 屏幕旋转一百八十度
--once                      成功发送一次后退出
```

## 构建 Windows EXE

在 Windows 命令提示符执行：

```bat
build-exe.bat
```

输出文件为 `dist\pico-monitor.exe`。双击后驻留系统托盘，运行日志位于 `%LOCALAPPDATA%\PicoMonitor\pico-monitor.log`。

日志使用 `[Monitor -> Pico]` 和 `[Pico -> Monitor]` 标识通信方向。Linux 服务可通过 `journalctl -u pico-monitor -f` 实时查看相同内容。

## 构建 Linux DEB

在 Debian 或 Ubuntu 中执行：

```bash
sudo apt update
sudo apt install build-essential debhelper devscripts
chmod 0755 debian/rules bin/pico-monitor
dpkg-buildpackage --no-sign -b
sudo apt install ../pico-monitor_1.0.0_all.deb
```

安装后可使用以下命令：

```bash
sudo systemctl status pico-monitor
sudo journalctl -u pico-monitor -f
sudo systemctl restart pico-monitor
```

运行配置位于 `/etc/pico-monitor.conf`。服务默认以 `root` 运行，从而读取硬件传感器并访问 USB 串口；如果发行版已配置 `dialout` 权限，可按安全要求调整服务用户。

## Pico 固件要求

先将 `pico-project/picoRP2040` 下的 MicroPython 程序部署到 Pico。主机端会发送 `PING:PICO_LCD?` 完成设备识别，再发送 `JSON:` 加单行 JSON；固件应返回 `ACK:JSON`。
