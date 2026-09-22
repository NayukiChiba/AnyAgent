export async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const error = new Error(body.detail?.message || `请求失败 (${response.status})`)
    error.fields = body.detail?.fields || {}
    error.status = response.status
    throw error
  }
  return response.status === 204 ? null : response.json()
}

/* Runner 档案：增删查改与启用切换 */
export const listProfiles = () => request('/api/v1/profiles')
export const createProfile = (values) =>
  request('/api/v1/profiles', { method: 'POST', body: JSON.stringify(values) })
export const updateProfile = (id, values) =>
  request(`/api/v1/profiles/${id}`, { method: 'PUT', body: JSON.stringify(values) })
export const deleteProfile = (id) => request(`/api/v1/profiles/${id}`, { method: 'DELETE' })
export const activateProfile = (id) =>
  request(`/api/v1/profiles/${id}/activate`, { method: 'POST' })
/* 连接测试作用于当前启用的档案 */
export const testActiveProfile = () =>
  request('/api/v1/settings/model_config/test', { method: 'POST' })

export function createEventParser(onEvent) {
  let pending = ''
  return {
    push(chunk) {
      pending += chunk
      let match
      while ((match = /\r?\n\r?\n/.exec(pending))) {
        const frame = pending.slice(0, match.index)
        pending = pending.slice(match.index + match[0].length)
        const data = frame
          .split(/\r?\n/)
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n')
        if (data) onEvent(JSON.parse(data))
      }
    },
  }
}

export async function streamHttp(sessionId, content, onEvent, signal) {
  const response = await fetch(`/api/v1/sessions/${sessionId}/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
    signal,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail?.message || `请求失败 (${response.status})`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let completed = false
  const parser = createEventParser((event) => {
    if (event.type === 'error') throw new Error(event.data.message)
    if (event.type === 'result') completed = true
    onEvent(event)
  })
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      parser.push(decoder.decode(value, { stream: true }))
    }
    parser.push(decoder.decode())
    if (!completed) throw new Error('连接已断开，回复尚未完成')
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export function streamWebSocket(sessionId, content, onEvent, signal, { cancelTimeoutMs }) {
  return new Promise((resolve, reject) => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${location.host}/ws/sessions/${sessionId}`)
    let finished = false
    let cancelTimer
    const finish = (error) => {
      if (finished) return
      finished = true
      clearTimeout(cancelTimer)
      signal.removeEventListener('abort', cancel)
      socket.close()
      if (error) reject(error)
      else resolve()
    }
    const cancel = () => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'cancel' }))
        cancelTimer = setTimeout(
          () => finish(new DOMException('已停止生成', 'AbortError')),
          cancelTimeoutMs,
        )
      } else finish(new DOMException('已停止生成', 'AbortError'))
    }
    signal.addEventListener('abort', cancel, { once: true })
    socket.onopen = () => {
      if (signal.aborted) cancel()
      else socket.send(JSON.stringify({ type: 'message', content }))
    }
    socket.onmessage = ({ data }) => {
      try {
        const event = JSON.parse(data)
        if (event.type === 'cancelled') return finish(new DOMException('已停止生成', 'AbortError'))
        if (event.type === 'error') return finish(new Error(event.data.message))
        onEvent(event)
        if (event.type === 'result') finish()
      } catch (error) {
        finish(error)
      }
    }
    socket.onerror = () => finish(new Error('WebSocket 连接失败'))
    socket.onclose = () => {
      if (!finished)
        finish(
          signal.aborted
            ? new DOMException('已停止生成', 'AbortError')
            : new Error('连接已断开，回复尚未完成'),
        )
    }
    if (signal.aborted) cancel()
  })
}
