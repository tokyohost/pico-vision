<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { invoke } from './bridge'
import AboutPage from './components/AboutPage.vue'
import AppSidebar from './components/AppSidebar.vue'
import CustomDataPage from './components/CustomDataPage.vue'
import DevicePage from './components/DevicePage.vue'
import GlobalLoadingOverlay from './components/GlobalLoadingOverlay.vue'
import LogsPage from './components/LogsPage.vue'
import NetworkPage from './components/NetworkPage.vue'
import SettingsPage from './components/SettingsPage.vue'
import StylesPage from './components/StylesPage.vue'
import UpdatePage from './components/UpdatePage.vue'

const loading = ref(true)
const saving = ref(false)
const activePage = ref('settings')
const metadata = reactive({
  applicationName: 'OmniWatch',
  version: 'development',
  styles: [],
  taskNames: {},
  defaultTasks: [],
  customDataPanels: [],
  dataDirectory: '',
  about: {
    author: '',
    wechat: '',
    repository: '',
    qrDataUrl: '',
  },
})
const settings = reactive({})
const device = reactive({ connected: null })
let deviceRefreshTimer = null
let deviceRefreshPending = false

const menuItems = [
  ['settings', '设置', 'Setting', '配置屏幕显示、数据采集、设备连接与任务频率。'],
  ['device', '设备管理', 'Monitor', '查看设备状态，管理固件升级与底层 SDK 刷写。'],
  ['network', '无线与客户端', 'Connection', '管理无线网络档案、连接优先级与客户端访问状态。'],
  ['styles', '屏幕样式', 'Brush', '选择屏幕与待机样式，预览详情或管理设备自定义样式。'],
  ['data', '自定义数据', 'DataAnalysis', '管理自定义数据插件及其采集配置。'],
  ['update', '检查更新', 'Upload', '检查设备固件、底层 SDK 与桌面控制中心的新版本。'],
  ['logs', '运行日志', 'Document', '查看实时运行记录，定位采集、通信与设备异常。'],
  ['about', '关于', 'InfoFilled', '查看应用版本、作者信息与本地数据目录。'],
]

const pageTitle = computed(
  () => menuItems.find((item) => item[0] === activePage.value)?.[1] || '',
)
const pageDescription = computed(
  () => menuItems.find((item) => item[0] === activePage.value)?.[3] || '',
)

/**
 * 读取应用首屏数据。
 */
async function bootstrap() {
  loading.value = true
  try {
    const data = await invoke('app.bootstrap')
    Object.assign(metadata, data)
    Object.assign(settings, data.settings)
    Object.assign(device, data.device)
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    loading.value = false
  }
}

/**
 * 静默刷新全局设备连接状态，确保侧边栏与后台实时状态一致。
 */
async function refreshDeviceStatus() {
  if (deviceRefreshPending) return
  deviceRefreshPending = true
  try {
    const latestDevice = await invoke('device.status')
    Object.assign(device, latestDevice || { connected: null })
  } catch {
    // 后台进程短暂切换时保留最近一次状态，下一轮自动重试。
  } finally {
    deviceRefreshPending = false
  }
}

/**
 * 保存所有设置并由 Python 桥接层热更新后台工作进程。
 */
async function saveSettings() {
  saving.value = true
  try {
    await invoke('settings.save', {
      settings: JSON.parse(JSON.stringify(settings)),
    })
    ElMessage.success('配置已保存并生效')
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    saving.value = false
  }
}

/**
 * 切换当前功能页面。
 */
function navigate(page) {
  activePage.value = page
}

/**
 * 更新设备返回的样式目录。
 */
function updateStyleCatalog(catalog) {
  metadata.styles = Array.isArray(catalog) ? catalog : metadata.styles
}

/**
 * 响应托盘菜单对已打开窗口的导航请求。
 */
function handleExternalNavigation(event) {
  navigate(event.detail || 'settings')
}

/**
 * 实时采用设备物理按键选择的屏幕样式。
 */
function handleDeviceConfigChange(event) {
  const key = String(event.detail?.key || '').trim()
  if (key && Object.prototype.hasOwnProperty.call(settings, key)) {
    settings[key] = event.detail.value
  }
}

onMounted(async () => {
  window.__omniwatchConfigChangeReady = true
  window.addEventListener('omniwatch:navigate', handleExternalNavigation)
  window.addEventListener('omniwatch:config-change', handleDeviceConfigChange)
  await bootstrap()
  deviceRefreshTimer = window.setInterval(refreshDeviceStatus, 1000)
})

onBeforeUnmount(() => {
  window.__omniwatchConfigChangeReady = false
  window.removeEventListener('omniwatch:navigate', handleExternalNavigation)
  window.removeEventListener('omniwatch:config-change', handleDeviceConfigChange)
  if (deviceRefreshTimer !== null) window.clearInterval(deviceRefreshTimer)
})
</script>

<template>
  <GlobalLoadingOverlay />
  <el-container class="shell" v-loading="loading">
    <AppSidebar
      :active-page="activePage"
      :application-name="metadata.applicationName"
      :version="metadata.version"
      :device="device"
      :menu-items="menuItems"
      @navigate="navigate"
    />

    <el-container>
      <el-header class="topbar">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p>{{ pageDescription }}</p>
        </div>
        <el-button circle @click="bootstrap">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </el-header>

      <el-main class="content">
        <SettingsPage
          v-if="activePage === 'settings'"
          :metadata="metadata"
          :settings="settings"
          :saving="saving"
          @save="saveSettings"
        />
        <DevicePage
          v-else-if="activePage === 'device'"
          :device="device"
          :settings="settings"
          :saving="saving"
          @save="saveSettings"
        />
        <NetworkPage v-else-if="activePage === 'network'" />
        <StylesPage
          v-else-if="activePage === 'styles'"
          :styles="metadata.styles"
          :settings="settings"
          :saving="saving"
          @save="saveSettings"
          @catalog-updated="updateStyleCatalog"
        />
        <CustomDataPage v-else-if="activePage === 'data'" @plugins-changed="bootstrap" />
        <UpdatePage v-else-if="activePage === 'update'" :device="device" :application-version="metadata.version" />
        <LogsPage v-else-if="activePage === 'logs'" />
        <AboutPage v-else :metadata="metadata" />
      </el-main>
    </el-container>
  </el-container>
</template>
