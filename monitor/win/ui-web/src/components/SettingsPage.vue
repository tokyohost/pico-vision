<script setup>
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { invoke } from '../bridge'

const props = defineProps({
  metadata: { type: Object, required: true },
  settings: { type: Object, required: true },
  saving: { type: Boolean, required: true },
})

const emit = defineEmits(['save'])

const normalStyles = computed(() => props.metadata.styles.filter((item) => !item.idle))
const idleStyles = computed(() => props.metadata.styles.filter((item) => item.idle))

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
    ElMessage.success('qBittorrent 账号验证成功')
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
</script>

<template>
  <div class="page-grid">
    <el-card shadow="never">
      <template #header><span>显示设置</span></template>
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="界面样式">
            <el-select v-model="settings.lcd_style">
              <el-option v-for="item in normalStyles" :key="item.name" :label="`${item.chinese_name}（${item.name}）`" :value="item.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="待机样式">
            <el-select v-model="settings.idle_style">
              <el-option v-for="item in idleStyles" :key="item.name" :label="`${item.chinese_name}（${item.name}）`" :value="item.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="屏幕旋转">
            <el-select v-model="settings.screen_rotation">
              <el-option :value="0" label="0°" />
              <el-option :value="180" label="180°" />
            </el-select>
          </el-form-item>
          <el-form-item label="空闲进入待机（秒）">
            <el-input-number v-model="settings.idle_timeout" :min="1" />
          </el-form-item>
        </div>
        <el-form-item label="背光亮度">
          <el-slider v-model="settings.lcd_brightness" :min="1" :max="100" show-input />
        </el-form-item>
        <el-form-item label="网络速率单位">
          <el-radio-group v-model="settings.network_unit">
            <el-radio-button value="MB">MB/s</el-radio-button>
            <el-radio-button value="Mbps">Mb/s</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header><span>连接与采集</span></template>
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="串口（留空自动识别）"><el-input v-model="settings.port" placeholder="自动识别" /></el-form-item>
          <el-form-item label="客户端名称"><el-input v-model="settings.websocket_client_name" /></el-form-item>
          <el-form-item label="Ping 目标"><el-input v-model="settings.ping_target" /></el-form-item>
          <el-form-item label="JSON 发送间隔（秒）"><el-input-number v-model="settings.interval" :min="0.3" :step="0.1" /></el-form-item>
          <el-form-item label="重连间隔（秒）"><el-input-number v-model="settings.reconnect_interval" :min="0.1" :step="0.5" /></el-form-item>
          <el-form-item label="串口探测间隔（秒）"><el-input-number v-model="settings.serial_probe_interval" :min="0.1" :step="0.5" /></el-form-item>
        </div>
        <el-switch v-model="settings.adaptive_transmit" active-text="自适应发送" />
        <el-switch v-model="settings.collection_task_logs" active-text="采集任务日志" class="switch-gap" />
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header><span>qBittorrent 指标</span></template>
      <el-form label-position="top">
        <el-switch v-model="settings.qbittorrent_enabled" active-text="启用指标采集" />
        <div class="form-grid section-gap">
          <el-form-item label="WebUI 地址"><el-input v-model="settings.qbittorrent_address" placeholder="http://127.0.0.1:8080" /></el-form-item>
          <el-form-item label="采集间隔（秒）"><el-input-number v-model="settings.qbittorrent_interval" :min="0.1" :step="0.5" /></el-form-item>
          <el-form-item label="用户名"><el-input v-model="settings.qbittorrent_username" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="settings.qbittorrent_password" type="password" show-password /></el-form-item>
        </div>
        <el-button @click="verifyQbittorrent">验证账号密码</el-button>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header><span>采集任务频率</span></template>
      <div class="task-grid">
        <label v-for="name in metadata.defaultTasks" :key="name">
          <span>{{ metadata.taskNames[name] || name }}</span>
          <el-input-number v-model="settings.collection_task_intervals[name]" :min="0.1" :step="0.1" size="small" />
        </label>
      </div>
    </el-card>

    <el-card v-for="panel in metadata.customDataPanels" :key="panel.name" shadow="never">
      <template #header><span>{{ panel.chineseName }}（{{ panel.name }}）</span></template>
      <el-form v-if="settings.custom_data_configs?.[panel.name]" label-position="top">
        <div class="form-grid">
          <el-form-item v-for="field in panel.fields" :key="field.key" :label="field.zh_name || field.name">
            <el-input-number
              v-if="field.type === 'number'"
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
            />
          </el-form-item>
        </div>
      </el-form>
    </el-card>
  </div>
  <div class="sticky-actions">
    <span class="sticky-action-hint">保存后配置将立即热更新</span>
    <el-button type="primary" :loading="saving" @click="saveSettings">保存配置</el-button>
  </div>
</template>
