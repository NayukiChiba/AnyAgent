<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import RunnerSwitcher from './RunnerSwitcher.vue'
import { createSession, loadSessions, sessionState } from '../stores/sessions.js'
import { loadAgent } from '../stores/agent.js'
import '../styles/sidebar.css'

const route = useRoute()
const router = useRouter()

const MANAGE_ITEMS = [
  { path: '/runners', label: 'Runner 管理', icon: 'runner' },
  { path: '/models', label: '模型', icon: 'chip' },
  { path: '/logs', label: '日志', icon: 'terminal' },
  { path: '/settings', label: '设置', icon: 'gear' },
]

/* 模式跟随路由：对话页展示会话，管理页展示管理导航；点击按钮显式切换 */
const override = ref(null)
const mode = computed(() => override.value ?? (route.path === '/' ? 'chat' : 'manage'))
watch(
  () => route.path,
  () => (override.value = null),
)

function switchMode(next) {
  override.value = next
  if (next === 'chat' && route.path !== '/') router.push('/')
  if (next === 'manage' && route.path === '/') router.push('/runners')
}
async function choose(session) {
  if (sessionState.busy || session.id === sessionState.currentId) return
  sessionState.currentId = session.id
  if (route.path !== '/') router.push('/')
}
async function create() {
  if (sessionState.busy) return
  try {
    await createSession()
    if (route.path !== '/') router.push('/')
  } catch {
    /* 创建失败时保持现状，错误会在聊天页提示 */
  }
}
async function onRunnerChanged() {
  await loadAgent()
}
onMounted(loadSessions)
</script>

<template>
  <aside class="sidebar">
    <RouterLink class="brand" to="/" aria-label="AnyAgent 首页"
      ><span class="brand-mark">A</span>AnyAgent<span class="version">0.1</span></RouterLink
    >

    <div class="mode-toggle" role="tablist" aria-label="侧栏模式">
      <button
        role="tab"
        :aria-selected="mode === 'chat'"
        :class="{ active: mode === 'chat' }"
        @click="switchMode('chat')"
      >
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24">
          <path
            d="M21 12a8 8 0 0 1-8 8H5l-2 2V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8Z"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linejoin="round"
          />
        </svg>
        会话
      </button>
      <button
        role="tab"
        :aria-selected="mode === 'manage'"
        :class="{ active: mode === 'manage' }"
        @click="switchMode('manage')"
      >
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24">
          <rect
            x="3"
            y="3"
            width="8"
            height="8"
            rx="2"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
          />
          <rect
            x="13"
            y="3"
            width="8"
            height="8"
            rx="2"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
          />
          <rect
            x="3"
            y="13"
            width="8"
            height="8"
            rx="2"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
          />
          <rect
            x="13"
            y="13"
            width="8"
            height="8"
            rx="2"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
          />
        </svg>
        管理
      </button>
    </div>

    <template v-if="mode === 'chat'">
      <RunnerSwitcher :disabled="sessionState.busy" @changed="onRunnerChanged" />
      <button class="new-session" :disabled="sessionState.busy" @click="create">
        <span>＋</span> 新建会话
      </button>
      <div class="session-heading">
        会话 <span>{{ sessionState.list.length }}</span>
      </div>
      <nav class="sessions" aria-label="会话列表">
        <button
          v-for="session in sessionState.list"
          :key="session.id"
          :class="{ active: session.id === sessionState.currentId }"
          :disabled="sessionState.busy"
          @click="choose(session)"
        >
          <span class="session-title">{{ session.title }}</span>
        </button>
        <p v-if="!sessionState.list.length" class="sessions-empty">还没有会话</p>
      </nav>
    </template>

    <nav v-else class="sidebar-nav manage-nav" aria-label="管理导航">
      <RouterLink
        v-for="item in MANAGE_ITEMS"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: route.path === item.path }"
      >
        <svg
          v-if="item.icon === 'runner'"
          aria-hidden="true"
          width="16"
          height="16"
          viewBox="0 0 24 24"
        >
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
        <svg
          v-else-if="item.icon === 'chip'"
          aria-hidden="true"
          width="16"
          height="16"
          viewBox="0 0 24 24"
        >
          <rect
            x="6"
            y="6"
            width="12"
            height="12"
            rx="2"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
          />
          <path
            d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
          />
        </svg>
        <svg
          v-else-if="item.icon === 'terminal'"
          aria-hidden="true"
          width="16"
          height="16"
          viewBox="0 0 24 24"
        >
          <path
            d="m5 7 5 5-5 5M12 17h7"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <svg v-else aria-hidden="true" width="16" height="16" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.6" />
          <path
            d="M19 12a7 7 0 0 0-.14-1.4l2.1-1.63-2-3.46-2.48 1a7 7 0 0 0-2.42-1.4L13.66 2h-3.32l-.4 2.61a7 7 0 0 0-2.42 1.4l-2.48-1-2 3.46 2.1 1.63a7 7 0 0 0 0 2.8l-2.1 1.63 2 3.46 2.48-1a7 7 0 0 0 2.42 1.4l.4 2.61h3.32l.4-2.61a7 7 0 0 0 2.42-1.4l2.48 1 2-3.46-2.1-1.63c.09-.46.14-.93.14-1.4Z"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linejoin="round"
          />
        </svg>
        {{ item.label }}
      </RouterLink>
    </nav>

    <div class="sidebar-footer">
      <p class="sidebar-note">
        {{ mode === 'chat' ? '会话保存在本机数据库中' : '管理 Runner、模型连接与运行日志' }}
      </p>
    </div>
  </aside>
</template>
