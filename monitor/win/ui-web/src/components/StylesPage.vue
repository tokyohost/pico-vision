<script setup>
import { onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { invoke } from '../bridge'

const props = defineProps({
  styles: { type: Array, required: true },
  settings: { type: Object, required: true },
  saving: { type: Boolean, required: true },
})

const emit = defineEmits(['save', 'catalog-updated'])
const remoteStyles = reactive({ loading: false, items: [], flash: {} })

/**
 * 刷新设备中的自定义屏幕样式。
 */
async function loadRemoteStyles() {
  remoteStyles.loading = true
  try {
    const result = await invoke('style.list')
    remoteStyles.items = (result.styles || []).filter((item) => item.type === 'custom')
    remoteStyles.flash = result.flash || {}
    if (result.catalog) emit('catalog-updated', result.catalog)
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    remoteStyles.loading = false
  }
}

/**
 * 选择并上传自定义屏幕样式。
 */
async function uploadStyle() {
  const existingNames = remoteStyles.items.map((item) => item.name)
  try {
    const result = await invoke('style.upload', { existingNames })
    if (!result.cancelled) {
      ElMessage.success('自定义样式上传成功')
      await loadRemoteStyles()
    }
  } catch (error) {
    if (/已存在/.test(error.message || '')) {
      try {
        await ElMessageBox.confirm(`${error.message}。是否覆盖？`, '覆盖样式', { type: 'warning' })
        await invoke('style.upload', { existingNames, overwrite: true })
        await loadRemoteStyles()
      } catch (nestedError) {
        if (nestedError !== 'cancel') ElMessage.error(nestedError?.message || String(nestedError))
      }
      return
    }
    ElMessage.error(error?.message || String(error))
  }
}

/**
 * 删除一个设备自定义样式。
 */
async function deleteStyle(item) {
  try {
    await ElMessageBox.confirm(`确定删除“${item.chinese_name}”吗？设备将自动重启。`, '删除样式', { type: 'warning' })
    await invoke('style.delete', { name: item.name, filename: item.filename })
    ElMessage.success('样式已删除')
    setTimeout(loadRemoteStyles, 4000)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error?.message || String(error))
  }
}

/**
 * 选择一个显示或待机样式。
 */
function selectStyle(item) {
  if (item.idle) props.settings.idle_style = item.name
  else props.settings.lcd_style = item.name
}

onMounted(loadRemoteStyles)
</script>

<template>
  <div class="page-title card-header">
    <div><h2>屏幕样式</h2><p>选择样式后保存，或上传设备自定义 Python 样式。</p></div>
    <div>
      <el-button :loading="remoteStyles.loading" @click="loadRemoteStyles">刷新设备</el-button>
      <el-button type="primary" @click="uploadStyle">上传样式</el-button>
    </div>
  </div>
  <div class="style-grid">
    <button
      v-for="item in styles"
      :key="item.name"
      :class="['style-card', { selected: settings.lcd_style === item.name || settings.idle_style === item.name }]"
      @click="selectStyle(item)"
    >
      <span class="style-icon"><el-icon><MagicStick /></el-icon></span>
      <strong>{{ item.chinese_name }}</strong>
      <small>{{ item.name }} · {{ item.type === 'custom' ? '自定义' : '内置' }}</small>
    </button>
  </div>
  <el-card v-if="remoteStyles.items.length" shadow="never" class="section-gap">
    <template #header><span>设备自定义样式</span></template>
    <el-table :data="remoteStyles.items">
      <el-table-column prop="chinese_name" label="中文名称" />
      <el-table-column prop="name" label="样式标识" />
      <el-table-column prop="filename" label="文件名" />
      <el-table-column prop="file_size" label="大小（字节）" width="120" />
      <el-table-column label="操作" width="90">
        <template #default="{ row }"><el-button text type="danger" @click="deleteStyle(row)">删除</el-button></template>
      </el-table-column>
    </el-table>
  </el-card>
  <div class="sticky-actions">
    <span>当前选择会与其他设置一并保存</span>
    <el-button type="primary" :loading="saving" @click="emit('save')">应用样式</el-button>
  </div>
</template>
