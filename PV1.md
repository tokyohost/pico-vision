# PV1 串口通信协议规范

## 1. 文档状态

本文定义 pico-vision Monitor 与 RP2040 Pico LCD 固件之间使用的 PV1 串口协议。

- 协议名称：PV1
- 协议版本：1
- 传输介质：USB CDC ACM 串口字节流
- 默认串口参数：115200 baud，8N1
- Monitor 实现：`monitor/pico_client.py`、`monitor/pico_upgrade.py`
- Pico 实现：`picoRP2040/protocol.py`、`picoRP2040/upgrade_manager.py`
- 兼容策略：仅支持 PV1，不兼容旧版 `PING:`、`JSON:`、`UPGRADE:` 裸文本协议

本文中的“必须”“不得”“应”“可以”分别对应 MUST、MUST NOT、SHOULD、MAY。

## 2. 设计目标

PV1 的目标如下：

1. 在 Windows 与 Linux USB CDC 上提供一致的消息边界。
2. 支持串口字节流的分段、合并、短写入和部分读取。
3. 在收到其他程序写入的非协议内容后重新同步。
4. 使用长度字段和 CRC 检测截断、拼接及传输损坏。
5. 避免未同步的短数据触发固定长度阻塞读取。
6. 使用批量读取和压缩降低 RP2040 的接收与解析耗时。
7. 限制帧大小、JSON 大小、半包驻留时间和解压内存。
8. 让握手、快照、升级、事件、确认和错误共用同一种帧格式。

PV1 的 CRC 只用于偶然错误检测，不提供身份认证、机密性或抗恶意篡改能力。

## 3. 分层模型

PV1 分为三层：

1. USB CDC 字节流层：不保留应用消息边界。
2. PV1 帧层：提供魔数、类型、长度、CRC、填充和换行边界。
3. 消息层：定义 `PING`、`PONG`、`JSONZ`、`ACK`、`ERR`、`EVENT`、`COMMAND` 和 `STATUS`。

## 4. 基本编码规则

- 协议关键字、类型、长度和 CRC 使用 ASCII。
- JSON 使用 UTF-8；Monitor 当前以 `ensure_ascii=True` 生成紧凑 JSON。
- 数字字段不得包含符号、空格或前导说明文字。
- 类型名称区分大小写，规范类型全部使用大写 ASCII。
- 一条物理帧以单个 LF 字节 `0x0A` 结束。
- 接收方可以接受 LF 前的传输填充空格，但不得把填充计入载荷。
- 载荷不得直接包含 LF。二进制内容必须先转换为 Base64 等行安全编码。

## 5. 帧格式

### 5.1 语法

```text
PV1:<TYPE>:<LENGTH>:<CRC16>:<PAYLOAD><PADDING>\n
```

等价的 ABNF 表示：

```text
frame       = magic ":" type ":" length ":" crc16 ":" payload padding LF
magic       = "PV1"
type        = 1*(ALPHA / DIGIT / "_")
length      = 1*DIGIT
crc16       = 4HEXDIG
payload     = *OCTET
padding     = *SP
LF          = %x0A
```

`payload` 的实际字节数必须恰好等于 `LENGTH`。解析器先按前四个冒号分割头部，剩余部分再按 `LENGTH` 划分为载荷和填充，因此载荷可以包含冒号。

### 5.2 字段定义

| 字段 | 含义 | 是否参与 CRC |
|---|---|---|
| `PV1` | 固定魔数和主版本 | 否 |
| `TYPE` | 消息类型 | 是 |
| `LENGTH` | `PAYLOAD` 的字节数 | 否 |
| `CRC16` | 四位大写十六进制校验值 | 不适用 |
| `PAYLOAD` | 消息载荷 | 是 |
| `PADDING` | 传输层空格填充 | 否 |
| LF | 帧结束符 | 否 |

### 5.3 长度

`LENGTH` 是原始 `PAYLOAD` 的字节数，不是字符数，也不包含：

