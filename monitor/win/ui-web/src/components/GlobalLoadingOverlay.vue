<script setup>
import { nextTick, ref, watch } from 'vue'
import { useGlobalLoading } from '../globalLoading'
import CopyableLog from './CopyableLog.vue'

const state = useGlobalLoading()
const logView = ref(null)

/**
 * 新日志出现后把日志窗口滚动到底部。
 */
async function scrollLogsToBottom() {
  await nextTick()
  if (logView.value) logView.value.scrollToBottom()
}

watch(() => state.logs.length, scrollLogsToBottom)
</script>

<template>
  <transition name="global-loading-fade">
    <div v-if="state.visible" class="global-loading-mask" role="dialog" aria-modal="true" :aria-label="state.title">
      <section class="global-loading-panel">
        <div class="global-loading-heading">
          <span class="global-loading-spinner" aria-hidden="true" />
          <div>
            <h3>{{ state.title }}</h3>
            <p>请勿关闭窗口或断开设备连接</p>
          </div>
          <strong>{{ state.progress }}%</strong>
        </div>
        <el-progress
          :percentage="state.progress"
          :status="state.status === 'active' ? undefined : state.status"
          :stroke-width="12"
          :show-text="false"
        />
        <CopyableLog
          ref="logView"
          :content="state.logs.join('\n')"
          pre-class="global-loading-logs"
          copy-success-text="操作日志已复制"
        />
      </section>
    </div>
  </transition>
</template>
