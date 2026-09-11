# Linux DEB 配置完整说明

本文说明 Pico Monitor Linux DEB 安装包使用的配置文件、所有可配置项、取值限制和常见用途。文中的配置适用于 Debian、Ubuntu、Linux Mint、Raspberry Pi OS 等使用 APT 的系统；使用通用 tar 包的 Linux 主机也可以复用同一套 YAML 配置。

## 先确认：这里不是自定义内核驱动

Pico Monitor 是用户态监控程序，不会安装或编译自定义 Linux 内核模块。DEB 包通过 Python、`/proc`、`/sys`、`smartmontools`、系统串口驱动和可选的 NVML/显卡接口读取指标，再通过 USB CDC 或 WebSocket 发送给 Pico LCD。Linux 内核、USB 串口、显卡和磁盘驱动仍由发行版负责。

因此，本文中的“驱动配置”实际指 Linux DEB 服务和 Pico Monitor 的运行配置；修改配置不会改变内核驱动参数。如果 `/dev/ttyACM*`、GPU 温度或磁盘 SMART 不可用，应先检查内核模块、设备权限和硬件支持。

## 配置文件位置和生效方式

DEB 安装后使用以下文件：

```text
/etc/pico-monitor.conf
```

仓库中的默认模板是 [`debian/pico-monitor.conf`](debian/pico-monitor.conf)。安装脚本只在目标文件不存在时复制模板，因此升级 DEB 通常会保留你已经修改的配置。

systemd 服务通常位于 `/lib/systemd/system/pico-monitor.service` 或 `/etc/systemd/system/pico-monitor.service`，启动命令为：

```text
/usr/bin/pico-monitor --config /etc/pico-monitor.conf
```

配置修改后重启服务：

```bash
sudo systemctl daemon-reload
sudo systemctl restart pico-monitor
sudo systemctl status pico-monitor --no-pager
```

查看实时日志：

```bash
sudo journalctl -u pico-monitor -f
```

### 配置优先级

同一个选项同时出现在多个位置时，优先级从高到低为：

1. 命令行参数，例如 `--interval 2`。
2. 对应的 `PICO_MONITOR_*` 环境变量。
3. YAML 文件中的嵌套键，例如 `monitor.interval`。
4. 程序内置默认值。

systemd 的 DEB 服务不会自动读取交互式 Shell 的环境变量。需要通过环境变量覆盖配置时，应使用 systemd drop-in：

```bash
sudo systemctl edit pico-monitor
```

```ini
[Service]
Environment=PICO_MONITOR_INTERVAL=2
Environment=PICO_MONITOR_HTTP_AUTH=请替换为随机长密钥
```

保存后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart pico-monitor
```

### YAML 语法和类型

- 文件必须是一个 YAML 对象，推荐使用 UTF-8 无 BOM 编码。
- 布尔值使用 `true` 或 `false`，不要把 `on`、`off` 当成 YAML 布尔值依赖解析器行为。
- URL、设备路径、密码和包含特殊字符的字符串建议使用双引号。
- 时间间隔支持整数和小数，单位统一为秒。
- 数字、布尔值和对象不要写成带引号的字符串，除非该字段明确要求字符串。
- 未知键会被忽略，不会自动变成新的运行参数；拼写错误通常表现为“配置看起来正确但仍使用默认值”。

## 一份可直接修改的完整示例

下面的示例合并了 DEB 模板和高级选项。首次使用时至少修改 `serial.port`、网络连接方式和 `http.auth`；没有固定串口时可把 `serial.port` 留空。

```yaml
# /etc/pico-monitor.conf
serial:
  port: ""                         # 例如 /dev/ttyACM1；留空自动发现
  probe_interval: 3.0              # USB PING 探测间隔，秒

network:
  websocket_url: ""               # 例如 ws://192.168.1.50:8765/pv1
  force_usb_cdc: false             # true 时只使用 USB，不搜索 Wi-Fi
  websocket_client_name: ""       # WebSocket 握手时显示的客户端名称
  websocket_client_id: ""         # 稳定客户端标识，留空自动生成
  discovery_strategy: announcement # announcement 或 scan
  announcement_port: 37856
  announcement_group: "239.255.77.77"
  announcement_timeout: 3.0
  ping_target: "www.baidu.com"
  unit: MB                         # MB 或 Mbps
  # 以下四项在当前版本建议通过同名环境变量或命令行覆盖；
  # 解析器暂未把它们映射到嵌套 YAML 路径：
  # lan_probe_port: 8765
  # lan_probe_path: "/pv1"
  # lan_probe_timeout: 0.3
  # lan_probe_max_workers: 256

monitor:
  interval: 1.0                    # DEB 模板值；裸程序默认值为 0.5
  adaptive_transmit: true
  reconnect_interval: 3.0
  dev: false

screen:
  rotation: 0                      # 0 或 180
  lcd_brightness: 100              # 1 到 100；裸程序默认值为 50
  lcd_style: "fps_simple"
  idle_style: "idle"
  idle_timeout: 30

collection_tasks:
  logs_enabled: true
  intervals:
    basic_information: 1
    cpu_memory: 1
    disk_capacity_health: 60
    disk_temperature: 5
    disk_rate: 1
    network: 1
    power: 1
    gpu: 1
    # Linux 不会注册 Windows 专属 fps 任务；自定义任务示例：
    # custom_data.my_data: 5

custom_data:
  configs:
    # 插件名称必须与 plugin.json 中的 name 相同。
    # my_data:
    #   interval: 5
    #   endpoint: "http://127.0.0.1:9000/metrics"
  enabled:
    # 当前版本建议通过 PICO_MONITOR_CUSTOM_DATA_ENABLED 环境变量或管理页面维护；
    # 嵌套 YAML 的 enabled 键暂未纳入文件解析映射。
    # my_data: true