- `PV1:` 头部；
- 类型、长度、CRC 及分隔冒号；
- 传输填充空格；
- 结尾 LF。

当前实现允许的最大帧载荷为 16 KiB。

### 5.4 CRC-16/CCITT-FALSE

CRC 参数如下：

| 参数 | 值 |
|---|---|
| 名称 | CRC-16/CCITT-FALSE |
| 多项式 | `0x1021` |
| 初始值 | `0xFFFF` |
| 输入反射 | false |
| 输出反射 | false |
| 最终异或 | `0x0000` |
| 标准测试向量 | `CRC("123456789") = 0x29B1` |

CRC 输入必须严格为：

```text
ASCII(TYPE) + b":" + PAYLOAD
```

CRC 不覆盖魔数、长度、填充和 LF。发送方使用四位大写十六进制输出；接收方可以按十六进制解析，但规范发送方必须使用大写。

RP2040 实现使用 256 项、16 位字节查找表。表占约 512 字节，每个输入字节只执行一次查表，避免 MicroPython 逐位算法造成明显延迟。

定制 UF2 可内置接口版本为 `1` 的 `fn_protocol` 用户 C 模块，由 C 完成帧头、长度、
尾部填充及 CRC 校验。Pico 启动代码会检查模块版本和 `parse_frame` 接口；模块缺失、
版本不匹配或接口不完整时，自动回退到上述纯 Python 查表实现，协议线格式不变。

## 6. 64 字节传输块

### 6.1 Monitor 到 Pico

Monitor 发送的每个 PV1 帧必须补齐为 64 字节的整数倍：

```text
padding_length = -(header_and_payload_length + 1) mod 64
```

发送顺序为：

```text
头部 + 载荷 + padding_length 个 ASCII 空格 + LF
```

因此 LF 总是位于一个 64 字节传输块的最后一个字节。

Monitor 当前将完整帧按最多 511 字节一块交给 pySerial。单次写入长度不得是 64 的整数倍；若最后剩余部分恰好是 64 的整数倍，必须再拆成一个非整倍数短块和余下字节。511 只是主机写入粒度，不是 PV1 消息边界。

在 POSIX/Linux 上，每个短块后执行 `flush()` 并等待约 2ms，防止 CDC 驱动重新合并为恰好 64 字节的满端点传输。64 字节 PING 因此按 63+1 两次物理写入，但逻辑上仍是一条完整 PV1 帧。

### 6.2 Pico 到 Monitor

Pico 响应帧当前不补齐到 64 字节，直接以 LF 结束。主机使用带超时的 `readline()` 接收，不依赖固定块读取。

### 6.3 填充校验

接收方必须：

1. 根据 `LENGTH` 截取载荷；
2. 检查载荷后、LF 前的剩余字节；
3. 剩余字节只能是 ASCII 空格；
4. 任何其他尾随字节必须返回 `BAD_FRAME_TRAILER`。

## 7. 接收状态机

### 7.1 未同步状态

Pico 不得在尚未识别 PV1 魔数时直接执行 `readinto(64)`。`poll()` 只证明至少一个字节可读，不保证已经存在 64 字节。

未同步时接收方必须：

1. 每次只读取一个已由 `poll()` 确认可读的字节；
2. 在缓存中搜索 `PV1:`；
3. 丢弃魔数之前的所有垃圾字节；
4. 尚未找到完整魔数时只保留最后三个字节，以便跨读取匹配 `PV1:`。

这能避免 ModemManager、brltty、串口终端或其他程序写入短 `AT` 探测命令后，Pico 因等待固定长度而永久阻塞。

### 7.2 已同步状态

缓存以 `PV1:` 开头后，接收方进入批量模式。Monitor 保证帧总长度是 64 的整数倍，因此 Pico 可以读取到下一个 64 字节边界：

```text
read_size = 64 - (buffer_length mod 64)
```

批量模式显著减少 MicroPython 轮询次数。例如约 4.4 KiB 的帧从约 4400 次单字节读取降为约 73 次读取。

### 7.3 行完成与多帧

