"""计算 ESP32-S3 独立 CDC 的收发缓冲区容量。"""


USB_FULL_SPEED_PACKET_SIZE = 64
DEFAULT_RX_BURST_FRAMES = 2


def align_endpoint_size(size, endpoint_size=USB_FULL_SPEED_PACKET_SIZE):
    """把缓冲区容量向上对齐到 USB 全速端点包长。"""
    size = max(endpoint_size, int(size))
    return ((size + endpoint_size - 1) // endpoint_size) * endpoint_size


def normalize_rx_buffer_size(
    requested_size,
    maximum_frame_size,
    burst_frames=DEFAULT_RX_BURST_FRAMES,
):
    """确保接收缓冲至少能容纳指定数量的最大协议帧。"""
    required_size = int(maximum_frame_size) * max(1, int(burst_frames))
    return align_endpoint_size(max(int(requested_size), required_size))
