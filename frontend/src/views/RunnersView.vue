<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import SettingSelect from '../components/SettingSelect.vue'
import {
  activateProfile,
  createProfile,
  deleteProfile,
  listProfiles,
  request,
  testActiveProfile,
  updateProfile,
} from '../api.js'
import '../styles/runners.css'

/* 直接调用模型 API 的引擎需要模型名称，也支持连接测试 */
const MODEL_TYPES = ['langchain', 'langgraph', 'loop', 'pi']

const profiles = ref([])
const activeId = ref(null)
const runnerTypes = ref([])
const loading = ref(true)
const busyId = ref('')
const testing = ref(false)
const notice = ref('')
const failed = ref(false)

const editorOpen = ref(false)
const editingId = ref(null)
const saving = ref(false)
const formError = ref('')
const form = ref(null)
const nameInput = ref(null)

const typeChoices = computed(() =>
  runnerTypes.value.map((item) => ({ value: item.id, label: item.label })),
)
const typeInfo = computed(
  () => runnerTypes.value.find((item) => item.id === form.value?.type) || null,
)
const needsModel = computed(() => MODEL_TYPES.includes(form.value?.type))
const needsBot = computed(() => form.value?.type === 'coze')
const editing = computed(() => profiles.value.find((item) => item.id === editingId.value) || null)

