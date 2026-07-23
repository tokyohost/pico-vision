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