qbittorrent:
  enabled: false
  address: "http://127.0.0.1:8080"
  username: "admin"
  password: "请替换为 qBittorrent 密码"
  interval: 2.0

disk_health_test:
  index: 0                         # 0 关闭；从 1 开始选择磁盘
  level: 3                         # 0 到 5

upgrade:
  url: ""                          # 留空使用当前版本默认 Release 地址
  sha256: ""                       # 可选 SHA-256

market:
  url: "https://omni.mzlblog.com"

logging:
  level: INFO                       # DEBUG、INFO、WARNING、ERROR、CRITICAL

diagnostics:
  threads: false
  thread_interval: 10.0

sensor_host:
  enabled: true                     # 仅 Windows 使用，Linux 会忽略
  path: ""
  pipe: "omniwatch.sensorhost"

http:
  enabled: true                     # DEB 模板开启；裸程序默认关闭
  host: "127.0.0.1"                # 局域网访问可改为 0.0.0.0
  port: 9876
  auth: "请替换为随机长密钥"
```

## `serial`：USB CDC 串口

| 配置项 | 类型和默认值 | 取值要求 | 作用和示例 |
| --- | --- | --- | --- |
| `serial.port` | 字符串；默认空 | Linux 设备路径或空字符串 | 固定使用某个数据 CDC，例如 `"/dev/ttyACM1"`。留空时程序扫描可用串口并通过 PV1 PING/PONG 识别 Pico，不建议把随机变化的 `/dev/ttyACM0` 写死。 |
| `serial.probe_interval` | 浮点数；`3.0` 秒 | 必须大于 0 | 没有连接时发送 USB 探测 PING 的间隔。设备频繁插拔或串口枚举较慢时可调到 `5`；需要更快发现时可设为 `1`。 |

USB 数据 CDC 和 MicroPython REPL CDC 可能同时出现。自动发现会用握手区分二者；固定端口时必须填写能返回 PV1 PONG 的接口。

示例：

```yaml
serial:
  port: "/dev/serial/by-id/usb-Raspberry_Pi_Pico_XXXX-if01"
  probe_interval: 2.0
```

使用 `/dev/serial/by-id/` 比使用 `/dev/ttyACM0` 稳定，因为前者通常包含设备序列号和接口信息。

## `network`：Wi-Fi、WebSocket、局域网发现和延迟

| 配置项 | 类型和默认值 | 取值要求 | 作用和示例 |
| --- | --- | --- | --- |
| `network.websocket_url` | 字符串；默认空 | `ws://` 或 `wss://` 地址，通常包含 `/pv1` | 固定通过 Wi-Fi 连接设备，例如 `"ws://192.168.1.50:8765/pv1"`。服务启动的主动探测仍先尝试 USB，USB 不可用后使用该地址；后续重连也会优先直连该地址。设备 IP 使用 DHCP 时不建议长期写死。 |
| `network.force_usb_cdc` | 布尔；`false` | `true` 或 `false` | `true` 时强制 USB CDC，并停止 WebSocket 直连、UDP 公告和局域网搜索。升级 Pico 或排查 Wi-Fi 时可临时启用。 |
| `network.websocket_client_name` | 字符串；默认空 | 任意短名称 | 写入 WebSocket 握手，便于设备端或日志区分客户端，例如 `"nas-monitor"`。 |
| `network.websocket_client_id` | 字符串；默认空 | 建议稳定且唯一 | 固定客户端身份。留空时按设备名称和网卡标识生成；多台 Monitor 共存时可显式设置，如 `"nas-01"`。 |
| `network.discovery_strategy` | 枚举；`announcement` | `announcement` 或 `scan` | `announcement` 先监听 ESP32 UDP 公告，超时后扫描网段；`scan` 直接扫描网段。组播被交换机隔离时可改为 `scan`。 |
| `network.announcement_port` | 整数；`37856` | 1 到 65535 | Monitor 监听 ESP32 主动公告的 UDP 端口，必须与固件一致。防火墙放行该 UDP 端口后才可接收公告。 |
| `network.announcement_group` | 字符串；`239.255.77.77` | 合法 IPv4 组播地址 | ESP32 公告组播地址。一般保持默认；多套隔离网络需要自定义组播地址时，两端必须相同。 |
| `network.announcement_timeout` | 浮点数；`3.0` 秒 | 必须大于 0 | 每轮等待 UDP 公告的最长时间。公告丢失后会转入网段扫描；网络较慢时可提高到 `5`。 |
| `network.ping_target` | 字符串；`www.baidu.com` | 域名或 IP | 用于生成网络延迟和在线状态。内网无外网时可改为网关，例如 `"192.168.1.1"`；目标不可达会使 `online` 显示离线，但不影响串口。 |
| `network.unit` | 枚举；`MB` | `MB` 或 `Mbps` | LCD 速率显示单位。`MB` 使用 B/s、KB/s、MB/s、GB/s；`Mbps` 使用 bps、Kbps、Mbps、Gbps。 |
| `network.lan_probe_port` | 整数；`8765` | 1 到 65535 | 网段扫描时尝试连接 Pico WebSocket 服务的 TCP 端口。设备端修改端口后必须同步。 |
| `network.lan_probe_path` | 字符串；`/pv1` | WebSocket 路径 | 网段扫描使用的升级路径，通常保持 `/pv1`。 |
| `network.lan_probe_timeout` | 浮点数；`0.3` 秒 | 必须大于 0 | 每个候选 IP 的连接超时。跨 VLAN 或无线较慢时可设 `0.8`；过大将使扫描等待明显变长。 |
| `network.lan_probe_max_workers` | 整数；`256` | 必须大于 0 | 网段扫描并发数。低功耗 NAS 可设 `32` 或 `64`，避免瞬时创建过多 TCP 连接。 |

