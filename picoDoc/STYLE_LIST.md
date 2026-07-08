# LCD 样式列表

本文档简述系统内置 LCD 样式。Monitor 可通过命令行参数选择样式：

```powershell
python pico_monitor.py --lcd-style simple
```

也可以设置环境变量 `PICO_MONITOR_LCD_STYLE`。Pico 未连接 Monitor 时，使用
`config.py` 中的 `LCD_STYLE` 默认值。

## 样式总览

| 选择名称 | 源文件 | 方向与分辨率 | 字体 | 主要用途 |
| --- | --- | --- | --- | --- |
| `default` | `styles/style_default.py` | 竖屏 240×320 | 原生字体 | 通用系统概览 |
| `disk` | `styles/style_disk.py` | 竖屏 240×320 | 原生字体 | 突出磁盘总容量和网络趋势 |
| `diskv2` | `styles/style_diskv2.py` | 横屏 320×240 | 紧凑字体 | 高密度显示最多十五块磁盘 |
| `diskv3` | `styles/style_diskv3.py` | 横屏 320×240 | 紧凑字体 | 顶部显示 IP 的十五磁盘视图 |
| `diskv4` | `styles/style_diskv4.py` | 横屏 320×240 | 紧凑字体 | 实心趋势与空磁盘占位视图 |
| `horizontal_disk` | `styles/style_horizontal_disk.py` | 横屏 320×240 | 二寸屏字体 | 高密度显示最多九块磁盘 |
| `horizontal_diskv2` | `styles/style_horizontal_diskv2.py` | 横屏 320×240 | 紧凑字体 | 原九磁盘布局的紧凑字体版本 |
| `horizontal_disk4x` | `styles/style_horizontal_disk4x.py` | 横屏 320×240 | 紧凑字体 | 清晰显示最多四块磁盘 |
| `horizontal_disk4x_qb` | `styles/style_horizontal_disk4x_qb.py` | 横屏 320×240 | 紧凑字体 | 四磁盘与 qBittorrent 状态 |
| `horizontal_disk6x` | `styles/style_horizontal_disk6x.py` | 横屏 320×240 | 紧凑字体 | 均衡显示最多六块磁盘 |
| `simple` | `styles/style_simple.py` | 横屏 320×240 | 紧凑字体 | 健康优先的三磁盘简洁视图 |
| `fps_simple` | `styles/style_fps_simple.py` | 横屏 320×240 | 紧凑字体 | 深色简约 FPS 实时监控与趋势统计 |

## default

项目的基础竖屏仪表盘，依次显示 CPU、内存、磁盘、网络和底部状态信息。
CPU、内存和磁盘均提供当前值、详细数值及历史趋势，适合需要完整系统概览且
不强调单块物理磁盘的场景。

## disk

以磁盘总容量和总体占用率为视觉重点，同时显示 CPU、内存、上下行网络速率、
历史趋势、时间和运行时长。布局比 `default` 更突出存储使用情况，适合竖屏设备。

## diskv2

横屏三列五行高密度磁盘仪表盘，最多显示十五块物理磁盘。顶部显示主机、系统、
时间和运行时长，左侧集中显示 CPU、内存、网络、延迟及 GPU，右侧显示磁盘总体
容量、总体占用率和物理磁盘卡片。样式使用紧凑字体，并对容量单位进行合并显示，
适合磁盘数量较多且需要在单屏快速浏览状态的存储服务器。

每块磁盘的 SMART 健康状态与空间占用率独立显示：占用率仅控制百分比和进度条颜色，
`UNKNOWN`、`HEALTHY`、`NOTICE`、`WARNING`、`CRITICAL`、`FAILED` 状态由 `health`
等级决定；达到警告等级时，磁盘边框和状态信息会按照等级变色或逐帧闪烁。

## diskv3

沿用 `diskv2` 的十五磁盘高密度布局，并将顶部左侧的主机名和系统类型替换为当前
网络 IP 地址。适合通过屏幕直接确认设备网络地址的无键盘服务器和存储设备。

## diskv4

沿用 `diskv3` 的十五磁盘高密度布局，将 CPU 和 GPU 历史折线改为实心面积图；
不足十五块磁盘时，剩余槽位绘制低对比度的 `EMPTY` 占位卡，使网格结构保持完整。

## horizontal_disk

横屏高密度磁盘仪表盘。左侧显示 CPU、内存和网络，右侧显示磁盘总览及三行三列
的物理磁盘卡片，最多显示九块磁盘。磁盘卡片包含容量、占用率、温度和健康告警，
适合磁盘数量较多的主机。

## horizontal_diskv2

完整继承 `horizontal_disk` 的横屏布局、九磁盘上限、增量刷新和健康告警规则，
仅将二寸屏字体替换为紧凑字体。适合希望保留原有信息结构，同时减少文字占用空间
并提高卡片留白的场景。

## horizontal_disk4x

横屏双列磁盘仪表盘，最多显示四块物理磁盘。相比九磁盘样式，单块磁盘拥有更大
的显示空间，可展示容量、占用率、温度、读写速率和健康状态；剩余区域用于网络、
GPU 等扩展信息。

## horizontal_disk4x_qb

在 `horizontal_disk4x` 布局基础上加入 qBittorrent 面板。最多显示四块物理磁盘，
并展示 qBittorrent 在线状态、上传下载速度及相关统计。适合同时承担下载任务的
NAS 或家庭服务器。

## horizontal_disk6x

横屏双列三行布局，最多显示六块物理磁盘。信息密度介于四磁盘和九磁盘样式之间，
磁盘卡片包含容量、占用率、温度、实时读写速率和健康告警，适合中等磁盘数量的主机。

## simple

横屏简洁样式，最多显示三块物理磁盘，并按照 `health` 从差到好优先展示。左侧显示
CPU、内存、GPU、网络及网络延迟，右侧显示磁盘总览和磁盘读写信息。CPU、内存、GPU、
网络及磁盘读写历史使用低开销实心渐变面积图。磁盘卡片显示占用率、已用/总容量、
H0 至 H5 健康等级、温度和实时读写速率，适合优先观察异常磁盘及快速刷新。

## fps_simple

参考深色青紫仪表盘设计，顶部显示 FPS 标题和当前时间，主区域显示当前帧率与最近
二十四个采样点的趋势，底部集中展示平均值、最低值、最高值、FPS 抖动、
采集来源和前台进程。无可用采集源时会明确显示 `N/A` 与不可用状态。

## 健康等级

物理磁盘健康值含义如下：

| 等级 | 含义 |
| --- | --- |
| `H0` | 未知 |
| `H1` | 健康 |
| `H2` | 注意 |
| `H3` | 警告 |
| `H4` | 严重 |
| `H5` | 失败 |

横屏磁盘样式会使用状态色显示健康告警；达到较高告警等级时，会通过变色或闪烁增强提示。

## 新增样式

新增样式时在 `styles` 文件夹内使用 `style_<名称>.py` 命名，并在模块末尾调用 `register_style()` 注册。
完整插件接口和脏区域刷新约定请参阅 `STYLE_PLUGIN.md`。若样式需要由 Monitor 命令行选择，
还需将选择名称加入 `monitor/monitor_core/style_commands.py` 的 `BUILTIN_LCD_STYLES`。
