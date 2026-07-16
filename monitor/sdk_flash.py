"""校验 ESP32-S3 SDK 镜像并通过 esptool 执行受控 USB 刷写。"""

import argparse
import hashlib
import json
import re
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from serial.tools import list_ports


ESP32_IMAGE_MAGIC = 0xE9
ESP32_S3_IMAGE_CHIP_ID = 9
ESP32_S3_PARTITION_TABLE_OFFSET = 0x8000
ESP32_S3_APPLICATION_OFFSET = 0x10000
ESPRESSIF_USB_VENDOR_ID = 0x303A
PARTITION_ENTRY_MAGIC = 0x50AA
PARTITION_ENTRY_SIZE = 32
MAXIMUM_SDK_IMAGE_SIZE = 8 * 1024 * 1024
SDK_VERSION_PATTERN = re.compile(
    rb"MPY version\s*:\s*(v[^\x00\r\n]{1,80}?)\s+on\s+\d{4}-\d{2}-\d{2}"
)


@dataclass(frozen=True)
class SdkPartition:
    """保存 SDK 合并镜像中的一个 ESP32 分区表项。"""

    partition_type: int
    subtype: int
    offset: int
    size: int
    label: str


@dataclass(frozen=True)
class SdkImageInformation:
    """保存通过全部安全校验的 SDK 镜像摘要。"""

    path: Path
    size: int
    sha256: str
    sdk_version: str
    partitions: tuple


def _image_chip_id(content, offset):
    """读取 ESP32 扩展镜像头中的目标芯片编号。"""
    if offset < 0 or offset + 14 > len(content):
        raise ValueError("SDK 镜像头不完整")
    if content[offset] != ESP32_IMAGE_MAGIC:
        raise ValueError("SDK 镜像缺少 ESP32 镜像头")
    return struct.unpack_from("<H", content, offset + 12)[0]


def _parse_partition_table(content):
    """解析合并镜像中的 ESP32 分区表并返回有效表项。"""
    partitions = []
    offset = ESP32_S3_PARTITION_TABLE_OFFSET
    table_end = min(len(content), offset + 0x1000)
    while offset + PARTITION_ENTRY_SIZE <= table_end:
        entry = content[offset:offset + PARTITION_ENTRY_SIZE]
        magic = struct.unpack_from("<H", entry, 0)[0]
        if magic != PARTITION_ENTRY_MAGIC:
            break
        partition_type, subtype, partition_offset, size, label, _flags = struct.unpack(
            "<BBII16sI", entry[2:]
        )
        partitions.append(SdkPartition(
            partition_type=partition_type,
            subtype=subtype,
            offset=partition_offset,
            size=size,
            label=label.split(b"\0", 1)[0].decode("ascii", errors="replace"),
        ))
        offset += PARTITION_ENTRY_SIZE
    if not partitions:
        raise ValueError("SDK 镜像在 0x8000 处缺少有效分区表")
    return tuple(partitions)


def _extract_sdk_version(content):
    """从定制 MicroPython 镜像中提取 SDK 发布版本。"""
    matched = SDK_VERSION_PATTERN.search(content)
    if matched is None:
        return "未知"
    return matched.group(1).decode("ascii", errors="replace").strip()


def inspect_sdk_image(path):
    """校验一个 ESP32-S3 完整合并 bin，并返回可供确认的镜像信息。"""
    image_path = Path(path).expanduser().resolve()
    if image_path.suffix.lower() != ".bin":
        raise ValueError("只能选择 ESP32-S3 SDK .bin 文件")
    try:
        content = image_path.read_bytes()
    except OSError as error:
        raise ValueError("无法读取 SDK 镜像：{}".format(error)) from error
    if len(content) < ESP32_S3_APPLICATION_OFFSET + 24:
        raise ValueError("SDK 镜像过小，不是完整的 ESP32-S3 合并镜像")
    if len(content) > MAXIMUM_SDK_IMAGE_SIZE:
        raise ValueError("SDK 镜像超过当前设备支持的 8 MiB Flash")
    if _image_chip_id(content, 0) != ESP32_S3_IMAGE_CHIP_ID:
        raise ValueError("SDK 镜像目标芯片不是 ESP32-S3")

    partitions = _parse_partition_table(content)
    factory = next((
        item for item in partitions
        if item.partition_type == 0 and item.subtype == 0 and item.label == "factory"
    ), None)
    if factory is None:
        raise ValueError("SDK 镜像缺少 factory 应用分区")
    if factory.offset != ESP32_S3_APPLICATION_OFFSET:
        raise ValueError("SDK 镜像 factory 应用偏移不是 0x10000")
    if factory.size <= 0 or factory.offset + factory.size > MAXIMUM_SDK_IMAGE_SIZE:
        raise ValueError("SDK 镜像 factory 分区超出 8 MiB Flash 范围")
    if _image_chip_id(content, factory.offset) != ESP32_S3_IMAGE_CHIP_ID:
        raise ValueError("SDK 镜像中的 factory 应用不是 ESP32-S3 程序")
    if len(content) > factory.offset + factory.size:
        raise ValueError("SDK 镜像内容超出 factory 分区末端")

    return SdkImageInformation(
        path=image_path,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest().upper(),
        sdk_version=_extract_sdk_version(content),
        partitions=partitions,
    )