### USB 优先级和 Wi-Fi 发现流程

未设置 `force_usb_cdc` 时，服务启动会先尝试 USB；没有可用 USB 连接时再按以下逻辑处理：

1. 有 `websocket_url` 时尝试固定地址。
2. `discovery_strategy=announcement` 时监听 `announcement_group:announcement_port`。
3. 公告窗口没有有效设备时执行局域网扫描。
4. 所有候选地址都要经过 TCP、WebSocket 升级和 PV1 握手三步确认。

如果 USB 数据线仍连接设备，USB 会优先于 Wi-Fi。验证纯 Wi-Fi 时应断开 USB 数据连接，但保留设备供电。

示例：固定 Wi-Fi 地址并禁用 USB：

```yaml
network:
  websocket_url: "ws://192.168.1.50:8765/pv1"
  force_usb_cdc: true
```

`force_usb_cdc: true` 会使上面的 WebSocket 地址不生效；验证 Wi-Fi 时应改为 `false`。

## `monitor`：采集、发送和重连

| 配置项 | 类型和默认值 | 取值要求 | 作用和示例 |
| --- | --- | --- | --- |
| `monitor.interval` | 浮点数；DEB 模板 `1.0`，程序默认 `0.5` 秒 | 不得小于 `0.3` 秒 | 完整快照的调度和发送周期。设为 `2.0` 可降低低性能 NAS 的 CPU 占用；单项采集任务还可在 `collection_tasks.intervals` 中独立设置。 |
| `monitor.adaptive_transmit` | 布尔；`true` | `true` 或 `false` | 根据 Pico JSON ACK 耗时调整发送节奏，拥塞时只保留最新快照。USB 线路不稳定或调试固定节拍时可设 `false`，但仍保留 ACK 背压。 |
| `monitor.reconnect_interval` | 浮点数；`3.0` 秒 | 必须大于 0 | WebSocket 或设备连接异常后的等待时间。局域网设备重启较慢时可设 `5` 或 `10`。USB 断开时程序还会等待端口重新枚举。 |
| `monitor.dev` | 布尔；`false` | `true` 或 `false` | 开发模式。没有 Pico 时持续采集并打印待发送 JSON，适合在 CI 或没有硬件的主机上检查 Linux 指标；生产服务应关闭。 |

示例：低功耗主机每 2 秒发送，关闭发送自适应：

```yaml
monitor:
  interval: 2.0
  adaptive_transmit: false
  reconnect_interval: 5.0
  dev: false
```

## `collection_tasks`：各类系统指标频率

`collection_tasks.intervals` 的键必须是任务英文标识，值是大于 0 的秒数。未填写的任务保持默认频率；未知键会被忽略。任务执行由线程池调度，某个任务暂时失败不会阻止其他任务继续发送。

| 任务键 | 中文含义 | Linux 默认值 | 采集内容和调整建议 |
| --- | --- | ---: | --- |
| `basic_information` | 基础信息采集 | `1` | 主机名、平台、系统运行时间等低成本信息。一般保持 `1`。 |
| `cpu_memory` | CPU 与内存采集 | `1` | CPU 使用率、频率、温度、内存使用率和历史曲线。CPU 很弱时可设 `2`。 |
| `disk_capacity_health` | 磁盘容量与健康 | `60` | 分区容量、占用率、SMART 健康等级。SMART 查询可能较慢，不建议设为 `1`。 |
| `disk_temperature` | 磁盘温度 | `5` | SATA、NVMe 等物理盘温度。硬盘数量多或 SMART 访问慢时可设 `10`。 |
| `disk_rate` | 磁盘读写速率 | `1` | 读写 B/s、每物理盘速度和 24 秒历史。需要平滑曲线时保持 `1`。 |
| `network` | 网络采集 | `1` | 上传/下载速率、累计流量、网卡速率、Ping 和在线状态。只关心总流量时可设 `2`。 |
| `power` | 功耗采集 | `1` | Linux RAPL 可用时读取实时功耗；不支持的平台返回空值。RAPL 计数器无效时降低频率也不会产生数据。 |
| `gpu` | GPU 采集 | `1` | NVIDIA NVML、AMD sysfs、Intel i915 PMU 等可用后采集 GPU 使用率、温度和显存。无独立 GPU 时可设 `5`。 |
| `fps` | FPS 采集 | 不注册 | 仅 Windows PresentMon/ETW 任务。Linux 配置此键不会创建 FPS 任务。 |
| `custom_data.<插件名>` | 自定义插件 | 插件定义值 | 插件名来自 `plugin.json` 的 `name`，例如 `custom_data.my_data: 5`。插件运行目录和配置格式见 `docs/custom_data_plugin_protocol_v2.md`。 |

DEB 模板中的完整频率示例：

```yaml
collection_tasks:
  logs_enabled: true
  intervals:
    basic_information: 1
    cpu_memory: 1
    disk_capacity_health: 60
    disk_temperature: 5
    disk_rate: 1
    network: 1
    power: 1
    gpu: 1
```

任务频率和 `monitor.interval` 是两层设置。例如 `monitor.interval=0.5`、`disk_capacity_health=60` 表示快照可以每 0.5 秒发送，但磁盘容量和 SMART 数据最多每 60 秒更新一次。

`collection_tasks.logs_enabled` 是布尔值，DEB 模板为 `true`，裸程序默认 `false`。开启后会记录任务提交、开始、完成和线程池状态；关闭后仍保留错误和告警。排查任务卡顿时建议临时开启。

## `custom_data`：自定义数据插件

