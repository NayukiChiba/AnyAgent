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

/* 模型连接：集中维护地址与密钥，供 Runner 引用 */
export const listModels = () => request('/api/v1/models')
export const createModel = (values) =>
  request('/api/v1/models', { method: 'POST', body: JSON.stringify(values) })
export const updateModel = (id, values) =>
  request(`/api/v1/models/${id}`, { method: 'PUT', body: JSON.stringify(values) })
export const deleteModel = (id) => request(`/api/v1/models/${id}`, { method: 'DELETE' })
export const testModel = (id) => request(`/api/v1/models/${id}/test`, { method: 'POST' })

export function createEventParser(onFrame) {
  /* 解析 SSE 帧的 id / event / data 行；data 按 JSON 解析后整体回调 */
  let pending = ''
  return {
    push(chunk) {
      pending += chunk
      let match
      while ((match = /\r?\n\r?\n/.exec(pending))) {
        const frame = pending.slice(0, match.index)
        pending = pending.slice(match.index + match[0].length)
        let event = 'message'
        let id = null
        const dataLines = []
        for (const line of frame.split(/\r?\n/)) {
          if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
          else if (line.startsWith('event:')) event = line.slice(6).trimStart()
          else if (line.startsWith('id:')) id = line.slice(3).trimStart()
        }
        if (dataLines.length) onFrame({ id, event, data: JSON.parse(dataLines.join('\n')) })
      }
    },
  }
}

/* Run API：创建后执行与订阅解耦，断线按事件序号续订 */
export const createRun = (sessionId, content) =>
  request('/api/v1/runs', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, content }),
  })
export const getRun = (id) => request(`/api/v1/runs/${id}`)
export const cancelRun = (id) => request(`/api/v1/runs/${id}/cancel`, { method: 'POST' })

const TERMINAL_STATUSES = ['succeeded', 'failed', 'cancelled']

function abortableSleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new DOMException('已停止生成', 'AbortError'))
      },
      { once: true },
    )
  })
}

async function streamRunEvents(runId, sinceSeq, signal, onPayload) {
  const headers = {}
  if (sinceSeq >= 0) headers['Last-Event-ID'] = String(sinceSeq)
  const response = await fetch(`/api/v1/runs/${runId}/events`, { headers, signal })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail?.message || `请求失败 (${response.status})`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parser = createEventParser((frame) => {
    // 错误帧沿用既有 SSE 错误格式 { type, data: { code, message } }
    if (frame.event === 'error') throw new Error(frame.data.data?.message || '执行失败')
    onPayload(frame.data)
  })
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      parser.push(decoder.decode(value, { stream: true }))
    }
    parser.push(decoder.decode())
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export async function followRun(runId, onEvent, signal, { retryIntervalMs = 1000 } = {}) {
  /* 订阅 Run 事件直到终态；网络中断时按已收到的最大序号重连续订。
     onEvent 收到 { seq, type, data }；succeeded 正常返回，failed 抛
     错误消息，cancelled 与主动停止抛 AbortError。 */
  let sinceSeq = -1
  while (true) {
    let terminal = null
    try {
      await streamRunEvents(runId, sinceSeq, signal, (payload) => {
        sinceSeq = payload.seq
        if (payload.type === 'status') {
          if (TERMINAL_STATUSES.includes(payload.data.status)) terminal = payload.data
          return
        }
        onEvent(payload)
      })
    } catch (error) {
      if (signal.aborted) throw new DOMException('已停止生成', 'AbortError')
      if (error.name === 'AbortError') throw error
      // HTTP 错误（如执行不存在）重连无意义，直接抛出；网络错误等待后重连
      if (error.message.startsWith('请求失败')) throw error
      await abortableSleep(retryIntervalMs, signal)
      continue
    }
    if (terminal) {
      if (terminal.status === 'failed') throw new Error(terminal.error?.message || '执行失败')
      if (terminal.status === 'cancelled') throw new DOMException('已停止生成', 'AbortError')
      return
    }
    // 流意外结束而未达终态：等待后重连
    await abortableSleep(retryIntervalMs, signal)
  }
}
