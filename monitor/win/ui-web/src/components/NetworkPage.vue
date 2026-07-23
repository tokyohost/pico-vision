<script setup>
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
    ElMessage.success('连接请求已发送')
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
    await ElMessageBox.confirm(`确定忘记网络“${ssid}”吗？`, '忘记网络', { type: 'warning' })
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
    ElMessage.success('客户端策略已保存')
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
  <div class="two-columns">
    <el-card shadow="never" v-loading="wifi.loading">
      <template #header>
        <div class="card-header">
          <span>Wi-Fi 网络</span>
          <el-button text @click="scanWifi">重新扫描</el-button>
        </div>
      </template>
      <el-input v-model="wifi.ssid" placeholder="网络名称" class="section-gap" />
      <el-input v-model="wifi.password" type="password" show-password placeholder="网络密码" class="section-gap" />
      <el-button type="primary" class="section-gap" :loading="wifi.connecting" :disabled="!wifi.ssid" @click="connectWifi">连接网络</el-button>
      <el-table :data="wifi.networks" class="section-gap" highlight-current-row @row-click="selectWifi">
        <el-table-column prop="ssid" label="SSID" />
        <el-table-column prop="state_label" label="状态" width="90" />
        <el-table-column label="信号" width="90">
          <template #default="{ row }">{{ Number.isInteger(row.rssi) ? `${row.rssi} dBm` : '--' }}</template>
        </el-table-column>
        <el-table-column prop="security_label" label="安全性" width="100" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button v-if="row.saved" text type="danger" @click.stop="forgetWifi(row.ssid)">忘记</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" v-loading="websocket.loading">
      <template #header>
        <div class="card-header">
          <span>WebSocket 客户端</span>
          <el-button text @click="loadWebsocketClients">刷新</el-button>
        </div>
      </template>
      <el-empty v-if="!websocket.clients.length" description="暂无客户端记录" />
      <div v-for="client in websocket.clients" :key="client.id" class="client-row">
        <div>
          <strong>{{ client.name || client.id }}</strong>
          <small>{{ client.active ? '当前连接' : (client.enabled === false ? '已禁用' : '允许') }} · {{ client.last_peer || '无最近地址' }} · {{ client.connections || 0 }} 次</small>
          <small>{{ client.id }}</small>
        </div>
        <el-switch v-model="client.enabled" />
        <el-input-number v-model="client.priority" :min="-1000" :max="1000" size="small" />
        <el-button size="small" @click="saveClient(client)">保存</el-button>
      </div>
    </el-card>
  </div>
</template>
