<script setup>
import { computed } from 'vue'

const props = defineProps({
  activePage: { type: String, required: true },
  applicationName: { type: String, required: true },
  version: { type: String, required: true },
  device: { type: Object, required: true },
  menuItems: { type: Array, required: true },
})

const emit = defineEmits(['navigate'])

const statusText = computed(() => {
  if (props.device.connected === true) return '设备在线'
  if (props.device.connected === false) return '连接异常'
  return '正在等待设备'
})

const statusType = computed(() => {
  if (props.device.connected === true) return 'success'
  if (props.device.connected === false) return 'danger'
  return 'warning'
})

/**
 * 把菜单选择事件交给根组件统一切换页面。
 */
function navigate(page) {
  emit('navigate', page)
}
</script>

<template>
  <el-aside width="246px" class="sidebar">
    <div class="brand">
      <div class="brand-mark"><el-icon><Cpu /></el-icon></div>
      <div>
        <strong>{{ applicationName }}</strong>
        <small>控制中心</small>
      </div>
    </div>
    <el-menu :default-active="activePage" class="navigation" @select="navigate">
      <el-menu-item v-for="[key, label, icon] in menuItems" :key="key" :index="key">
        <el-icon><component :is="icon" /></el-icon>
        <span>{{ label }}</span>
      </el-menu-item>
    </el-menu>
    <div class="sidebar-status">
      <el-tag :type="statusType" effect="dark" round>{{ statusText }}</el-tag>
      <small>版本 {{ version }}</small>
    </div>
  </el-aside>
</template>
