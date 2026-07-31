# OmniWatch NAS 安装说明

本文说明群晖、威联通和 TrueNAS 的支持版本、发布包选择、安装步骤与限制。

## 支持范围

| NAS 系统 | 支持版本 | 发布包 | 安装方式 |
|---|---|---|---|
| 群晖 DSM | DSM 7.2 及以上 | `OmniWatch-synology-noarch-v<版本>.tar.gz` | SSH 解压安装 |
| QNAP QTS | QTS 5.1 及以上 | `OmniWatch-qnap-noarch-v<版本>.tar.gz` | SSH 解压安装 |
| QNAP QuTS hero | h5.1 及以上 | `OmniWatch-qnap-noarch-v<版本>.tar.gz` | SSH 解压安装 |
| TrueNAS SCALE | 24.10 及以上 | `OmniWatch-truenas-noarch-v<版本>.tar.gz` | 自定义 Docker App 优先；宿主机安装仅用于测试 |
| TrueNAS CORE | 13.3 | 采集代码兼容 FreeBSD | 不提供生产安装包 |

发布包是与 CPU 架构无关的 Python 源码包，安装时在 NAS 本机创建虚拟环境。使用前应先从厂商应用中心安装 Python 3，并确保 `python3 --version` 为 3.10 或更高版本。

TrueNAS CORE 13.3 已把 Plugin、Jail 和虚拟机标记为停用且不再提供支持，因此不把 Jail 安装作为生产方案。需要长期运行时应迁移到 TrueNAS SCALE。

## 校验版本与摘要

下载与 NAS 对应的压缩包和 `OmniWatch-SHA256SUMS-nas.txt`，然后执行：

```sh
sha256sum -c OmniWatch-SHA256SUMS-nas.txt --ignore-missing
tar -xzf OmniWatch-synology-noarch-v1.0.0.tar.gz
cd OmniWatch-synology-noarch-v1.0.0
cat nas-package.json
```

`nas-package.json` 中的 `version` 是 Monitor 版本，`format` 是 NAS 包格式版本。运行版本可在安装后通过 `pico-monitor --version` 查看。

## 群晖 DSM

在“控制面板 → 终端机和 SNMP”中临时开启 SSH，通过管理员账号登录并切换为 root：

```sh
sudo -i
cd /volume1/下载目录/OmniWatch-synology-noarch-v1.0.0
chmod 0755 install-linux.sh
./install-linux.sh
```

DSM 提供 systemd 时安装脚本会注册并启动 `pico-monitor.service`。查看状态：

```sh
systemctl status pico-monitor
journalctl -u pico-monitor -f
```

安装完成并确认服务正常后，建议关闭 DSM SSH。系统大版本升级后应复查服务状态。

## QNAP QTS 与 QuTS hero

在“控制台 → 网络和文件服务 → Telnet/SSH”中临时开启 SSH，然后执行：

```sh
sudo -i
cd /share/Public/OmniWatch-qnap-noarch-v1.0.0
chmod 0755 install-linux.sh
./install-linux.sh
```

部分 QNAP 固件没有 systemd。此时脚本只安装程序，不修改 QNAP 的 `qpkg.conf` 或厂商启动配置，以免系统升级后产生无效配置。可先手动验证：

```sh
pico-monitor --version
pico-monitor --config /etc/pico-monitor.conf
```

需要开机启动时，应通过 QNAP App Center 支持的自动运行机制或管理员维护的启动脚本调用上述命令。升级 QTS/QuTS hero 后应重新确认 Python、USB 权限和启动项。

## TrueNAS SCALE

TrueNAS SCALE 24.10 及以上推荐通过“Apps → Discover → Custom App”运行第三方容器，不建议直接修改只读或由升级管理的宿主系统。容器需要：

- 使用 Host Network；
- 映射 `/dev` 中实际使用的 Pico USB 设备；
- 只读映射宿主 `/proc` 和 `/sys` 才能采集宿主指标；
- 为配置和运行数据挂载持久化数据集；
- 使用与发布版本一致的镜像标签或源码包版本。

直接运行 `install-linux.sh` 仅用于开发测试，而且 TrueNAS 升级可能清除宿主机改动。生产环境应制作基于该发布包的固定版本容器镜像，再通过 Custom App 安装。

## 配置与排错

配置文件位于 `/etc/pico-monitor.conf`。建议优先使用 Wi-Fi WebSocket 连接 Pico；USB 连接需要确认 NAS 能看到设备：

```sh
ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
pico-monitor --version
pico-monitor --dev
```

CPU 温度、SMART 和 USB 串口通常需要 root 或等效设备权限。群晖、QNAP、TrueNAS 的系统升级都可能改变传感器路径或设备权限，升级后应检查日志和采集字段。
