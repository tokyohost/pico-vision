# 跨平台桌面端

公共层已经从 Windows 托盘实现中抽出，Windows 保留现有行为，Linux 默认仍运行无界面服务。macOS 适配和双架构打包链路已实现，但尚未在 Mac 真机完成构建、签名、公证及硬件验收。

## 目录与兼容入口

```text
desktop/
  common/      配置、worker 控制、设备操作、日志、HTTP 服务、Vue 业务桥接
  win/         Windows 托盘、WebView2、注册表启动项、休眠事件、旧 Tk 窗口
  linux/       原有 HTTP 桥接、可选 GTK/WebKit 桌面、XDG 启动项
  macos/       菜单栏、WKWebView、LaunchAgent、通知、唤醒、应用更新与构建
```

原有 `win.settings`、`win.tray`、`win.ui-web-api`、`win.ui`、`web_admin`、`windows_update` 等入口是兼容转发模块，避免修改外部调用和测试补丁路径。传感器宿主、Windows FPS 与设备协议不因桌面迁移而改变。

Vue 源码暂时保留在历史位置 `win/ui-web`，三个桌面端共用同一份构建产物与 action 协议，不存在独立 Mac 页面。基础 API 不加载 GUI 或 Cocoa。Linux 原有 HTTP 管理页面继续使用 Linux 桥接；新增桌面使用公共桌面桥接。

## 启动和退出

Windows 冻结 EXE 的默认启动行为不变；Linux 的默认 CLI、systemd、DEB/NAS 安装行为不变，只有显式 `--desktop` 才加载桌面。Mac `.app` 默认运行菜单栏桌面。

Windows spec 会检查 Tcl/Tk 是否可用，避免 PyInstaller 静默丢弃旧窗口。自定义 Python 安装若不能发现已有资源，需为构建进程提供正确的 `TCL_LIBRARY`/`TK_LIBRARY`；不要把不完整 EXE 当作兼容验证通过。

```powershell
# Windows 源码桌面；原有启动入口也继续有效。
python pico_monitor.py --desktop
```

```bash
# Linux 默认无界面服务；桌面为可选安装。
python3 pico_monitor.py
python3 -m pip install -r desktop/linux/requirements.txt
# 需要发行版提供 GTK3、WebKitGTK、PyGObject 和可用的托盘/状态通知支持。
python3 pico_monitor.py --desktop

# Mac 源码开发（macOS 12+，使用对应架构 Python）。
python3 -m pip install -r desktop/macos/requirements.txt
npm ci --prefix win/ui-web
npm run build --prefix win/ui-web
python3 pico_monitor.py --desktop
```

关闭控制窗口只隐藏，不停止采集；菜单“退出”才停止 worker、HTTP 管理服务和平台监听。Mac 菜单栏与 WKWebView 共用主线程的 NSApplication；不要求 WebView2，不加载 Windows 注册表、PresentMon 或 SensorHost。

Windows 继续使用 `%LOCALAPPDATA%/PicoMonitor`；Mac 设置、日志与插件位于 `~/Library/Application Support/OmniWatch`；Linux 桌面位于 `$XDG_DATA_HOME/omniwatch`，默认 `~/.local/share/omniwatch`。非 Windows 桌面会为 worker 设置 `PICO_MONITOR_DATA_ROOT`，但尊重用户已提供的环境变量；该变量自定义插件存储，并不迁移桌面设置文件。

Mac 启动项仅写入当前用户 LaunchAgents，不要求 root，不启用 KeepAlive。通知依赖用户授权；拒绝授权不影响采集。系统唤醒复用 `RESUME_PROBE`，恢复 USB/Wi-Fi 探测。串口支持 ESP32-S3/RP2040 原生 USB CDC；CH343 驱动由用户从 WCH 官方安装，本程序不静默安装驱动。设备实际识别与重连仍需真机验证。

## 原生双架构打包

`pico_monitor_macos.spec` 独立生成 `OmniWatch.app`，`desktop/macos/build.py` 制作保留链接与权限的 ZIP 和 DMG。ZIP 内含 `.app`，供自动更新；DMG 内含 `.app` 和 Applications 快捷入口，供首次人工安装。Intel 与 Apple Silicon 必须分别原生构建，不在 Windows 交叉编译，也不把系统 Python 作为插件运行时。

```bash
python3 -m pip install -r desktop/macos/requirements.txt 'uv==0.8.22'
export UV_PYTHON_INSTALL_DIR="$PWD/.build-python"
uv python install 3.13.5
runtime_python="$(uv python find --managed-python 3.13.5)"
runtime_root="$("$runtime_python" -I -c 'import sys; print(sys.prefix)')"
# Intel 使用 x86_64；Apple Silicon 使用 arm64。
python3 -B -m desktop.macos.build --architecture arm64 --runtime "$runtime_root" --unsigned
```

