<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'

const props = defineProps({
  device: { type: Object, required: true },
  settings: { type: Object, required: true },
  saving: { type: Boolean, required: true },
})
const emit = defineEmits(['save'])

const probe = reactive({ loading: false, log: '', detail: {} })
const liveDevice = reactive({})
const sdk = reactive({
  busy: false,
  status: 'idle',
  message: '',
  image: null,
  logs: '',
  ports: [],
  selectedPort: '',
})
const sdkLogView = ref(null)
const deviceLogView = ref(null)
const deviceLogs = ref('')
let refreshTimer = null

const currentDevice = computed(() => ({
  ...probe.detail,
  ...props.device,
  ...liveDevice,
}))

const statusText = computed(() => {
  if (currentDevice.value.connected === true) return '设备在线'
  if (currentDevice.value.connected === false) return '连接异常'
  return '正在等待设备'
})

const statusType = computed(() => {
  if (currentDevice.value.connected === true) return 'success'
  if (currentDevice.value.connected === false) return 'danger'
  return 'warning'
})

const controlledFlashSupported = computed(() => {
  const device = currentDevice.value
  const board = String(device.board_model || '').toLowerCase().replaceAll('_', '-')
  const transport = String(device.transport || '').toLowerCase()
  return Boolean(
    device.connected
    && board.includes('esp32-s3')
    && (transport.includes('串口') || ['serial', 'usb', 'usb cdc'].includes(transport))
    && device.sdk_update_supported,
  )
})

/**
 * 执行一次独立设备探测。
 */
