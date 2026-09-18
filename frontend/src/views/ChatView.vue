<script setup>
import { onBeforeRouteLeave } from 'vue-router'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { request, streamHttp, streamWebSocket } from '../api.js'

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
async function refreshAgent() {
  try {
    agent.value = await request('/api/v1/agent')
    if (!transport.value) transport.value = agent.value.frontend.default_transport
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
onMounted(async () => {
  try {
    await refreshAgent()
    await refreshSessions()
    if (sessions.value.length) await selectSession(sessions.value[0].id)
    else await newSession()
  } catch (error) {
    notice.value = error.message
  } finally {
    loading.value = false
  }
})
onBeforeUnmount(stop)
onBeforeRouteLeave(
  () => !busy.value || window.confirm('回复仍在生成，离开页面将停止生成。确定离开吗？'),
)
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <a class="brand" href="/" aria-label="AnyAgent 首页"
        ><span class="brand-mark">A</span>AnyAgent<span class="version">0.1</span></a
      >
      <div class="sidebar-caption">AGENT WORKSPACE</div>
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
          <span class="session-icon">◇</span><span class="session-title">{{ session.title }}</span>
        </button>
      </nav>
      <div class="sidebar-footer">
        <span class="memory-dot"></span>内存会话
        <p>服务重启后清空</p>
        <a href="/docs" target="_blank" rel="noopener">API 文档 ↗</a>
      </div>
    </aside>
    <main class="main">
      <header class="topbar">
        <div>
          <span class="eyebrow">LANGCHAIN AGENT</span>
          <h1>{{ title }}</h1>
        </div>
        <div class="topbar-actions">
          <RouterLink to="/settings" class="icon-button settings-link">设置</RouterLink>
          <span class="status" :class="{ connected: agent?.configured }"
            ><i></i>{{ agent?.configured ? '模型已配置' : '等待模型配置' }}</span
          ><button
            class="icon-button"
            :disabled="busy"
            @click="removeSession"
            aria-label="删除当前会话"
          >
            删除会话
          </button>
        </div>
      </header>
      <section class="model-bar" aria-label="模型与连接设置">
        <div>
          <span class="model-icon">◈</span><strong>{{ agent?.model || '尚未选择模型' }}</strong
          ><span class="provider">OpenAI Compatible</span>
          <span v-if="agent" class="output-mode">{{
            agent.streaming ? '流式输出' : '非流式输出'
          }}</span>
        </div>
        <div class="connection-controls">
          <label for="transport">连接方式</label
          ><select id="transport" v-model="transport" :disabled="busy">
            <option value="websocket">WebSocket</option>
            <option value="http">HTTP · SSE</option></select
          ><button class="text-button" :disabled="busy" @click="refreshAgent">刷新配置</button>
        </div>
      </section>
      <div v-if="agent && !agent.configured" class="config-hint">
        还没有连接模型。<RouterLink to="/settings">打开设置</RouterLink
        >，填写模型信息并测试连接，就能开始聊天。
      </div>
      <div v-if="notice" class="notice" role="alert">{{ notice }}</div>
      <section ref="thread" class="thread" aria-label="聊天消息" aria-live="polite">
        <div v-if="!messages.length" class="welcome">
          <div class="welcome-symbol">✳</div>
          <span class="eyebrow">YOUR AGENT, ONE CONVERSATION AWAY</span>
          <h2>从一个问题开始</h2>
          <p>与 LangChain Agent 对话，让工具参与解决问题。</p>
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
              message.role === 'user' ? '你' : 'LangChain Agent'
            }}</span>
            <div class="message-text">{{ message.content || (busy ? '正在思考…' : '') }}</div>
            <span v-if="busy && index === messages.length - 1" class="typing-indicator">● ● ●</span>
          </div>
        </article>
      </section>
      <section v-if="tools.length" class="tool-panel" aria-label="本轮工具调用">
        <div class="tool-heading">
          工具执行 <span>{{ tools.length }}</span>
        </div>
        <details v-for="call in tools" :key="call.id" open>
          <summary>
            <span>⌘ {{ call.name }}</span
            ><span :class="{ done: call.result !== null }">{{
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
            <span>↵ 发送 · Shift + Enter 换行</span
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
        <p class="composer-note">会话保存在当前服务内存中 · 工具：calculate</p>
      </footer>
    </main>
  </div>
</template>
