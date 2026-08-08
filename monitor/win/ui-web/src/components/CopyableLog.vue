<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  content: { type: String, default: '' },
  emptyText: { type: String, default: '暂无日志' },
  preClass: { type: [String, Array, Object], default: '' },
  copySuccessText: { type: String, default: '日志已复制' },
})
const emit = defineEmits(['scroll'])
const logElement = ref(null)

/**
 * 将当前日志框的全部原始内容复制到系统剪贴板。
 */
async function copyAllLogs() {
  if (!props.content) {
    ElMessage.warning('暂无可复制的日志')
    return
  }
  try {
    await navigator.clipboard.writeText(props.content)
    ElMessage.success(props.copySuccessText)
  } catch (error) {
    ElMessage.error(error?.message || '复制日志失败')
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
  <div class="copyable-log-container">
    <el-tooltip content="复制全部日志" placement="left">
      <el-button
        class="copyable-log-button"
        circle
        aria-label="复制全部日志"
        @click="copyAllLogs"
      >
        <el-icon><CopyDocument /></el-icon>
      </el-button>
    </el-tooltip>
    <pre
      ref="logElement"
      :class="preClass"
      @scroll="emit('scroll', $event)"
    >{{ content || emptyText }}</pre>
  </div>
</template>
