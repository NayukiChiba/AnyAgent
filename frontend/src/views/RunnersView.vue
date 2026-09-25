<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import SettingSelect from '../components/SettingSelect.vue'
import {
  activateProfile,
  createProfile,
  deleteProfile,
  listModels,
  listProfiles,
  request,
  testActiveProfile,
  updateProfile,
} from '../api.js'
import '../styles/runners.css'

/* 直接调用模型 API 的引擎要求模型连接填写了模型名称，也支持连接测试 */
const MODEL_TYPES = ['langchain', 'langgraph', 'loop', 'pi']

const profiles = ref([])
const activeId = ref(null)
const runnerTypes = ref([])
const models = ref([])
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
const needsBot = computed(() => form.value?.type === 'coze')
const modelChoices = computed(() =>
  models.value.map((item) => ({
    value: item.id,
    label: item.model ? `${item.name}（${item.model}）` : item.name,
  })),
)
const editing = computed(() => profiles.value.find((item) => item.id === editingId.value) || null)

function typeLabel(type) {
  return runnerTypes.value.find((item) => item.id === type)?.label || type
}
async function load() {
  loading.value = true
  try {
    const [profileData, runnerData, modelData] = await Promise.all([
      listProfiles(),
      request('/api/v1/runners'),
      listModels(),
    ])
    profiles.value = profileData.profiles
    activeId.value = profileData.active
    runnerTypes.value = runnerData.runners
    models.value = modelData.models
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
    model_id: models.value[0]?.id || '',
    bot_id: '',
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
    model_id: profile.model_id,
    bot_id: profile.bot_id,
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
  saving.value = true
  formError.value = ''
  try {
    if (editingId.value) {
      await updateProfile(editingId.value, form.value)
      editorOpen.value = false
      await load()
      announce(`已保存「${form.value.name}」。`)
    } else {
      const created = await createProfile(form.value)
      editorOpen.value = false
      await load()
      announce(
        created.active
          ? `已创建「${form.value.name}」并启用。`
          : `已创建「${form.value.name}」，点击卡片上的「启用」即可切换。`,
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
        <p>Runner 是对话的执行引擎。选择一个模型连接，就能开始聊天。</p>
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
          <p v-if="profile.model" class="runner-card-meta">
            {{ profile.model.name
            }}<template v-if="profile.model.model"> · {{ profile.model.model }}</template>
          </p>
          <p v-else class="runner-card-meta runner-card-warning">模型连接已删除，请重新选择</p>
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
            <button class="btn btn-sm" :disabled="busyId === profile.id" @click="openEdit(profile)">
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
              ? `修改「${editing?.name}」的引擎与连接。`
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
            <span id="runner-model-label" class="form-label">模型连接</span>
            <SettingSelect
              id="runner-model"
              v-model="form.model_id"
              :choices="modelChoices"
              labelledby="runner-model-label"
              :disabled="saving || !models.length"
            />
            <p class="form-hint">
              连接信息在<RouterLink to="/models" @click="editorOpen = false"
                >「模型」页面</RouterLink
              >集中维护，多个 Runner 可共用同一个连接。
            </p>
            <p v-if="!models.length" class="form-hint form-warning">
              还没有模型连接，请先在「模型」页面创建。
            </p>
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
          <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
          <div class="modal-actions">
            <button type="button" class="btn" :disabled="saving" @click="closeEditor">取消</button>
            <button type="submit" class="btn btn-primary" :disabled="saving || !form.model_id">
              {{ saving ? '正在保存…' : editingId ? '保存修改' : '创建 Runner' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </main>
</template>
