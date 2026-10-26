<script setup>
import { t } from '../i18n'

import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { copyText } from '../bridge'

const props = defineProps({
  content: { type: String, default: '' },
  emptyText: { type: String, default: '' },
  preClass: { type: [String, Array, Object], default: '' },
  copySuccessText: { type: String, default: '' },
})
const emit = defineEmits(['scroll'])
const logElement = ref(null)

/**
 * 规范化 Vue 动态类名，避免依赖早期 macOS 12 WebKit 不支持的 :has。
 */
function classTokens(value) {
  if (typeof value === 'string') return value.split(/\s+/)
  if (Array.isArray(value)) return value.flatMap(classTokens)
  return Object.keys(value || {}).filter((key) => value[key])
}
const needsSpacing = computed(() => {
  const tokens = classTokens(props.preClass)
  return tokens.includes('global-loading-logs') || (tokens.includes('terminal') &&
    !tokens.some((token) => ['device-log-view', 'probe-log-view', 'log-view', 'plugin-test-result'].includes(token)))
})

/**
 * 将当前日志框的全部原始内容复制到系统剪贴板。
 */
async function copyAllLogs() {
  if (!props.content) {
    ElMessage.warning(t('ui.no_logs_to_copy'))
    return
  }
  try {
    await copyText(props.content)
    ElMessage.success(props.copySuccessText || t('ui.logs_copied'))
  } catch (error) {
    ElMessage.error(error?.message || t('ui.failed_to_copy_logs'))
  }
}

/**
 * 将日志滚动位置移动到内容末尾。
 */
function scrollToBottom() {
  const element = logElement.value
  if (element) element.scrollTop = element.scrollHeight
}

/**
 * 判断日志框是否仍接近内容末尾。
 */
function isNearBottom(threshold = 32) {
  const element = logElement.value
  return !element || element.scrollHeight - element.scrollTop - element.clientHeight < threshold
}

defineExpose({ isNearBottom, scrollToBottom })
</script>

<template>
  <div class="copyable-log-container" :class="{ 'copyable-log-spaced': needsSpacing }">
    <el-tooltip :content="t('ui.copy_all_logs')" placement="left">
      <el-button
        class="copyable-log-button"
        circle
        :aria-label="t('ui.copy_all_logs')"
        @click="copyAllLogs"
      >
        <el-icon><CopyDocument /></el-icon>
      </el-button>
    </el-tooltip>
    <pre
      ref="logElement"
      :class="preClass"
      @scroll="emit('scroll', $event)"
    >{{ content || emptyText || t('ui.no_logs') }}</pre>
  </div>
</template>
