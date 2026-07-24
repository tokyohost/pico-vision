<script setup>
import { computed, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { invoke } from '../bridge'

const props = defineProps({
  device: { type: Object, required: true },
  applicationVersion: { type: String, required: true },
})

const checks = reactive({
  firmware: { loading: false, result: null, error: '' },
  sdk: { loading: false, result: null, error: '' },
  application: { loading: false, result: null, error: '' },
})

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
    description: '检查 ESP32-S3 底层 MicroPython SDK 镜像。',
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
</script>

<template>
  <div class="page-title card-header">
    <div>
      <h2>检查更新</h2>
      <p>分别检查设备固件、底层 SDK 与 OmniWatch 桌面应用。</p>
    </div>
    <el-button type="primary" :loading="Object.values(checks).some((state) => state.loading)" @click="checkAllUpdates">
      检查全部更新
    </el-button>
  </div>

  <div class="update-grid section-gap">
    <el-card v-for="item in updateItems" :key="item.key" shadow="never" class="update-card">
      <div class="update-card-heading">
        <span class="update-icon"><el-icon><component :is="item.icon" /></el-icon></span>
        <div>
          <h3>{{ item.title }}</h3>
          <p>{{ item.description }}</p>
        </div>
      </div>

      <div class="update-version-row">
        <span>当前版本</span>
        <strong>{{ checks[item.key].result?.currentVersion || item.current }}</strong>
      </div>
      <div class="update-version-row">
        <span>最新版本</span>
        <strong>{{ checks[item.key].result?.latestVersion || '--' }}</strong>
      </div>
      <div class="update-result-row">
        <el-tag :type="resultTagType(checks[item.key])" effect="dark">
          {{ resultText(checks[item.key]) }}
        </el-tag>
        <el-button
          type="primary"
          plain
          :disabled="item.disabled"
          :loading="checks[item.key].loading"
          @click="checkUpdate(item.key)"
        >立即检查</el-button>
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
    </el-card>
  </div>
</template>
