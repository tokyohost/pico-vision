# 自定义数据插件协议 2

## 设计目标

协议 2 将插件功能分成三个互不混淆的层次：

1. Monitor 生命周期状态：决定插件是否启用和参与调度。
2. 插件业务配置：传递给 `collect(config_json)` 的字段。
3. 插件动作与卸载钩子：在用户明确操作时通过隔离进程执行。

`custom_data_enabled` 由 Monitor 持久化，不会写入插件的业务配置，也不会传给
`collect()`、动作或卸载钩子。禁用插件会停止其采集任务和常驻子进程，但保留配置、
独立环境和插件数据。

## 清单示例

```json
{
  "protocol": 2,
  "key": "application_metrics",
  "name": "application_metrics",
  "zh_name": "应用指标",
  "interval": 5,
  "config_panel": [
    {
      "kind": "field",
      "key": "application_path",
      "name": "application_path",
      "zh_name": "应用安装目录",
      "type": "string",
      "default": "",
      "readonly": true
    },
    {
      "kind": "action",
      "action": "detect_application",
      "zh_name": "自动检测安装目录",
      "loading_text": "正在检测……"
    }
  ],
  "actions": {
    "detect_application": {
      "method": "detect_application",
      "timeout": 10,
      "config_keys": ["application_path"],
      "description": "检测本机应用安装目录"
    }
  },
  "uninstall": true,
  "entry": "main.py"
}
```

未声明 `kind` 的旧面板元素仍按 `field` 处理。协议 1 插件可以继续使用原有字段，
但不能声明动作和卸载钩子。

## 动作方法

动作方法接收一个上下文对象：

```python
def detect_application(context):
    """检测应用目录并返回配置补丁。"""
    current_config = context["config"]
    return {
        "message": "检测成功",
        "warnings": [],
        "config_patch": {
            "application_path": find_application_path(current_config),
        },
    }
```

上下文中的 `config` 是经过 Monitor 校验的当前表单快照。动作返回值必须是可进行
JSON 序列化的对象。支持以下返回字段：

- `message`：成功提示。
- `warnings`：需要逐条提示的警告数组。
- `data`：不写入配置的附加结果。
- `config_patch`：回填当前表单的配置补丁。

`config_patch` 只能包含该动作 `config_keys` 明确授权的字段，并会再次经过字段类型、
范围、选项和正则校验。`interval`、Monitor 启用状态、其他插件配置均不能由动作修改。
回填仅修改尚未保存的表单，用户仍需点击“保存配置”才会持久化并热更新采集任务。

动作通过插件独立 Python 环境执行。单次超时范围为 0.1 至 60 秒；超时后 Monitor
终止插件子进程，下次请求会自动创建新进程。插件应当为网络和外部进程调用设置更短
的自身超时。

## 卸载清理钩子

清单声明 `"uninstall": true` 后，入口必须定义：

```python
def uninstall(context):
    """清理由插件自行创建且明确归属插件的数据。"""
    config = context["config"]
    reason = context["reason"]
    cleanup_owned_data(config, reason)
    return {"message": "插件数据清理完成"}
```

当前 `reason` 为 `delete`。Monitor 的删除顺序为：

1. 确认插件独立环境可用。
2. 使用当前已校验配置调用 `uninstall(context)`。
3. 钩子成功后停止插件进程。
4. 删除插件目录和独立环境。
5. 删除 Monitor 保存的该插件启用状态及业务配置。

钩子抛出异常或超时时，删除立即中止，插件目录、独立环境和 Monitor 配置均保留，
便于修复后重试。覆盖安装属于升级流程，不调用卸载钩子。

卸载方法只能删除插件明确拥有的数据。必须解析并校验精确路径，禁止递归删除用户
目录、磁盘根目录、Monitor 数据根目录等宽泛目标。

## 兼容与迁移

- 协议 1 插件无需修改即可继续采集。
- 老版本设置没有 `custom_data_enabled` 时，已安装插件迁移为启用，保持原行为。
- 新导入插件由托盘应用写入显式 `false`，用户确认启用后才加入调度。
- 禁用状态不进入 `custom_data_configs`，插件无法自行启用。


## 快照插件数据模式

`plugin.json` 支持 `data_mode`：

- `active_style`：仅当 `display.style` 与绑定文件 `style_<样式名>.py` 的样式名一致时，快照 `ext` 携带此插件的数据。要求 `bind_style: true`。
- `always`：所有样式下都携带数据，适用于多个样式共用的数据插件。

省略时，绑定样式插件默认 `active_style`，未绑定样式插件默认 `always`。该模式只影响发送视图，不停止后台采集。切换离开后，增量事务删除设备上的对应 `ext` 字段；切回后发送最新缓存。

事务快照从构帧到最终带请求序号的 JSON ACK 共用 400ms 预算。超出预算判定本次失败并清除发送基线，下次发送完整快照；不截断业务字段来伪造成功。USB 写入超时废弃连接，防止残留半帧污染后续事务。旧固件的非事务传输保持原有超时行为。

400ms 是软件成功判定预算，不是任意数据量、设备停顿或驱动阻塞下的物理交付保证。需要分别在真实 RP2040、ESP32-S3 的 USB 和网络链路测量整批确认耗时；无法及时送达时会明确失败。

完整事务可超过 16KiB，每片解压 JSON 仍不超过 4096 字节。设备通过 `snapshot_chunks.max_bytes` 公告事务序列化预算（ESP32-S3 256KiB、RP2040 64KiB）。性能测量和网络异常验证见 [Snapshot 验证记录](snapshot_reliability_20260910.md)。
