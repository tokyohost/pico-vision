# 磁盘 SMART 健康检查说明

## 检查频次

磁盘信息后台线程在 `monitor` 启动后立即执行第一次 SMART 健康检查。检查结果缓存 30 分钟；缓存有效期内的磁盘信息采集直接复用上一次结果，缓存到期后再次检查。

- 首次检查：程序每次启动时。
- 周期检查：每 30 分钟一次。
- 磁盘基础信息采集：每 10 秒一次，但不会绕过 30 分钟 SMART 缓存。
- 热插拔检查：每 10 秒比较物理磁盘、分区及挂载关系；发现变化后立即清空 SMART、`health` 和温度缓存，并在同一采集轮次重新读取。
- 单块磁盘 SMART 命令超时：10 秒。
- 告警日志：健康等级达到 `NOTICE(2)` 或更高时记录警告日志。

Linux 使用 `smartctl -a -j` 读取 SMART JSON，并通过 `smartctl --scan-open -j` 发现 SATA、NVMe、SCSI、USB 转接及 RAID 控制器后的磁盘。系统需要安装 `smartmontools`，并授予进程读取磁盘 SMART 信息的权限。

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