- 缓存出现 LF 后，接收方提取 LF 之前的完整行。
- 消费当前行后，剩余字节保留给下一帧。
- 一次轮询可以接收一个帧的一部分、一个完整帧或多个连续帧。
- 应用层只能处理通过全部结构检查和 CRC 检查的帧。

### 7.4 半包超时

缓存非空且连续 1000ms 没有收到新字节时：

1. 清空接收缓存；
2. 清除帧开始时间和读取计数；
3. 返回 `ERR` 帧，载荷为 `FRAME_TIMEOUT`；
4. 回到未同步状态。

### 7.5 大小限制

当前 Pico 每轮最多读取 2048 字节。接收缓存上限取以下较大值并预留一个传输块：

```text
max(MAX_JSON_SIZE + 64, MAX_UPGRADE_LINE_SIZE + 64)
```

当前参数：

- `MAX_JSON_SIZE = 16 KiB`
- `MAX_UPGRADE_LINE_SIZE = 1024`
- `SERIAL_READ_BUDGET = 2048`

超过接收缓存上限时必须清空缓存并返回 `ERR: FRAME_TOO_LARGE`。

### 7.6 批量读取的安全边界

当前 RP2040 优化实现只凭完整魔数 `PV1:` 切换到 64 字节批量读取。普通非协议垃圾不会触发批量模式，但一个恰好以 `PV1:` 开头、又没有补齐到 64 字节的伪帧仍可能使底层阻塞式 `readinto()` 等待后续字节。

因此：

- 合规发送方必须一次发送完整、64 字节对齐的 Monitor→Pico 帧；
- 系统应通过串口独占、udev 规则和禁用 ModemManager 探测，避免其他进程写入；
- 面向不可信串口写入者的实现应使用真正的非阻塞批量读取或具备底层读取超时，不得仅依赖魔数；
- 1 秒协议超时只能处理中间返回主循环的半包，不能中断已经进入底层阻塞调用的读取。

## 8. 帧校验顺序

接收方必须按以下顺序处理帧：

1. 搜索并定位 `PV1:` 魔数；
2. 检查头部分隔字段数量；
3. 解析十进制 `LENGTH`；
4. 解析十六进制 `CRC16`；
5. 检查长度范围；
6. 按长度截取载荷；
7. 检查尾部只有空格填充；
8. 计算并比较 CRC；
9. 识别消息类型；
10. 对载荷执行 Base64、解压、JSON 或升级命令解析；
11. 仅在全部成功后修改应用状态。

未经 CRC 校验的数据不得交给 JSON 解析器、解压器、升级管理器或 LCD 渲染器。

## 9. 消息类型

### 9.1 `PING`

方向：Monitor → Pico

载荷为空。用于设备发现和握手。

逻辑帧示例（省略填充）：

```text
PV1:PING:0:<CRC>:\n
```

Monitor 最多尝试三次，每次等待约 1.2 秒，只接受通过校验且类型为 `PONG` 的响应。

Linux/POSIX 实现首次握手前执行恢复性同步：清空主机输入输出缓冲，发送 64 个 LF 作为无害边界，等待至少 1 秒让 Pico 的半包超时状态复位，再清空收到的诊断残留并发送正式 `PING`。同步块不是 PV1 帧，接收方只能将其用于丢弃旧半包，不得交给应用层。

### 9.2 `PONG`

方向：Pico → Monitor

载荷是未压缩 UTF-8 JSON，包含：

```json
{
  "board_model": "rp2040_typec",
  "screen_color_profile": "st7789_2_4inch",
  "firmware_version": "1.2.3",
  "device_name": "PICO_LCD",
  "lcd_driver": "ST7789",
  "width": 240,
  "height": 320,
  "pixel_format": "RGB565"
}
```

### 9.3 `JSONZ`

方向：Monitor → Pico

用于发送系统快照。编码流水线必须为：

```text
应用快照
  → 删除线路上重复的顶层 disks（存在 physical_disks 时）
  → 紧凑 UTF-8 JSON
  → zlib 压缩
  → Base64
  → PV1 JSONZ 帧
  → 64 字节传输填充
```