| 配置项 | 类型和默认值 | 作用 |
| --- | --- | --- |
| `custom_data.configs` | 对象；`{}` | 按插件名保存面板字段，例如 `my_data: {endpoint: "http://127.0.0.1:9000"}`。字段必须符合插件 `plugin.json` 中的 `config_panel` 定义，数字范围、正则和必填项由插件协议校验。 |
| `custom_data.enabled` | 对象；`{}` | 按插件名控制是否启用，例如 `my_data: true`。启用状态通常由 HTTP 管理页面或 Windows 设置页持久化。 |

配置示例：

```yaml
custom_data:
  configs:
    my_data:
      interval: 5
      endpoint: "http://127.0.0.1:9100/metrics"
      token: "只在插件要求时填写"
  enabled:
    my_data: true
```

兼容性提示：当前解析器已经支持 `PICO_MONITOR_CUSTOM_DATA_ENABLED` 环境变量，但没有把它映射到嵌套 YAML 路径。若 `custom_data.enabled` 在你的版本中没有生效，请改用环境变量，或把下面的旧式根键写入配置文件：

```text
PICO_MONITOR_CUSTOM_DATA_ENABLED='{"my_data": true}'
```

插件脚本在独立运行环境中执行，超时或异常会被隔离；不要把插件密码、令牌提交到公开仓库。插件详细字段格式请参阅 [`docs/custom_data_plugin_protocol_v2.md`](docs/custom_data_plugin_protocol_v2.md)。

## `screen`：Pico LCD 显示

| 配置项 | 类型和默认值 | 取值要求 | 作用和示例 |
| --- | --- | --- | --- |
| `screen.rotation` | 整数；`0` | 只能是 `0` 或 `180` | 屏幕倒置安装时设为 `180`。其他角度会在参数校验阶段拒绝。 |
| `screen.lcd_brightness` | 整数；DEB 模板 `100`，程序默认 `50` | 1 到 100 | LCD 背光百分比。夜间运行可设 `20` 或 `30`；设为 `100` 最亮但功耗和发热更高。 |
| `screen.lcd_style` | 字符串；DEB 模板 `fps_simple`，程序默认 `horizontal_disk4x` | 内置样式名或设备已同步的自定义样式名 | 常见内置值：`default`、`disk`、`diskv2`、`diskv3`、`diskv4`、`horizontal_disk`、`horizontal_diskv2`、`horizontal_disk4x`、`horizontal_disk4x_qb`、`horizontal_disk6x`、`simple`、`fpstest`、`fps_simple`、`game`、`idle`。自定义样式必须先上传并同步到设备。 |
| `screen.idle_style` | 字符串；`idle` | 设备样式目录中的待机样式 | 连续超过 `idle_timeout` 未收到有效快照后显示的样式。通常保持 `idle`。 |
| `screen.idle_timeout` | 整数；`30` 秒 | 必须大于 0 | Pico 多久没有收到 JSON 后切换到待机样式。USB 或 Wi-Fi 经常短暂断线时可设 `60`，避免频繁切换。 |

示例：倒置安装、低亮度、四盘布局：

```yaml
screen:
  rotation: 180
  lcd_brightness: 35
  lcd_style: "horizontal_disk4x"
  idle_style: "idle"
  idle_timeout: 60

## `logging` 和 `diagnostics`：日志与线程诊断

### 日志级别

```yaml
logging:
  level: INFO
```

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `logging.level` | `INFO` | 支持 `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL`。排查串口握手、WebSocket 扫描和采集耗时时使用 `DEBUG`；生产环境通常使用 `INFO`。 |

### 线程诊断

```yaml
diagnostics:
  threads: false
  thread_interval: 10.0
```

| 配置项 | 类型和默认值 | 说明 |
| --- | --- | --- |
| `diagnostics.threads` | 布尔；`false` | 开启后周期输出 `threading.enumerate()` 摘要和 `faulthandler` 全线程栈。仅在服务卡死、线程池不退出或采集超时期间临时开启。 |
| `diagnostics.thread_interval` | 浮点数；`10.0` 秒 | 诊断输出周期，必须大于 0。设得过小会快速增加日志量。 |

排查结束后关闭线程诊断：

```yaml
diagnostics:
  threads: false
```

## `sensor_host`：外置传感器宿主

该组配置用于 Windows SensorHost 外置硬件传感器进程。Linux 下 `SystemInformationCollector` 不创建 SensorHost，配置会被安全忽略；Linux 温度、GPU 和功耗使用本机 `/sys`、NVML、i915 PMU 或 RAPL 等接口。

| 配置项 | 类型和默认值 | 说明 |
| --- | --- | --- |
| `sensor_host.enabled` | 布尔；`true` | 仅 Windows 有效。Linux 无需为了此项安装额外服务。 |
| `sensor_host.path` | 字符串；默认空 | Windows SensorHost 可执行文件路径。留空时从打包目录查找。 |
| `sensor_host.pipe` | 字符串；`omniwatch.sensorhost` | Windows Named Pipe 名称。只有自定义宿主管道时才修改。 |

## `qbittorrent`：qBittorrent Web API

| 配置项 | 类型和默认值 | 取值要求 | 作用和示例 |
| --- | --- | --- | --- |
| `qbittorrent.enabled` | 布尔；`false` | `true` 时三项连接信息都必须填写 | 是否启动 qBittorrent 后台采集线程。 |
| `qbittorrent.address` | 字符串；默认空 | 例如 `http://127.0.0.1:8080` | qBittorrent Web UI 地址，不要填写 `/api/v2` 后缀。 |
| `qbittorrent.username` | 字符串；默认空 | 登录账号 | Web UI 用户名。 |
| `qbittorrent.password` | 字符串；默认空 | 登录密码 | Web UI 密码。建议使用权限为 `600` 的配置文件或 systemd 环境变量。 |
| `qbittorrent.interval` | 浮点数；`2.0` 秒 | 必须大于 0 | API 采集间隔。qBittorrent 任务很多时可设 `5`。 |