async function probeDevice() {
  probe.loading = true
  probe.log = ''
  try {
    const result = await invoke('device.probe', {
      websocketUrl: props.settings.force_usb_cdc ? '' : props.settings.websocket_url,
    })
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
 * 保存连接策略，并让后台立即按新的传输方式重新连接。
 */
function saveConnectionPolicy() {
  emit('save')
}

/**
 * 刷新设备连接和 SDK 后台任务状态。
 */
async function refreshRuntimeState(showError = false) {
  try {
    const shouldFollowDeviceLog = !deviceLogView.value
      || deviceLogView.value.scrollHeight - deviceLogView.value.scrollTop - deviceLogView.value.clientHeight < 32
    const [deviceResult, sdkResult, logResult] = await Promise.all([
      invoke('device.status'),
      invoke('device.sdk.status'),
      invoke('log.read', { maximum: 160000 }),
    ])
    Object.keys(liveDevice).forEach((key) => delete liveDevice[key])
    Object.assign(liveDevice, deviceResult || {})
    Object.assign(sdk, sdkResult || {})
    deviceLogs.value = logResult?.content || ''
    await nextTick()
    if (sdkLogView.value && sdk.busy) {
      sdkLogView.value.scrollTop = sdkLogView.value.scrollHeight
    }
    if (deviceLogView.value && shouldFollowDeviceLog) {
      deviceLogView.value.scrollTop = deviceLogView.value.scrollHeight
    }
  } catch (error) {
    if (showError) ElMessage.error(error?.message || String(error))
  }
}

/**
 * 选择并校验待刷写的 ESP32-S3 SDK 镜像。
 */
async function selectSdkImage() {
  try {
    const result = await invoke('device.sdk.select')
    if (!result.cancelled) {
      sdk.image = result.image
      ElMessage.success('SDK 镜像校验通过')
    }
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 刷新强刷模式可选择的串口。
 */
async function loadSdkPorts() {
  try {
    const result = await invoke('device.sdk.ports')
    sdk.ports = result.ports || []
    if (!sdk.ports.some((item) => item.device === sdk.selectedPort)) {
      sdk.selectedPort = sdk.ports[0]?.device || ''
    }
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 展示镜像摘要并启动 SDK 更新任务。
 */
async function startSdkFlash(force = false) {
  if (!sdk.image) {
    ElMessage.warning('请先选择 SDK 镜像')
    return
  }
  if (force && !sdk.selectedPort) {
    ElMessage.warning('请先选择强刷目标 COM 口')
    return
  }
  const target = force ? `目标串口：${sdk.selectedPort}\n` : `当前 SDK：${currentDevice.value.sdk_version || '未知'}\n`
  try {
    await ElMessageBox.confirm(
      `${target}目标 SDK：${sdk.image.sdkVersion}\n`
      + `镜像大小：${(sdk.image.size / 1024 / 1024).toFixed(2)} MiB\n`
      + `SHA-256：${sdk.image.sha256}\n\n`
      + `${force ? '强刷会尝试控制所选串口进入下载模式。' : '设备将自动进入 ROM USB 下载模式。'}`
      + '\n刷写期间请勿断电、拔线或让电脑休眠。',
      force ? '确认强刷 SDK' : '确认刷写 USB SDK',
      { type: 'warning', confirmButtonText: '开始刷写', distinguishCancelAndClose: true },
    )
    const result = await invoke('device.sdk.flash', {
      force,
      port: force ? sdk.selectedPort : '',
    })
    Object.assign(sdk, result)
    ElMessage.success('SDK 更新任务已启动')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error?.message || String(error))
    }
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

onMounted(async () => {
  await Promise.all([refreshRuntimeState(true), loadSdkPorts()])
  refreshTimer = window.setInterval(refreshRuntimeState, 800)
})

onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="hero-card">
    <div>
      <el-tag :type="statusType" effect="dark">{{ statusText }}</el-tag>
      <h2>{{ currentDevice.board_model || 'OmniWatch 设备' }}</h2>
      <p>{{ currentDevice.address || currentDevice.wifi_address || '等待连接信息' }}</p>
    </div>
    <div class="hero-actions">
      <el-button :loading="probe.loading" type="primary" @click="probeDevice">主动探测</el-button>
      <el-button @click="takeScreenshot">屏幕截图</el-button>
      <el-button type="danger" plain @click="rebootDevice">重启设备</el-button>
    </div>
  </div>
  <el-card shadow="never" class="section-gap connection-policy-card">
    <div class="connection-policy-row">
      <div>
        <strong>强制切换 USB-CDC</strong>
        <p>开启后断开当前 WebSocket，不再主动搜索 Wi-Fi 设备，并持续优先探测 USB 串口。</p>
      </div>
      <el-switch
        v-model="settings.force_usb_cdc"
        :loading="saving"
        active-text="仅使用 USB-CDC"
        inactive-text="允许 Wi-Fi / USB"
        @change="saveConnectionPolicy"
      />
    </div>
  </el-card>
  <el-card shadow="never" class="section-gap">
    <template #header><span>设备详情</span></template>
    <el-descriptions :column="2" border>
      <el-descriptions-item label="开发板">{{ currentDevice.board_model || '--' }}</el-descriptions-item>
      <el-descriptions-item label="连接方式">{{ currentDevice.transport || '--' }}</el-descriptions-item>
      <el-descriptions-item label="LCD">{{ currentDevice.lcd_device_type || '--' }}</el-descriptions-item>
      <el-descriptions-item label="分辨率">{{ currentDevice.screen_resolution || '--' }}</el-descriptions-item>
      <el-descriptions-item label="固件版本">{{ currentDevice.firmware_version || '--' }}</el-descriptions-item>
      <el-descriptions-item label="SDK 版本">{{ currentDevice.sdk_version || '--' }}</el-descriptions-item>
      <el-descriptions-item label="SDK 受控刷写">
        <el-tag :type="controlledFlashSupported ? 'success' : 'info'" size="small">
          {{ controlledFlashSupported ? '支持' : '不支持' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="Wi-Fi 支持">{{ currentDevice.wifi_supported ? '是' : '否' }}</el-descriptions-item>
    </el-descriptions>
  </el-card>
  <el-card shadow="never" class="section-gap">
    <template #header>
      <div class="card-header">
        <span>USB SDK 更新</span>
        <el-tag v-if="sdk.busy" type="warning">正在刷写</el-tag>
        <el-tag v-else-if="sdk.status === 'success'" type="success">刷写完成</el-tag>
        <el-tag v-else-if="sdk.status === 'error'" type="danger">刷写失败</el-tag>
      </div>
    </template>
    <el-alert
      title="刷写期间请勿断电、拔线或让电脑休眠。"
      type="warning"
      :closable="false"
      show-icon
    />
    <div class="sdk-toolbar section-gap">
      <el-button :disabled="sdk.busy" @click="selectSdkImage">选择并校验 SDK 镜像</el-button>
      <el-select
        v-model="sdk.selectedPort"
        :disabled="sdk.busy"
        placeholder="强刷目标 COM 口"
        class="sdk-port-select"
        @visible-change="(visible) => visible && loadSdkPorts()"
      >
        <el-option
          v-for="port in sdk.ports"
          :key="port.device"
          :label="port.label"
          :value="port.device"
        />
      </el-select>
      <el-button :disabled="sdk.busy || !sdk.image" @click="startSdkFlash(true)">强刷 SDK</el-button>
      <el-button
        type="primary"
        :loading="sdk.busy"
        :disabled="!sdk.image || !controlledFlashSupported"
        @click="startSdkFlash(false)"
      >
        刷写 USB SDK
      </el-button>
    </div>
    <el-descriptions v-if="sdk.image" :column="2" border class="section-gap">
      <el-descriptions-item label="镜像文件">{{ sdk.image.name }}</el-descriptions-item>
      <el-descriptions-item label="目标版本">{{ sdk.image.sdkVersion }}</el-descriptions-item>
      <el-descriptions-item label="镜像大小">{{ (sdk.image.size / 1024 / 1024).toFixed(2) }} MiB</el-descriptions-item>
      <el-descriptions-item label="SHA-256"><span class="hash-value">{{ sdk.image.sha256 }}</span></el-descriptions-item>
    </el-descriptions>
    <p v-if="sdk.message" class="sdk-status">{{ sdk.message }}</p>
    <pre v-if="sdk.logs" ref="sdkLogView" class="terminal sdk-log-view">{{ sdk.logs }}</pre>
  </el-card>
  <el-card shadow="never" class="section-gap">
    <template #header>
      <div class="card-header">
        <span>设备实时日志</span>
      </div>
    </template>
    <pre ref="deviceLogView" class="terminal device-log-view">{{ deviceLogs || '暂无设备通信日志' }}</pre>
    <template v-if="probe.log">
      <p class="probe-log-title">最近一次主动探测输出</p>
      <pre class="terminal probe-log-view">{{ probe.log }}</pre>
    </template>
  </el-card>
</template>
