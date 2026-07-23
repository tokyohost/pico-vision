<script setup>
import { onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'

const customData = reactive({ loading: false, items: [], errors: [], output: '' })

/**
 * 读取自定义数据插件清单。
 */
async function loadCustomData() {
  customData.loading = true
  try {
    const result = await invoke('data.list')
    customData.items = result.items || []
    customData.errors = result.errors || []
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    customData.loading = false
  }
}

/**
 * 选择并导入自定义数据 ZIP 插件。
 */
async function importCustomData() {
  try {
    const result = await invoke('data.import')
    if (!result.cancelled) {
      ElMessage.success(`插件“${result.chineseName}”导入成功`)
      await loadCustomData()
    }
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 激活一个尚未运行的自定义数据插件。
 */
async function activateCustomData(item) {
  try {
    await invoke('data.activate', { name: item.name })
    ElMessage.success('插件已加入采集任务')
    await loadCustomData()
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 测试执行一个自定义数据插件。
 */
async function testCustomData(item) {
  try {
    const result = await invoke('data.test', { name: item.name })
    customData.output = result.output || ''
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 删除一个自定义数据插件。
 */
async function deleteCustomData(item) {
  try {
    await ElMessageBox.confirm(`确定删除插件“${item.chineseName}”及其独立环境吗？`, '删除插件', { type: 'warning' })
    await invoke('data.delete', { path: item.path })
    await loadCustomData()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error?.message || String(error))
  }
}

/**
 * 打开插件数据目录。
 */
async function openDataDirectory() {
  try {
    await invoke('system.openDataDirectory')
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

onMounted(loadCustomData)
</script>

<template>
  <div class="page-title card-header">
    <div><h2>自定义数据插件</h2><p>导入、测试和管理隔离运行的 ZIP 插件。</p></div>
    <div>
      <el-button @click="openDataDirectory">打开目录</el-button>
      <el-button type="primary" @click="importCustomData">导入 ZIP</el-button>
    </div>
  </div>
  <el-card shadow="never" class="section-gap" v-loading="customData.loading">
    <el-table :data="customData.items">
      <el-table-column prop="chineseName" label="插件" min-width="120" />
      <el-table-column prop="key" label="JSON Key" min-width="110" />
      <el-table-column prop="interval" label="间隔（秒）" width="100" />
      <el-table-column prop="environment" label="独立环境" min-width="130" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '运行中' : '未激活' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button v-if="!row.enabled" text type="primary" @click="activateCustomData(row)">激活</el-button>
          <el-button text @click="testCustomData(row)">测试</el-button>
          <el-button text type="danger" @click="deleteCustomData(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-alert
      v-for="error in customData.errors"
      :key="error.path"
      :title="error.path"
      :description="error.message"
      type="error"
      show-icon
      class="section-gap"
    />
  </el-card>
  <pre v-if="customData.output" class="terminal">{{ customData.output }}</pre>
</template>