function typeLabel(type) {
  return runnerTypes.value.find((item) => item.id === type)?.label || type
}
async function load() {
  loading.value = true
  try {
    const [profileData, runnerData] = await Promise.all([
      listProfiles(),
      request('/api/v1/runners'),
    ])
    profiles.value = profileData.profiles
    activeId.value = profileData.active
    runnerTypes.value = runnerData.runners
    failed.value = false
  } catch (error) {
    failed.value = true
    notice.value = error.message
  } finally {
    loading.value = false
  }
}
function announce(message, isError = false) {
  notice.value = message
  failed.value = isError
}
function openCreate() {
  editingId.value = null
  form.value = {
    name: '',
    type: 'langchain',
    base_url: '',
    model: '',
    api_key: '',
    bot_id: '',
    streaming: true,
    timeout_seconds: 60,
    temperature: 0.7,
  }
  formError.value = ''
  editorOpen.value = true
  nextTick(() => nameInput.value?.focus())
}
function openEdit(profile) {
  editingId.value = profile.id
  form.value = {
    name: profile.name,
    type: profile.type,
    base_url: profile.base_url,
    model: profile.model,
    api_key: '',
    bot_id: profile.bot_id,
    streaming: profile.streaming,
    timeout_seconds: profile.timeout_seconds,
    temperature: profile.temperature,
  }
  formError.value = ''
  editorOpen.value = true
  nextTick(() => nameInput.value?.focus())
}
function closeEditor() {
  if (saving.value) return
  editorOpen.value = false
}
async function submit() {
  const values = {
    ...form.value,
    timeout_seconds: Number(form.value.timeout_seconds),
    temperature: Number(form.value.temperature),
  }
  saving.value = true
  formError.value = ''
  try {
    if (editingId.value) {
      await updateProfile(editingId.value, values)
      editorOpen.value = false
      await load()
      announce(`已保存「${values.name}」。`)
    } else {
      const created = await createProfile(values)
      editorOpen.value = false
      await load()
      announce(
        created.active
          ? `已创建「${values.name}」并启用。`
          : `已创建「${values.name}」，点击卡片上的「启用」即可切换。`,
      )
    }
  } catch (error) {
    formError.value = error.message
  } finally {
    saving.value = false
  }
}
async function activate(profile) {
  busyId.value = profile.id
  try {
    await activateProfile(profile.id)
    await load()
    announce(`已切换到「${profile.name}」，下一次对话即生效。`)
  } catch (error) {
    announce(error.message, true)
  } finally {
    busyId.value = ''
  }
}
async function remove(profile) {
  const warning =
    profile.id === activeId.value && profiles.value.length > 1
      ? '它是当前启用的 Runner，删除后会自动启用列表中的第一个。'
      : ''
  if (!window.confirm(`确定删除 Runner「${profile.name}」吗？${warning}此操作不可撤销。`)) return
  busyId.value = profile.id
  try {
    await deleteProfile(profile.id)
    await load()
    announce(`已删除「${profile.name}」。`)
  } catch (error) {
    announce(error.message, true)
  } finally {
    busyId.value = ''
  }
}
async function testConnection() {
  testing.value = true
  try {
    const result = await testActiveProfile()
    announce(result.message)
  } catch (error) {
    announce(error.message, true)
  } finally {
    testing.value = false
  }
}
function editorKeydown(event) {
  if (event.key === 'Escape') closeEditor()
}
onMounted(load)
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <RouterLink class="brand" to="/" aria-label="AnyAgent 首页"
        ><span class="brand-mark">A</span>AnyAgent<span class="version">0.1</span></RouterLink
      >
      <nav class="sidebar-nav" aria-label="主导航">
        <RouterLink to="/" class="nav-item">
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24">
            <path
              d="M21 12a8 8 0 0 1-8 8H5l-2 2V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8Z"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linejoin="round"
            />
          </svg>
          对话
        </RouterLink>
        <RouterLink to="/runners" class="nav-item active" aria-current="page">
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
      </nav>
      <div class="sidebar-footer">
        <p class="sidebar-note">每个 Runner 独立配置，启用后下一次对话立即生效。</p>
      </div>
    </aside>

    <main class="main runners-main">
      <header class="topbar">
        <div class="topbar-title">
          <div>
            <span class="eyebrow">AGENT RUNNERS</span>
            <h1>Runner 管理</h1>
          </div>
        </div>
        <div class="topbar-actions">
          <button class="btn" :disabled="loading" @click="load">刷新</button>
          <button class="btn btn-primary" @click="openCreate">新建 Runner</button>
        </div>
      </header>

      <div class="runners-content">
        <div
          v-if="notice"
          class="notice"
          :class="{ 'notice-error': failed }"
          :role="failed ? 'alert' : 'status'"
        >
          {{ notice }}
        </div>
        <p v-if="loading" class="runners-empty" role="status">正在载入 Runner…</p>
        <div v-else-if="!profiles.length" class="runners-empty">
          <div class="welcome-symbol">◈</div>
          <h2>还没有 Runner</h2>
          <p>Runner 是对话的执行引擎。创建一个并填入连接信息，就能开始聊天。</p>
          <button class="btn btn-primary" @click="openCreate">创建第一个 Runner</button>
        </div>
        <div v-else class="runner-grid">
          <article
            v-for="profile in profiles"
            :key="profile.id"
            class="runner-card"
            :class="{ active: profile.id === activeId }"
          >
            <div class="runner-card-head">
              <span class="type-badge" :data-type="profile.type">{{ profile.type }}</span>
              <h2>{{ profile.name }}</h2>
              <span v-if="profile.id === activeId" class="badge badge-success">已启用</span>
            </div>
            <p class="runner-card-desc">{{ typeLabel(profile.type) }}</p>
            <p class="runner-card-meta">
              {{ profile.base_url.replace(/^https?:\/\//, '')
              }}<template v-if="profile.model"> · {{ profile.model }}</template>
            </p>
            <p class="runner-card-meta">
              {{ profile.streaming ? '流式输出' : '非流式输出' }} · 等待上限
              {{ profile.timeout_seconds }} 秒
            </p>
            <div class="runner-card-actions">
              <button
                v-if="profile.id !== activeId"
                class="btn btn-sm"
                :disabled="busyId === profile.id"
                @click="activate(profile)"
              >
                启用
              </button>
              <button
                v-if="profile.id === activeId && MODEL_TYPES.includes(profile.type)"
                class="btn btn-sm"
                :disabled="testing"
                @click="testConnection"
              >
                {{ testing ? '正在测试…' : '测试连接' }}
              </button>
              <button
                class="btn btn-sm"
                :disabled="busyId === profile.id"
                @click="openEdit(profile)"
              >
                编辑
              </button>
              <button
                class="btn btn-sm btn-danger-ghost"
                :disabled="busyId === profile.id"
                @click="remove(profile)"
              >
                删除
              </button>
            </div>
          </article>
        </div>
      </div>

      <div
        v-if="editorOpen"
        class="modal-overlay"
        role="dialog"
        aria-modal="true"
        :aria-label="editingId ? '编辑 Runner' : '新建 Runner'"
        @keydown="editorKeydown"
      >
        <div class="modal-card">
          <h2 class="modal-title">{{ editingId ? '编辑 Runner' : '新建 Runner' }}</h2>
          <p class="modal-subtitle">
            {{
              editingId
                ? `修改「${editing?.name}」的连接与行为。`
                : '每个 Runner 独立配置，互不干扰。'
            }}
          </p>
          <form novalidate @submit.prevent="submit">
            <div class="form-field">
              <label class="form-label" for="runner-name">名称</label>
              <input
                id="runner-name"
                ref="nameInput"
                v-model="form.name"
                class="input"
                maxlength="40"
                placeholder="例如：本地 DeepSeek"
                :disabled="saving"
              />
            </div>
            <div class="form-field">
              <span id="runner-type-label" class="form-label">类型</span>
              <SettingSelect
                id="runner-type"
                v-model="form.type"
                :choices="typeChoices"
                labelledby="runner-type-label"
                :disabled="saving"
              />
              <p v-if="typeInfo" class="form-hint">{{ typeInfo.description }}</p>
            </div>
            <div class="form-field">
              <label class="form-label" for="runner-base-url">接口地址</label>
              <input
                id="runner-base-url"
                v-model="form.base_url"
                class="input"
                placeholder="https://api.openai.com/v1"
                :disabled="saving"
              />
              <p class="form-hint">填写接口前缀，不要包含 /chat/completions。</p>
            </div>
            <div v-if="needsModel" class="form-field">
              <label class="form-label" for="runner-model">模型名称</label>
              <input
                id="runner-model"
                v-model="form.model"
                class="input"
                placeholder="例如：gpt-4.1-mini"
                :disabled="saving"
              />
            </div>
            <div v-if="needsBot" class="form-field">
              <label class="form-label" for="runner-bot-id">Bot ID</label>
              <input
                id="runner-bot-id"
                v-model="form.bot_id"
                class="input"
                placeholder="在 Coze 平台的 Bot 页面获取"
                :disabled="saving"
              />
            </div>
            <div class="form-field">
              <label class="form-label" for="runner-api-key">API Key</label>
              <input
                id="runner-api-key"
                v-model="form.api_key"
                class="input"
                type="password"
                autocomplete="new-password"
                :placeholder="
                  editingId && editing?.has_api_key
                    ? '已保存密钥，留空保持不变'
                    : '填写密钥，本地服务可填 local'
                "
                :disabled="saving"
              />
            </div>
            <div class="form-field form-switch-row">
              <div>
                <label class="form-label" for="runner-streaming">流式输出</label>
                <p class="form-hint">开启时逐步显示回复；关闭时等待完整回复。</p>
              </div>
              <input
                id="runner-streaming"
                v-model="form.streaming"
                class="switch"
                type="checkbox"
                :disabled="saving"
              />
            </div>
            <div class="form-row" style="margin-top: 14px">
              <div class="form-field">
                <label class="form-label" for="runner-timeout">单次等待时间（秒）</label>
                <input
                  id="runner-timeout"
                  v-model="form.timeout_seconds"
                  class="input"
                  type="number"
                  min="1"
                  max="600"
                  step="1"
                  :disabled="saving"
                />
              </div>
              <div class="form-field">
                <label class="form-label" for="runner-temperature">回答随机性</label>
                <input
                  id="runner-temperature"
                  v-model="form.temperature"
                  class="input"
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  :disabled="saving"
                />
              </div>
            </div>
            <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
            <div class="modal-actions">
              <button type="button" class="btn" :disabled="saving" @click="closeEditor">
                取消
              </button>
              <button type="submit" class="btn btn-primary" :disabled="saving">
                {{ saving ? '正在保存…' : editingId ? '保存修改' : '创建 Runner' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </main>
  </div>
</template>
