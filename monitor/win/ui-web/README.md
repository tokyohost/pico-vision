# OmniWatch Windows Web UI

此目录是 Windows 托盘程序的完整 Web 界面源代码，技术栈为 Vue 3、Element Plus 与 Vite。

前端不启动开发服务器，也不访问 REST API。所有桌面能力统一调用：

```js
window.pywebview.api.invoke(action, payload)
```

Python 兼容入口位于相邻的 `win/ui_web.py`，按职责拆分后的桥接实现位于
`win/ui-web-api`。生产构建使用相对资源路径，可被 PyInstaller 单文件程序从
临时解包目录通过 `file://` 直接加载。

## 本地开发

```powershell
npm ci
npm run dev
```

Vite 开发页会加载 HTTP 兼容桥接；联调业务动作时需把 `/ws` 代理到已启用的
Monitor HTTP 管理服务。

## HTTP 管理页面

同一份生产构建可以由内置 HTTP 服务提供。普通浏览器加载页面时，
`httpBridge.js` 会使用 `reconnecting-websocket` 创建具备退避重连能力的
兼容 `window.pywebview.api.invoke`，并通过 `/ws?auth=...` 代理原 action
协议，因此业务 Vue 组件不区分桌面和 HTTP 传输。服务端使用 `aiohttp`
承载静态页面、HTTP 接口和 WebSocket Upgrade。

Windows 可在“设置 → HTTP 管理页面”中配置启停、端口和 Auth，默认端口为
`9876`，首次运行会生成随机 Auth。Linux 通过 `pico-monitor.conf` 的 `http`
节点配置。浏览器首次访问会要求输入 Auth，并保存到当前浏览器的
`localStorage`。

如果配置端口被占用、被 Windows 排除或没有监听权限，服务会从该端口开始
向后寻找可监听端口。Windows 会把实际端口回写设置并通过托盘通知；Linux
保持配置文件不变，并在启动日志中输出实际端口。

额外的 `POST /api/invoke` 接口使用 `Authorization: Bearer <Auth>` 鉴权；
健康检查地址为 `GET /api/health`。原生文件选择、打开服务器本地目录等桌面
专属动作会在 HTTP 代理层返回不支持，不会进入原业务桥接。

## 插件市场

“插件市场”菜单通过 iframe 加载市场页面，并自动附加
`embed=1&theme=dark`。Monitor 版本为 `development` 时使用
`http://localhost/market`；正式版本使用控制中心“设置 → 插件市场”中保存的地址。

## 生产构建

```powershell
npm ci
npm run build
```

仓库根目录的 Windows GitHub Actions 工作流和 `monitor/build-exe.bat` 会先执行上述
构建，再把 `dist` 目录加入 PyInstaller 数据文件。
