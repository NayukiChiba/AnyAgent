<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import SettingSelect from '../components/SettingSelect.vue'
import '../styles/logs.css'

const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
const LEVEL_CHOICES = [
  { value: 'ALL', label: '全部级别' },
  { value: 'INFO', label: 'INFO 及以上' },
  { value: 'WARNING', label: 'WARNING 及以上' },
  { value: 'ERROR', label: '仅错误' },
]
const MAX_ENTRIES = 1000

const entries = ref([])
const paused = ref(false)
const levelFilter = ref('ALL')
const connected = ref(false)
const consoleEl = ref(null)
let source = null

const visible = computed(() => {
  if (levelFilter.value === 'ALL') return entries.value
  const minimum = LEVELS.indexOf(levelFilter.value)
  return entries.value.filter((entry) => LEVELS.indexOf(entry.level) >= minimum)
})

function formatTime(epoch) {
  const date = new Date(epoch * 1000)
  const pad = (value, size = 2) => String(value).padStart(size, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`
}
async function scrollToEnd() {
  await nextTick()
  if (consoleEl.value) consoleEl.value.scrollTop = consoleEl.value.scrollHeight
}
function push(entry) {
  entries.value.push(entry)
  if (entries.value.length > MAX_ENTRIES) {
    entries.value.splice(0, entries.value.length - MAX_ENTRIES)
  }
  scrollToEnd()
}
function connect() {
  source = new EventSource('/api/v1/logs/stream')
  source.addEventListener('log', (event) => {
    const entry = JSON.parse(event.data)
    if (entry.level === 'PING') return
    connected.value = true
    if (!paused.value) push(entry)
  })
  source.onerror = () => {
    /* EventSource 会自动重连，期间标记为未连接 */
    connected.value = false
  }
}
function togglePause() {
  paused.value = !paused.value
}
function clear() {
  entries.value = []
}
onMounted(connect)
onBeforeUnmount(() => source?.close())
</script>

<template>
  <main class="main logs-main">
    <header class="topbar">
      <div class="topbar-title">
        <div>
          <span class="eyebrow">RUNTIME LOGS</span>
          <h1>运行日志</h1>
        </div>
      </div>
      <div class="topbar-actions">
        <span class="status-pill" :class="{ connected }"
          ><i></i>{{ connected ? '实时接收中' : '连接中断，重连中…' }}</span
        >
        <span id="log-level-label" class="picker-label">级别</span>
        <SettingSelect
          id="log-level"
          v-model="levelFilter"
          class="log-level-picker"
          labelledby="log-level-label"
          :choices="LEVEL_CHOICES"
        />
        <button class="btn btn-sm" @click="togglePause">{{ paused ? '继续' : '暂停' }}</button>
        <button class="btn btn-sm" :disabled="!entries.length" @click="clear">清空</button>
      </div>
    </header>

    <div class="logs-content">
      <p class="logs-hint">
        展示服务运行期间的日志，刷新页面后会重新回放最近的缓存。完整历史请查看日志文件。
      </p>
      <div ref="consoleEl" class="log-console" aria-label="运行日志" aria-live="polite">
        <p v-if="!visible.length" class="log-empty">暂无日志</p>
        <p v-for="(entry, index) in visible" :key="index" class="log-line">
          <span class="log-time">{{ formatTime(entry.time) }}</span>
          <span class="log-level" :data-level="entry.level">{{ entry.level }}</span>
          <span class="log-logger">{{ entry.logger }}</span>
          <span class="log-message">{{ entry.message }}</span>
        </p>
      </div>
    </div>
  </main>
</template>