`JSONZ` 的 `LENGTH` 和 CRC 针对 Base64 文本载荷，而不是压缩前 JSON 或 Base64 解码后的 DEFLATE 数据。

解压后的 JSON 使用模式信封。监控快照格式为：

```json
{"mode":"snapshot","data":{"host":"示例主机"}}
```

命令格式为：

```json
{"mode":"command","command":"reboot","params":{},"request_id":"可选请求编号"}
```

固件暂时兼容没有 `mode` 字段的旧快照对象。新实现不得再增加独立的 PV1
命令类型；配置修改、升级和重启等操作都应通过 JSON 命令策略扩展。

命令结果使用 `COMMAND` 帧返回 JSON：

```json
{"status":"ok","command":"config.update","data":{"restart_required":true},"request_id":"1"}
```

固件从 `picoRP2040/command` 自动发现公开 `COMMAND_STRATEGY` 的模块。自定义策略
必须继承 `CommandStrategy`、声明唯一 `name`，并实现带中文规范注释的 `execute` 方法。

### 9.4 `ACK`

方向：Pico → Monitor

成功接收、校验、解压并解析快照后返回：

```text
TYPE    = ACK
PAYLOAD = JSON
```

Monitor 只有收到完全匹配的 `ACK/JSON` 后才认为本次快照交互完成。

### 9.5 `ERR`

方向：双向均可，当前主要由 Pico 返回

载荷是 ASCII 错误码。规范错误码如下：

| 错误码 | 含义 |
|---|---|
| `BAD_FRAME_HEADER` | 头部字段缺失或数值无法解析 |
| `BAD_FRAME_LENGTH` | 长度越界或实际数据不足 |
| `BAD_FRAME_TRAILER` | 载荷后存在非空格尾随内容 |
| `BAD_FRAME_CRC` | CRC 不匹配 |
| `BAD_FRAME_TYPE` | 类型不是 ASCII |
| `FRAME_TIMEOUT` | 半包空闲超过 1000ms |
| `FRAME_TOO_LARGE` | 接收缓存超过上限 |
| `BAD_JSON` | Base64、zlib、UTF-8 或 JSON 处理失败，或发生内存不足 |
| `UPGRADE_UNAVAILABLE` | 固件未启用升级管理器 |
| `UNKNOWN_TYPE` | 消息类型不受支持 |

### 9.6 `EVENT`

方向：Pico → Monitor

承载启动、配置、LCD 绘制和性能诊断消息。载荷是 UTF-8 或 ASCII 文本。常见事件：

```text
BOOT:PICO_LCD_READY
CONFIG:LCD_STYLE:horizontal_disk4x_qb
ACK:LCD_FRAME:<version>:TOTAL=...MS:...:CANVAS_BACKEND=C:PROTOCOL_BACKEND=C
PROTOCOL_TIMING:TYPE=JSONZ:...
FATAL:<ExceptionType>:<message>
```

`PROTOCOL_BACKEND` 为 `C` 时表示 PV1 帧由 UF2 原生模块解析，为 `PYTHON` 时表示使用 Python 兼容解析器。

`EVENT` 不构成对请求的确认，Monitor 必须继续等待对应 `ACK`、`PONG` 或 `STATUS`。

### 9.7 `COMMAND`

方向：Pico → Monitor

载荷是 UTF-8 JSON 命令执行结果。成功和失败分别使用 `ok`、`error` 状态，
并原样返回请求中的可选 `request_id`。命令级错误使用此帧返回，不应误报为
传输层 `ERR`。

升级使用 `JSONZ` 中名为 `upgrade` 的命令，支持以下 `params.action`：

```text
begin
file
data
file_end
commit
abort
```

升级文件数据在 `data` 动作内使用 Base64。每个升级命令仍由 JSONZ 压缩信封、PV1 长度和 CRC 保护。

### 9.8 `STATUS`

方向：Pico → Monitor

用于返回升级确认、进度和错误文本，例如：

