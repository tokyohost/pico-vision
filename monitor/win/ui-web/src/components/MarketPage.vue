<script setup>
import { computed } from 'vue'

const props = defineProps({
  applicationVersion: { type: String, required: true },
  configuredUrl: { type: String, default: '' },
})

/**
 * 按应用版本解析市场地址，并追加嵌入模式和深色主题参数。
 */
const marketUrl = computed(() => {
  const baseUrl = props.applicationVersion === 'development'
    ? 'http://localhost/market'
    : String(props.configuredUrl || '').trim()
  if (!baseUrl) return ''
  try {
    const url = new URL(baseUrl)
    if (!['http:', 'https:'].includes(url.protocol)) return ''
    url.searchParams.set('embed', '1')
    url.searchParams.set('theme', 'dark')
    return url.toString()
  } catch {
    return ''
  }
})
</script>

<template>
  <section class="market-frame-page">
    <iframe
      v-if="marketUrl"
      class="market-frame"
      :src="marketUrl"
      title="OmniWatch 插件市场"
      referrerpolicy="strict-origin-when-cross-origin"
      allow="clipboard-read; clipboard-write"
    />
    <div v-else class="market-frame-empty">
      <el-empty description="尚未配置有效的插件市场地址">
        <template #description>
          <p>请在“设置 → 插件市场”中填写以 http:// 或 https:// 开头的市场地址。</p>
        </template>
      </el-empty>
    </div>
  </section>
</template>