def serial_port_signature(port):
    """返回用于比较 Windows 串口重新枚举结果的稳定特征。"""
    return (
        str(getattr(port, "device", "") or "").upper(),
        getattr(port, "vid", None),
        getattr(port, "pid", None),
        str(getattr(port, "serial_number", "") or ""),
        str(getattr(port, "location", "") or ""),
        str(getattr(port, "description", "") or ""),
        str(getattr(port, "product", "") or ""),
        str(getattr(port, "interface", "") or ""),
    )


def is_espressif_usb_port(device, ports=None):
    """判断指定串口是否由 Espressif 原生 USB 接口枚举。"""
    target = str(device or "").strip().upper()
    if not target:
        return False
    candidates = list_ports.comports() if ports is None else ports
    return any(
        str(getattr(port, "device", "") or "").upper() == target
        and getattr(port, "vid", None) == ESPRESSIF_USB_VENDOR_ID
        for port in candidates
    )


def select_esp32s3_bootloader_port(ports, source_port=None, previous_signatures=()):
    """仅在目标可被唯一识别时返回 ESP32-S3 ROM 下载端口。"""
    source_location = str(getattr(source_port, "location", "") or "")
    source_serial = str(getattr(source_port, "serial_number", "") or "")
    previous = set(previous_signatures)
    candidates = [
        port for port in ports
        if getattr(port, "vid", None) == ESPRESSIF_USB_VENDOR_ID
        and serial_port_signature(port) not in previous
    ]
    if not candidates:
        return None

    if source_location:
        location_matches = [
            port for port in candidates
            if str(getattr(port, "location", "") or "") == source_location
        ]
        if len(location_matches) == 1:
            return location_matches[0]
        if len(location_matches) > 1:
            candidates = location_matches

    if source_serial:
        serial_matches = [
            port for port in candidates
            if str(getattr(port, "serial_number", "") or "") == source_serial
        ]
        if len(serial_matches) == 1:
            return serial_matches[0]
        if len(serial_matches) > 1:
            return None

    return candidates[0] if len(candidates) == 1 else None


def wait_for_esp32s3_bootloader_port(
    source_device,
    previous_ports,
    timeout=15.0,
    poll_interval=0.2,
    port_provider=None,
):
    """等待目标 ESP32-S3 重新枚举为 Espressif ROM USB 串口。"""
    provider = port_provider or list_ports.comports
    previous_ports = tuple(previous_ports)
    source_port = next((
        item for item in previous_ports
        if str(getattr(item, "device", "")).upper() == str(source_device).upper()
    ), None)
    previous_signatures = tuple(serial_port_signature(item) for item in previous_ports)
    deadline = time.monotonic() + max(0.1, float(timeout))
    # 给设备留出退出 TinyUSB 应用 CDC 并完成 Windows PnP 重枚举的时间。
    time.sleep(min(0.5, max(0.0, float(poll_interval))))
    while time.monotonic() < deadline:
        selected = select_esp32s3_bootloader_port(
            provider(), source_port, previous_signatures
        )
        if selected is not None:
            return str(selected.device)
        time.sleep(max(0.05, float(poll_interval)))
    raise RuntimeError("设备未在 15 秒内重新枚举为 ESP32-S3 ROM USB 端口")


def run_esptool_flash(port, image_path, baud=460800):
    """再次校验镜像后调用 esptool 写入 ESP32-S3 的 0x0 地址。"""
    information = inspect_sdk_image(image_path)
    print(
        "SDK_FLASH_META:" + json.dumps({
            "port": str(port),
            "path": str(information.path),
            "size": information.size,
            "sha256": information.sha256,
            "sdk_version": information.sdk_version,
        }, ensure_ascii=False, separators=(",", ":")),
        flush=True,
    )
    import esptool

    esptool.main([
        "--chip", "esp32s3",
        "--port", str(port),
        "--baud", str(int(baud)),
        "--before", "no-reset",
        "--after", "watchdog-reset",
        "write-flash", "0x0", str(information.path),
    ])
    print("SDK_FLASH_COMPLETE", flush=True)
    return 0


def run_sdk_flasher_cli(arguments=None):
    """解析隐藏刷写子进程参数并返回适合主程序传播的退出码。"""
    parser = argparse.ArgumentParser(description="ESP32-S3 USB SDK 受控刷写器")
    parser.add_argument("--port", required=True, help="ROM 下载模式串口")
    parser.add_argument("--image", required=True, help="完整 ESP32-S3 合并 bin")
    parser.add_argument("--baud", type=int, default=460800, help="刷写波特率")
    parsed = parser.parse_args(arguments)
    try:
        return run_esptool_flash(parsed.port, parsed.image, parsed.baud)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 1
        print("SDK_FLASH_ERROR:esptool 参数或运行环境错误", flush=True)
        return code or 1
    except (OSError, RuntimeError, ValueError) as error:
        print("SDK_FLASH_ERROR:{}".format(error), flush=True)
        return 1
