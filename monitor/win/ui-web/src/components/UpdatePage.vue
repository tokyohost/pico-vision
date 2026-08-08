<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'
import CopyableLog from './CopyableLog.vue'

const props = defineProps({
  device: { type: Object, required: true },
  applicationVersion: { type: String, required: true },
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
    title: '设备固件更新',
    icon: 'Cpu',
    description: '检查设备中运行的 OmniWatch Python 固件。',
    current: props.device.firmware_version || '等待设备连接',
    disabled: props.device.connected !== true,
  },
  {
    key: 'sdk',
    title: '设备 SDK 更新',
    icon: 'SetUp',
    description: '检查 SDK 镜像。',
    current: props.device.sdk_version || '等待设备连接',
    disabled: props.device.connected !== true,
  },
  {
    key: 'application',
    title: 'OmniWatch 应用更新',
    icon: 'Monitor',
    description: '检查 Windows 桌面控制中心安装包。',
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
  if (state.loading) return '正在检查'
  if (state.error) return '检查失败'
  if (!state.result) return '尚未检查'
  if (state.result.applicable === false) return '当前设备不适用'
  return state.result.updateAvailable ? '发现新版本' : '已是最新版本'
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
  if (errorCount) ElMessage.warning(`更新检查完成，${errorCount} 项检查失败`)
  else ElMessage.success('更新检查已完成')
}

/**
 * 确认风险提示后立即启动指定类别的更新任务。
 */
async function installUpdate(category) {
  const state = checks[category]
  if (category !== 'application') {
    try {
      await ElMessageBox.confirm(
        '更新期间请勿断开设备、关闭电源或退出 OmniWatch。是否立即更新？',
        '确认立即更新',
        { confirmButtonText: '立即更新', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
  }
  state.installing = true
  try {
    await invoke('update.install', { category })
    await refreshUpdateStatus()
    ElMessage.success(category === 'application' ? '已打开应用更新流程' : '更新任务已启动')
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
    <el-button type="primary" :loading="Object.values(checks).some((state) => state.loading)" @click="checkAllUpdates">
      检查全部更新
    </el-button>
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
            <span>当前版本</span>
            <strong :title="checks[item.key].result?.currentVersion || item.current">
              {{ checks[item.key].result?.currentVersion || item.current }}
            </strong>
          </div>
          <div class="update-version-row">
            <span>最新版本</span>
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
            >立即检查</el-button>
            <el-button
              v-if="checks[item.key].result?.updateAvailable && checks[item.key].result?.assetAvailable"
              type="danger"
              :loading="checks[item.key].installing"
              @click="installUpdate(item.key)"
            >立即更新</el-button>
          </div>
        </div>
      </div>

      <el-alert
        v-if="item.disabled"
        title="请先连接设备后再检查"
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
        <p v-if="checks[item.key].result.assetName" class="update-asset">
          发布资源：{{ checks[item.key].result.assetName }}
        </p>
        <el-alert
          v-if="checks[item.key].result.updateAvailable && !checks[item.key].result.assetAvailable"
          title="发现新版本，但当前发布中缺少适配资源"
          type="warning"
          :closable="false"
          show-icon
        />
        <details v-if="checks[item.key].result.notes" class="update-notes">
          <summary>查看更新说明</summary>
          <pre>{{ checks[item.key].result.notes }}</pre>
        </details>
      </template>
      <div v-if="checks[item.key].status !== 'idle'" class="update-runtime">
        <div class="update-runtime-heading">
          <span>{{ checks[item.key].message || '正在准备更新' }}</span>
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
          copy-success-text="更新日志已复制"
        />
      </div>
    </el-card>
  </div>
</template>
