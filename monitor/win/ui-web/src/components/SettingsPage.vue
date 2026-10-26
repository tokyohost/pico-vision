<script setup>
import { t, styleLabel, taskLabel } from '../i18n'

import { computed, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'

const props = defineProps({
  metadata: { type: Object, required: true },
  settings: { type: Object, required: true },
  saving: { type: Boolean, required: true },
})

const emit = defineEmits(['save'])

const normalStyles = computed(() => props.metadata.styles.filter((item) => !item.idle))
const idleStyles = computed(() => props.metadata.styles.filter((item) => item.idle))
const idleDisabled = computed({
  get: () => !props.settings.idle_enabled,
  set: (disabled) => { props.settings.idle_enabled = !disabled },
})
const runningActions = reactive({})

/**
 * 验证 qBittorrent WebUI 账号。
 */
async function verifyQbittorrent() {
  try {
    await invoke('settings.verifyQbittorrent', {
      address: props.settings.qbittorrent_address,
      username: props.settings.qbittorrent_username,
      password: props.settings.qbittorrent_password,
    })
    ElMessage.success(t('ui.qbittorrent_account_verified'))
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 使用系统默认浏览器打开本机 HTTP 管理页面。
 */
async function openHttpManagement() {
  const port = Number(props.settings.http_port)
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    ElMessage.warning(t('ui.enter_a_valid_http_management_port_first'))
    return
  }
  try {
    await invoke('system.openExternalUrl', {
      url: `http://127.0.0.1:${port}`,
    })
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 请求根组件保存完整配置。
 */
function saveSettings() {
  emit('save')
}

/**
 * 返回数字配置项对应的小数步长。
 */
function numberStep(field) {
  const decimal = Number.isInteger(field.decimal) ? field.decimal : 1
  return 10 ** -decimal
}

/**
 * 返回下拉选项的显示名称。
 */
function optionLabel(option) {
  return typeof option === 'object' ? (option.label ?? option.zh_name ?? option.value) : option
}

/**
 * 返回下拉选项的实际配置值。
 */
function optionValue(option) {
  return typeof option === 'object' ? option.value : option
}

/**
 * 返回插件面板的兼容元素集合。
 */
function panelItems(panel) {
  return Array.isArray(panel.items) ? panel.items : panel.fields
}

/**
 * 调用插件公开动作并把受校验的补丁回填到当前表单。
 */
async function invokePluginAction(panel, item) {
  const loadingKey = `${panel.name}:${item.action}`
  if (runningActions[loadingKey]) return
  try {
    if (item.confirm) {
      await ElMessageBox.confirm(
        t('ui.run_value', { value0: item.zh_name || item.action }),
        t('ui.run_plugin_action'),
        { type: 'warning' },
      )
    }
    runningActions[loadingKey] = true
    const config = props.settings.custom_data_configs?.[panel.name] || {}
    const result = await invoke('data.invokeAction', {
      name: panel.name,
      action: item.action,
      config: JSON.parse(JSON.stringify(config)),
    })
    Object.assign(config, result.config_patch || {})
    for (const warning of result.warnings || []) ElMessage.warning(String(warning))
    ElMessage.success(result.message || t('ui.plugin_action_completed_settings_updated_save_to_apply'))
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error?.message || String(error))
    }
  } finally {
    delete runningActions[loadingKey]
  }
}

/**
 * 判断指定插件动作是否正在执行。
 */
function isActionRunning(panel, item) {
  return Boolean(runningActions[`${panel.name}:${item.action}`])
}
</script>

<template>
  <div class="page-grid">
    <el-card shadow="never">
      <template #header><span>{{ t('ui.display_settings') }}</span></template>
      <el-form label-position="top">
        <el-form-item :label="t('common.language')">
          <el-select v-model="settings.locale">
            <el-option value="zh-CN" label="简体中文" />
            <el-option value="en-US" label="English" />
          </el-select>
        </el-form-item>
        <div class="form-grid">
          <el-form-item :label="t('ui.screen_style')">
            <el-select v-model="settings.lcd_style">
              <el-option v-for="item in normalStyles" :key="item.name" :label="`${styleLabel(item)}（${item.name}）`" :value="item.name" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <template #label>
              <span class="idle-setting-label">
                <span>{{ t('ui.idle_style') }}</span>
                <el-checkbox v-model="idleDisabled" class="idle-disable-option">{{ t('ui.disable_idle_mode') }}</el-checkbox>
              </span>
            </template>
            <el-select v-model="settings.idle_style" :disabled="idleDisabled">
              <el-option v-for="item in idleStyles" :key="item.name" :label="`${styleLabel(item)}（${item.name}）`" :value="item.name" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('ui.screen_rotation')">
            <el-select v-model="settings.screen_rotation">
              <el-option :value="0" label="0°" />
              <el-option :value="180" label="180°" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('ui.idle_timeout_s')">
            <el-input-number v-model="settings.idle_timeout" :min="1" :disabled="idleDisabled" />
          </el-form-item>
        </div>
        <el-form-item :label="t('ui.brightness')">
          <el-slider v-model="settings.lcd_brightness" :min="1" :max="100" show-input />
        </el-form-item>
        <el-form-item :label="t('ui.network_rate_unit')">
          <el-radio-group v-model="settings.network_unit">
            <el-radio-button value="MB">MB/s</el-radio-button>
            <el-radio-button value="Mbps">Mb/s</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header><span>{{ t('ui.connection_collection') }}</span></template>
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item :label="t('ui.serial_port_blank_for_auto')"><el-input v-model="settings.port" :placeholder="t('ui.auto_detect')" /></el-form-item>
          <el-form-item :label="t('ui.client_name')"><el-input v-model="settings.websocket_client_name" /></el-form-item>
          <el-form-item :label="t('ui.ping_target')"><el-input v-model="settings.ping_target" /></el-form-item>
          <el-form-item :label="t('ui.json_send_interval_s')"><el-input-number v-model="settings.interval" :min="0.3" :step="0.1" /></el-form-item>
          <el-form-item>
            <template #label>
              <span class="form-label-with-help">
                <span>{{ t('ui.json_chunk_size_bytes') }}</span>
                <el-popover
                  trigger="hover"
                  placement="top"
                  :width="320"
                  :content="t('ui.applies_after_saving_and_is_capped_by_the_device')"
                >
                  <template #reference>
                    <el-icon class="form-help-icon" tabindex="0" :aria-label="t('ui.about_json_chunk_size')">
                      <QuestionFilled />
                    </el-icon>
                  </template>
                </el-popover>
              </span>
            </template>
            <el-select v-model="settings.json_chunk_size">
              <el-option :value="512" :label="t('ui.512_bytes')" />
              <el-option :value="1024" :label="t('ui.1024_bytes_1_kb')" />
              <el-option :value="2048" :label="t('ui.2048_bytes_2_kb')" />
              <el-option :value="4096" :label="t('ui.4096_bytes_4_kb_default')" />
              <el-option :value="8192" :label="t('ui.8192_bytes_8_kb')" />
              <el-option :value="16384" :label="t('ui.16384_bytes_16_kb')" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('ui.reconnect_interval_s')"><el-input-number v-model="settings.reconnect_interval" :min="0.1" :step="0.5" /></el-form-item>
          <el-form-item :label="t('ui.serial_probe_interval_s')"><el-input-number v-model="settings.serial_probe_interval" :min="0.1" :step="0.5" /></el-form-item>
          <el-form-item :label="t('ui.wi_fi_discovery')">
            <el-select v-model="settings.wifi_discovery_strategy">
              <el-option value="announcement" :label="t('ui.esp32_udp_announcements_recommended_scan_fallback')" />
              <el-option value="scan" :label="t('ui.scan_local_network_directly')" />
            </el-select>
          </el-form-item>
        </div>
        <el-switch v-model="settings.adaptive_transmit" :active-text="t('ui.adaptive_sending')" />
        <el-switch v-model="settings.collection_task_logs" :active-text="t('ui.collection_task_logs')" class="switch-gap" />
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header><span>{{ t('ui.qbittorrent_metrics') }}</span></template>
      <el-form label-position="top">
        <el-switch v-model="settings.qbittorrent_enabled" :active-text="t('ui.enable_metric_collection')" />
        <div class="form-grid section-gap">
          <el-form-item :label="t('ui.webui_url')"><el-input v-model="settings.qbittorrent_address" placeholder="http://127.0.0.1:8080" /></el-form-item>
          <el-form-item :label="t('ui.collection_interval_s')"><el-input-number v-model="settings.qbittorrent_interval" :min="0.1" :step="0.5" /></el-form-item>
          <el-form-item :label="t('ui.username')"><el-input v-model="settings.qbittorrent_username" /></el-form-item>
          <el-form-item :label="t('ui.password')"><el-input v-model="settings.qbittorrent_password" type="password" show-password /></el-form-item>
        </div>
        <el-button @click="verifyQbittorrent">{{ t('ui.verify_credentials') }}</el-button>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header><span>{{ t('ui.collection_task_intervals') }}</span></template>
      <div class="task-grid">
        <label v-for="name in metadata.defaultTasks" :key="name">
          <span>{{ taskLabel(name, metadata.taskNames[name]) }}</span>
          <el-input-number v-model="settings.collection_task_intervals[name]" :min="0.1" :step="0.1" size="small" />
        </label>
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header><span>{{ t('ui.plugin_market') }}</span></template>
      <el-form label-position="top">
        <el-form-item :label="t('ui.stable_market_url')">
          <el-input
            v-model="settings.market_url"
            placeholder="https://omni.mzlblog.com"
          />
        </el-form-item>
<!--        <el-alert-->
<!--          title="development 版本固定使用 http://localhost/market，正式版本使用此地址。"-->
<!--          type="info"-->
<!--          :closable="false"-->
<!--          show-icon-->
<!--        />-->
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header><span>{{ t('ui.http_management') }}</span></template>
      <el-form label-position="top">
        <el-switch
          v-model="settings.http_enabled"
          :active-text="t('ui.enable_lan_http_management')"
        />
        <div class="form-grid section-gap">
          <el-form-item :label="t('ui.listen_port')">
            <el-input-number
              v-model="settings.http_port"
              :min="1"
              :max="65535"
            />
          </el-form-item>
          <el-form-item label="Auth">
            <el-input
              v-model="settings.http_auth"
              type="password"
              show-password
            />
          </el-form-item>
        </div>
        <el-alert
          :title="t('ui.default_port_9876_enter_auth_on_first_access_it')"
          type="info"
          :closable="false"
          show-icon
        />
        <el-button
          class="section-gap"
          type="primary"
          :disabled="!settings.http_enabled"
          @click="openHttpManagement"
        >{{ t('ui.open_now') }}</el-button>
      </el-form>
    </el-card>

    <el-card v-for="panel in metadata.customDataPanels" :key="panel.name" shadow="never">
      <template #header>
        <div class="card-header">
          <span>{{ panel.chineseName }}（{{ panel.name }}）</span>
          <el-switch
            v-model="settings.custom_data_enabled[panel.name]"
            inline-prompt
            :active-text="t('ui.enable')"
            :inactive-text="t('ui.disable')"
          />
        </div>
      </template>
      <el-form v-if="settings.custom_data_configs?.[panel.name]" label-position="top">
        <div class="form-grid">
          <el-form-item
            v-for="field in panelItems(panel)"
            :key="field.kind === 'action' ? `action:${field.action}` : field.key"
            :label="field.kind === 'action' ? '' : (field.zh_name || field.name)"
          >
            <el-button
              v-if="field.kind === 'action'"
              :type="field.style || 'primary'"
              :loading="isActionRunning(panel, field)"
              @click="invokePluginAction(panel, field)"
            >
              {{ isActionRunning(panel, field) ? field.loading_text : field.zh_name }}
            </el-button>
            <el-input-number
              v-else-if="field.type === 'number'"
              v-model="settings.custom_data_configs[panel.name][field.key]"
              :min="field.min"
              :max="field.max"
              :precision="field.decimal"
              :step="numberStep(field)"
            />
            <el-switch
              v-else-if="field.type === 'boolean'"
              v-model="settings.custom_data_configs[panel.name][field.key]"
            />
            <el-select
              v-else-if="field.type === 'select'"
              v-model="settings.custom_data_configs[panel.name][field.key]"
            >
              <el-option
                v-for="option in field.options"
                :key="String(optionValue(option))"
                :label="optionLabel(option)"
                :value="optionValue(option)"
              />
            </el-select>
            <el-input
              v-else
              v-model="settings.custom_data_configs[panel.name][field.key]"
              :type="field.type === 'password' ? 'password' : field.type === 'textarea' ? 'textarea' : 'text'"
              :show-password="field.type === 'password'"
              :readonly="field.readonly"
            />
          </el-form-item>
        </div>
      </el-form>
    </el-card>
  </div>
  <div class="sticky-actions">
    <span class="sticky-action-hint">{{ t('ui.settings_apply_immediately_after_saving') }}</span>
    <el-button type="primary" :loading="saving" @click="saveSettings">{{ t('ui.save_settings') }}</el-button>
  </div>
</template>
