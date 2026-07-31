<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { invoke } from '../bridge'
import { runWithGlobalLoading } from '../globalLoading'

const props = defineProps({
  applicationVersion: { type: String, required: true },
  configuredUrl: { type: String, default: '' },
})
const marketFrame = ref(null)
const installedPlugins = ref([])
const inventoryReady = ref(false)
const monitorChannel = (
  window.crypto?.randomUUID?.()
  || `monitor-${Date.now()}-${Math.random().toString(16).slice(2)}`
)

/**
 * 按应用版本解析市场地址，并追加嵌入模式和深色主题参数。
 */
const marketUrl = computed(() => {
  const baseUrl = props.applicationVersion === 'development'
    ? 'http://localhost/market'
    : String(props.configuredUrl || '').trim()
  if (!baseUrl) return ''
  try {
    const url = new URL(baseUrl)
    if (!['http:', 'https:'].includes(url.protocol)) return ''
    url.searchParams.set('embed', '1')
    url.searchParams.set('theme', 'dark')
    url.searchParams.set('omniwatchChannel', monitorChannel)
    return url.toString()
  } catch {
    return ''
  }
})

/**
 * 等待指定毫秒数，供安装状态轮询控制频率。
 */
function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

/**
 * 将 Monitor 身份和通信通道注入已加载的市场 iframe。
 */
async function loadInstalledPlugins() {
  try {
    const result = await invoke('data.list')
    installedPlugins.value = (result.items || []).map((item) => ({
      key: String(item.key || ''),
      version: String(item.version || '')
    })).filter((item) => item.key)
  } catch (error) {
    installedPlugins.value = []
    ElMessage.warning(`读取已安装插件失败：${error?.message || String(error)}`)
  } finally {
    inventoryReady.value = true
  }
}

/**
 * 将 Monitor 身份、通信通道和已安装插件注入市场 iframe。
 */
function injectMonitorHook() {
  if (!marketFrame.value?.contentWindow || !marketUrl.value || !inventoryReady.value) return
  const targetOrigin = new URL(marketUrl.value).origin
  const installedPluginSnapshot = installedPlugins.value.map((plugin) => ({
    key: String(plugin.key || ''),
    version: String(plugin.version || ''),
  }))
  marketFrame.value.contentWindow.postMessage({
    source: 'omniwatch-monitor',
    type: 'host-ready',
    channel: monitorChannel,
    version: props.applicationVersion,
    installedPlugins: installedPluginSnapshot,
  }, targetOrigin)
}

/**
 * 在全局进度日志弹框中轮询插件下载安装状态。
 */
async function installMarketPlugin(payload) {
  const pluginName = String(payload?.pluginName || '未命名插件')
  const pluginType = payload?.pluginType === 'style' ? 'style' : 'plugin'
  const isStyle = pluginType === 'style'
  await runWithGlobalLoading({
    title: `正在安装“${pluginName}”`,
    message: 'Monitor 已获取下载地址，正在创建安装任务',
    progress: 2,
    successMessage: isStyle ? 'Style 界面样式安装完成' : '插件下载安装完成',
  }, async ({ progress, log }) => {
    await invoke('market.install', {
      pluginName,
      pluginType,
      downloadUrl: String(payload?.downloadUrl || ''),
    })
    let renderedLogCount = 0
    while (true) {
      const status = await invoke('market.installStatus')
      const logs = String(status.logs || '').split(/\r?\n/).filter(Boolean)
      for (const message of logs.slice(renderedLogCount)) log(message)
      renderedLogCount = logs.length
      progress(status.progress)
      if (!status.busy) {
        if (status.status === 'success') return status.result
        throw new Error(status.message || '插件安装失败')
      }
      await delay(250)
    }
  })
  ElMessage.success(
    isStyle
      ? `Style“${pluginName}”已安装，可在屏幕样式中查看`
      : `插件“${pluginName}”已安装，可在插件管理中启用`
  )
  await loadInstalledPlugins()
  injectMonitorHook()
}

/**
 * 接收市场 iframe 通过浏览器钩子发出的安装请求。
 */
async function handleMarketMessage(event) {
  if (
    event.source !== marketFrame.value?.contentWindow
    || event.data?.source !== 'omniwatch-market'
    || event.data?.channel !== monitorChannel
  ) return
  const expectedOrigin = new URL(marketUrl.value).origin
  if (event.origin !== expectedOrigin) return
  if (event.data?.type === 'market-ready') {
    injectMonitorHook()
    return
  }
  if (event.data?.type !== 'install-plugin') return
  try {
    await installMarketPlugin(event.data.payload)
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

window.addEventListener('message', handleMarketMessage)
onMounted(loadInstalledPlugins)
onBeforeUnmount(() => window.removeEventListener('message', handleMarketMessage))
</script>

<template>
  <section class="market-frame-page">
    <iframe
      v-if="marketUrl && inventoryReady"
      ref="marketFrame"
      class="market-frame"
      :src="marketUrl"
      title="OmniWatch 插件市场"
      referrerpolicy="strict-origin-when-cross-origin"
      allow="clipboard-read; clipboard-write"
      @load="injectMonitorHook"
    />
    <div v-else-if="!marketUrl" class="market-frame-empty">
      <el-empty description="尚未配置有效的插件市场地址">
        <template #description>
          <p>请在“设置 → 插件市场”中填写以 http:// 或 https:// 开头的市场地址。</p>
        </template>
      </el-empty>
    </div>
    <div v-else class="market-frame-empty">
      <el-icon class="is-loading"><Loading /></el-icon>
      <p>正在读取已安装插件...</p>
    </div>
  </section>
</template>
