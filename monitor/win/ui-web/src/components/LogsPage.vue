<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'
import CopyableLog from './CopyableLog.vue'

const logs = ref('')
const loading = ref(false)
const autoRefresh = ref(true)
const followLatest = ref(true)
const logView = ref(null)
let refreshTimer = null
let reading = false

/**
 * 读取最新运行日志。
 */
async function loadLogs(silent = false) {
  if (reading) return
  reading = true
  if (!silent) loading.value = true
  try {
    const result = await invoke('log.read', { maximum: 500000 })
    logs.value = result.content || ''
    await nextTick()
    if (followLatest.value && logView.value) {
      logView.value.scrollToBottom()
    }
  } catch (error) {
    if (!silent) ElMessage.error(error?.message || String(error))
  } finally {
    reading = false
    if (!silent) loading.value = false
  }
}

/**
 * 根据用户滚动位置决定是否继续跟随最新日志。
 */
function updateFollowState() {
  const view = logView.value
  if (!view) return
  followLatest.value = view.isNearBottom()
}

/**
 * 切换实时刷新状态，并在恢复时立即读取一次日志。
 */
function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) loadLogs(true)
}

/**
 * 导出带脱敏配置快照的日志。
 */
async function exportLogs() {
  try {
    await invoke('log.export')
    ElMessage.success('日志已导出')
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 清空运行日志。
 */
async function clearLogs() {
  try {
    await ElMessageBox.confirm('确定清空当前运行日志吗？', '清空日志', { type: 'warning' })
    await invoke('log.clear')
    logs.value = ''
    followLatest.value = true
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error?.message || String(error))
  }
}

onMounted(async () => {
  await loadLogs()
  refreshTimer = window.setInterval(() => {
    if (autoRefresh.value) loadLogs(true)
  }, 800)
})

onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="log-toolbar">
    <el-button :loading="loading" @click="loadLogs(false)">刷新</el-button>
    <el-button :type="autoRefresh ? 'success' : 'default'" @click="toggleAutoRefresh">
      {{ autoRefresh ? '实时查看中' : '继续实时查看' }}
    </el-button>
    <el-tag :type="followLatest ? 'success' : 'warning'" effect="plain">
      {{ followLatest ? '跟随最新' : '已暂停滚动' }}
    </el-tag>
    <el-button @click="exportLogs">导出日志</el-button>
    <el-button type="danger" plain @click="clearLogs">清空日志</el-button>
  </div>
  <CopyableLog
    ref="logView"
    :content="logs"
    pre-class="terminal log-view"
    copy-success-text="运行日志已复制"
    @scroll="updateFollowState"
  />
</template>
