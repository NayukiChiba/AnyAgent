/* 会话列表的共享状态：侧边栏与聊天页共用，避免各页面各自维护 */

import { reactive } from 'vue'
import { request } from '../api.js'

export const sessionState = reactive({
  list: [],
  currentId: '',
  busy: false,
})

export async function loadSessions() {
  sessionState.list = await request('/api/v1/sessions')
}

export async function createSession() {
  const session = await request('/api/v1/sessions', { method: 'POST' })
  await loadSessions()
  sessionState.currentId = session.id
  return session
}

export async function removeSession(id) {
  await request(`/api/v1/sessions/${id}`, { method: 'DELETE' })
  await loadSessions()
  if (sessionState.currentId === id) {
    sessionState.currentId = sessionState.list[0]?.id || ''
  }
}

export async function renameSession(id, title) {
  await request(`/api/v1/sessions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })
  await loadSessions()
}
