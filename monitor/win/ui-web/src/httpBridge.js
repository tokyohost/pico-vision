import { t } from './i18n'
import ReconnectingWebSocket from 'reconnecting-websocket'

/**
 * 为普通 HTTP 浏览器页面提供与 pywebview 一致的 invoke 接口。
 */
function installHttpBridge() {
  if (window.location.protocol === 'file:' || window.pywebview?.api?.invoke) return

  const authStorageKey = 'omniwatch.http.auth'
  const unsupportedActions = new Map([
    ['device.firmware.select', 'ui.selecting_firmware_from_the_server_is_not_available_in'],
    ['device.firmware.updateLocal', 'ui.selecting_firmware_from_the_server_is_not_available_in'],
    ['device.sdk.select', 'ui.selecting_images_from_the_server_is_not_available_in'],
    ['log.export', 'ui.native_save_dialogs_are_not_available_in_the_web'],
    ['style.upload', 'ui.native_file_selection_is_not_available_in_the_web'],
    ['system.openDataDirectory', 'ui.opening_server_directories_is_not_available_in_the_web'],
  ])
  const pending = new Map()
  let socket = null
  let connectionPromise = null
  let sequence = 0

  /**
   * 允许带有 uploadId 的 action 复用浏览器上传临时文件。
   */
  const uploadActions = new Set([
    'data.import',
    'data.importDirectory',
    'style.upload',
    'device.firmware.select',
    'device.firmware.updateLocal',
    'device.sdk.select',
  ])

  /**
   * 请求用户输入鉴权密钥并保存到当前浏览器。
   */
  function requireAuth() {
    const saved = window.localStorage.getItem(authStorageKey)
    if (saved) return saved
    const entered = window.prompt(t('ui.enter_the_omniwatch_http_management_auth_token'))
    if (!entered) throw new Error(t('ui.no_http_management_auth_token_entered'))
    window.localStorage.setItem(authStorageKey, entered)
    return entered
  }

  /**
   * 拒绝连接断开时尚未完成的全部 RPC 请求。
   */
  function rejectPendingRequests() {
    for (const request of pending.values()) {
      window.clearTimeout(request.timer)
      request.reject(new Error(t('ui.websocket_disconnected_reconnecting_automatically')))
    }
    pending.clear()
  }

  /**
   * 创建具备退避重连能力的成熟 WebSocket 客户端。
   */
  function createSocket() {
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const auth = requireAuth()
    const client = new ReconnectingWebSocket(
      `${scheme}//${window.location.host}/ws?auth=${encodeURIComponent(auth)}`,
      [],
      {
        connectionTimeout: 4000,
        maxReconnectionDelay: 10000,
        minReconnectionDelay: 1000,
        reconnectionDelayGrowFactor: 1.5,
        maxRetries: 5,
      },
    )
    client.addEventListener('message', (event) => {
      let message
      try {
        message = JSON.parse(event.data)
      } catch {
        return
      }
      const request = pending.get(message.id)
      if (!request || message.type !== 'result') return
      pending.delete(message.id)
      window.clearTimeout(request.timer)
      request.resolve(message.result)
    })
    client.addEventListener('close', rejectPendingRequests)
    return client
  }

  /**
   * 等待自动重连客户端进入可发送状态。
   */
  function ensureConnected() {
    if (!socket) socket = createSocket()
    if (socket.readyState === WebSocket.OPEN) return Promise.resolve(socket)
    if (connectionPromise) return connectionPromise
    connectionPromise = new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        socket?.close()
        socket = null
        connectionPromise = null
        window.localStorage.removeItem(authStorageKey)
        reject(new Error(t('ui.authentication_failed_or_connection_unavailable_enter_the_auth_token')))
      }, 12000)
      socket.addEventListener('open', () => {
        window.clearTimeout(timeout)
        connectionPromise = null
        resolve(socket)
      }, { once: true })
    })
    return connectionPromise
  }

  /**
   * 通过 WebSocket 发送一次带请求编号的 invoke 调用。
   */
  async function invoke(action, payload = {}) {
    const unsupported = unsupportedActions.get(action)
    if (unsupported && !(uploadActions.has(action) && payload?.uploadId)) {
      return { ok: false, message: t(unsupported) }
    }
    const client = await ensureConnected()
    const id = `${Date.now()}-${++sequence}`
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        pending.delete(id)
        reject(new Error(t('ui.operation_timed_out_value', { value0: action })))
      }, 30000)
      pending.set(id, { resolve, reject, timer })
      client.send(JSON.stringify({ type: 'invoke', id, action, payload }))
    })
  }

  /**
   * 将一个或多个 File 对象上传到受鉴权保护的临时目录。
   */
  async function upload(kind, fileList) {
    const files = Array.from(fileList || [])
    if (!files.length) throw new Error(t('ui.no_file_selected'))
    const form = new FormData()
    for (const file of files) {
      const name = file.webkitRelativePath || file.name
      form.append('files', file, name)
    }
    const response = await window.fetch(
      `/api/uploads/${encodeURIComponent(kind)}`,
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${requireAuth()}` },
        body: form,
      },
    )
    let result
    try {
      result = await response.json()
    } catch {
      result = { ok: false, message: t('ui.the_server_returned_an_invalid_upload_response') }
    }
    if (!response.ok || !result?.ok) {
      if (response.status === 401) window.localStorage.removeItem(authStorageKey)
      throw new Error(result?.message || t('ui.file_upload_failed_value', { value0: response.status }))
    }
    return result.data ?? result
  }

  window.__omniwatchHttpBridge = { upload }
  window.pywebview = { api: { invoke } }
  window.dispatchEvent(new Event('pywebviewready'))
}

installHttpBridge()
