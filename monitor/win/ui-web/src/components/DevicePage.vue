<script setup>
import { t } from '../i18n'

import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke, isHttpBridge, uploadFile, copyText } from '../bridge'
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
const firmwareFileInput = ref(null)
const sdkFileInput = ref(null)
const deviceLogs = ref('')
const registration = reactive({ registered: false, checking: false, uuid: '' })
let refreshTimer = null

/**
 * 将当前设备UUID复制到系统剪贴板。
 */
async function copyDeviceUuid() {
  const uuid = currentDevice.value.device_id
  if (!uuid) {
    ElMessage.warning(t('ui.no_device_uuid_to_copy'))
    return
  }
  await copyText(uuid)
  ElMessage.success(t('ui.device_uuid_copied'))
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
    console.warn(t('ui.failed_to_check_device_registration'), error)
  } finally {
    registration.checking = false
  }
}

/**
 * 粘贴Base64注册码并立即注册当前设备。
 */
async function registerDeviceNow() {
  if (!currentDevice.value.device_id) {
    ElMessage.warning(t('ui.the_device_has_not_provided_a_uuid'))
    return
  }
  try {
    const { value } = await ElMessageBox.prompt(
      t('ui.paste_the_registration_code'),
      t('ui.register_device'),
      {
        confirmButtonText: t('ui.register_now'),
        cancelButtonText: t('ui.cancel'),
        inputType: 'textarea',
        inputValidator: (text) => Boolean(String(text || '').trim()) || t('ui.registration_code_is_required'),
      },
    )
    const result = await invoke('device.registration.register', {
      registrationCode: String(value || '').trim(),
    })
    registration.uuid = result.uuid
    registration.registered = Boolean(result.registered)
    ElMessage.success(t('ui.device_registered'))
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
  if (currentDevice.value.connected === true) return t('ui.device_online')
  if (currentDevice.value.connected === false) return t('ui.connection_error')
  return t('ui.waiting_for_device')
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
    && (transport.includes(t('ui.serial_port')) || ['serial', 'usb', 'usb cdc'].includes(transport))
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
    ElMessage.success(t('ui.device_scan_completed'))
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
  if (isHttpBridge()) {
    firmwareFileInput.value?.click()
    return
  }
  try {
    const result = await invoke('device.firmware.select')
    if (!result.cancelled) {
      firmware.package = result.package
      ElMessage.success(t('ui.firmware_zip_validated'))
    }
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 接收浏览器上传的固件 ZIP，并调用统一固件包校验 action。
 */
async function handleBrowserFirmwareFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    const upload = await uploadFile('firmware', [file])
    const result = await invoke('device.firmware.select', { uploadId: upload.uploadId })
    if (!result.cancelled) {
      firmware.package = result.package
      ElMessage.success(t('ui.firmware_zip_validated'))
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
    ElMessage.warning(t('ui.select_a_firmware_zip_first'))
    return
  }
  if (!firmware.selectedPort) {
    ElMessage.warning(t('ui.select_the_target_serial_port_for_firmware_update'))
    return
  }
  const mode = firmware.force ? t('ui.full_update_skip_hash_checks_and_replace_all_files') : t('ui.incremental_update_copy_only_files_with_different_hashes')
  try {
    await ElMessageBox.confirm(
      t('ui.firmware_package_value', { value0: firmware.package.name })
      + t('ui.file_count_value', { value0: firmware.package.fileCount })
      + t('ui.target_port_value', { value0: firmware.selectedPort })
      + t('ui.update_mode_value', { value0: mode })
      + t('ui.do_not_power_off_unplug_the_device_or_exit'),
      t('ui.confirm_local_firmware_update'),
      { type: 'warning', confirmButtonText: t('ui.start_update'), distinguishCancelAndClose: true },
    )
    const payload = {
      port: firmware.selectedPort,
      force: firmware.force,
    }
    if (firmware.package.uploadId) payload.uploadId = firmware.package.uploadId
    else payload.packagePath = firmware.package.path
    const result = await invoke('device.firmware.updateLocal', payload)
    if (result.started) {
      ElMessage.success(t('ui.started_value_update_value', { value0: firmware.force ? t('common.full') : t('common.incremental'), value1: result.packageName }))
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
  if (isHttpBridge()) {
    sdkFileInput.value?.click()
    return
  }
  try {
    const result = await invoke('device.sdk.select')
    if (!result.cancelled) {
      sdk.image = result.image
      ElMessage.success(t('ui.sdk_image_validated'))
    }
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 接收浏览器上传的 SDK 镜像，并调用统一镜像校验 action。
 */
async function handleBrowserSdkFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    const upload = await uploadFile('sdk', [file])
    const result = await invoke('device.sdk.select', { uploadId: upload.uploadId })
    if (!result.cancelled) {
      sdk.image = { ...result.image, uploadId: upload.uploadId }
      ElMessage.success(t('ui.sdk_image_validated'))
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
    ElMessage.warning(t('ui.select_an_sdk_image_first'))
    return
  }
  if (force && !sdk.selectedPort) {
    ElMessage.warning(t('ui.select_the_target_port_for_forced_flashing'))
    return
  }
  const target = force ? t('ui.target_port_value', { value0: sdk.selectedPort }) : t('ui.current_sdk_value', { value0: currentDevice.value.sdk_version || t('ui.unknown') })
  try {
    await ElMessageBox.confirm(
      t('ui.valuetarget_sdk_value', { value0: target, value1: sdk.image.sdkVersion })
      + t('ui.image_size_value_mib', { value0: (sdk.image.size / 1024 / 1024).toFixed(2) })
      + `SHA-256：${sdk.image.sha256}\n\n`
      + `${force ? t('ui.forced_flashing_will_try_to_enter_download_mode_through') : t('ui.the_device_will_enter_rom_usb_download_mode_automatically')}`
      + t('ui.do_not_power_off_unplug_the_device_or_let'),
      force ? t('ui.confirm_forced_sdk_flash') : t('ui.confirm_usb_sdk_flash'),
      { type: 'warning', confirmButtonText: t('ui.start_flashing'), distinguishCancelAndClose: true },
    )
    const payload = {
      force,
      port: force ? sdk.selectedPort : '',
    }
    if (sdk.image.uploadId) payload.uploadId = sdk.image.uploadId
    const result = await invoke('device.sdk.flash', payload)
    Object.assign(sdk, result)
    ElMessage.success(t('ui.sdk_update_started'))
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
    ElMessage.success(t('ui.screenshot_requested'))
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 请求设备安全重启。
 */
async function rebootDevice() {
  try {
    await ElMessageBox.confirm(t('ui.restart_the_current_device_now'), t('ui.restart_device'), { type: 'warning' })
    await invoke('device.reboot')
    ElMessage.success(t('ui.device_restart_command_sent'))
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
      <h2>{{ currentDevice.board_model || t('ui.omniwatch_device') }}</h2>
      <p>{{ currentDevice.address || currentDevice.wifi_address || t('ui.waiting_for_connection_details') }}</p>
    </div>
    <div class="hero-actions">
      <el-button :loading="probe.loading" type="primary" @click="probeDevice">{{ t('ui.scan_devices') }}</el-button>
      <el-button @click="takeScreenshot">{{ t('ui.screenshot') }}</el-button>
      <el-button type="danger" plain @click="rebootDevice">{{ t('ui.restart_device') }}</el-button>
    </div>
  </div>
  <el-card shadow="never" class="section-gap connection-policy-card">
    <div class="connection-policy-row">
      <div>
        <strong>{{ t('ui.force_usb_cdc') }}</strong>
        <p>{{ t('ui.disconnect_websocket_stop_wi_fi_discovery_and_continuously_probe') }}</p>
      </div>
      <el-switch
        v-model="settings.force_usb_cdc"
        :loading="saving"
        :active-text="t('ui.usb_cdc_only')"
        :inactive-text="t('ui.allow_wi_fi_usb')"
        @change="saveConnectionPolicy"
      />
    </div>
  </el-card>
  <el-card shadow="never" class="section-gap">
    <template #header><span>{{ t('ui.device_details') }}</span></template>
    <el-descriptions :column="2" border>
      <el-descriptions-item :label="t('ui.device_uuid')">
        <div class="uuid-actions">
          <span class="hash-value">{{ currentDevice.device_id || '--' }}</span>
          <el-tag
            v-if="registration.registered && registration.uuid === currentDevice.device_id"
            type="success"
            size="small"
          >{{ t('ui.registered') }}</el-tag>
          <el-button link type="primary" :disabled="!currentDevice.device_id" @click="copyDeviceUuid">{{ t('ui.copy') }}</el-button>
          <el-button
            v-if="!registration.registered || registration.uuid !== currentDevice.device_id"
            link
            type="primary"
            :disabled="!currentDevice.connected || !currentDevice.device_id"
            @click="registerDeviceNow"
          >{{ t('ui.register_now') }}</el-button>
        </div>
      </el-descriptions-item>
      <el-descriptions-item :label="t('ui.board')">{{ currentDevice.board_model || '--' }}</el-descriptions-item>
      <el-descriptions-item :label="t('ui.connection')">{{ currentDevice.transport || '--' }}</el-descriptions-item>
      <el-descriptions-item label="LCD">{{ currentDevice.lcd_device_type || '--' }}</el-descriptions-item>
      <el-descriptions-item :label="t('ui.resolution')">{{ currentDevice.screen_resolution || '--' }}</el-descriptions-item>
      <el-descriptions-item :label="t('ui.firmware_version')">{{ currentDevice.firmware_version || '--' }}</el-descriptions-item>
      <el-descriptions-item :label="t('ui.sdk_version')">{{ currentDevice.sdk_version || '--' }}</el-descriptions-item>
      <el-descriptions-item :label="t('ui.managed_sdk_flashing')">
        <el-tag :type="controlledFlashSupported ? 'success' : 'info'" size="small">
          {{ controlledFlashSupported ? t('ui.supported') : t('ui.not_supported') }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item :label="t('ui.wi_fi_support')">{{ currentDevice.wifi_supported ? t('ui.yes') : t('ui.no') }}</el-descriptions-item>
    </el-descriptions>
  </el-card>
  <el-card shadow="never" class="section-gap">
    <template #header>
      <div class="card-header">
        <span>{{ t('ui.usb_sdk_update') }}</span>
        <el-tag v-if="sdk.busy" type="warning">{{ t('ui.flashing') }}</el-tag>
        <el-tag v-else-if="sdk.status === 'success'" type="success">{{ t('ui.flash_completed') }}</el-tag>
        <el-tag v-else-if="sdk.status === 'error'" type="danger">{{ t('ui.flash_failed') }}</el-tag>
      </div>
    </template>
    <el-alert
      :title="t('ui.do_not_power_off_unplug_the_device_or_let_2')"
      type="warning"
      :closable="false"
      show-icon
    />
    <div class="sdk-toolbar section-gap">
      <el-button :disabled="sdk.busy" @click="selectSdkImage">{{ t('ui.select_and_validate_sdk_image') }}</el-button>
      <input
        v-if="isHttpBridge()"
        ref="sdkFileInput"
        type="file"
        accept=".bin"
        hidden
        @change="handleBrowserSdkFile"
      />
      <el-select
        v-model="sdk.selectedPort"
        :disabled="sdk.busy"
        :placeholder="t('ui.forced_flash_target_port')"
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
      <el-button :disabled="sdk.busy || !sdk.image" @click="startSdkFlash(true)">{{ t('ui.force_flash_sdk') }}</el-button>
      <el-button
        type="primary"
        :loading="sdk.busy"
        :disabled="!sdk.image || !controlledFlashSupported"
        @click="startSdkFlash(false)"
      >{{ t('ui.flash_usb_sdk') }}</el-button>
    </div>
    <el-descriptions v-if="sdk.image" :column="2" border class="section-gap">
      <el-descriptions-item :label="t('ui.image_file')">{{ sdk.image.name }}</el-descriptions-item>
      <el-descriptions-item :label="t('ui.target_version')">{{ sdk.image.sdkVersion }}</el-descriptions-item>
      <el-descriptions-item :label="t('ui.image_size')">{{ (sdk.image.size / 1024 / 1024).toFixed(2) }} MiB</el-descriptions-item>
      <el-descriptions-item label="SHA-256"><span class="hash-value">{{ sdk.image.sha256 }}</span></el-descriptions-item>
    </el-descriptions>
    <p v-if="sdk.message" class="sdk-status">{{ sdk.message }}</p>
    <CopyableLog
      v-if="sdk.logs"
      ref="sdkLogView"
      :content="sdk.logs"
      pre-class="terminal sdk-log-view"
      :copy-success-text="t('ui.sdk_logs_copied')"
    />
    <el-divider />
    <div class="card-header">
      <div>
        <strong>{{ t('ui.firmware_update') }}</strong>
        <p class="sdk-status">{{ t('ui.select_a_target_port_and_full_firmware_zip_only') }}</p>
      </div>
      <el-tag v-if="firmware.busy" type="warning">{{ t('ui.updating') }}</el-tag>
      <el-tag v-else-if="firmware.status === 'success'" type="success">{{ t('ui.update_completed') }}</el-tag>
      <el-tag v-else-if="firmware.status === 'error'" type="danger">{{ t('ui.update_failed') }}</el-tag>
    </div>
    <div class="firmware-update-toolbar section-gap">
      <el-button :disabled="firmware.busy" @click="selectFirmwarePackage">{{ t('ui.select_firmware_zip') }}</el-button>
      <input
        v-if="isHttpBridge()"
        ref="firmwareFileInput"
        type="file"
        accept=".zip"
        hidden
        @change="handleBrowserFirmwareFile"
      />
      <el-select
        v-model="firmware.selectedPort"
        :disabled="firmware.busy"
        :placeholder="t('ui.firmware_update_target_port')"
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
      <el-checkbox v-model="firmware.force" :disabled="firmware.busy" class="firmware-force-checkbox">{{ t('ui.full_update') }}</el-checkbox>
      <el-button
        type="primary"
        :loading="firmware.busy"
        :disabled="sdk.busy || firmware.busy || !firmware.package || !firmware.selectedPort"
        @click="updateLocalFirmware"
      >{{ t('ui.start_firmware_update') }}</el-button>
    </div>
    <div v-if="firmware.package" class="firmware-package-summary">
      <span>{{ t('ui.selected') }}{{ firmware.package.name }}</span>
      <span>{{ firmware.package.fileCount }}{{ t('ui.files') }}</span>
      <el-tag :type="firmware.force ? 'danger' : 'success'" size="small">
        {{ firmware.force ? t('ui.replace_all') : t('ui.hash_incremental') }}
      </el-tag>
    </div>
    <el-alert
      v-if="firmware.force"
      :title="t('ui.a_full_update_skips_device_hash_checks_and_replaces')"
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
        <span>{{ t('ui.live_device_logs') }}</span>
      </div>
    </template>
    <CopyableLog
      ref="deviceLogView"
      :content="deviceLogs"
      :empty-text="t('ui.no_device_communication_logs')"
      pre-class="terminal device-log-view"
      :copy-success-text="t('ui.device_communication_logs_copied')"
    />
    <template v-if="probe.log">
      <p class="probe-log-title">{{ t('ui.latest_device_scan_output') }}</p>
      <CopyableLog
        :content="probe.log"
        pre-class="terminal probe-log-view"
        :copy-success-text="t('ui.device_scan_logs_copied')"
      />
    </template>
  </el-card>
</template>
