import ReconnectingWebSocket from 'reconnecting-websocket'

/**
 * 为普通 HTTP 浏览器页面提供与 pywebview 一致的 invoke 接口。
 */
function installHttpBridge() {
  if (window.location.protocol === 'file:' || window.pywebview?.api?.invoke) return

  const authStorageKey = 'omniwatch.http.auth'
  const unsupportedActions = new Map([
    ['device.firmware.select', 'HTTP 页面不支持服务器本地固件选择'],
    ['device.firmware.updateLocal', 'HTTP 页面不支持服务器本地固件选择'],
    ['device.sdk.select', 'HTTP 页面不支持服务器本地镜像选择'],
    ['log.export', 'HTTP 页面不支持原生文件保存对话框'],
    ['style.upload', 'HTTP 页面不支持原生文件选择'],
    ['system.openDataDirectory', 'HTTP 页面不支持打开服务器本地目录'],
  ])
  const pending = new Map()
  let socket = null
  let connectionPromise = null
  let sequence = 0

  /**
   * 请求用户输入鉴权密钥并保存到当前浏览器。
   */
  function requireAuth() {
    const saved = window.localStorage.getItem(authStorageKey)
    if (saved) return saved
    const entered = window.prompt('请输入 OmniWatch HTTP 管理页面 Auth')
    if (!entered) throw new Error('未输入 HTTP 管理页面 Auth')
    window.localStorage.setItem(authStorageKey, entered)
    return entered
  }

  /**
   * 拒绝连接断开时尚未完成的全部 RPC 请求。
   */
  function rejectPendingRequests() {
    for (const request of pending.values()) {
      window.clearTimeout(request.timer)
      request.reject(new Error('WebSocket 连接已断开，客户端正在自动重连'))
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
        reject(new Error('HTTP 管理页面鉴权失败或连接不可用，请重新输入 Auth'))
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
    if (unsupported) return { ok: false, message: unsupported }
    const client = await ensureConnected()
    const id = `${Date.now()}-${++sequence}`
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        pending.delete(id)
        reject(new Error(`操作超时：${action}`))
      }, 30000)
      pending.set(id, { resolve, reject, timer })
      client.send(JSON.stringify({ type: 'invoke', id, action, payload }))
    })
  }

  window.pywebview = { api: { invoke } }
  window.dispatchEvent(new Event('pywebviewready'))
}

installHttpBridge()