开发包名包含 `-dev`，不用于正式自动更新。完整插件 Python 随 `.app` 打包，支持 pip/venv，安装目录迁移和创建虚拟环境都必须通过构建验证。代码对插件解释器单独设置所需签名权限，主应用不整体放宽库验证。运行时缺失或不可迁移时构建失败，不退回冻结入口冒充 Python。

正式构建需要 Developer ID Application 证书和 Apple 公证账户：

```bash
export MONITOR_MAC_SIGNING_IDENTITY='Developer ID Application: 团队名称 (TEAMID)'
export MONITOR_MAC_NOTARY_PROFILE='omniwatch-notary'
# 先用 xcrun notarytool store-credentials 将凭据保存到钥匙串。
python3 -B -m desktop.macos.build --architecture arm64 --runtime "$runtime_root"
```

构建检查所有 Mach-O 的目标架构和最低部署版本；高于 macOS 12 的依赖直接拒绝。`MACOSX_DEPLOYMENT_TARGET=12.0` 或 Info.plist 声明不能单独证明兼容 macOS 12：还必须在 macOS 12 真机检查系统符号、启动、传感器、WKWebView 和硬件行为。独立运行时在 PyInstaller `.app` 布局中的可迁移性也尚待实际 Mac 构建验证。

## GitHub Actions

新增 `build-macos-dmg.yml`，使用 `macos-15-intel` 构建 x86_64、`macos-15` 构建 arm64。手动运行默认只生成开发 Artifact；勾选签名公证时生成正式 Artifact；`v` 开头标签强制签名、公证，并发布两个架构的 ZIP/DMG。Runner 不等于 macOS 12 验收环境。另有 `desktop-regression.yml` 在 Windows 与 Ubuntu 隔离执行公共层和无界面入口回归。

仓库 Secrets：

| 名称 | 用途 |
| --- | --- |
| `MACOS_CERTIFICATE_P12_BASE64` | Developer ID Application 私钥证书 P12 的 Base64 |
| `MACOS_CERTIFICATE_PASSWORD` | P12 密码 |
| `MACOS_SIGNING_IDENTITY` | 完整 Developer ID Application 签名身份 |
| `MACOS_APPLE_ID` | 公证账户 |
| `MACOS_APP_PASSWORD` | App-specific password，不是 Apple ID 登录密码 |
| `MACOS_TEAM_ID` | Apple Developer 团队 ID |
| `OMNIWATCH_DOC_TOKEN` | 同步当前自动更新仓库 `tokyohost/omniwatch-doc` 的令牌 |

临时证书和钥匙串在任务结束时清理。没有凭据时正式发布会失败，不会悄悄发布未公证包。添加工作流不会自动配置 Secrets，也不会立即执行或发布制品。

## 应用自动更新边界

仅签名、已安装的 `.app` 支持自动更新。更新器按当前进程架构选择 `OmniWatch-macos-<架构>-v<版本>.zip`，要求 GitHub SHA-256 摘要，验证归档路径、签名团队、Bundle ID、版本、Gatekeeper 和架构。开发包不参与选择；源码模式或不可写的安装目录提示人工通过 DMG 更新。

独立助手等待主进程退出后，在安装目录建立新副本并原子替换。启动命令失败会还原旧应用；成功后保留 `.omniwatch-backup-*.app`，不静默删除旧版本。记录位于数据目录的 `updates/last-update.json`，助手失败记录位于对应暂存目录的 `error.log`。`open` 成功只表示系统接受启动请求，不能证明新应用随后没有崩溃；本版尚无跨版本启动健康确认握手。

## 验证清单

现有 Windows 托盘、Tk 兼容入口、WebView2、启动项、更新和固件操作需持续回归。Linux 首先保证默认 CLI/HTTP/systemd 和打包清单，不把 GUI 变成基础依赖；新增 GTK 桌面还需桌面环境验证。Mac 需分别测试 Intel/ARM、macOS 12 与新版本、通知授权、菜单栏、隐藏/退出、登录启动、休眠恢复、插件安装、签名更新/回滚，以及 USB CDC、CH343 和 Wi-Fi 热插拔。

macOS 采集的温度、GPU、功耗和 FPS 受硬件、权限及后端能力限制；不可读时沿用 `null`/未知状态，不伪造值。参见上级 README 的采集后端说明。Windows 上通过 mock 的 Mac 单元测试不等同于完成真机验收。

参考：[GitHub Runner 架构](https://github.com/actions/runner-images)、[PyInstaller spec 与 BUNDLE](https://pyinstaller.org/en/stable/spec-files.html)、[pywebview 引擎](https://pywebview.flowrl.com/guide/web_engine.html)、[Apple 公证](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)。
