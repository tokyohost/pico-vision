"""编译 SDK 的实际控制回调和 C 组帧函数，检查控制线重配置是否产生半帧超时。"""

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_cdc_line_state import extract_function


WORKSPACE = Path(__file__).resolve().parents[3]
CDC_SOURCE = WORKSPACE / "micropython/shared/tinyusb/mp_usbd_cdc.c"
FRAME_SOURCE = WORKSPACE / "micropython/ports/esp32/usermod/fn_usb_cdc/mod_usb_cdc_data.c"


def build_test_frame():
    """调用主机实际构帧函数生成包含合法长度、CRC 和物理填充的二进制帧。"""
    spec = importlib.util.spec_from_file_location(
        "host_frame_for_cdc_test", WORKSPACE / "pico-project/monitor/pico_protocol.py",
    )
    protocol = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(protocol)
    return protocol.build_frame("JSONB", bytes(range(256)) * 16)


def run_frame_timeout_harness(callback_source):
    """编译真实组帧器及指定控制回调，返回三个完整帧中出现超时的数量。"""
    compiler = shutil.which("cl") or shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        raise unittest.SkipTest("没有可运行 C 组帧回归测试的编译器")
    source = FRAME_SOURCE.read_text(encoding="utf-8")
    definitions = source[source.index("#define USB_CDC_FRAME_QUEUE_DEPTH"):source.index("// 优先从 PSRAM")]
    harness = r'''
typedef unsigned char uint8_t;
#ifdef _WIN64
typedef unsigned long long size_t;
#else
typedef unsigned long size_t;
#endif
typedef unsigned long TickType_t;
typedef int bool;
typedef int TaskHandle_t;
typedef int StaticSemaphore_t;
typedef int SemaphoreHandle_t;
#define false 0
#define true 1
#define ESP_TASK_PRIO_MIN 0
#define pdMS_TO_TICKS(value) (value)
#define MICROPY_HW_USB_CDC 1
#define MICROPY_HW_USB_CDC_DATA 1
#define MICROPY_EXCLUDE_SHARED_TINYUSB_USBD_CDC 0
#define MICROPY_HW_USB_CDC_DTR_RTS_BOOTLOADER 0
#define MICROPY_HW_USB_CDC_1200BPS_TOUCH 0
#define MICROPY_WRAP_TUD_CDC_LINE_STATE_CB(name) name
#define MP_USBD_CDC_DATA_ITF 1
#define TUD_OPT_RHPORT 0
#define USBD_CDC_EP_IN 0x83
#define USBD_CDC_DATA_EP_CMD 0x84
#define USBD_CDC_DATA_EP_OUT 0x02
#define USBD_CDC_DATA_EP_IN 0x82
#define TUSB_SPEED_HIGH 2
#define CDC_DATA_RX_LOCK()
#define CDC_DATA_RX_UNLOCK()
static TickType_t test_tick;
static bool cdc_data_dtr;
static int cdc_connected_flush_delay;
static int cdc_itf_pending;
static struct { size_t length; uint8_t bytes[512]; } cdc_data_rx_ringbuf;
// 最小缓冲及端点桩只模拟外设，控制会话和组帧逻辑均提取 SDK 源码。
static void *memcpy(void *destination, const void *source, size_t size) {
    uint8_t *out = destination; const uint8_t *in = source;
    for (size_t index = 0; index < size; ++index) out[index] = in[index];
    return destination;
}
static int memcmp(const void *left, const void *right, size_t size) {
    const uint8_t *a = left; const uint8_t *b = right;
    for (size_t index = 0; index < size; ++index) if (a[index] != b[index]) return a[index] - b[index];
    return 0;
}
static TickType_t xTaskGetTickCount(void) { return test_tick; }
static bool mp_usbd_cdc_data_rx_ready(void) { return true; }
static void ringbuf_reset(void *buffer) { cdc_data_rx_ringbuf.length = 0; }
static bool tusb_inited(void) { return true; }
static void tud_cdc_n_write_clear(int itf) {}
static int usbd_edpt_stalled(int port, int endpoint) { return 0; }
static void usbd_edpt_clear_stall(int port, int endpoint) {}
static int tud_speed_get(void) { return 0; }
static void tud_sof_cb_enable(bool enabled) {}
'''
    harness += definitions
    for signature in (
        "static void usb_cdc_frame_reset_locked(void)",
        "static bool usb_cdc_parse_payload_length(",
        "static void usb_cdc_parse_header_locked(void)",
        "static bool usb_cdc_enqueue_frame_locked(void)",
        "static void usb_cdc_feed_byte_locked(uint8_t value)",
        "static void usb_cdc_expire_partial_frame_locked(void)",
    ):
        harness += "\n" + extract_function(source, signature)
    harness += "\n" + extract_function(callback_source, "static void mp_usbd_cdc_data_reset_session(void)")
    harness += "\n" + extract_function(callback_source, "void MICROPY_WRAP_TUD_CDC_LINE_STATE_CB(tud_cdc_line_state_cb)")
    # 控制回调与 C 组帧器在 CRC 校验之前处理字节，这里仍使用主机生成的合法 PV1 帧。
    packet = build_test_frame()
    harness += "\nstatic const uint8_t packet[] = {" + ",".join(map(str, packet)) + "};\n"
    harness += r'''
static uint8_t work[USB_CDC_FRAME_WORK_SIZE];
static uint8_t queue[USB_CDC_FRAME_QUEUE_DEPTH * USB_CDC_FRAME_WORK_SIZE];
// 每个测试独立初始化接收状态，模拟队列中尚未被 C 接收任务消费的 512 字节。
static void initialize_case(void) {
    usb_cdc_frame_work_buffer = work;
    usb_cdc_frame_queue_storage = queue;
    usb_cdc_frame_queue_head = usb_cdc_frame_queue_tail = usb_cdc_frame_queue_count = 0;
    usb_cdc_frame_timeout_pending = false;
    cdc_data_rx_ringbuf.length = 0;
    test_tick = 100;
    usb_cdc_frame_reset_locked();
}
int main(void) {
    int timeouts = 0;
    cdc_data_dtr = false;
    tud_cdc_line_state_cb(1, true, true);
    // 相同 DTR/RTS、仅 RTS 切换和再次重复控制请求均属于同一打开会话。
    for (int scenario = 0; scenario < 3; ++scenario) {
        initialize_case();
        for (size_t index = 0; index < 64; ++index) usb_cdc_feed_byte_locked(packet[index]);
        memcpy(cdc_data_rx_ringbuf.bytes, packet + 64, 512);
        cdc_data_rx_ringbuf.length = 512;
        tud_cdc_line_state_cb(1, true, scenario != 1);
        for (size_t index = 0; index < cdc_data_rx_ringbuf.length; ++index) {
            usb_cdc_feed_byte_locked(cdc_data_rx_ringbuf.bytes[index]);
        }
        for (size_t index = 576; index < sizeof(packet); ++index) usb_cdc_feed_byte_locked(packet[index]);
        test_tick += 1500;
        usb_cdc_expire_partial_frame_locked();
        if (usb_cdc_frame_timeout_pending) ++timeouts;
        else if (usb_cdc_frame_queue_count != 1) return 10;
    }
    // 真正停止发送的半帧仍需报超时，不能通过禁用超时掩盖数据丢失。
    initialize_case();
    for (size_t index = 0; index < 64; ++index) usb_cdc_feed_byte_locked(packet[index]);
    test_tick += 1500;
    usb_cdc_expire_partial_frame_locked();
    if (!usb_cdc_frame_timeout_pending || usb_cdc_frame_queue_count != 0) return 11;
    return timeouts;
}
'''
    with tempfile.TemporaryDirectory(prefix="cdc-frame-test-", dir=WORKSPACE) as temporary:
        directory = Path(temporary)
        source_path = directory / "cdc_frame_test.c"
        executable = directory / "cdc_frame_test.exe"
        source_path.write_text(harness, encoding="utf-8")
        if Path(compiler).name.lower() in ("cl", "cl.exe"):
            command = [compiler, "/nologo", "/TC", "/Od", "/GS-", "/Oi-", "/utf-8",
                       str(source_path), "/Fo" + str(directory / "cdc_frame_test.obj"),
                       "/Fe" + str(executable), "/link", "/ENTRY:main", "/SUBSYSTEM:CONSOLE", "/NODEFAULTLIB"]
        else:
            command = [compiler, "-fno-builtin", str(source_path), "-o", str(executable)]
        compiled = subprocess.run(command, cwd=directory, capture_output=True)
        if compiled.returncode:
            raise RuntimeError((compiled.stdout + compiled.stderr).decode("utf-8", errors="replace"))
        return subprocess.run([str(executable)], cwd=directory, capture_output=True).returncode


class CdcFrameTimeoutTest(unittest.TestCase):
    """检查实际 SDK 控制回调在完整帧和真正缺字节的半帧中的行为。"""

    def test_repeated_control_requests_do_not_cause_frame_timeout(self):
        """同一会话的控制请求保留三个完整帧，真正缺尾帧继续触发超时。"""
        self.assertEqual(0, run_frame_timeout_harness(CDC_SOURCE.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
