import { reactive } from 'vue'

const globalLoading = reactive({
  visible: false,
  title: '',
  progress: 0,
  status: 'active',
  logs: [],
})

/**
 * 把进度值限制在 0～100，避免组件收到非法百分比。
 */
function normalizeProgress(value) {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, Math.min(100, Math.round(number))) : 0
}

/**
 * 追加一条带时间的全局操作日志。
 */
function appendGlobalLoadingLog(message) {
  const text = String(message || '').trim()
  if (!text) return
  globalLoading.logs.push(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] ${text}`)
}

/**
 * 更新全局遮罩中的进度和提示日志。
 */
function updateGlobalLoading(progress, message = '') {
  globalLoading.progress = normalizeProgress(progress)
  appendGlobalLoadingLog(message)
}

/**
 * 在全局遮罩中运行异步任务，并向任务提供进度与日志方法。
 */
export async function runWithGlobalLoading(options, task) {
  if (globalLoading.visible) throw new Error('已有操作正在执行，请稍候')
  globalLoading.visible = true
  globalLoading.title = String(options?.title || '正在处理')
  globalLoading.progress = normalizeProgress(options?.progress ?? 5)
  globalLoading.status = 'active'
  globalLoading.logs = []
  appendGlobalLoadingLog(options?.message || '操作开始')
  try {
    const result = await task({
      log: appendGlobalLoadingLog,
      progress: updateGlobalLoading,
    })
    globalLoading.progress = 100
    globalLoading.status = 'success'
    appendGlobalLoadingLog(options?.successMessage || '操作完成')
    return result
  } catch (error) {
    globalLoading.status = 'exception'
    appendGlobalLoadingLog(`操作失败：${error?.message || String(error)}`)
    throw error
  } finally {
    await new Promise((resolve) => window.setTimeout(resolve, globalLoading.status === 'success' ? 450 : 900))
    globalLoading.visible = false
  }
}

/**
 * 返回全局遮罩的响应式状态，供根组件统一渲染。
 */
export function useGlobalLoading() {
  return globalLoading
}
