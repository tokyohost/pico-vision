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
  <div class="network-stack">
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
      <el-table :data="wifi.networks" class="section-gap theme-table wifi-table" highlight-current-row @row-click="selectWifi">
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
      <el-table
        :data="websocket.clients"
        class="theme-table websocket-table"
        empty-text="暂无客户端记录"
        show-header
      >
        <el-table-column label="客户端" min-width="210">
          <template #default="{ row }">
            <div class="client-identity">
              <strong>{{ row.name || row.id }}</strong>
              <small>{{ row.id }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.active" type="success" size="small">当前连接</el-tag>
            <el-tag v-else-if="row.enabled === false" type="info" size="small">已禁用</el-tag>
            <el-tag v-else type="primary" size="small">允许</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_peer" label="最近地址" min-width="180">
          <template #default="{ row }">{{ row.last_peer || '无最近地址' }}</template>
        </el-table-column>
        <el-table-column prop="connections" label="连接次数" width="100">
          <template #default="{ row }">{{ row.connections || 0 }}</template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }"><el-switch v-model="row.enabled" /></template>
        </el-table-column>
        <el-table-column width="140">
          <template #header>
            <span class="priority-header">
              <span>优先级</span>
              <el-tooltip
                content="取值范围为 -1000 至 1000，数值越大优先级越高。新客户端仅在优先级严格高于当前客户端时才能抢占连接，相同优先级不会抢占。"
                placement="top"
                :show-after="200"
              >
                <span class="priority-help" tabindex="0" aria-label="查看优先级说明">!</span>
              </el-tooltip>
            </span>
          </template>
          <template #default="{ row }">
            <el-input-number v-model="row.priority" :min="-1000" :max="1000" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="saveClient(row)">保存</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
