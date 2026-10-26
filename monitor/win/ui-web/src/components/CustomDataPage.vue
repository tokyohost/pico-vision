<script setup>
import { t } from '../i18n'

import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke, isHttpBridge, uploadFile } from '../bridge'
import { runWithGlobalLoading } from '../globalLoading'
import CopyableLog from './CopyableLog.vue'

const emit = defineEmits(['plugins-changed', 'catalog-updated'])
const dataZipInput = ref(null)
const dataDirectoryInput = ref(null)

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
  if (isHttpBridge()) {
    const input = action === 'data.importDirectory'
      ? dataDirectoryInput.value
      : dataZipInput.value
    input?.click()
    return
  }
  await importCustomDataPayload(action, sourceLabel, {})
}

/**
 * 使用指定参数导入插件，并在重复时复用浏览器上传内容或本地来源路径。
 */
async function importCustomDataPayload(action, sourceLabel, payload) {
  try {
    let result = await invoke(action, payload)
    if (result.requiresOverwrite) {
      await ElMessageBox.confirm(
        t('ui.value_replacing_will_delete_the_old_plugin_directory_and', { value0: result.message }),
        t('ui.replace_plugin'),
        { type: 'warning', confirmButtonText: t('ui.confirm_replacement') },
      )
      result = await invoke(action, payload.uploadId
        ? { ...payload, overwrite: true }
        : { overwrite: true, sourcePath: result.sourcePath })
    }
    if (!result.cancelled) {
      ElMessage.success(t('ui.value_value_imported', { value0: sourceLabel, value1: result.chineseName }))
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
 * 接收浏览器选择的 ZIP 或目录文件，并调用对应插件导入 action。
 */
async function handleBrowserImport(event, directory) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length) return
  const action = directory ? 'data.importDirectory' : 'data.import'
  const sourceLabel = directory ? t('ui.directory_plugin') : t('ui.plugin')
  try {
    const upload = await uploadFile(directory ? 'data-directory' : 'data', files)
    await importCustomDataPayload(action, sourceLabel, { uploadId: upload.uploadId })
  } catch (error) {
    ElMessage.error(error?.message || String(error))
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
      title: t('ui.installing_environment_for_value', { value0: item.chineseName }),
      message: t('ui.preparing_isolated_plugin_environment'),
      progress: 8,
      successMessage: t('ui.plugin_environment_installed'),
    }, async ({ progress, log }) => {
      progress(20, t('ui.checking_python_runtime_and_virtual_environment'))
      progress(35, t('ui.creating_environment_and_installing_requirements_txt_dependencies'))
      const response = await invoke('data.installDependencies', { name: item.name })
      for (const line of String(response.output || '').split(/\r?\n/)) log(line)
      progress(92, t('ui.refreshing_plugin_environment_status'))
      return response
    })
    customData.output = result.output || result.status || t('ui.environment_installed')
    ElMessage.success(t('ui.plugin_value_value', { value0: item.chineseName, value1: result.status }))
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
    ElMessage.success(enabled ? t('ui.plugin_enabled') : t('ui.plugin_disabled'))
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
    customData.testResult.title = t('ui.value_test_result', { value0: item.chineseName })
    customData.testResult.content = result.output || t('ui.test_completed_the_plugin_returned_no_content')
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
    customData.detail.title = result.title || t('ui.value_plugin_description', { value0: item.chineseName })
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
      title: t('ui.syncing_value', { value0: item.boundStyle }),
      message: t('ui.preparing_to_validate_linked_style'),
      progress: 8,
      successMessage: t('ui.linked_style_synced'),
    }, async ({ progress, log }) => {
      progress(25, t('ui.validating_style_filename_encoding_and_required_methods'))
      progress(45, t('ui.sending_style_to_device'))
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
                  t('ui.sending_style_to_device_value_value_bytes', { value0: item.uploaded_bytes, value1: item.total_bytes }),
                )
              } else if (item.stage === 'begin') {
                log(t('ui.device_ready_to_receive_value_bytes', { value0: item.total_bytes }))
              } else if (item.stage === 'finish') {
                progress(85, t('ui.style_sent_value_value_bytes', { value0: item.total_bytes, value1: item.total_bytes }))
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
      progress(88, t('ui.style_received_refreshing_device_style_catalog'))
      return response
    })
    if (result.catalog) emit('catalog-updated', result.catalog)
    ElMessage.success(t('ui.linked_style_value_synced_to_device', { value0: item.boundStyle }))
  } catch (error) {
    if (!overwrite && error?.code === 'file_exists') {
      try {
        await ElMessageBox.confirm(t('ui.value_replace_the_style_on_the_device', { value0: error.message }), t('ui.replace_linked_style'), { type: 'warning' })
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
    const cleanupHint = item.hasUninstall ? t('ui.running_the_plugin_uninstall_cleanup_hook_first') : ''
    await ElMessageBox.confirm(
      t('ui.delete_plugin_value_and_its_isolated_environmentvalue', { value0: item.chineseName, value1: cleanupHint }),
      t('ui.delete_plugin'),
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
    <el-button @click="importCustomData('data.importDirectory', t('ui.directory_plugin'))">{{ t('ui.import_directory') }}</el-button>
    <el-button type="primary" @click="importCustomData('data.import', t('ui.plugin'))">{{ t('ui.import_zip') }}</el-button>
    <input
      v-if="isHttpBridge()"
      ref="dataDirectoryInput"
      type="file"
      webkitdirectory
      hidden
      @change="handleBrowserImport($event, true)"
    />
    <input
      v-if="isHttpBridge()"
      ref="dataZipInput"
      type="file"
      accept=".zip"
      hidden
      @change="handleBrowserImport($event, false)"
    />
  </div>
  <section class="custom-data-section section-gap" v-loading="customData.loading">
    <el-empty v-if="!customData.items.length" :description="t('ui.no_plugins')" />
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
              :alt="t('ui.value_preview', { value0: item.chineseName })"
              class="custom-data-preview"
            />
            <span v-else>{{ t('ui.no_preview') }}</span>
          </div>
          <div class="custom-data-card-content">
            <div class="custom-data-card-header">
              <div>
                <h3>{{ item.chineseName }}</h3>
                <p>{{ item.name }}</p>
              </div>
              <div class="custom-data-enabled">
                <span>{{ t('ui.enable') }}</span>
                <el-switch
                  v-model="item.enabled"
                  :loading="customData.togglingNames.includes(item.name)"
                  @change="(enabled) => setCustomDataEnabled(item, enabled)"
                />
              </div>
            </div>
            <div class="custom-data-meta">
              <div><span>JSON Key</span><strong>{{ item.key }}</strong></div>
              <div><span>{{ t('ui.collection_interval') }}</span><strong>{{ item.interval }}{{ t('ui.s') }}</strong></div>
              <div><span>{{ t('ui.isolated_environment') }}</span><strong>{{ item.environment }}</strong></div>
              <div class="custom-data-meta-full"><span>{{ t('ui.linked_style') }}</span><strong>{{ item.boundStyle || t('ui.not_linked') }}</strong></div>
              <div class="custom-data-meta-full"><span>{{ t('ui.version_number') }}</span><strong>{{ item.version || t('ui.unknown') }}</strong></div>
            </div>
          </div>
        </div>
        <div class="custom-data-actions">
          <el-button
            text
            size="small"
            :loading="isInstallingEnvironment(item)"
            @click="installEnvironment(item)"
          >{{ t('ui.install_environment') }}</el-button>
          <el-button text size="small" @click="testCustomData(item)">{{ t('ui.test') }}</el-button>
          <el-button v-if="item.hasDetail" text size="small" @click="openPluginDetail(item)">{{ t('ui.description') }}</el-button>
          <el-button v-if="item.boundStyle" text size="small" type="primary" @click="syncBoundStyle(item)">{{ t('ui.sync_style') }}</el-button>
          <el-button text size="small" type="danger" @click="deleteCustomData(item)">{{ t('ui.delete') }}</el-button>
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
    :copy-success-text="t('ui.plugin_operation_logs_copied')"
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
      :copy-success-text="t('ui.plugin_test_logs_copied')"
    />
    <template #footer>
      <el-button type="primary" @click="customData.testResult.visible = false">{{ t('ui.close') }}</el-button>
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