```text
ACK:UPGRADE:BEGIN:<version>
ACK:UPGRADE:DATA:<sequence>
PROGRESS:UPGRADE:INSTALL:<percent>
ACK:UPGRADE:COMPLETE:<version>
ERR:UPGRADE:<reason>
```

## 10. JSONZ 压缩规范

### 10.1 JSON 预处理

Monitor 必须：

- 使用 UTF-8 编码；
- 使用紧凑分隔符 `,` 和 `:`；
- 当前实现将非 ASCII 字符转义为 `\uXXXX`；
- 当 `physical_disks` 存在时，不在线路上重复发送顶层 `disks`；
- 不修改采集器持有的原始快照对象。

### 10.2 zlib 参数

| 参数 | 值 |
|---|---|
| 容器格式 | zlib |
| DEFLATE 压缩级别 | 6 |
| 窗口位数 | 9 |
| 窗口大小 | 512 字节 |
| 字典 | 无 |

不得使用 zlib 默认的 15 位、32 KiB 窗口。RP2040 的 MicroPython 堆可能因碎片化无法提供连续 32768 字节，导致 `MemoryError`。

Monitor 使用等价于以下过程的压缩：

```python
compressor = zlib.compressobj(level=6, wbits=9)
compressed = compressor.compress(json_bytes) + compressor.flush()
```

### 10.3 Base64

zlib 结果是任意二进制，可能包含 LF。由于 PV1 使用 LF 作为物理边界，压缩结果必须再做标准 Base64 编码。

不得把原始 zlib 二进制直接放入当前 PV1 行帧，否则压缩数据中的 `0x0A` 会被误判为帧结束。

### 10.4 Pico 解压

Pico 的解码顺序为：

1. 校验 PV1 CRC；
2. Base64 解码；
3. 使用 zlib 容器和 9 位窗口解压；
4. 检查解压后大小不超过 16 KiB；
5. UTF-8 解码；
6. JSON 解析；
7. 更新最新快照缓存；
8. 返回 `ACK/JSON`。

MicroPython 1.27 固件不保证提供 `zlib` 或 `uzlib` 模块。当前实现优先使用 `zlib.decompress(data, 15)`；不存在 `zlib` 时，使用：

```python
deflate.DeflateIO(io.BytesIO(data), deflate.ZLIB, 9)
```

### 10.5 内存约束

- zlib 窗口固定为 512 字节。
- Base64 解码会产生一份压缩数据。
- 解压会产生一份 JSON 字节串。
- JSON 解析会产生字典、列表和字符串对象。
- `MemoryError` 必须被捕获并转换为 `ERR/BAD_JSON`，不得让协议主循环进入 FATAL 状态。
- 当前实现解压后检查 16 KiB 上限。安全等级更高的实现应采用有输出上限的流式解压，在分配完整输出前阻止解压炸弹。

## 11. 典型交互

### 11.1 握手

```text
Monitor → Pico: PING(empty)
Pico → Monitor: PONG(device JSON)
```

### 11.2 快照

```text
Monitor → Pico: JSONZ(Base64(zlib(JSON)))
Pico → Monitor: EVENT(PROTOCOL_TIMING...)
Pico → Monitor: ACK(JSON)
```

处理失败时：

```text
Monitor → Pico: JSONZ(...)
Pico → Monitor: ERR(BAD_FRAME_CRC | BAD_JSON | ...)
```

### 11.3 升级

```text
Monitor → Pico: UPGRADE(BEGIN...)
Pico → Monitor: STATUS(ACK:UPGRADE:BEGIN...)
Monitor → Pico: UPGRADE(FILE...)
Pico → Monitor: STATUS(ACK:UPGRADE:FILE...)
Monitor → Pico: UPGRADE(DATA...)
Pico → Monitor: STATUS(ACK:UPGRADE:DATA...)
Monitor → Pico: UPGRADE(FILE_END)
Pico → Monitor: STATUS(ACK:UPGRADE:FILE_END...)
Monitor → Pico: UPGRADE(COMMIT)
Pico → Monitor: STATUS(PROGRESS...)
Pico → Monitor: STATUS(ACK:UPGRADE:COMPLETE...)
```

