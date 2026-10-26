<script setup>
import { t } from '../i18n'

import { onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'

const wifi = reactive({
  loading: false,
  connecting: false,
  networks: [],
  ssid: '',
  password: '',
})
const websocket = reactive({ loading: false, clients: [] })

/**
 * 扫描附近无线网络。
 */
async function scanWifi() {
  wifi.loading = true
  try {
    const result = await invoke('wifi.list')
    wifi.networks = result.networks || []
    const savedSsid = result.wifi?.ssid
    if (savedSsid && !wifi.ssid) wifi.ssid = savedSsid
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    wifi.loading = false
  }
}

/**
 * 把选中的无线网络载入连接表单。
 */
function selectWifi(network) {
  wifi.ssid = network?.ssid || ''
  wifi.password = ''
}

/**
 * 连接当前选择的无线网络。
 */
async function connectWifi() {
  wifi.connecting = true
  try {
    await invoke('wifi.connect', { ssid: wifi.ssid, password: wifi.password })
    ElMessage.success(t('ui.connection_requested'))
    await scanWifi()
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    wifi.connecting = false
  }
}

/**
 * 忘记指定无线网络。
 */
async function forgetWifi(ssid) {
  try {
    await ElMessageBox.confirm(t('ui.forget_network_value', { value0: ssid }), t('ui.forget_network'), { type: 'warning' })
    await invoke('wifi.forget', { ssid })
    await scanWifi()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error?.message || String(error))
  }
}

/**
 * 读取 WebSocket 客户端策略。
 */
async function loadWebsocketClients() {
  websocket.loading = true
  try {
    const result = await invoke('websocket.list')
    websocket.clients = result.clients || []
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    websocket.loading = false
  }
}

/**
 * 保存一个客户端策略。
 */
async function saveClient(client) {
  try {
    await invoke('websocket.update', {
      id: client.id,
      enabled: client.enabled,
      priority: client.priority,
    })
    ElMessage.success(t('ui.client_policy_saved'))
    await loadWebsocketClients()
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  }
}

onMounted(() => {
  scanWifi()
  loadWebsocketClients()
})
</script>

<template>
  <div class="network-stack">
    <el-card shadow="never" v-loading="wifi.loading">
      <template #header>
        <div class="card-header">
          <span>{{ t('ui.wi_fi_networks') }}</span>
          <el-button text @click="scanWifi">{{ t('ui.rescan') }}</el-button>
        </div>
      </template>
      <el-input v-model="wifi.ssid" :placeholder="t('ui.network_name')" class="section-gap" />
      <el-input v-model="wifi.password" type="password" show-password :placeholder="t('ui.network_password')" class="section-gap" />
      <el-button type="primary" class="section-gap" :loading="wifi.connecting" :disabled="!wifi.ssid" @click="connectWifi">{{ t('ui.connect') }}</el-button>
      <el-table :data="wifi.networks" class="section-gap theme-table wifi-table" highlight-current-row @row-click="selectWifi">
        <el-table-column prop="ssid" label="SSID" />
        <el-table-column prop="state_label" :label="t('ui.status')" width="90" />
        <el-table-column :label="t('ui.signal')" width="90">
          <template #default="{ row }">{{ Number.isInteger(row.rssi) ? `${row.rssi} dBm` : '--' }}</template>
        </el-table-column>
        <el-table-column prop="security_label" :label="t('ui.security')" width="100" />
        <el-table-column :label="t('ui.actions')" width="90">
          <template #default="{ row }">
            <el-button v-if="row.saved" text type="danger" @click.stop="forgetWifi(row.ssid)">{{ t('ui.forget') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" v-loading="websocket.loading">
      <template #header>
        <div class="card-header">
          <span>{{ t('ui.websocket_clients') }}</span>
          <el-button text @click="loadWebsocketClients">{{ t('ui.refresh') }}</el-button>
        </div>
      </template>
      <el-table
        :data="websocket.clients"
        class="theme-table websocket-table"
        :empty-text="t('ui.no_client_records')"
        show-header
      >
        <el-table-column :label="t('ui.client')" min-width="210">
          <template #default="{ row }">
            <div class="client-identity">
              <strong>{{ row.name || row.id }}</strong>
              <small>{{ row.id }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('ui.status')" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.active" type="success" size="small">{{ t('ui.active_connection') }}</el-tag>
            <el-tag v-else-if="row.enabled === false" type="info" size="small">{{ t('ui.disabled') }}</el-tag>
            <el-tag v-else type="primary" size="small">{{ t('ui.allow') }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_peer" :label="t('ui.last_address')" min-width="180">
          <template #default="{ row }">{{ row.last_peer || t('ui.no_recent_address') }}</template>
        </el-table-column>
        <el-table-column prop="connections" :label="t('ui.connection_count')" width="100">
          <template #default="{ row }">{{ row.connections || 0 }}</template>
        </el-table-column>
        <el-table-column :label="t('ui.enable')" width="90">
          <template #default="{ row }"><el-switch v-model="row.enabled" /></template>
        </el-table-column>
        <el-table-column min-width="210">
          <template #header>
            <span class="priority-header">
              <span>{{ t('ui.priority') }}</span>
              <el-tooltip
                :content="t('ui.range_1000_to_1000_higher_values_have_higher_priority')"
                placement="top"
                :show-after="200"
              >
                <span class="priority-help" tabindex="0" :aria-label="t('ui.about_priorities')">!</span>
              </el-tooltip>
            </span>
          </template>
          <template #default="{ row }">
            <el-input-number v-model="row.priority" :min="-1000" :max="1000" size="small" />
          </template>
        </el-table-column>
        <el-table-column :label="t('ui.actions')" width="90" align="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="saveClient(row)">{{ t('ui.save') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
