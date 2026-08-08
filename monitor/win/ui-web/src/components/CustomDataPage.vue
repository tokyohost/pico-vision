<script setup>
import { onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'
import { runWithGlobalLoading } from '../globalLoading'
import CopyableLog from './CopyableLog.vue'

const emit = defineEmits(['plugins-changed', 'catalog-updated'])

const customData = reactive({
  loading: false,
  items: [],
  errors: [],
  output: '',
  installingNames: [],
  togglingNames: [],
  detail: { visible: false, title: '', content: '' },
  testResult: { visible: false, title: '', content: '' },
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
        '覆盖插件',
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
 * 立即持久化插件启用状态并同步采集工作进程。
 */
async function setCustomDataEnabled(item, enabled) {
  if (customData.togglingNames.includes(item.name)) return
  customData.togglingNames.push(item.name)
  try {
    await invoke('data.setEnabled', { name: item.name, enabled })
    ElMessage.success(enabled ? '插件已启用' : '插件已停用')
    await loadCustomData()
    emit('plugins-changed')
  } catch (error) {
    item.enabled = !enabled
    ElMessage.error(error?.message || String(error))
  } finally {
    customData.togglingNames = customData.togglingNames.filter((name) => name !== item.name)
  }
}

/**
 * 测试执行一个自定义数据插件。
 */
async function testCustomData(item) {
  try {
    const result = await invoke('data.test', { name: item.name })
    customData.testResult.title = `${item.chineseName} · 测试结果`
    customData.testResult.content = result.output || '测试完成，插件未返回内容。'
    customData.testResult.visible = true
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
    }, async ({ progress, log }) => {
      progress(25, '正在校验样式文件名、编码和必需方法')
      progress(45, '正在将样式发送到设备')
      let polling = true
      let lastProgressKey = ''
      const pollingTask = (async () => {
        while (polling) {
          try {
            const state = await invoke('data.syncStyleProgress')
            for (const item of state.progresses || []) {
              const progressKey = `${item.stage}:${item.completed}`
              if (progressKey === lastProgressKey) continue
              lastProgressKey = progressKey
              if (item.stage === 'sent') {
                const percent = item.total_bytes
                  ? Math.round(item.uploaded_bytes * 1000 / item.total_bytes) / 10
                  : 0
                progress(
                  45 + Math.round(percent * 0.38),
                  `正在将样式发送到设备：${item.uploaded_bytes}/${item.total_bytes} 字节`,
                )
              } else if (item.stage === 'begin') {
                log(`设备已准备接收，共 ${item.total_bytes} 字节`)
              } else if (item.stage === 'finish') {
                progress(85, `样式发送完成：${item.total_bytes}/${item.total_bytes} 字节`)
              }
            }
          } catch {
            // 上传主请求负责报告错误，进度轮询失败不应中断上传。
          }
          if (polling) await new Promise((resolve) => window.setTimeout(resolve, 500))
        }
      })()
      let response
      try {
        response = await invoke('data.syncStyle', { name: item.name, overwrite })
      } finally {
        polling = false
        await pollingTask
      }
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
    const cleanupHint = item.hasUninstall ? '，并先执行插件 uninstall 清理钩子' : ''
    await ElMessageBox.confirm(
      `确定删除插件“${item.chineseName}”及其独立环境${cleanupHint}吗？`,
      '删除插件',
      { type: 'warning' },
    )
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
  <div class="custom-data-toolbar">
    <el-button @click="importCustomData('data.importDirectory', '目录插件')">导入目录</el-button>
    <el-button type="primary" @click="importCustomData('data.import', '插件')">导入 ZIP</el-button>
  </div>
  <section class="custom-data-section section-gap" v-loading="customData.loading">
    <el-empty v-if="!customData.items.length" description="暂无插件" />
    <div v-else class="custom-data-card-list">
      <el-card
        v-for="item in customData.items"
        :key="item.name"
        shadow="never"
        class="custom-data-card"
      >
        <div class="custom-data-card-main">
          <div class="custom-data-preview-wrap">
            <img
              v-if="item.previewDataUrl"
              :src="item.previewDataUrl"
              :alt="`${item.chineseName}预览图`"
              class="custom-data-preview"
            />
            <span v-else>暂无预览</span>
          </div>
          <div class="custom-data-card-content">
            <div class="custom-data-card-header">
              <div>
                <h3>{{ item.chineseName }}</h3>
                <p>{{ item.name }}</p>
              </div>
              <div class="custom-data-enabled">
                <span>启用</span>
                <el-switch
                  v-model="item.enabled"
                  :loading="customData.togglingNames.includes(item.name)"
                  @change="(enabled) => setCustomDataEnabled(item, enabled)"
                />
              </div>
            </div>
            <div class="custom-data-meta">
              <div><span>JSON Key</span><strong>{{ item.key }}</strong></div>
              <div><span>采集间隔</span><strong>{{ item.interval }} 秒</strong></div>
              <div><span>独立环境</span><strong>{{ item.environment }}</strong></div>
              <div class="custom-data-meta-full"><span>绑定样式</span><strong>{{ item.boundStyle || '未绑定' }}</strong></div>
              <div class="custom-data-meta-full"><span>版本号</span><strong>{{ item.version || '未知' }}</strong></div>
            </div>
          </div>
        </div>
        <div class="custom-data-actions">
          <el-button
            text
            size="small"
            :loading="isInstallingEnvironment(item)"
            @click="installEnvironment(item)"
          >安装环境</el-button>
          <el-button text size="small" @click="testCustomData(item)">测试</el-button>
          <el-button v-if="item.hasDetail" text size="small" @click="openPluginDetail(item)">查看简介</el-button>
          <el-button v-if="item.boundStyle" text size="small" type="primary" @click="syncBoundStyle(item)">同步样式</el-button>
          <el-button text size="small" type="danger" @click="deleteCustomData(item)">删除</el-button>
        </div>
      </el-card>
    </div>
    <el-alert
      v-for="error in customData.errors"
      :key="error.path"
      :title="error.path"
      :description="error.message"
      type="error"
      show-icon
      class="section-gap"
    />
  </section>
  <CopyableLog
    v-if="customData.output"
    :content="customData.output"
    pre-class="terminal"
    copy-success-text="插件操作日志已复制"
  />
  <el-dialog
    v-model="customData.testResult.visible"
    :title="customData.testResult.title"
    width="min(760px, 88vw)"
    class="plugin-test-result-dialog"
  >
    <CopyableLog
      :content="customData.testResult.content"
      pre-class="terminal plugin-test-result"
      copy-success-text="插件测试日志已复制"
    />
    <template #footer>
      <el-button type="primary" @click="customData.testResult.visible = false">关闭</el-button>
    </template>
  </el-dialog>
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
