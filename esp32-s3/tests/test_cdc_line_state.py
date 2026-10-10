"""编译实际 SDK 控制回调，验证重复 DTR、RTS 切换与 USB 重连的会话边界。"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
CDC_SOURCE = WORKSPACE_ROOT / "micropython/shared/tinyusb/mp_usbd_cdc.c"


def extract_function(source, signature):
    """按花括号边界提取真实 C 函数，使回归测试执行 SDK 原实现。"""
    start = source.index(signature)
    body_start = source.index("{", start)
    depth = 1
    end = body_start + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class CdcLineStateTest(unittest.TestCase):
    """以最小 TinyUSB 桩运行 SDK 回调，验证缓存不会被重复控制请求清空。"""

    def test_repeated_control_requests_preserve_pending_bytes(self):
        """相同 DTR 和仅 RTS 变化保留半帧与 ACK，真实重开和重新枚举清理会话。"""
        compiler = shutil.which("cl") or shutil.which("cc") or shutil.which("gcc")
        if compiler is None:
            self.skipTest("本机没有可运行 C 回调回归测试的编译器")
        source = CDC_SOURCE.read_text(encoding="utf-8")
        callback = extract_function(
            source,
            "void MICROPY_WRAP_TUD_CDC_LINE_STATE_CB(tud_cdc_line_state_cb)",
        )
        mount = extract_function(source, "void tud_mount_cb(void)")
        unmount = extract_function(source, "void tud_umount_cb(void)")
        harness = r'''
typedef unsigned char uint8_t;
typedef int bool;
#define false 0
#define true 1
#define MICROPY_HW_USB_CDC 1
#define MICROPY_HW_USB_CDC_DATA 1
#define MICROPY_EXCLUDE_SHARED_TINYUSB_USBD_CDC 0
#define MICROPY_HW_USB_CDC_DTR_RTS_BOOTLOADER 0
#define MICROPY_HW_USB_CDC_1200BPS_TOUCH 0
#define MICROPY_WRAP_TUD_CDC_LINE_STATE_CB(name) name
#define MP_USBD_CDC_DATA_ITF 1
#define TUD_OPT_RHPORT 0
#define USBD_CDC_EP_IN 0x83
#define TUSB_SPEED_HIGH 2
static bool cdc_data_dtr;
static int cdc_connected_flush_delay;
static int resets, tx_clears, rx_bytes, tx_bytes;
// 模拟会话清理的实际效果，保留重复回调前后的待接收与待发送字节数。
static void mp_usbd_cdc_data_reset_session(void) {
    ++resets;
    rx_bytes = tx_bytes = 0;
}
// 控制台端点桩用于验证数据接口的控制请求不会改变其他接口。
static int usbd_edpt_stalled(int port, int endpoint) { return 0; }
static void usbd_edpt_clear_stall(int port, int endpoint) {}
static int tud_speed_get(void) { return 0; }
static void tud_sof_cb_enable(int enabled) {}
static void tud_cdc_n_write_clear(int itf) { ++tx_clears; tx_bytes = 0; }
'''
        harness += mount + "\n" + unmount + "\n" + callback + r'''
// 顺序覆盖首次打开、重复配置、RTS 变化、关闭、重开及总线重新枚举。
int main(void) {
    tud_mount_cb();
    tud_cdc_line_state_cb(1, true, true);
    if (resets != 1) return 1;
    rx_bytes = 511; tx_bytes = 64;
    tud_cdc_line_state_cb(1, true, true);
    tud_cdc_line_state_cb(1, true, false);
    if (resets != 1 || rx_bytes != 511 || tx_bytes != 64) return 2;
    tud_cdc_line_state_cb(0, true, false);
    if (resets != 1 || rx_bytes != 511 || tx_bytes != 64) return 3;
    tud_cdc_line_state_cb(1, false, false);
    if (resets != 2 || rx_bytes != 0 || tx_bytes != 0) return 4;
    tud_cdc_line_state_cb(1, false, true);
    if (resets != 2 || tx_clears != 1) return 5;
    tud_cdc_line_state_cb(1, true, true);
    if (resets != 3) return 6;
    tud_umount_cb();
    tud_cdc_line_state_cb(1, true, true);
    if (resets != 4) return 7;
    tud_mount_cb();
    tud_cdc_line_state_cb(1, true, true);
    if (resets != 5) return 8;
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="cdc-callback-test-", dir=WORKSPACE_ROOT) as temporary:
            directory = Path(temporary)
            source_path = directory / "cdc_callback_test.c"
            executable = directory / "cdc_callback_test.exe"
            source_path.write_text(harness, encoding="utf-8")
            if Path(compiler).name.lower() in ("cl", "cl.exe"):
                command = [
                    compiler, "/nologo", "/TC", "/Od", "/GS-", "/utf-8",
                    str(source_path), "/Fo" + str(directory / "cdc_callback_test.obj"),
                    "/Fe" + str(executable), "/link", "/ENTRY:main", "/SUBSYSTEM:CONSOLE", "/NODEFAULTLIB",
                ]
            else:
                command = [compiler, str(source_path), "-o", str(executable)]
            compiled = subprocess.run(command, cwd=directory, capture_output=True)
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            executed = subprocess.run([str(executable)], cwd=directory, capture_output=True)
            self.assertEqual(0, executed.returncode, "CDC 会话边界验证失败，阶段=" + str(executed.returncode))


if __name__ == "__main__":
    unittest.main()
