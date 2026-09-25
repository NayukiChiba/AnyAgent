<script setup>
import { onBeforeRouteLeave } from 'vue-router'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import SettingSelect from '../components/SettingSelect.vue'
import MarkdownMessage from '../components/MarkdownMessage.vue'
import { request, streamHttp, streamWebSocket } from '../api.js'
import {
  createSession,
  loadSessions,
  removeSession,
  renameSession,
  sessionState,
} from '../stores/sessions.js'
import { agent, loadAgent } from '../stores/agent.js'
import { FRONTEND_CONFIG_REVISION_KEY } from '../configSync.js'

const messages = ref([])
const input = ref('')
const transport = ref('')
const loading = ref(true)
const notice = ref('')
const tools = ref([])
const thread = ref(null)
const renaming = ref(false)
const renameValue = ref('')
const renameSaving = ref(false)
const renameInput = ref(null)
let controller
let loadSeq = 0
const busy = computed({
  get: () => sessionState.busy,
  set: (value) => (sessionState.busy = value),
})
const currentId = computed(() => sessionState.currentId)
const title = computed(
  () => sessionState.list.find((item) => item.id === currentId.value)?.title || '新会话',
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
    await loadAgent()
    if (syncTransport || !transport.value) transport.value = agent.value.frontend.default_transport
  } catch (error) {
    notice.value = error.message
  }
}
async function loadMessages(id) {
  const seq = ++loadSeq
  try {
    const session = await request(`/api/v1/sessions/${id}`)
    if (seq !== loadSeq || sessionState.currentId !== id) return
    messages.value = session.messages
    tools.value = []
    notice.value = ''
    await scrollToEnd()
  } catch (error) {
    if (seq === loadSeq) notice.value = error.message
  }
}
watch(currentId, (id) => {
  if (id) loadMessages(id)
  else messages.value = []
})
async function removeCurrent() {
  if (busy.value || !currentId.value) return
  try {
    await removeSession(currentId.value)
    if (!sessionState.currentId) await createSession()
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
    await renameSession(currentId.value, next)
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
      await loadSessions()
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
    await loadSessions()
    if (sessionState.currentId) await loadMessages(sessionState.currentId)
    else if (sessionState.list.length) sessionState.currentId = sessionState.list[0].id
    else await createSession()
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
          @click="removeCurrent"
        >
          删除
        </button>
      </div>
    </header>

    <div v-if="agent && !agent.configured" class="config-hint">
      还没有启用的 Runner。<RouterLink to="/runners">打开 Runner 管理</RouterLink>，创建一个 Runner
      并选择模型连接，就能开始聊天。
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
            <span v-if="busy && index === messages.length - 1" class="typing-indicator">● ● ●</span>
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
</template>