## 12. 性能诊断

Monitor 记录：

- 构帧耗时；
- 每次 pySerial 写入的请求字节数、实际字节数和阻塞耗时；
- write 合计和最慢 write；
- flush 耗时；
- ACK 等待耗时；
- 构帧到 ACK 的总耗时。

Pico 在处理 `JSONZ` 后发送 `PROTOCOL_TIMING` 事件：

```text
PROTOCOL_TIMING:
TYPE=JSONZ:
BYTES=<PV1 line bytes>:
JSON_BYTES=<decompressed bytes>:
READS=<read calls>:
RX=<receive ms>MS:
FRAME_PARSE=<header+CRC ms>MS:
DECOMPRESS=<base64+zlib ms>MS:
JSON=<json parse ms>MS
```

诊断事件在 `ACK/JSON` 之前发送，因此 Monitor 可以在本次交互日志中看到完整分段耗时。

## 13. 错误恢复要求

- 坏头、坏长度、坏尾部或坏 CRC：不得处理载荷，返回对应 `ERR`。
- 未知类型：返回 `ERR/UNKNOWN_TYPE`。
- JSONZ 解码、解压、UTF-8 或 JSON 失败：返回 `ERR/BAD_JSON`。
- 解压内存不足：捕获 `MemoryError`，返回 `ERR/BAD_JSON`，保持主循环运行。
- 半包超时：清空缓存并返回 `ERR/FRAME_TIMEOUT`。
- 缓存超限：清空缓存并返回 `ERR/FRAME_TOO_LARGE`。
- 收到非 PV1 垃圾：逐字节扫描并丢弃，直到重新发现 `PV1:`。
- Monitor 收到 `EVENT` 时不得误认为请求完成。
- Monitor 只接受与当前请求匹配的确认类型。

## 14. 实现一致性检查

实现至少应覆盖以下测试：

1. 标准 CRC 向量 `123456789 → 29B1`。
2. 主机与 Pico 对随机载荷计算相同 CRC。
3. 帧载荷包含冒号时仍能正确解析。
4. 长度不足、超长、坏十六进制和非空格尾部被拒绝。
5. 单字节、跨块和多帧连续输入。
6. 魔数前存在 `AT` 等无换行垃圾时能重新同步。
7. 普通短垃圾不会触发 64 字节阻塞读取。
8. 半包空闲 1000ms 后被丢弃。
9. JSONZ 中 zlib 数据包含 LF 时，Base64 后仍能完整传输。
10. zlib 头声明 9 位窗口，即 512 字节。
11. 解压后 JSON 超过 16 KiB 被拒绝。
12. 解压 `MemoryError` 不终止固件主循环。
13. `EVENT` 不会被当作 `ACK`。
14. 升级序号、文件长度和 SHA-256 验证失败时不会提交安装。

## 15. 版本演进

- `PV1` 是完整主版本魔数，而不是独立的版本字段。
- 不兼容的帧格式变更必须使用新魔数，例如 `PV2`。
- 在 PV1 内新增消息类型属于兼容扩展；旧接收方会返回 `UNKNOWN_TYPE`。
- 改变 CRC 参数、字段顺序、长度含义、填充规则或 JSONZ 编码流水线属于不兼容变更。
- 当前项目明确不兼容 PV1 之前的裸文本协议。

## 16. 安全说明

- CRC 不是 MAC，不能验证发送方身份。
- USB 串口被本机不可信进程访问时，应使用操作系统权限和独占锁保护。
- Linux 建议通过 udev 设置设备权限并禁止 ModemManager 探测。
- 升级包除 PV1 CRC 外，还必须继续验证清单中的文件长度和 SHA-256。
- 路径必须拒绝绝对路径、空路径、隐藏暂存路径和 `..` 路径穿越。
- 任何实现都不得在 CRC 校验前执行升级命令或解析 JSON。
