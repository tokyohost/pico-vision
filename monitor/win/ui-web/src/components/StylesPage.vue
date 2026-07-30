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
const customStyleTutorialUrl = 'https://github.com/tokyohost/omniwatch-doc'
const remoteStyles = reactive({ loading: false, items: [], flash: {} })
const customStyleAssets = reactive({})
const previewModules = import.meta.glob('../../assert/style/*', {
  eager: true,
  query: '?url',
  import: 'default',
})
const stylePreviewSources = Object.fromEntries(
  Object.entries(previewModules).map(([path, url]) => {
    const filename = path.split('/').pop() || ''
    const styleName = filename.replace(/\.[^.]+$/, '').toLowerCase()
    return [styleName, url]
  }),
)
const detailModules = import.meta.glob('../../assert/styleDetail/*.html', {
  eager: true,
  query: '?raw',
  import: 'default',
})
const styleDetailSources = Object.fromEntries(
  Object.entries(detailModules).map(([path, content]) => {
    const filename = path.split('/').pop() || ''
    const styleName = filename.replace(/\.html$/i, '').toLowerCase()
    return [styleName, content]
  }),
)
const styleDetail = reactive({ visible: false, title: '', content: '' })

/**
 * 为独立详情页注入与主界面一致的滚动条主题。
 */
function applyDetailScrollbarTheme(content) {
  const scrollbarStyle = `<style>
    * { scrollbar-width: thin; scrollbar-color: rgba(91, 140, 255, .48) transparent; }
    *::-webkit-scrollbar { width: 9px; height: 9px; }
    *::-webkit-scrollbar-track { background: transparent; }
    *::-webkit-scrollbar-thumb {
      min-width: 36px; min-height: 36px;
      border: 2px solid transparent; border-radius: 999px;
      background: rgba(91, 140, 255, .48); background-clip: padding-box;
    }
    *::-webkit-scrollbar-thumb:hover { background-color: rgba(111, 153, 255, .76); }
    *::-webkit-scrollbar-thumb:active { background-color: rgba(129, 166, 255, .92); }
    *::-webkit-scrollbar-button { display: none; width: 0; height: 0; }
    *::-webkit-scrollbar-corner { background: transparent; }
  </style>`
  return content.replace(/<\/head>/i, `${scrollbarStyle}</head>`)
}

/**
 * 返回与样式标识同名的本地界面截图地址。
 */
function stylePreview(item) {
  const styleName = String(item?.name || '').toLowerCase()
  return customStyleAssets[styleName]?.previewDataUrl || stylePreviewSources[styleName] || ''
}

/**
 * 判断指定样式是否存在同名 HTML 详情页。
 */
function hasStyleDetail(item) {
  const styleName = String(item?.name || '').toLowerCase()
  return Boolean(customStyleAssets[styleName]?.detailHtml || styleDetailSources[styleName])
}

/**
 * 在应用内打开指定样式的指标详情页。
 */
function openStyleDetail(item) {
  const styleName = String(item?.name || '').toLowerCase()
  const content = customStyleAssets[styleName]?.detailHtml || styleDetailSources[styleName]
  if (!content) return
  styleDetail.title = `${item.chinese_name} · 样式详情`
  styleDetail.content = applyDetailScrollbarTheme(content)
  styleDetail.visible = true
}

/**
 * 尝试加载自定义数据插件随绑定样式提供的可选预览图和 HTML 详情。
 */
async function loadCustomStyleAssets() {
  try {
    const result = await invoke('style.assets')
    for (const key of Object.keys(customStyleAssets)) delete customStyleAssets[key]
    Object.assign(customStyleAssets, result.assets || {})
  } catch {
    // 自定义资源不是必需项，读取失败时保留内置资源和空状态。
  }
}

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
    applyActiveDeviceStyle(result.active_style, result.catalog)
    await loadCustomStyleAssets()
  } catch (error) {
    ElMessage.error(error?.message || String(error))
  } finally {
    remoteStyles.loading = false
  }
}

/**
 * 使用设备渲染器当前生效的样式初始化页面选中态，忽略启动页等非候选样式。
 */
function applyActiveDeviceStyle(activeStyle, catalog) {
  const name = String(activeStyle || '').trim()
  const items = Array.isArray(catalog) ? catalog : props.styles
  const activeItem = items.find((item) => item?.name === name)
  if (!activeItem) return
  if (activeItem.idle) props.settings.idle_style = name
  else props.settings.lcd_style = name
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
    await ElMessageBox.confirm(`确定删除“${item.chinese_name}”吗？`, '删除样式', { type: 'warning' })
    const result = await invoke('style.delete', { name: item.name, filename: item.filename })
    remoteStyles.items = remoteStyles.items.filter((style) => style.name !== item.name)
    const catalog = (result.catalog || props.styles).filter((style) => style.name !== item.name)
    emit('catalog-updated', catalog)
    repairDeletedStyleSelection(item.name, catalog)
    ElMessage.success('样式已删除')
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error?.message || String(error))
  }
}

/**
 * 删除当前选中样式后切回仍然存在的默认候选项，避免表单继续引用旧名称。
 */
function repairDeletedStyleSelection(deletedName, catalog) {
  if (props.settings.lcd_style === deletedName) {
    props.settings.lcd_style = catalog.find((style) => !style.idle)?.name || 'default'
  }
  if (props.settings.idle_style === deletedName) {
    props.settings.idle_style = catalog.find((style) => style.idle)?.name || 'idle'
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
  <div class="style-toolbar">
    <el-button
      tag="a"
      :href="customStyleTutorialUrl"
      target="_blank"
      rel="noopener noreferrer"
      title="在浏览器中打开自定义屏幕教程"
    >自定义屏幕教程</el-button>
    <el-button :loading="remoteStyles.loading" @click="loadRemoteStyles">刷新设备</el-button>
    <el-button type="primary" @click="uploadStyle">上传样式</el-button>
  </div>
  <div class="style-grid">
    <article
      v-for="item in styles"
      :key="item.name"
      :class="['style-card', { selected: settings.lcd_style === item.name || settings.idle_style === item.name }]"
      role="button"
      tabindex="0"
      @click="selectStyle(item)"
      @keydown.enter="selectStyle(item)"
      @keydown.space.prevent="selectStyle(item)"
    >
      <span class="style-preview-shell">
        <img
          v-if="stylePreview(item)"
          :src="stylePreview(item)"
          :alt="`${item.chinese_name}界面预览`"
          class="style-preview"
        />
        <span v-else class="style-preview-empty">
          <span class="style-icon"><el-icon><MagicStick /></el-icon></span>
          <small>暂无界面预览</small>
        </span>
      </span>
      <span class="style-card-copy">
        <strong>{{ item.chinese_name }}</strong>
        <span class="style-card-meta">
          <small>{{ item.name }} · {{ item.type === 'custom' ? '自定义' : '内置' }}</small>
          <el-button
            v-if="hasStyleDetail(item)"
            text
            size="small"
            type="primary"
            @click.stop="openStyleDetail(item)"
          >查看详情</el-button>
        </span>
      </span>
    </article>
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
    <span class="sticky-action-hint">当前选择会与其他设置一并保存</span>
    <el-button type="primary" :loading="saving" @click="emit('save')">应用样式</el-button>
  </div>
  <el-dialog v-model="styleDetail.visible" :title="styleDetail.title" width="min(920px, 88vw)" class="style-detail-dialog">
    <iframe
      :srcdoc="styleDetail.content"
      :title="styleDetail.title"
      class="style-detail-frame"
      sandbox=""
    />
  </el-dialog>
</template>
