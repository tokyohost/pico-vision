# Pico Vision Windows 兼容性说明

## 1. 适用范围

本文说明 Pico Vision 在 Windows 环境下的系统兼容范围，重点描述基于 PresentMon/ETW 的 FPS 采集能力。其他硬件监控功能的实际可用性还会受到设备型号、驱动程序和系统权限影响。

## 2. Windows 系统兼容范围

| Windows 系统 | CPU 架构 | 兼容级别 | 说明 |
| --- | --- | --- | --- |
| Windows 11 | x64 | 正式支持 | 推荐使用仍处于 Microsoft 支持周期内的版本 |
| Windows 10 | x64 | 正式支持 | 推荐使用 Windows 10 22H2 或受支持的 LTSC 版本 |
| Windows 11 | ARM64 | 未验证 | 内置 PresentMon 为 x64 程序，可能依赖 Windows x64 模拟层，不作为正式支持环境 |
| Windows 8.1、Windows 8 | x64/x86 | 不支持 | 当前项目及内置 PresentMon 2.4.1 未纳入兼容性验证 |
| Windows 7 | x64/x86 | 不支持 | 即使旧版 PresentMon 可能运行，也不代表当前项目能够稳定工作 |
| 32 位 Windows | x86 | 不支持 | 项目内置的 PresentMon 和发布目标均为 64 位 |

项目对外可声明的系统兼容范围为：**Windows 10 64 位和 Windows 11 64 位**。

## 3. FPS 采集兼容性

Pico Vision 默认使用 `PresentMonBackend`，通过 Windows ETW（Event Tracing for Windows）接收帧呈现事件。项目内置官方 PresentMon 2.4.1 64 位控制台程序。

支持的主要图形接口如下：

- DirectX 9；
- DirectX 11；
- DirectX 12；
- OpenGL；
- Vulkan。

PresentMon 不限定 Intel 显卡，可用于 Intel、AMD 和 NVIDIA 显卡。FPS 是否能够正常产生，还取决于目标程序是否提交可被 ETW 捕获的帧呈现事件。

当前实现仅统计前台程序及其关联进程中最活跃的 SwapChain，用于生成约一秒窗口的 FPS 数据。当前实现不采集 GPU 时序、输入延迟，也不写入 PresentMon CSV 文件。

## 4. 运行权限

PresentMon 启动 ETW 会话时，运行 Pico Vision 的账户应满足以下任一条件：

- 使用管理员权限运行；
- 属于 Windows 的 `Performance Log Users`（性能日志用户）组。

权限不足时，PresentMon 可能因 `Access Denied` 无法创建 ETW 会话，FPS 字段将不可用，但不应影响项目中的其他监控指标。

修改用户组后通常需要注销并重新登录，权限才会生效。

## 5. AMD ADLX 回退能力

AMD ADLX 不是 Windows 系统自带组件。项目中的 `AdlxBackend` 是可选回退方案，需要额外部署 `adlx_fps_bridge.dll` 及其依赖的 AMD ADLX 运行环境。

未部署 ADLX 桥接库时出现“未找到 ADLX FPS 桥接库”警告属于预期行为。只要 `PresentMonBackend` 已正常启动并收到帧事件，FPS 采集仍可使用。

ADLX 方案仅适用于兼容的 AMD 显卡和驱动环境，不能替代 PresentMon 作为跨显卡厂商的通用方案。

## 6. 已知限制

- 无管理员权限或性能日志用户权限时，ETW 会话可能启动失败；
- 受保护进程、其他用户启动的进程或生命周期很短的进程，可能无法获得完整的进程信息；
- OpenGL 和 Vulkan 的部分高级时序指标精度低于 DirectX，但本项目主要统计帧事件数量，通常仍可计算 FPS；
- 无画面更新、最小化、后台限帧或未产生 Present 事件的程序可能显示空 FPS；
- 多进程应用由前台窗口、关联进程识别和最活跃 SwapChain 共同决定采样目标，特殊启动器或跨权限进程可能识别失败；
- 远程桌面、虚拟机、云桌面及无物理显示输出环境未列入正式支持范围；
- Windows ARM64、Windows Server 和精简版 Windows 尚未完成项目级验证。

## 7. 推荐验证矩阵

正式发布前建议至少验证以下组合：

| 系统 | 显卡厂商 | 建议测试内容 |
| --- | --- | --- |
| Windows 10 22H2 x64 | Intel、AMD、NVIDIA | PresentMon 启动、前台进程识别、FPS 连续采集 |
| Windows 11 23H2 或更高版本 x64 | Intel、AMD、NVIDIA | PresentMon 启动、前台切换、全屏与窗口模式采集 |
| Windows 10/11 x64 普通用户 | 任一 | 性能日志用户组权限验证 |
| Windows 10/11 x64 管理员 | 任一 | 管理员权限采集及跨权限进程行为验证 |

每次升级 PresentMon、Python 运行环境、打包工具或前台进程识别逻辑后，都应重新执行兼容性验证。

## 8. 部署检查

部署或排查 FPS 功能时，应确认：

1. 操作系统为 Windows 10/11 64 位；
2. `PresentMon.exe` 已随程序打包，或通过 `PICO_MONITOR_PRESENTMON` 指定了有效路径；
3. 当前账户具备 ETW 会话所需权限；
4. 显卡驱动已正确安装并处于正常状态；
5. 日志中出现 `PresentMonBackend` 初始化成功和 ETW 采集启动信息；
6. 前台目标程序正在持续渲染并产生帧呈现事件。

当日志显示 `PresentMonBackend` 已启动，而 `AdlxBackend` 因缺少桥接库初始化失败时，应优先检查 PresentMon 是否持续收到帧事件，不需要仅因 ADLX 警告判定 FPS 功能不可用。