启用示例：

```yaml
qbittorrent:
  enabled: true
  address: "http://127.0.0.1:8080"
  username: "admin"
  password: "替换为实际密码"
  interval: 2.0
```

启用后地址、账号、密码任何一项为空，服务启动校验都会失败。更完整的字段和 API 说明见 [`qbittorrent_config.md`](qbittorrent_config.md)。

## `disk_health_test`：磁盘健康显示测试

此组用于验证 Pico 样式的健康等级颜色和图标，不会修改硬盘 SMART 数据。

| 配置项 | 类型和默认值 | 取值要求 | 说明 |
| --- | --- | --- | --- |
| `disk_health_test.index` | 整数；`0` | `0` 关闭；大于等于 `1` 选择按发送顺序排列的物理磁盘 | 例如 `2` 只让第二块盘进入测试显示。实际磁盘顺序可能随设备枚举变化，长期运行应关闭。 |
| `disk_health_test.level` | 整数；`3` | 0 到 5 | 测试健康等级：`0` 未知、`1` 健康、`2` 注意、`3` 警告、`4` 严重、`5` 失败。 |

测试示例：

```yaml
disk_health_test:
  index: 1
  level: 5
```

验证完成后恢复：

```yaml
disk_health_test:
  index: 0
```

真实 Linux 磁盘健康信息依赖 `smartmontools`。DEB 主依赖不一定自动安装该工具，可手动执行：

```bash
sudo apt-get update
sudo apt-get install -y smartmontools
```

## `upgrade`：Pico 固件在线升级

| 配置项 | 类型和默认值 | 说明 |
| --- | --- | --- |
| `upgrade.url` | 字符串；默认空 | 留空时按当前 Monitor 版本选择 GitHub Release 中的 Pico 全量固件包；本地测试或私有发布可填写 HTTP/HTTPS 地址。 |
| `upgrade.sha256` | 字符串；默认空 | 可选的固件 ZIP SHA-256 摘要。填写后下载完成必须匹配，否则不会写入设备。 |

配置示例：

```yaml
upgrade:
  url: "https://example.com/OmniWatch-pico-full-vlocal-test.zip"
  sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
```

升级命令需要停止 systemd 服务以释放串口：

```bash
sudo systemctl stop pico-monitor
sudo /usr/bin/pico-monitor --config /etc/pico-monitor.conf --upgrade-pico
sudo systemctl start pico-monitor
```

升级提交阶段不要断电、拔线或让主机休眠。`upgrade.url` 和 `upgrade.sha256` 只决定固件包来源和校验，不会执行 Linux DEB 更新。

## `market`：插件市场

```yaml
market:
  url: "https://omni.mzlblog.com"
```

`market.url` 是 HTTP 管理页面加载插件市场和同源资源的地址，默认值为 `https://omni.mzlblog.com`。必须使用 `http://` 或 `https://`；内网部署可改为自建市场地址，例如 `http://192.168.1.10:8081`。如果不使用插件市场，仍可保留默认值，或者在防火墙层面限制管理页面访问。

## `http`：Linux HTTP 管理页面

| 配置项 | 类型和默认值 | 取值要求 | 作用和示例 |
| --- | --- | --- | --- |
| `http.enabled` | 布尔；DEB 模板 `true`，程序默认 `false` | `true` 或 `false` | 启用浏览器管理页面、设备控制和插件市场。无桌面 DEB 主机通常开启；不需要远程管理时可关闭。 |
| `http.host` | 字符串；`0.0.0.0` | 本机地址或绑定网卡地址 | `127.0.0.1` 只允许本机访问；`0.0.0.0` 监听所有 IPv4 网卡，适合局域网管理但必须配合强 Auth 和防火墙。 |
| `http.port` | 整数；`9876` | 1 到 65535 | 管理页面端口，例如 `9988`。修改后需同步防火墙规则。 |
| `http.auth` | 字符串；DEB 模板为示例密钥，裸程序默认空 | 建议至少 32 个随机字符 | WebSocket Upgrade 和管理 API 的鉴权密钥。留空时每次启动随机生成并写入启动日志；首次登录后应立即改成随机长密钥。 |

推荐的仅本机配置：

```yaml
http:
  enabled: true
  host: "127.0.0.1"
  port: 9876
  auth: "替换为 32 位以上随机密钥"
```

局域网访问示例（假设主机防火墙只允许管理网段）：

```yaml
http:
  enabled: true
  host: "0.0.0.0"
  port: 9876
  auth: "替换为 32 位以上随机密钥"
```

然后限制端口来源，例如使用 UFW：

```bash
sudo ufw allow from 192.168.1.0/24 to any port 9876 proto tcp
sudo ufw deny 9876/tcp
```

不要把默认的 `omni-watch-123456789` 暴露到不可信网络。密码、qBittorrent 凭据和插件令牌会出现在配置文件中，建议设置文件权限：

