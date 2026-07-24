<script setup>
import { onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'

const customData = reactive({
  loading: false,
  items: [],
  errors: [],
  output: '',
  installingNames: [],
})

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
 * 选择插件来源并处理重复插件覆盖确认。
 */
async function importCustomData(action, sourceLabel) {
  try {
    let result = await invoke(action)
    if (result.requiresOverwrite) {
      await ElMessageBox.confirm(
        `${result.message}\n\n覆盖会删除旧插件目录及其独立环境，确定继续吗？`,
        '覆盖自定义数据插件',
        { type: 'warning', confirmButtonText: '确认覆盖' },
      )
      result = await invoke(action, {
        overwrite: true,
        sourcePath: result.sourcePath,
      })
    }
    if (!result.cancelled) {
      ElMessage.success(`${sourceLabel}“${result.chineseName}”导入成功`)
      await loadCustomData()
    }
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error?.message || String(error))
    }
  }
}

/**
 * 判断指定插件是否正在安装独立环境。
 */
function isInstallingEnvironment(item) {
  return customData.installingNames.includes(item.name)
}

/**
 * 创建插件独立环境并安装 requirements.txt 中声明的依赖。
 */
async function installEnvironment(item) {
  if (isInstallingEnvironment(item)) return
  customData.installingNames.push(item.name)
  customData.output = `正在为插件“${item.chineseName}”安装独立环境，请稍候……`
  try {
    const result = await invoke('data.installDependencies', { name: item.name })
    customData.output = result.output || result.status || '环境安装完成'
    ElMessage.success(`插件“${item.chineseName}”${result.status}`)
    await loadCustomData()
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    customData.installingNames = customData.installingNames.filter((name) => name !== item.name)
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

onMounted(loadCustomData)
</script>

<template>
  <div class="page-title card-header">
    <div><h2>自定义数据插件</h2><p>通过 ZIP 包或本地插件目录导入、测试和管理隔离运行的插件。</p></div>
    <div>
      <el-button @click="importCustomData('data.importDirectory', '目录插件')">导入目录</el-button>
      <el-button type="primary" @click="importCustomData('data.import', '插件')">导入 ZIP</el-button>
    </div>
  </div>
  <el-card shadow="never" class="section-gap" v-loading="customData.loading">
    <el-table
      :data="customData.items"
      class="theme-table custom-data-table"
      empty-text="暂无自定义数据插件"
    >
      <el-table-column prop="chineseName" label="插件" min-width="120" />
      <el-table-column prop="key" label="JSON Key" min-width="110" />
      <el-table-column prop="interval" label="间隔（秒）" width="100" />
      <el-table-column prop="environment" label="独立环境" min-width="130" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '运行中' : '未激活' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="290">
        <template #default="{ row }">
          <el-button
            text
            size="small"
            :loading="isInstallingEnvironment(row)"
            @click="installEnvironment(row)"
          >安装环境</el-button>
          <el-button v-if="!row.enabled" text size="small" type="primary" @click="activateCustomData(row)">激活</el-button>
          <el-button text size="small" @click="testCustomData(row)">测试</el-button>
          <el-button text size="small" type="danger" @click="deleteCustomData(row)">删除</el-button>
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
