# Pico LCD 系统硬件监控程序

本目录提供独立电脑端监控程序，兼容 `pico-project/picoRP2040` 固件的 `JSON:` 行协议。程序通过操作系统内核公开接口采集 CPU、内存、磁盘、网络、运行时间和可用温度传感器数据，经 USB 串口持续发送给 Pico RP2040。

本程序不安装自定义内核驱动：Windows 使用系统性能接口和串口驱动，Linux 使用 `/proc`、`/sys` 及系统串口驱动。这样无需驱动签名，也不会绑定特定内核版本。

磁盘明细通过 JSON 顶层 `disks` 数组发送。同一物理盘的多个分区会合并，字段包括 `name`、`devices`、`mountpoints`、`filesystems`、`used_bytes`、`total_bytes`、`percent`、`temperature_c` 和 `health`。同时，面向 Pico 显示的物理磁盘统计通过顶层 `physical_disks` 数组发送，每块物理盘也包含 `health`、温度、容量、占用率、实时读写速度 `read_bps`/`write_bps`，以及固定长度的读写速度历史 `read_history`/`write_history`。程序在启动时检查 SMART，之后每 30 分钟复查；Linux 需要安装 `smartmontools`。`health` 取值为：`0` 未知、`1` 健康、`2` 注意、`3` 警告、`4` 严重、`5` 失败。分级以 smartmontools 总体自检结论为最高优先级，并结合 NVMe Critical Warning、寿命百分比和 ATA 重映射、待映射及不可校正扇区等公开指标；无法读取 SMART、USB 硬盘盒不支持或权限不足时返回 `0`。

网络统计通过 `network.receive_bytes` 提供已下载总流量，通过 `network.transmit_bytes` 提供已上传总流量，单位均为字节。

开启并配置 qBittorrent Web UI 后，程序会在后台通过 Web API 采集 `qbittorrent` 顶层指标，不会阻塞系统指标发送。字段包括实时上传下载速度及历史、会话与历史流量、历史分享率、会话丢弃、连接用户、下载目录剩余空间和种子状态数量。完整配置与字段说明见 [qbittorrent_config.md](qbittorrent_config.md)。

## 主要功能

- 自动发现并握手识别 Pico LCD，也可固定串口。
- 磁盘汇总统计所有有效本地分区，并发送每个磁盘的设备、挂载点、容量、占用率和可用温度。
- Linux 支持通过 RAPL 能耗计数器发送实时功耗；不支持的平台明确发送空值。
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
--ping-target 1.1.1.1       指定延迟探测目标，默认 www.baidu.com
--interval 1.0              指定采集发送间隔
--reconnect-interval 3.0    指定断线重连间隔
--screen-rotation 180       将 Pico 屏幕旋转一百八十度
--network-unit MB           按 B/s、KB/s、MB/s、GB/s 自动选择单位
--network-unit Mbps         按 bps、Kbps、Mbps、Gbps 自动选择单位
--lcd-style default|disk|horizontal_disk|horizontal_disk4x|horizontal_disk4x_qb|horizontal_disk6x
                            切换 Pico 固件内置 LCD 样式；horizontal_disk4x_qb 保留双列四磁盘布局，并将 IP/GPU 区域替换为 qBittorrent 仪表盘
--qbittorrent-enabled       开启 qBittorrent 指标采集
--no-qbittorrent            显式关闭 qBittorrent 指标采集
--qbittorrent-address http://127.0.0.1:8080
                            qBittorrent Web UI 地址
--qbittorrent-username admin
                            qBittorrent Web UI 登录账号
--qbittorrent-password password
                            qBittorrent Web UI 登录密码
--qbittorrent-interval 2.0 qBittorrent 指标采集间隔，单位为秒
--disk-health-test-index 1  指定从 1 开始的磁盘序号并启用 health 显示测试，0 表示关闭
--disk-health-test-level 3  指定测试 health 等级 0 至 5，默认 3
--dev                       开发模式；未发现 Pico 后停止重试并持续打印 JSON
--once                      成功发送一次后退出
```

开发模式也可通过环境变量 `PICO_MONITOR_DEV=1` 开启。首次串口扫描未找到 Pico 后，程序不再重试 COM 口，而是按照 `--interval` 周期持续采集，并以 `[DEV][Monitor -> Pico][JSON]` 标识打印完整 `JSON:` 协议行，方便在没有硬件时调试采集数据。

qBittorrent 也可通过环境变量 `PICO_MONITOR_QBITTORRENT_ENABLED`、`PICO_MONITOR_QBITTORRENT_ADDRESS`、`PICO_MONITOR_QBITTORRENT_USERNAME`、`PICO_MONITOR_QBITTORRENT_PASSWORD` 和 `PICO_MONITOR_QBITTORRENT_INTERVAL` 配置。启用采集后地址、账号、密码必须全部配置。建议使用环境变量或 Linux 配置文件保存密码，避免密码出现在进程命令行中。

## 构建 Windows EXE

在 Windows 命令提示符执行：

```bat
build-exe.bat
```

输出文件为 `dist\pico-monitor.exe`。双击后驻留系统托盘，运行日志位于 `%LOCALAPPDATA%\PicoMonitor\pico-monitor.log`。

日志使用 `[Monitor -> Pico]` 和 `[Pico -> Monitor]` 标识通信方向。Linux 服务可通过 `journalctl -u pico-monitor -f` 实时查看相同内容。

## 构建 Linux DEB

Linux 发布明确构建以下四种架构：

- `amd64`：主流 Intel/AMD 64 位电脑，优先支持 Debian、Ubuntu。
- `arm64`：64 位 ARM 设备，包括 Ubuntu Server ARM64 和 Debian ARM64。
- `armhf`：32 位 ARM 硬浮点设备，包括部分 Raspberry Pi OS。
- `i386`：32 位 Intel/AMD 电脑。

DEB 原生支持 Debian、Ubuntu 及使用兼容 APT 依赖仓库的衍生发行版。Fedora、RHEL、openSUSE、Arch Linux 等非 Debian 系统请使用 Release 中的通用 `linux.tar.gz`，解压后运行 `sudo ./install-linux.sh`。

在 Debian 或 Ubuntu 中执行：

```bash
sudo apt update
sudo apt install build-essential debhelper devscripts
chmod 0755 debian/rules bin/pico-monitor
dpkg-buildpackage --no-sign -b
sudo apt install ../pico-monitor_1.0.0_$(dpkg --print-architecture).deb
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

## GitHub Actions 自动发布

`pico-project/.github/workflows` 提供 Windows EXE 与 Linux DEB 两套工作流。手动运行工作流时只生成 Actions Artifact；推送 `v` 开头的标签时会自动创建或更新 GitHub Release，并上传以下产物：

- `pico-monitor-windows-x86.exe`
- `pico-monitor-windows-x64.exe`
- `pico-monitor_<版本>_amd64.deb`：Intel/AMD 64 位电脑
- `pico-monitor_<版本>_arm64.deb`：ARM 64 位设备
- `pico-monitor_<版本>_armhf.deb`：ARM 32 位硬浮点设备
- `pico-monitor_<版本>_i386.deb`：Intel/AMD 32 位电脑
- `pico-monitor-<版本>-linux.tar.gz`：Fedora、RHEL、openSUSE、Arch 等 systemd 发行版通用安装包

发布示例：

```bash
git tag v1.0.0
git push origin v1.0.0
```