```bash
sudo chown root:root /etc/pico-monitor.conf
sudo chmod 600 /etc/pico-monitor.conf

## 命令行专用参数

以下开关不属于常驻 YAML 配置，写入 YAML 不会产生作用，应在执行一次性命令时直接使用：

| 参数 | 用途和示例 |
| --- | --- |
| `--config PATH` | 指定配置文件，例如 `sudo pico-monitor --config /tmp/test.conf --pico-info`。也可使用 `PICO_MONITOR_CONFIG` 或 `PICO_MONITOR_CONFIG_PATH` 指定路径。 |
| `--version` | 打印 Monitor 版本并退出。 |
| `--once` | 成功发送一次快照后退出，适合手动验证连接。 |
| `--pico-info` | 连接 Pico，显示板型、屏幕方案和固件版本后退出。 |
| `--upgrade-pico` | 下载并执行 Pico 固件升级。 |
| `--update` | 从 GitHub 最新 Release 下载并安装当前架构的 Linux DEB；与 `--pico-info`、`--upgrade-pico` 互斥。 |
| `--worker` | 供内部 HTTP/后台工作流程使用，普通用户不应手动设置。 |
| `--force-usb-cdc` / `--no-force-usb-cdc` | 临时覆盖 `network.force_usb_cdc`。 |
| `--adaptive-transmit` / `--no-adaptive-transmit` | 临时覆盖 `monitor.adaptive_transmit`。 |
| `--collection-task-intervals '{"network": 0.8}'` | 临时覆盖采集任务频率，值必须是 JSON 对象。 |
| `--http-enabled` / `--no-http` | 临时覆盖 HTTP 页面开关。 |

常用一次性检查：

```bash
# 检查版本和命令入口
pico-monitor --version

# 显示帮助；会先读取并解析指定 YAML
pico-monitor --config /etc/pico-monitor.conf --help

