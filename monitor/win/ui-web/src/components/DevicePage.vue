<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'
import CopyableLog from './CopyableLog.vue'

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
const firmware = reactive({
  busy: false,
  status: 'idle',
  message: '',
  progress: 0,
  package: null,
  ports: [],
  selectedPort: '',
  force: false,
})
const sdkLogView = ref(null)
const deviceLogView = ref(null)
const deviceLogs = ref('')
const registration = reactive({ registered: false, checking: false, uuid: '' })
let refreshTimer = null

/**
 * 将当前设备UUID复制到系统剪贴板。
 */
async function copyDeviceUuid() {
  const uuid = currentDevice.value.device_id
  if (!uuid) {
    ElMessage.warning('当前设备没有可复制的UUID')
    return
  }
  await navigator.clipboard.writeText(uuid)
  ElMessage.success('设备UUID已复制')
}

/**
 * 调用远程接口检查当前设备注册状态。
 */
async function checkRegistrationStatus(uuid = currentDevice.value.device_id) {
  if (!uuid || registration.checking) return
  registration.checking = true
  try {
    const result = await invoke('device.registration.status', { uuid })
    if (result.uuid === uuid) {
      registration.uuid = uuid
      registration.registered = Boolean(result.registered)
    }
  } catch (error) {
    registration.uuid = uuid
    registration.registered = false
    console.warn('检查设备注册状态失败', error)
  } finally {
    registration.checking = false
  }
}

/**
 * 粘贴Base64注册码并立即注册当前设备。
 */
async function registerDeviceNow() {
  if (!currentDevice.value.device_id) {
    ElMessage.warning('当前设备未提供UUID')
    return
  }
  try {
    const { value } = await ElMessageBox.prompt(
      '请粘贴注册码',
      '立即注册设备',
      {
        confirmButtonText: '立即注册',
        cancelButtonText: '取消',
        inputType: 'textarea',
        inputValidator: (text) => Boolean(String(text || '').trim()) || '注册码不能为空',
      },
    )
    const result = await invoke('device.registration.register', {
      registrationCode: String(value || '').trim(),
    })
    registration.uuid = result.uuid
    registration.registered = Boolean(result.registered)
    ElMessage.success('设备注册成功')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error?.message || String(error))
    }
  }
}

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
      || deviceLogView.value.isNearBottom()
    const [deviceResult, sdkResult, updateResult, logResult] = await Promise.all([
      invoke('device.status'),
      invoke('device.sdk.status'),
      invoke('update.status'),
      invoke('log.read', { maximum: 160000 }),
    ])
    Object.keys(liveDevice).forEach((key) => delete liveDevice[key])
    Object.assign(liveDevice, deviceResult || {})
    Object.assign(sdk, sdkResult || {})
    Object.assign(firmware, updateResult?.firmware || {})
    deviceLogs.value = logResult?.content || ''
    await nextTick()
    if (sdkLogView.value && sdk.busy) {
      sdkLogView.value.scrollToBottom()
    }
    if (deviceLogView.value && shouldFollowDeviceLog) {
      deviceLogView.value.scrollToBottom()
    }
  } catch (error) {
    if (showError) ElMessage.error(error?.message || String(error))
  }
}

/**
 * 选择并校验本地固件全量包。
 */
