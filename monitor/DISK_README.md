# 磁盘 SMART 健康检查说明

## 检查频次

Linux/NAS 在设置页独立配置 **SMART 健康检查周期（分钟）**，默认 30，最小 1，仅接受正整数。保存后热更新，按上次成功检查时间重新计算到期时间；容量、温度和读写速率任务频率不随之改变。

**允许磁盘休眠时主动查询（可能唤醒磁盘）**默认选中，以保持旧行为。飞牛 NAS 用户应取消勾选来保护休眠。

- 允许主动查询时，启动和热插拔可立即检查，之后按配置周期检查；温度只读取属性，不借温度任务重复执行完整健康查询。
- 保护休眠时，首次启动和空闲期间仅被动枚举，不执行 `--scan-open`。看到业务 I/O 后才对已确认的直连 SATA 设备尝试受保护 SMART 查询。
- SMART 命令显式指定设备类型，并使用 `-n standby,3,5`，在休眠及电源检测不支持时退出。任何失败都不回退到无保护查询，重试至少间隔 30 秒。
- USB、硬 RAID 转接、NVMe 等不能通过当前安全策略确认的设备只提供被动信息，不主动探测。
- 温度、健康不可用时返回未知；容量使用内存缓存，并通过可选字段 `capacity_stale` 和 `capacity_updated_at` 表明过期及最后成功更新时间。管理页显示对应提示。
- 每次成功健康检查仍保留 NOTICE 及以上告警；休眠跳过不逐次记录日志。

参数、日志路径注意事项及 90 分钟真机验收步骤见 [Linux 配置说明](linux-config-full.md#disk磁盘休眠与-smart-健康检查)。SMART 参数依据 [smartmontools 官方说明](https://github.com/smartmontools/smartmontools/blob/main/src/smartctl.8.in)。

Windows 优先使用系统存储接口提供的物理磁盘 `HealthStatus`。无法获得物理磁盘状态时返回 `UNKNOWN(0)`。

## 健康状态

每块磁盘在 JSON 的 `disks` 和 `physical_disks` 数组中均包含整数类型的 `health` 字段。

| 数值 | 状态 | 建议颜色 | 含义与处理建议 |
| ---: | --- | --- | --- |
| 0 | `UNKNOWN` | 灰色 | 无法读取 SMART、USB 硬盘盒不支持、权限不足或工具未安装。 |
| 1 | `HEALTHY` | 绿色 | SMART 状态正常，未发现已纳入规则的异常指标。 |
| 2 | `NOTICE` | 蓝色或青色 | 存在轻微异常或寿命接近设计值，建议持续观察。 |
| 3 | `WARNING` | 黄色 | 存在待处理坏块、不可校正错误或较多介质错误，建议立即备份。 |
| 4 | `CRITICAL` | 橙色或红色 | 寿命耗尽、坏块数量较高或 NVMe 发出严重警告，建议尽快更换。 |
| 5 | `FAILED` | 红色闪烁 | SMART 总体测试失败、属性已失败，或 NVMe 进入只读/可靠性严重下降状态，应尽快停用。 |

## 分级规则

规则按照从高到低的优先级执行，命中后立即返回对应等级。一个磁盘同时命中多个条件时，以最高等级为准。

### FAILED（5）

- smartmontools 返回 `smart_status.passed=false`。
- 任意 ATA SMART 属性的 `when_failed` 不为空且不为 `-`。
- NVMe `critical_warning` 的位 2 或位 3 被置位，即可靠性严重下降或介质进入只读状态。
- Windows 物理磁盘 `HealthStatus=Unhealthy`。

### CRITICAL（4）

- NVMe `critical_warning` 存在其他非零警告，例如可用备用空间低于阈值或温度越界。
- NVMe `percentage_used >= 100`，表示达到或超过厂商设计寿命。
- ATA `Current_Pending_Sector >= 100`。
- ATA `Offline_Uncorrectable >= 100`。

### WARNING（3）

- ATA `Current_Pending_Sector > 0`。
- ATA `Offline_Uncorrectable > 0`。
- ATA `Reallocated_Sector_Ct >= 100`。
- NVMe `media_errors >= 100`。
- Windows 物理磁盘 `HealthStatus=Warning`。

### NOTICE（2）

- ATA `Reallocated_Sector_Ct > 0`。
- ATA `Reported_Uncorrect > 0`。
- NVMe `media_errors > 0`。
- NVMe `percentage_used >= 90`。

### HEALTHY（1）

smartmontools 明确返回 SMART 通过，或成功读取到 NVMe/ATA SMART 数据，且未命中上述异常规则。

### UNKNOWN（0）

SMART JSON 为空、格式错误、命令不存在、执行超时、权限不足、设备不支持 SMART，或者没有可用于判断的 SMART 数据。

## JSON 示例

```json
{
  "physical_disks": [
    {
      "name": "nvme0n1",
      "devices": ["/dev/nvme0n1p1"],
      "temperature_c": 42.0,
      "health": 1,
      "used_bytes": 500000000000,
      "total_bytes": 1000000000000,
      "percent": 50.0
    }
  ]
}
```

`health` 只表示 SMART 健康等级，不等同于磁盘空间占用率或温度等级。上层界面应按状态表独立显示颜色和告警效果。

## LCD 告警显示测试

开发或硬件联调时可覆盖指定磁盘的 `health`，磁盘序号从 `1` 开始：

```powershell
python pico_monitor.py --dev --disk-health-test-index 2 --disk-health-test-level 5
```

省略 `--disk-health-test-level` 时默认使用 `3`；将 `--disk-health-test-index` 设为 `0` 可关闭测试。也可分别通过环境变量 `PICO_MONITOR_DISK_HEALTH_TEST_INDEX` 和 `PICO_MONITOR_DISK_HEALTH_TEST_LEVEL` 配置。

`horizontal_disk` 和 `horizontal_disk6x` 样式按帧显示告警：

- `health=3`：磁盘边框和名称在灰色、黄色之间逐帧切换。
- `health=4`：磁盘边框和名称在黄色、红色之间逐帧切换。
- `health=5`：一帧显示红色边框和 `WARN` 标识，下一帧将磁盘卡片内全部字符及图形显示为红色，随后循环闪烁。