# 停止服务后，仅发送一次快照进行连接验证
sudo systemctl stop pico-monitor
sudo pico-monitor --config /etc/pico-monitor.conf --once
sudo systemctl start pico-monitor
```

## 环境变量完整对照

所有 `PICO_MONITOR_*` 环境变量都可以覆盖同名配置。下表列出变量、常用 YAML 路径和备注：

| 环境变量 | YAML 路径 | 备注 |
| --- | --- | --- |
| `PICO_MONITOR_PORT` | `serial.port` | 固定串口 |
| `PICO_MONITOR_SERIAL_PROBE_INTERVAL` | `serial.probe_interval` | USB 探测周期 |
| `PICO_MONITOR_WEBSOCKET_URL` | `network.websocket_url` | 固定 WebSocket |
| `PICO_MONITOR_FORCE_USB_CDC` | `network.force_usb_cdc` | `1/true/yes/on` 为真 |
| `PICO_MONITOR_WEBSOCKET_CLIENT_NAME` | `network.websocket_client_name` | 握手名称 |
| `PICO_MONITOR_WEBSOCKET_CLIENT_ID` | `network.websocket_client_id` | 稳定身份 |
| `PICO_MONITOR_WIFI_DISCOVERY_STRATEGY` | `network.discovery_strategy` | `announcement` 或 `scan` |
| `PICO_MONITOR_WIFI_ANNOUNCEMENT_PORT` | `network.announcement_port` | UDP 公告端口 |
| `PICO_MONITOR_WIFI_ANNOUNCEMENT_GROUP` | `network.announcement_group` | UDP 组播地址 |
| `PICO_MONITOR_WIFI_ANNOUNCEMENT_TIMEOUT` | `network.announcement_timeout` | 公告窗口 |
| `PICO_MONITOR_PING_TARGET` | `network.ping_target` | 延迟目标 |
| `PICO_MONITOR_NETWORK_UNIT` | `network.unit` | `MB` 或 `Mbps` |
| `PICO_MONITOR_LAN_PROBE_PORT` | `network.lan_probe_port` | 环境变量可用；当前版本未纳入嵌套 YAML 映射 |
| `PICO_MONITOR_LAN_PROBE_PATH` | `network.lan_probe_path` | 环境变量可用；当前版本未纳入嵌套 YAML 映射 |
| `PICO_MONITOR_LAN_PROBE_TIMEOUT` | `network.lan_probe_timeout` | 环境变量可用；当前版本未纳入嵌套 YAML 映射 |
| `PICO_MONITOR_LAN_PROBE_MAX_WORKERS` | `network.lan_probe_max_workers` | 环境变量可用；当前版本未纳入嵌套 YAML 映射 |
| `PICO_MONITOR_INTERVAL` | `monitor.interval` | 最小 0.3 秒 |
| `PICO_MONITOR_ADAPTIVE_TRANSMIT` | `monitor.adaptive_transmit` | 发送自适应 |
| `PICO_MONITOR_RECONNECT_INTERVAL` | `monitor.reconnect_interval` | 重连周期 |
| `PICO_MONITOR_DEV` | `monitor.dev` | 开发模式 |
| `PICO_MONITOR_COLLECTION_TASK_INTERVALS` | `collection_tasks.intervals` | JSON 对象 |
| `PICO_MONITOR_COLLECTION_TASK_LOGS` | `collection_tasks.logs_enabled` | 任务常规日志 |
| `PICO_MONITOR_CUSTOM_DATA_CONFIGS` | `custom_data.configs` | JSON 对象 |
| `PICO_MONITOR_CUSTOM_DATA_ENABLED` | `custom_data.enabled` | 环境变量可用；当前版本未纳入嵌套 YAML 映射 |
| `PICO_MONITOR_SCREEN_ROTATION` | `screen.rotation` | `0` 或 `180` |
| `PICO_MONITOR_LCD_BRIGHTNESS` | `screen.lcd_brightness` | 1 到 100 |
| `PICO_MONITOR_LCD_STYLE` | `screen.lcd_style` | 样式名 |
| `PICO_MONITOR_IDLE_STYLE` | `screen.idle_style` | 待机样式 |
| `PICO_MONITOR_IDLE_TIMEOUT` | `screen.idle_timeout` | 正整数秒 |
| `PICO_MONITOR_LOG_LEVEL` | `logging.level` | 日志级别 |
| `PICO_MONITOR_THREAD_DIAGNOSTICS` | `diagnostics.threads` | 线程诊断开关 |
| `PICO_MONITOR_THREAD_DIAGNOSTICS_INTERVAL` | `diagnostics.thread_interval` | 诊断周期 |
| `PICO_MONITOR_SENSOR_HOST_ENABLED` | `sensor_host.enabled` | 仅 Windows |
| `PICO_MONITOR_SENSOR_HOST_PATH` | `sensor_host.path` | 仅 Windows |
| `PICO_MONITOR_SENSOR_HOST_PIPE` | `sensor_host.pipe` | 仅 Windows |
| `PICO_MONITOR_QBITTORRENT_ENABLED` | `qbittorrent.enabled` | 启用 qBittorrent |
| `PICO_MONITOR_QBITTORRENT_ADDRESS` | `qbittorrent.address` | Web UI 地址 |
| `PICO_MONITOR_QBITTORRENT_USERNAME` | `qbittorrent.username` | 登录账号 |
| `PICO_MONITOR_QBITTORRENT_PASSWORD` | `qbittorrent.password` | 登录密码 |
| `PICO_MONITOR_QBITTORRENT_INTERVAL` | `qbittorrent.interval` | 采集周期 |
| `PICO_MONITOR_DISK_HEALTH_TEST_INDEX` | `disk_health_test.index` | 测试磁盘序号 |
| `PICO_MONITOR_DISK_HEALTH_TEST_LEVEL` | `disk_health_test.level` | 测试等级 |
| `PICO_MONITOR_UPGRADE_URL` | `upgrade.url` | 固件包地址 |
| `PICO_MONITOR_UPGRADE_SHA256` | `upgrade.sha256` | 固件包摘要 |
| `PICO_MONITOR_MARKET_URL` | `market.url` | 插件市场 |
| `PICO_MONITOR_HTTP_ENABLED` | `http.enabled` | HTTP 开关 |
| `PICO_MONITOR_HTTP_HOST` | `http.host` | 监听地址 |
| `PICO_MONITOR_HTTP_PORT` | `http.port` | 监听端口 |
| `PICO_MONITOR_HTTP_AUTH` | `http.auth` | 鉴权密钥 |

布尔环境变量识别 `1`、`true`、`yes`、`on`（不区分大小写）为真，其余字符串按假处理。对象环境变量必须是合法 JSON，例如：

```bash
sudo systemctl edit pico-monitor
```

```ini
[Service]
Environment="PICO_MONITOR_COLLECTION_TASK_INTERVALS={\"cpu_memory\":0.8,\"network\":1.5}"
Environment="PICO_MONITOR_CUSTOM_DATA_ENABLED={\"my_data\":true}"
```

## 旧版 EnvironmentFile 格式

旧版本曾使用每行一个 `PICO_MONITOR_*` 的环境变量文件。当前程序仍兼容这种文件：如果配置文件第一个有效内容行以 `PICO_MONITOR_` 开头，程序会按旧格式解析，而不是按 YAML 解析。

旧格式示例：

```text
# /etc/pico-monitor.conf（旧格式）
PICO_MONITOR_PORT="/dev/ttyACM1"
PICO_MONITOR_INTERVAL="1.0"
PICO_MONITOR_HTTP_ENABLED="true"
PICO_MONITOR_HTTP_AUTH="替换为随机长密钥"
PICO_MONITOR_COLLECTION_TASK_INTERVALS='{"disk_rate":2}'
```

新部署建议使用本文前面的 YAML 格式。迁移时逐项把环境变量移动到对应的 YAML 路径；对象值仍保持 JSON 字符串。

## systemd 服务和文件权限

DEB 服务的关键属性通常如下：

```ini
[Service]
ExecStart=/usr/bin/pico-monitor --config /etc/pico-monitor.conf
Restart=always
RestartSec=3
User=root
Environment=HOME=/var/lib/pico-monitor
Environment=PICO_MONITOR_DATA_ROOT=/var/lib/pico-monitor
Environment=PICO_MONITOR_SCREENSHOT_DIR=/var/lib/pico-monitor/screenshot
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
```

以 root 运行是为了直接读取系统级 i915 PMU、RAPL、SMART 和 USB 串口。若你已为运行账号配置 `dialout`、`video`、`render`、`adm` 等权限，可以复制服务并降低权限，但必须重新验证串口、GPU、功耗和 SMART 数据；不要直接修改包管理器管理的服务文件。

配置中的密码和令牌应限制为 root 可读：

```bash
sudo chown root:root /etc/pico-monitor.conf
sudo chmod 600 /etc/pico-monitor.conf
```

systemd drop-in 中的环境变量同样可能包含秘密信息，修改后请检查：

```bash
sudo systemctl cat pico-monitor
```

服务单元中还有三项路径环境变量，它们不是 YAML 配置项：

| 环境变量 | DEB 默认值 | 用途 |
| --- | --- | --- |
| `HOME` | `/var/lib/pico-monitor` | systemd 服务的运行主目录。 |
| `PICO_MONITOR_DATA_ROOT` | `/var/lib/pico-monitor` | 自定义插件、插件运行环境和导出数据的根目录。 |
| `PICO_MONITOR_SCREENSHOT_DIR` | `/var/lib/pico-monitor/screenshot` | Pico LCD 截图保存目录。 |

需要迁移数据目录时，应通过 systemd drop-in 同时修改这些变量并提前创建目录、设置 root 权限；不要把它们写入 `pico-monitor.conf`，因为 Monitor 配置解析器不会读取这些路径键。

另外几个高级环境变量也不属于 YAML：

| 环境变量 | 作用 |
| --- | --- |
| `PICO_MONITOR_ERROR_LOG_PATH` | 将 `ERROR` 及以上日志追加写入指定文件，例如 `/var/lib/pico-monitor/error.log`。目录必须先存在且服务用户可写；使用 `/var/log` 时还要在服务单元中增加对应的 `ReadWritePaths`。 |
| `PICO_MONITOR_PLUGIN_PYTHON` | 指定创建和运行插件虚拟环境的 Python 解释器路径。Linux 通常留空，使用服务自身的 `/usr/bin/python3`。 |
| `PICO_MONITOR_SETTINGS_PATH` | 覆盖样式目录等设置文件路径；主要用于开发或自定义部署。 |
| `PICO_MONITOR_PRESENTMON` | Windows FPS 采集使用的 PresentMon 路径，Linux 忽略。 |
| `PICO_MONITOR_ADLX_BRIDGE` | Windows AMD ADLX 回退桥接程序路径，Linux 忽略。 |

## 常见配置场景

### 1. 只使用 USB，完全关闭网络发现

```yaml
serial:
  port: "/dev/serial/by-id/usb-Pico-if01"
