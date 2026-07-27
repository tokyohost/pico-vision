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

Vite 开发页不具备 Python 桥接对象，业务动作需要在 pywebview 宿主内联调。

## 生产构建

```powershell
npm ci
npm run build
```

仓库根目录的 Windows GitHub Actions 工作流和 `monitor/build-exe.bat` 会先执行上述
构建，再把 `dist` 目录加入 PyInstaller 数据文件。
