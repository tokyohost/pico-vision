<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'

const logs = ref('')
const loading = ref(false)

/**
 * 读取最新运行日志。
 */
async function loadLogs() {
  loading.value = true
  try {
    const result = await invoke('log.read', { maximum: 500000 })
    logs.value = result.content || ''
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    loading.value = false
  }
}

/**
 * 复制全部运行日志。
 */
async function copyLogs() {
  try {
    await navigator.clipboard.writeText(logs.value)
    ElMessage.success('日志已复制')
  } catch (error) {
    ElMessage.error(error?.message || '复制日志失败')
  }
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
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error?.message || String(error))
  }
}

onMounted(loadLogs)
</script>

<template>
  <div class="log-toolbar">
    <el-button :loading="loading" @click="loadLogs">刷新</el-button>
    <el-button @click="copyLogs">复制全部</el-button>
    <el-button @click="exportLogs">导出日志</el-button>
    <el-button type="danger" plain @click="clearLogs">清空日志</el-button>
  </div>
  <pre class="terminal log-view">{{ logs || '暂无日志' }}</pre>
</template>