network:
  force_usb_cdc: true
http:
  enabled: false
```

适合没有局域网、只在本机使用 LCD 的场景。`serial.port` 应填写实际 PV1 数据接口。

### 2. 固定 Wi-Fi 地址，不扫描整个网段

```yaml
serial:
  port: ""
network:
  websocket_url: "ws://192.168.1.50:8765/pv1"
  force_usb_cdc: false
```

设备使用 DHCP 时地址可能变化；此时建议删除 `websocket_url`，使用 `announcement` 自动发现。

### 3. 无外网环境，用网关测延迟

```yaml
network:
  ping_target: "192.168.1.1"
  discovery_strategy: scan
```

如果交换机不转发组播，`scan` 比 `announcement` 更直接，但会产生局域网探测流量。

### 4. 低性能 NAS 降低采集开销

```yaml
monitor:
  interval: 2.0
collection_tasks:
  intervals:
    cpu_memory: 2
    disk_capacity_health: 300
    disk_temperature: 30
    disk_rate: 2
    network: 2
    power: 2
    gpu: 10
```

磁盘健康和温度的频率可以比 LCD 发送频率低很多；快照会继续发送最近一次有效值。

### 5. 开启 HTTP 管理页面但只允许本机访问

```yaml
http:
  enabled: true
  host: "127.0.0.1"
  port: 9876
  auth: "替换为随机长密钥"
```

访问 `http://127.0.0.1:9876/`。如果要从远程浏览器访问，建议通过 SSH 端口转发，而不是直接把 `9876` 暴露到公网：

```bash
ssh -L 9876:127.0.0.1:9876 user@linux-host
```

### 6. qBittorrent 与四盘样式

```yaml
screen:
  lcd_style: "horizontal_disk4x_qb"
qbittorrent:
  enabled: true
  address: "http://127.0.0.1:8080"
  username: "admin"
  password: "替换为实际密码"
  interval: 2.0
```

该样式会保留四盘布局，并使用 qBittorrent 仪表盘替换部分 IP/GPU 区域；没有 qBittorrent 服务时不要开启 `enabled`。

## 修改后的排错顺序

1. 先检查 YAML 缩进、引号和布尔值：

   ```bash
   sudo pico-monitor --config /etc/pico-monitor.conf --help >/dev/null
   ```

2. 查看 systemd 实际加载的命令和环境：

   ```bash
   sudo systemctl cat pico-monitor
   ```

3. 查看最近 100 行日志：

   ```bash
   sudo journalctl -u pico-monitor -n 100 --no-pager
   ```

4. 检查串口和权限：

   ```bash
   ls -l /dev/serial/by-id/ /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
   id
   dmesg | tail -n 50
   ```

5. 检查 Linux 可选硬件工具：

   ```bash
   command -v smartctl || true
   ls /sys/class/powercap 2>/dev/null || true
   ls /sys/class/drm 2>/dev/null || true
   ```

6. 配置改动后确认服务没有被旧进程占用：

   ```bash
   sudo systemctl restart pico-monitor
   sudo systemctl is-active pico-monitor
   ```

常见错误与处理：

| 日志或现象 | 原因和处理 |
| --- | --- |
| `YAML 配置解析失败` | 缩进、冒号、引号或 JSON 字符串错误。用 `python3 -c 'import yaml; yaml.safe_load(open("/etc/pico-monitor.conf"))'` 定位语法。 |
| `采集间隔不得低于 0.3 秒` | `monitor.interval` 太小；改为 `0.3` 或更大。 |
| `开启 qBittorrent 采集后必须配置` | `qbittorrent.enabled=true` 时地址、账号、密码不能留空。 |
| 服务反复重启 | 查看 `journalctl -u pico-monitor -b`，重点检查配置类型、Python 依赖、串口权限和端口冲突。 |
| 找不到 Pico | 先确认 USB 线支持数据，查看 `dmesg`；不要把 REPL CDC 当成 PV1 数据 CDC。 |
| Wi-Fi 找不到设备 | 检查设备与主机是否同一网段、防火墙是否允许 TCP 8765/UDP 37856；组播不可用时将策略改为 `scan`。 |
| 磁盘温度或健康为未知 | 安装 `smartmontools`，确认服务有 root 权限，并检查 USB 硬盘盒是否透传 SMART。 |
| 功耗为 `null` | 只有支持 RAPL 的 Intel 平台通常能读取 Linux 实时功耗；其他平台属于正常情况。 |
| HTTP 页面打不开 | 确认 `http.enabled`、监听地址、端口和 Auth；`127.0.0.1` 只能从本机访问。 |

修改硬件驱动、内核参数或 udev 规则后，建议重新插拔设备并重启 `pico-monitor`，再通过 `journalctl` 确认出现 `PONG:PICO_LCD` 和正常快照发送日志。
```
```
