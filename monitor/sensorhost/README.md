# OmniWatch SensorHost

OmniWatch SensorHost 是 Windows 上的独立硬件传感器宿主进程。它使用 C# 和 `LibreHardwareMonitorLib` 读取 CPU、GPU、内存、磁盘与功耗传感器，通过 Named Pipe 向 Python monitor 返回 JSON 快照。

## 构建

```powershell
dotnet restore
dotnet build -c Release
```

## 发布流水线

GitHub Actions 配置位于 `.github/workflows/release.yml`。

- 推送到 `main` 或 `master`：执行还原、编译、发布和上传构建产物。
- 创建 `v*` 标签，例如 `v1.0.0`：自动创建 GitHub Release，并上传 zip 与 SHA256。
- 手动运行 `workflow_dispatch`：可填写版本号，并选择是否创建 GitHub Release。

发布包名称格式为 `omniwatch-sensor-host-win-x64-<version>.zip`，包内可执行文件名称格式为 `OmniWatch.SensorHost-<version>.exe`，包含 Windows x64 自包含可执行文件、Python Named Pipe 客户端和 README。

## 调试

```powershell
dotnet run --project src\OmniWatch.SensorHost -- --once --pretty
dotnet run --project src\OmniWatch.SensorHost -- --pipe omniwatch.sensorhost
```

## Named Pipe 协议

管道名称默认是 `omniwatch.sensorhost`，Windows 完整路径是 `\\.\pipe\omniwatch.sensorhost`。请求和响应均为 UTF-8 无 BOM、单行 JSON，以换行符结尾。

请求示例：

```json
{"command":"snapshot"}
```

响应示例：

```json
{"ok":true,"data":{"version":1,"cpu":{"percent":12.3}}}
```

支持命令：

- `ping`：返回宿主健康状态。
- `snapshot`：返回一次硬件传感器快照。
- `shutdown`：优雅退出宿主进程。

## Python 进程管理

`python/omniwatch_sensor_host.py` 提供 `SensorHostProcess` 和 `SensorHostClient`。`SensorHostProcess` 使用 `subprocess.Popen` 启动宿主，并通过 pywin32 Job Object 设置 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，确保 monitor 退出时子进程一起退出。
