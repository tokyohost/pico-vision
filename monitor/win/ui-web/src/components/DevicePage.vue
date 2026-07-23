<script setup>
import { computed, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'

const props = defineProps({
  device: { type: Object, required: true },
  settings: { type: Object, required: true },
})

const probe = reactive({ loading: false, log: '', detail: {} })

const statusText = computed(() => {
  if (props.device.connected === true) return '设备在线'
  if (props.device.connected === false) return '连接异常'
  return '正在等待设备'
})

const statusType = computed(() => {
  if (props.device.connected === true) return 'success'
  if (props.device.connected === false) return 'danger'
  return 'warning'
})

/**
 * 执行一次独立设备探测。
 */
async function probeDevice() {
  probe.loading = true
  probe.log = ''
  try {
    const result = await invoke('device.probe', { websocketUrl: props.settings.websocket_url })
    probe.detail = result.device || {}
    probe.log = result.log || ''
    ElMessage.success('设备探测完成')
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    probe.loading = false
  }
}

/**
 * 请求设备截图。
 */
async function takeScreenshot() {
  try {
    await invoke('device.screenshot')
    ElMessage.success('截图请求已发送')
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 请求设备安全重启。
 */
async function rebootDevice() {
  try {
    await ElMessageBox.confirm('确定立即重启当前设备吗？', '重启设备', { type: 'warning' })
    await invoke('device.reboot')
    ElMessage.success('设备重启命令已发送')
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error?.message || String(error))
  }
}
</script>

<template>
  <div class="hero-card">
    <div>
      <el-tag :type="statusType" effect="dark">{{ statusText }}</el-tag>
      <h2>{{ device.board_model || probe.detail.board_model || 'OmniWatch 设备' }}</h2>
      <p>{{ device.address || probe.detail.wifi_address || '等待连接信息' }}</p>
    </div>
    <div class="hero-actions">
      <el-button :loading="probe.loading" type="primary" @click="probeDevice">主动探测</el-button>
      <el-button @click="takeScreenshot">屏幕截图</el-button>
      <el-button type="danger" plain @click="rebootDevice">重启设备</el-button>
    </div>
  </div>
  <el-card shadow="never" class="section-gap">
    <template #header><span>设备详情</span></template>
    <el-descriptions :column="2" border>
      <el-descriptions-item label="开发板">{{ device.board_model || probe.detail.board_model || '--' }}</el-descriptions-item>
      <el-descriptions-item label="连接方式">{{ device.transport || probe.detail.transport || '--' }}</el-descriptions-item>
      <el-descriptions-item label="LCD">{{ device.lcd_device_type || probe.detail.lcd_device_type || '--' }}</el-descriptions-item>
      <el-descriptions-item label="分辨率">{{ device.screen_resolution || probe.detail.screen_resolution || '--' }}</el-descriptions-item>
      <el-descriptions-item label="固件版本">{{ device.firmware_version || probe.detail.firmware_version || '--' }}</el-descriptions-item>
      <el-descriptions-item label="SDK 版本">{{ device.sdk_version || probe.detail.sdk_version || '--' }}</el-descriptions-item>
    </el-descriptions>
  </el-card>
  <pre v-if="probe.log" class="terminal">{{ probe.log }}</pre>
</template>
