<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { invoke } from './bridge'
import AboutPage from './components/AboutPage.vue'
import AppSidebar from './components/AppSidebar.vue'
import CustomDataPage from './components/CustomDataPage.vue'
import DevicePage from './components/DevicePage.vue'
import LogsPage from './components/LogsPage.vue'
import NetworkPage from './components/NetworkPage.vue'
import SettingsPage from './components/SettingsPage.vue'
import StylesPage from './components/StylesPage.vue'

const loading = ref(true)
const saving = ref(false)
const activePage = ref('settings')
const metadata = reactive({
  applicationName: 'OmniWatch',
  version: 'development',
  styles: [],
  taskNames: {},
  defaultTasks: [],
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

const menuItems = [
  ['settings', '设置', 'Setting'],
  ['device', '设备管理', 'Monitor'],
  ['network', '无线与客户端', 'Connection'],
  ['styles', '屏幕样式', 'Brush'],
  ['data', '自定义数据', 'DataAnalysis'],
  ['logs', '运行日志', 'Document'],
  ['about', '关于', 'InfoFilled'],
]

const pageTitle = computed(
  () => menuItems.find((item) => item[0] === activePage.value)?.[1] || '',
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

onMounted(() => {
  window.addEventListener('omniwatch:navigate', handleExternalNavigation)
  bootstrap()
})

onBeforeUnmount(() => {
  window.removeEventListener('omniwatch:navigate', handleExternalNavigation)
})
</script>

<template>
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
          <p>集中管理 OmniWatch 采集、显示与设备连接</p>
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
        <CustomDataPage v-else-if="activePage === 'data'" />
        <LogsPage v-else-if="activePage === 'logs'" />
        <AboutPage v-else :metadata="metadata" />
      </el-main>
    </el-container>
  </el-container>
</template>