async function selectFirmwarePackage() {
  try {
    const result = await invoke('device.firmware.select')
    if (!result.cancelled) {
      firmware.package = result.package
      ElMessage.success('固件 ZIP 包校验通过')
    }
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 刷新固件更新可选择的串口，并优先选择当前设备对应的 REPL 串口。
 */
async function loadFirmwarePorts() {
  try {
    const result = await invoke('device.firmware.ports')
    firmware.ports = result.ports || []
    if (!firmware.ports.some((item) => item.device === firmware.selectedPort)) {
      firmware.selectedPort = result.recommendedPort || firmware.ports[0]?.device || ''
    }
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 使用所选串口和更新模式启动 mpremote 固件复制任务。
 */
async function updateLocalFirmware() {
  if (!firmware.package) {
    ElMessage.warning('请先选择固件 ZIP 包')
    return
  }
  if (!firmware.selectedPort) {
    ElMessage.warning('请选择固件更新目标串口')
    return
  }
  const mode = firmware.force ? '全量更新：跳过 Hash 校验并覆盖全部文件' : '增量更新：仅复制 Hash 不一致的文件'
  try {
    await ElMessageBox.confirm(
      `固件包：${firmware.package.name}\n`
      + `文件数量：${firmware.package.fileCount}\n`
      + `目标串口：${firmware.selectedPort}\n`
      + `更新模式：${mode}\n\n`
      + '更新期间请勿断电、拔线或退出 OmniWatch。',
      '确认本地固件更新',
      { type: 'warning', confirmButtonText: '开始更新', distinguishCancelAndClose: true },
    )
    const result = await invoke('device.firmware.updateLocal', {
      packagePath: firmware.package.path,
      port: firmware.selectedPort,
      force: firmware.force,
    })
    if (result.started) {
      ElMessage.success(`已开始${firmware.force ? '全量' : '增量'}更新：${result.packageName}`)
      await refreshRuntimeState()
    }
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error?.message || String(error))
    }
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
  await Promise.all([refreshRuntimeState(true), loadSdkPorts(), loadFirmwarePorts()])
  await checkRegistrationStatus()
  refreshTimer = window.setInterval(refreshRuntimeState, 800)
})

watch(
  () => currentDevice.value.device_id,
  (uuid, previousUuid) => {
    if (uuid && uuid !== previousUuid && uuid !== registration.uuid) {
      checkRegistrationStatus(uuid)
    }
  },
)

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
      <el-descriptions-item label="设备 UUID">
        <div class="uuid-actions">
          <span class="hash-value">{{ currentDevice.device_id || '--' }}</span>
          <el-tag
            v-if="registration.registered && registration.uuid === currentDevice.device_id"
            type="success"
            size="small"
          >已注册</el-tag>
          <el-button link type="primary" :disabled="!currentDevice.device_id" @click="copyDeviceUuid">复制</el-button>
          <el-button
            v-if="!registration.registered || registration.uuid !== currentDevice.device_id"
            link
            type="primary"
            :disabled="!currentDevice.connected || !currentDevice.device_id"
            @click="registerDeviceNow"
          >立即注册</el-button>
        </div>
      </el-descriptions-item>
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
    <CopyableLog
      v-if="sdk.logs"
      ref="sdkLogView"
      :content="sdk.logs"
      pre-class="terminal sdk-log-view"
      copy-success-text="SDK 日志已复制"
    />
    <el-divider />
    <div class="card-header">
      <div>
        <strong>固件更新</strong>
        <p class="sdk-status">选择目标串口和 ZIP 全量固件包，默认仅复制 Hash 不一致的文件。</p>
      </div>
      <el-tag v-if="firmware.busy" type="warning">正在更新</el-tag>
      <el-tag v-else-if="firmware.status === 'success'" type="success">更新完成</el-tag>
      <el-tag v-else-if="firmware.status === 'error'" type="danger">更新失败</el-tag>
    </div>
    <div class="firmware-update-toolbar section-gap">
      <el-button :disabled="firmware.busy" @click="selectFirmwarePackage">
        选择固件 ZIP
      </el-button>
      <el-select
        v-model="firmware.selectedPort"
        :disabled="firmware.busy"
        placeholder="固件更新目标串口"
        class="sdk-port-select"
        @visible-change="(visible) => visible && loadFirmwarePorts()"
      >
        <el-option
          v-for="port in firmware.ports"
          :key="port.device"
          :label="port.label"
          :value="port.device"
        />
      </el-select>
      <el-checkbox v-model="firmware.force" :disabled="firmware.busy" class="firmware-force-checkbox">
        全量更新
      </el-checkbox>
      <el-button
        type="primary"
        :loading="firmware.busy"
        :disabled="sdk.busy || firmware.busy || !firmware.package || !firmware.selectedPort"
        @click="updateLocalFirmware"
      >
        开始固件更新
      </el-button>
    </div>
    <div v-if="firmware.package" class="firmware-package-summary">
      <span>已选择：{{ firmware.package.name }}</span>
      <span>{{ firmware.package.fileCount }} 个文件</span>
      <el-tag :type="firmware.force ? 'danger' : 'success'" size="small">
        {{ firmware.force ? '全量覆盖' : 'Hash 增量' }}
      </el-tag>
    </div>
    <el-alert
      v-if="firmware.force"
      title="全量更新将跳过设备文件 Hash 校验，直接复制并替换固件包中的全部文件。"
      type="warning"
      :closable="false"
      show-icon
      class="section-gap"
    />
    <el-progress
      v-if="firmware.status !== 'idle'"
      :percentage="firmware.progress"
      :status="firmware.status === 'success' ? 'success' : firmware.status === 'error' ? 'exception' : ''"
      :stroke-width="10"
      class="section-gap"
    />
    <p v-if="firmware.message" class="sdk-status">{{ firmware.message }}</p>
  </el-card>
  <el-card shadow="never" class="section-gap">
    <template #header>
      <div class="card-header">
        <span>设备实时日志</span>
      </div>
    </template>
    <CopyableLog
      ref="deviceLogView"
      :content="deviceLogs"
      empty-text="暂无设备通信日志"
      pre-class="terminal device-log-view"
      copy-success-text="设备通信日志已复制"
    />
    <template v-if="probe.log">
      <p class="probe-log-title">最近一次主动探测输出</p>
      <CopyableLog
        :content="probe.log"
        pre-class="terminal probe-log-view"
        copy-success-text="设备探测日志已复制"
      />
    </template>
  </el-card>
</template>
