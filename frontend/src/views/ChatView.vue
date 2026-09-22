<script setup>
import { onBeforeRouteLeave } from 'vue-router'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import SettingSelect from '../components/SettingSelect.vue'
import RunnerSwitcher from '../components/RunnerSwitcher.vue'
import MarkdownMessage from '../components/MarkdownMessage.vue'
import { request, streamHttp, streamWebSocket } from '../api.js'
import { FRONTEND_CONFIG_REVISION_KEY } from '../configSync.js'

const agent = ref(null)
const sessions = ref([])
const currentId = ref('')
const messages = ref([])
const input = ref('')
const transport = ref('')
const busy = ref(false)
const loading = ref(true)
const notice = ref('')
const tools = ref([])
const thread = ref(null)
const renaming = ref(false)
const renameValue = ref('')
const renameSaving = ref(false)
const renameInput = ref(null)
let controller
const title = computed(
  () => sessions.value.find((item) => item.id === currentId.value)?.title || '新会话',
)
const suggestions = [
  '请使用工具计算 123 × 456',
  '帮我制定一个学习 Python 的计划',
  '用简单的例子解释 Agent 是什么',
]

async function scrollToEnd() {
  await nextTick()
  if (thread.value) thread.value.scrollTop = thread.value.scrollHeight
}
async function refreshAgent({ syncTransport = false } = {}) {
  try {
    agent.value = await request('/api/v1/agent')
    if (syncTransport || !transport.value) transport.value = agent.value.frontend.default_transport
  } catch (error) {
    notice.value = error.message
  }
}
async function refreshSessions() {
  sessions.value = await request('/api/v1/sessions')
}
async function selectSession(id) {
  if (busy.value) return
  try {
    const session = await request(`/api/v1/sessions/${id}`)
    currentId.value = id
    messages.value = session.messages
    tools.value = []
    notice.value = ''
    await scrollToEnd()
  } catch (error) {
    notice.value = error.message
  }
}
async function newSession() {
  if (busy.value) return
  try {
    const session = await request('/api/v1/sessions', { method: 'POST' })
    await refreshSessions()
    await selectSession(session.id)
  } catch (error) {
    notice.value = error.message
  }
}
async function removeSession() {
  if (busy.value || !currentId.value) return
  try {
    await request(`/api/v1/sessions/${currentId.value}`, { method: 'DELETE' })
    await refreshSessions()
    currentId.value = ''
    messages.value = []
    if (sessions.value.length) await selectSession(sessions.value[0].id)
    else await newSession()
  } catch (error) {
    notice.value = error.message
  }
}
function startRename() {
  if (busy.value || !currentId.value) return
  renameValue.value = title.value
  renaming.value = true
  nextTick(() => {
    renameInput.value?.focus()
    renameInput.value?.select()
  })
}
function cancelRename() {
  renaming.value = false
}
async function commitRename() {
  if (!renaming.value || renameSaving.value) return
  const next = renameValue.value.trim()
  renaming.value = false
  if (!next || next === title.value) return
  renameSaving.value = true
  try {
    await request(`/api/v1/sessions/${currentId.value}`, {
      method: 'PATCH',
      body: JSON.stringify({ title: next }),
    })
    await refreshSessions()
  } catch (error) {
    notice.value = error.message
  } finally {
    renameSaving.value = false
  }
}
async function send() {
  const content = input.value.trim()
  if (!content || busy.value || !currentId.value) return
  busy.value = true
  notice.value = ''
  tools.value = []
  input.value = ''
  controller = new AbortController()
  const assistantIndex = messages.value.length + 1
  messages.value.push({ role: 'user', content }, { role: 'assistant', content: '' })
  await scrollToEnd()
  try {
    await refreshAgent()
    const stream = transport.value === 'websocket' ? streamWebSocket : streamHttp
    await stream(
      currentId.value,
      content,
      (event) => {
        if (event.type === 'delta') messages.value[assistantIndex].content += event.data.content
        if (event.type === 'result') messages.value[assistantIndex].content = event.data.content
        if (event.type === 'tool_call') tools.value.push({ ...event.data, result: null })
        if (event.type === 'tool_result') {
          const call = tools.value.find((item) => item.id === event.data.id)
          if (call) call.result = event.data.content
        }
        scrollToEnd()
      },
      controller.signal,
      { cancelTimeoutMs: agent.value.frontend.cancel_timeout_ms },
    )
  } catch (error) {
    notice.value = error.name === 'AbortError' ? '已停止生成，本轮未写入会话历史。' : error.message
  } finally {
    controller = null
    try {
      const session = await request(`/api/v1/sessions/${currentId.value}`)
      messages.value = session.messages
      await refreshSessions()
    } catch (error) {
      notice.value = error.message
    }
    await refreshAgent()
    busy.value = false
    await scrollToEnd()
  }
}
function stop() {
  controller?.abort()
}
function handleKey(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    send()
  }
}
function handleConfigStorage(event) {
  if (event.key === FRONTEND_CONFIG_REVISION_KEY) refreshAgent({ syncTransport: true })
}
onMounted(async () => {
  window.addEventListener('storage', handleConfigStorage)
  try {
    await refreshAgent({ syncTransport: true })
    await refreshSessions()
    if (sessions.value.length) await selectSession(sessions.value[0].id)
    else await newSession()
  } catch (error) {
    notice.value = error.message
  } finally {
    loading.value = false
  }
})
onBeforeUnmount(() => {
  stop()
  window.removeEventListener('storage', handleConfigStorage)
})
onBeforeRouteLeave(
  () => !busy.value || window.confirm('回复仍在生成，离开页面将停止生成。确定离开吗？'),
)
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <RouterLink class="brand" to="/" aria-label="AnyAgent 首页"
        ><span class="brand-mark">A</span>AnyAgent<span class="version">0.1</span></RouterLink
      >
      <RunnerSwitcher :disabled="busy" @changed="refreshAgent()" @failed="notice = $event" />
      <button class="new-session" :disabled="busy || loading" @click="newSession">
        <span>＋</span> 新建会话
      </button>
      <div class="session-heading">
        会话 <span>{{ sessions.length }}</span>
      </div>
      <nav class="sessions" aria-label="会话列表">
        <button
          v-for="session in sessions"
          :key="session.id"
          :class="{ active: session.id === currentId }"
          :disabled="busy"
          @click="selectSession(session.id)"
        >
          <span class="session-title">{{ session.title }}</span>
        </button>
        <p v-if="!sessions.length" class="sessions-empty">还没有会话</p>
      </nav>
      <div class="sidebar-footer">
        <RouterLink to="/runners" class="nav-item">
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24">
            <rect
              x="3"
              y="4"
              width="18"
              height="7"
              rx="2"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
            />
            <rect
              x="3"
              y="13"
              width="18"
              height="7"
              rx="2"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
            />
          </svg>
          Runner 管理
        </RouterLink>
        <RouterLink to="/settings" class="nav-item">
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.6" />
            <path
              d="M19 12a7 7 0 0 0-.14-1.4l2.1-1.63-2-3.46-2.48 1a7 7 0 0 0-2.42-1.4L13.66 2h-3.32l-.4 2.61a7 7 0 0 0-2.42 1.4l-2.48-1-2 3.46 2.1 1.63a7 7 0 0 0 0 2.8l-2.1 1.63 2 3.46 2.48-1a7 7 0 0 0 2.42 1.4l.4 2.61h3.32l.4-2.61a7 7 0 0 0 2.42-1.4l2.48 1 2-3.46-2.1-1.63c.09-.46.14-.93.14-1.4Z"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linejoin="round"
            />
          </svg>
          设置
        </RouterLink>
        <p class="sidebar-note">会话保存在本机数据库中</p>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div class="topbar-title">
          <input
            v-if="renaming"
            ref="renameInput"
            v-model="renameValue"
            class="rename-input"
            aria-label="会话标题"
            maxlength="60"
            :disabled="renameSaving"
            @keydown.enter.prevent="commitRename"
            @keydown.esc="cancelRename"
            @blur="commitRename"
          />
          <h1 v-else>{{ title }}</h1>
          <button
            v-if="!renaming"
            class="btn btn-ghost btn-sm"
            aria-label="重命名会话"
            title="重命名会话"
            :disabled="busy || !currentId"
            @click="startRename"
          >
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24">
              <path
                d="M17 3a2.8 2.8 0 1 1 4 4L8 20l-5 1 1-5Z"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linejoin="round"
              />
            </svg>
          </button>
        </div>
        <div class="topbar-actions">
          <span class="status-pill" :class="{ connected: agent?.configured }"
            ><i></i>{{ agent?.configured ? agent.profile.name : '未启用 Runner' }}</span
          >
          <span v-if="agent?.configured" class="badge">{{
            agent.streaming ? '流式输出' : '非流式输出'
          }}</span>
          <span id="transport-label" class="picker-label">连接方式</span>
          <SettingSelect
            id="transport"
            v-model="transport"
            class="transport-picker"
            :disabled="busy"
            labelledby="transport-label"
            :choices="[
              { value: 'websocket', label: 'WebSocket' },
              { value: 'http', label: 'HTTP · SSE' },
            ]"
          />
          <button
            class="btn btn-sm"
            :disabled="busy || !currentId"
            aria-label="删除当前会话"
            @click="removeSession"
          >
            删除
          </button>
        </div>
      </header>

      <div v-if="agent && !agent.configured" class="config-hint">
        还没有启用的 Runner。<RouterLink to="/runners">打开 Runner 管理</RouterLink>，创建一个
        Runner 并填入连接信息，就能开始聊天。
      </div>
      <div v-if="notice" class="chat-notice notice notice-error" role="alert">{{ notice }}</div>

      <section ref="thread" class="thread" aria-label="聊天消息" aria-live="polite">
        <div class="thread-inner">
          <div v-if="!messages.length" class="welcome">
            <div class="welcome-symbol">✳</div>
            <h2>从一个问题开始</h2>
            <p>与当前启用的 Runner 对话，让工具参与解决问题。</p>
            <div class="suggestions">
              <button
                v-for="suggestion in suggestions"
                :key="suggestion"
                :disabled="busy"
                @click="input = suggestion"
              >
                {{ suggestion }}<span>↗</span>
              </button>
            </div>
          </div>
          <article
            v-for="(message, index) in messages"
            :key="index"
            class="message"
            :class="message.role"
          >
            <div class="avatar">{{ message.role === 'user' ? '你' : 'A' }}</div>
            <div class="message-body">
              <span class="message-author">{{
                message.role === 'user' ? '你' : agent?.profile?.name || '助手'
              }}</span>
              <MarkdownMessage
                v-if="message.role === 'assistant' && message.content"
                class="message-text"
                :content="message.content"
              />
              <div v-else class="message-text">
                {{ message.content || (busy ? '正在思考…' : '') }}
              </div>
              <span v-if="busy && index === messages.length - 1" class="typing-indicator"
                >● ● ●</span
              >
            </div>
          </article>
        </div>
      </section>

      <section v-if="tools.length" class="tool-panel" aria-label="本轮工具调用">
        <div class="tool-heading">
          工具执行 <span>{{ tools.length }}</span>
        </div>
        <details v-for="call in tools" :key="call.id" open>
          <summary>
            <span>⌘ {{ call.name }}</span
            ><span class="tool-state" :class="{ done: call.result !== null }">{{
              call.result === null ? '执行中' : '已完成'
            }}</span>
          </summary>
          <code>{{ JSON.stringify(call.arguments) }}</code>
          <p v-if="call.result !== null">结果：{{ call.result }}</p>
        </details>
      </section>

      <footer class="composer-wrap">
        <form class="composer" @submit.prevent="send">
          <label class="sr-only" for="message">消息内容</label
          ><textarea
            id="message"
            v-model="input"
            placeholder="输入消息，与 Agent 一起解决问题…"
            rows="2"
            :maxlength="agent?.limits.max_input_chars"
            :disabled="busy || loading"
            @keydown="handleKey"
          ></textarea>
          <div class="composer-bottom">
            <span class="composer-hint">↵ 发送 · Shift + Enter 换行</span
            ><button v-if="busy" type="button" class="stop-button" @click="stop">■ 停止生成</button
            ><button
              v-else
              class="send-button"
              :disabled="!input.trim() || loading || !agent?.configured"
            >
              发送 <span>↑</span>
            </button>
          </div>
        </form>
        <p class="composer-note">
          {{
            agent?.tools?.length ? `可用工具：${agent.tools.join('、')}` : '当前引擎不使用本地工具'
          }}
        </p>
      </footer>
    </main>
  </div>
</template>
