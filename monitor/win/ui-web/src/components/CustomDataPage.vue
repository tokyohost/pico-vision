<script setup>
import { onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'
import { runWithGlobalLoading } from '../globalLoading'

const emit = defineEmits(['plugins-changed', 'catalog-updated'])

const customData = reactive({
  loading: false,
  items: [],
  errors: [],
  output: '',
  installingNames: [],
  detail: { visible: false, title: '', content: '' },
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
      emit('plugins-changed')
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
  customData.output = ''
  try {
    const result = await runWithGlobalLoading({
      title: `正在安装“${item.chineseName}”环境`,
      message: '准备创建插件独立环境',
      progress: 8,
      successMessage: '插件环境安装完成',
    }, async ({ progress, log }) => {
      progress(20, '正在检查 Python Runtime 和虚拟环境')
      progress(35, '正在创建环境并安装 requirements.txt 依赖')
      const response = await invoke('data.installDependencies', { name: item.name })
      for (const line of String(response.output || '').split(/\r?\n/)) log(line)
      progress(92, '正在刷新插件环境状态')
      return response
    })
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
 * 在受限页面中显示插件绑定的 HTML 简介。
 */
async function openPluginDetail(item) {
  try {
    const result = await invoke('data.detail', { name: item.name })
    customData.detail.title = result.title || `${item.chineseName} · 插件简介`
    customData.detail.content = result.content || ''
    customData.detail.visible = true
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 将插件包内绑定的屏幕样式同步到设备。
 */
async function syncBoundStyle(item, overwrite = false) {
  try {
    const result = await runWithGlobalLoading({
      title: `正在同步“${item.boundStyle}”`,
      message: '准备校验绑定样式',
      progress: 8,
      successMessage: '绑定样式同步完成',
    }, async ({ progress }) => {
      progress(25, '正在校验样式文件名、编码和必需方法')
      progress(45, '正在将样式发送到设备')
      const response = await invoke('data.syncStyle', { name: item.name, overwrite })
      progress(88, '设备已接收样式，正在刷新样式目录')
      return response
    })
    if (result.catalog) emit('catalog-updated', result.catalog)
    ElMessage.success(`绑定样式“${item.boundStyle}”已同步到设备`)
  } catch (error) {
    if (!overwrite && /已存在/.test(error?.message || '')) {
      try {
        await ElMessageBox.confirm(`${error.message}。是否覆盖设备中的样式？`, '覆盖绑定样式', { type: 'warning' })
        await syncBoundStyle(item, true)
      } catch (nestedError) {
        if (nestedError !== 'cancel' && nestedError !== 'close') ElMessage.error(nestedError?.message || String(nestedError))
      }
      return
    }
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
    emit('plugins-changed')
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
      <el-table-column label="预览" width="100">
        <template #default="{ row }">
          <img
            v-if="row.previewDataUrl"
            :src="row.previewDataUrl"
            :alt="`${row.chineseName}预览图`"
            class="custom-data-preview"
          />
          <span v-else>无</span>
        </template>
      </el-table-column>
      <el-table-column prop="key" label="JSON Key" min-width="110" />
      <el-table-column prop="interval" label="间隔（秒）" width="100" />
      <el-table-column prop="boundStyle" label="绑定样式" min-width="120">
        <template #default="{ row }">{{ row.boundStyle || '未绑定' }}</template>
      </el-table-column>
      <el-table-column prop="environment" label="独立环境" min-width="130" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '运行中' : '未激活' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="440">
        <template #default="{ row }">
          <el-button
            text
            size="small"
            :loading="isInstallingEnvironment(row)"
            @click="installEnvironment(row)"
          >安装环境</el-button>
          <el-button v-if="!row.enabled" text size="small" type="primary" @click="activateCustomData(row)">激活</el-button>
          <el-button text size="small" @click="testCustomData(row)">测试</el-button>
          <el-button v-if="row.hasDetail" text size="small" @click="openPluginDetail(row)">查看简介</el-button>
          <el-button v-if="row.boundStyle" text size="small" type="primary" @click="syncBoundStyle(row)">同步样式</el-button>
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
  <el-dialog
    v-model="customData.detail.visible"
    :title="customData.detail.title"
    width="min(920px, 88vw)"
    class="style-detail-dialog"
  >
    <iframe
      :srcdoc="customData.detail.content"
      :title="customData.detail.title"
      class="style-detail-frame"
      sandbox=""
    />
  </el-dialog>
</template>
