<script setup>
import { t } from '../i18n'

import { computed, nextTick, onBeforeUnmount, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'
import CopyableLog from './CopyableLog.vue'

const props = defineProps({
  device: { type: Object, required: true },
  applicationVersion: { type: String, required: true },
  platform: { type: String, default: 'win32' },
})

const checks = reactive({
  firmware: { loading: false, installing: false, result: null, error: '', progress: 0, status: 'idle', message: '', logs: '' },
  sdk: { loading: false, installing: false, result: null, error: '', progress: 0, status: 'idle', message: '', logs: '' },
  application: { loading: false, installing: false, result: null, error: '', progress: 0, status: 'idle', message: '', logs: '' },
})
let statusTimer = null
const logElements = {}

const updateItems = computed(() => [
  {
    key: 'firmware',
    title: t('ui.device_firmware_update'),
    icon: 'Cpu',
    description: t('ui.check_the_omniwatch_python_firmware_running_on_the_device'),
    current: props.device.firmware_version || t('ui.waiting_for_device_connection'),
    disabled: props.device.connected !== true,
  },
  {
    key: 'sdk',
    title: t('ui.device_sdk_update'),
    icon: 'SetUp',
    description: t('ui.check_the_sdk_image'),
    current: props.device.sdk_version || t('ui.waiting_for_device_connection'),
    disabled: props.device.connected !== true,
  },
  {
    key: 'application',
    title: t('ui.omniwatch_application_update'),
    icon: 'Monitor',
    description: t('ui.check_the_value_desktop_control_center_package', { value0: { win32: 'Windows', darwin: 'macOS', linux: 'Linux' }[props.platform] || t('common.current_platform') }),
    current: props.applicationVersion || 'development',
    disabled: false,
  },
])

/**
 * 返回更新检查结果对应的标签类型。
 */
function resultTagType(state) {
  if (state.error) return 'danger'
  if (!state.result) return 'info'
  if (state.result.applicable === false) return 'info'
  return state.result.updateAvailable ? 'warning' : 'success'
}

/**
 * 返回更新检查结果对应的中文状态。
 */
function resultText(state) {
  if (state.loading) return t('ui.checking')
  if (state.error) return t('ui.check_failed')
  if (!state.result) return t('ui.not_checked')
  if (state.result.applicable === false) return t('ui.not_applicable_to_this_device')
  return state.result.updateAvailable ? t('ui.new_version_available') : t('ui.up_to_date')
}

/**
 * 检查指定类别的最新发布版本和配套资源。
 */
async function checkUpdate(category, showError = true) {
  const state = checks[category]
  state.loading = true
  state.error = ''
  try {
    state.result = await invoke('update.check', { category })
  } catch (error) {
    state.error = error?.message || String(error)
    if (showError) ElMessage.error(state.error)
  } finally {
    state.loading = false
  }
}

/**
 * 依次检查全部适用的更新类别。
 */
async function checkAllUpdates() {
  for (const item of updateItems.value) {
    if (!item.disabled) await checkUpdate(item.key, false)
  }
  const errorCount = Object.values(checks).filter((state) => state.error).length
  if (errorCount) ElMessage.warning(t('ui.update_check_completed_value_checks_failed', { value0: errorCount }))
  else ElMessage.success(t('ui.update_check_completed'))
}

/**
 * 确认风险提示后立即启动指定类别的更新任务。
 */
async function installUpdate(category) {
  const state = checks[category]
  if (category !== 'application') {
    try {
      await ElMessageBox.confirm(
        t('ui.do_not_disconnect_the_device_power_off_or_exit'),
        t('ui.confirm_update'),
        { confirmButtonText: t('ui.update_now'), cancelButtonText: t('ui.cancel'), type: 'warning' },
      )
    } catch {
      return
    }
  }
  state.installing = true
  try {
    await invoke('update.install', { category })
    await refreshUpdateStatus()
    ElMessage.success(category === 'application' ? t('ui.application_update_download_started') : t('ui.update_task_started'))
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    state.installing = state.status === 'running'
  }
}

/**
 * 保存各更新类别的日志容器，供轮询刷新后自动滚动到底部。
 */
function setLogElement(category, element) {
  if (element) logElements[category] = element
  else delete logElements[category]
}

/**
 * 拉取全部在线更新任务的最新进度和日志快照。
 */
async function refreshUpdateStatus() {
  try {
    const states = await invoke('update.status')
    for (const [category, updateState] of Object.entries(states)) {
      Object.assign(checks[category], updateState, { installing: updateState.busy })
    }
    await nextTick()
    for (const element of Object.values(logElements)) {
      element.scrollToBottom()
    }
  } catch {
    // 短暂的桥接失败不打断更新，下一轮轮询会继续同步。
  }
}

onMounted(() => {
  refreshUpdateStatus()
  statusTimer = window.setInterval(refreshUpdateStatus, 700)
})

onBeforeUnmount(() => {
  if (statusTimer !== null) window.clearInterval(statusTimer)
})
</script>

<template>
  <div class="update-toolbar">
    <el-button type="primary" :loading="Object.values(checks).some((state) => state.loading)" @click="checkAllUpdates">{{ t('ui.check_all_updates') }}</el-button>
  </div>

  <div class="update-grid">
    <el-card v-for="item in updateItems" :key="item.key" shadow="never" class="update-card">
      <div class="update-card-main">
        <div class="update-card-heading">
          <span class="update-icon"><el-icon><component :is="item.icon" /></el-icon></span>
          <div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.description }}</p>
          </div>
        </div>

        <div class="update-version-list">
          <div class="update-version-row">
            <span>{{ t('ui.current_version') }}</span>
            <strong :title="checks[item.key].result?.currentVersion || item.current">
              {{ checks[item.key].result?.currentVersion || item.current }}
            </strong>
          </div>
          <div class="update-version-row">
            <span>{{ t('ui.latest_version') }}</span>
            <strong :title="checks[item.key].result?.latestVersion || '--'">
              {{ checks[item.key].result?.latestVersion || '--' }}
            </strong>
          </div>
        </div>

        <div class="update-card-actions">
          <el-tag :type="resultTagType(checks[item.key])" effect="dark">
            {{ resultText(checks[item.key]) }}
          </el-tag>
          <div class="update-action-buttons">
            <el-button
              type="primary"
              plain
              :disabled="item.disabled"
              :loading="checks[item.key].loading"
              @click="checkUpdate(item.key)"
            >{{ t('ui.check_now') }}</el-button>
            <el-button
              v-if="checks[item.key].result?.updateAvailable && checks[item.key].result?.assetAvailable"
              type="danger"
              :loading="checks[item.key].installing"
              @click="installUpdate(item.key)"
            >{{ t('ui.update_now') }}</el-button>
          </div>
        </div>
      </div>

      <el-alert
        v-if="item.disabled"
        :title="t('ui.connect_a_device_before_checking')"
        type="info"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="checks[item.key].error"
        :title="checks[item.key].error"
        type="error"
        :closable="false"
        show-icon
      />
      <template v-else-if="checks[item.key].result">
        <p v-if="checks[item.key].result.assetName" class="update-asset">{{ t('ui.release_asset') }}{{ checks[item.key].result.assetName }}
        </p>
        <el-alert
          v-if="checks[item.key].result.updateAvailable && !checks[item.key].result.assetAvailable"
          :title="t('ui.new_version_available_but_no_compatible_asset_was_found')"
          type="warning"
          :closable="false"
          show-icon
        />
        <details v-if="checks[item.key].result.notes" class="update-notes">
          <summary>{{ t('ui.release_notes') }}</summary>
          <pre>{{ checks[item.key].result.notes }}</pre>
        </details>
      </template>
      <div v-if="checks[item.key].status !== 'idle'" class="update-runtime">
        <div class="update-runtime-heading">
          <span>{{ checks[item.key].message || t('ui.preparing_update') }}</span>
          <strong>{{ checks[item.key].progress }}%</strong>
        </div>
        <el-progress
          :percentage="checks[item.key].progress"
          :status="checks[item.key].status === 'success' ? 'success' : checks[item.key].status === 'error' ? 'exception' : ''"
          :stroke-width="10"
        />
        <CopyableLog
          v-if="checks[item.key].logs"
          :ref="(element) => setLogElement(item.key, element)"
          :content="checks[item.key].logs"
          pre-class="update-live-log"
          :copy-success-text="t('ui.update_logs_copied')"
        />
      </div>
    </el-card>
  </div>
</template>
