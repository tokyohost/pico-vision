# qBittorrent 采集配置

monitor 端通过 qBittorrent Web API 在后台采集传输、用户统计和种子状态。默认关闭；开启后地址、账号、密码均为必填项。API 断开不会阻塞 Pico 主采集循环，最近一次快照会被保留，同时 `qbittorrent.online` 变为 `false`。

## 开启 Web UI

在 qBittorrent 的“工具 → 选项 → Web UI”中启用 Web 用户界面，配置监听地址、端口、用户名和密码。monitor 所在主机必须能够访问该地址；如果跨主机访问，请同时检查防火墙和 qBittorrent 的 Web UI 访问控制设置。

## 命令行配置

```powershell
python pico_monitor.py `
  --qbittorrent-enabled `
  --qbittorrent-address http://127.0.0.1:8080 `
  --qbittorrent-username admin `
  --qbittorrent-password your-password `
  --qbittorrent-interval 2.0
```

使用 `--no-qbittorrent` 可显式关闭采集。密码直接写入命令行可能被系统进程列表记录，长期运行时建议使用环境变量或 Linux 配置文件。

## 环境变量配置

```text
PICO_MONITOR_QBITTORRENT_ENABLED="1"
PICO_MONITOR_QBITTORRENT_ADDRESS="http://127.0.0.1:8080"
PICO_MONITOR_QBITTORRENT_USERNAME="admin"
PICO_MONITOR_QBITTORRENT_PASSWORD="your-password"
PICO_MONITOR_QBITTORRENT_INTERVAL="2.0"
```

Linux 安装包可在 `/etc/pico-monitor.conf` 中填写以上变量，修改后执行：

```bash
sudo systemctl restart pico-monitor
sudo journalctl -u pico-monitor -f
```

`PICO_MONITOR_QBITTORRENT_ENABLED` 支持 `1`、`true`、`yes` 和 `on`。启用后若地址、账号或密码为空，monitor 会立即报告缺失参数并退出；关闭时不会连接 qBittorrent。

## 采集字段

采集结果放在 JSON 顶层 `qbittorrent` 中：

| 字段 | 含义 | 单位 |
| --- | --- | --- |
| `enabled` | qBittorrent 采集已启用 | 布尔值 |
| `online` | 最近一次 API 采集是否成功 | 布尔值 |
| `connection_status` | qBittorrent 连接状态 | `connected`、`firewalled` 或 `disconnected` |
| `error` | 最近一次采集错误，成功时为空 | 文本 |
| `upload_bps` | 当前上传速度 | 字节/秒 |
| `download_bps` | 当前下载速度 | 字节/秒 |
| `upload_history` | 最近 24 次上传速度 | 字节/秒数组 |
| `download_history` | 最近 24 次下载速度 | 字节/秒数组 |
| `uploaded_bytes` | 本次会话已上传 | 字节 |
| `downloaded_bytes` | 本次会话已下载 | 字节 |
| `free_space_bytes` | qBittorrent 下载位置剩余空间 | 字节 |
| `user_statistics.alltime_uploaded_bytes` | 历史上传 | 字节 |
| `user_statistics.alltime_downloaded_bytes` | 历史下载 | 字节 |
| `user_statistics.alltime_share_ratio` | 历史分享率 | 比率 |
| `user_statistics.session_wasted_bytes` | 本次会话丢弃数据 | 字节 |
| `user_statistics.connected_users` | 当前连接用户数 | 个 |

`qbittorrent.torrents` 包含以下种子计数：

| 字段 | 含义 |
| --- | --- |
| `all` | 全部种子数 |
| `downloading` | 正在下载数 |
| `seeding` | 正在做种数 |
| `completed` | 已完成数 |
| `resumed` | 已恢复且未暂停数 |
| `paused` | 已暂停数 |
| `active` | 当前有上传或下载流量的种子数 |
| `inactive` | 当前无上传下载流量的种子数 |
| `paused_uploading` | 已完成且上传暂停数 |
| `stalled_uploading` | 上传停滞数 |
| `checking` | 正在检查数 |
| `errored` | 错误或文件缺失数 |

字节字段由显示端按 B、KiB、MiB、GiB、TiB 自动格式化。例如历史上传 `3961542100992` 字节可显示为约 `3.603 TiB`。
