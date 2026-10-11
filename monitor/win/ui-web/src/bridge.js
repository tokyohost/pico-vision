/**
 * 等待 pywebview 注入桥接对象。
 */
export function waitForBridge() {
  if (window.pywebview?.api?.invoke) {
    return Promise.resolve()
  }
  return new Promise((resolve) => {
    window.addEventListener('pywebviewready', resolve, { once: true })
  })
}

/**
 * 判断当前页面是否运行在独立 HTTP 管理服务中。
 */
export function isHttpBridge() {
  return Boolean(window.__omniwatchHttpBridge)
}

/**
 * 通过浏览器 multipart 上传文件，并返回服务端分配的一次性 uploadId。
 */
export async function uploadFile(kind, files) {
  await waitForBridge()
  const uploader = window.__omniwatchHttpBridge?.upload
  if (typeof uploader !== 'function') {
    throw new Error('当前页面不支持浏览器文件上传')
  }
  return uploader(kind, files)
}

/**
 * 通过唯一 action 入口调用 Python，不经过 HTTP 或 REST API。
 */
export async function invoke(action, payload = {}) {
  await waitForBridge()
  const result = await window.pywebview.api.invoke(action, payload)
  if (!result?.ok) {
    throw new Error(result?.message || '操作失败')
  }
  return result.data ?? result
}

/**
 * 优先使用浏览器剪贴板，桌面环境失败后通过受控原生桥接兜底。
 */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(String(text))
    return
  } catch (error) {
    if (isHttpBridge()) throw error
    await invoke('system.copyText', { text: String(text) })
  }
}
