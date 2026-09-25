<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { createModel, deleteModel, listModels, testModel, updateModel } from '../api.js'
import '../styles/runners.css'
import '../styles/models.css'

const models = ref([])
const loading = ref(true)
const busyId = ref('')
const testingId = ref('')
const notice = ref('')
const failed = ref(false)

const editorOpen = ref(false)
const editingId = ref(null)
const saving = ref(false)
const formError = ref('')
const form = ref(null)
const nameInput = ref(null)

async function load() {
  loading.value = true
  try {
    models.value = (await listModels()).models
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
    base_url: '',
    model: '',
    api_key: '',
    streaming: true,
    timeout_seconds: 60,
    temperature: 0.7,
  }
  formError.value = ''
  editorOpen.value = true
  nextTick(() => nameInput.value?.focus())
}
function openEdit(model) {
  editingId.value = model.id
  form.value = {
    name: model.name,
    base_url: model.base_url,
    model: model.model,
    api_key: '',
    streaming: model.streaming,
    timeout_seconds: model.timeout_seconds,
    temperature: model.temperature,
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
      await updateModel(editingId.value, values)
      editorOpen.value = false
      await load()
      announce(`已保存「${values.name}」，引用它的 Runner 立即使用新连接。`)
    } else {
      await createModel(values)
      editorOpen.value = false
      await load()
      announce(`已创建「${values.name}」，现在可以在 Runner 中选择它。`)
    }
  } catch (error) {
    formError.value = error.message
  } finally {
    saving.value = false
  }
}
async function remove(model) {
  if (!window.confirm(`确定删除模型连接「${model.name}」吗？此操作不可撤销。`)) return
  busyId.value = model.id
  try {
    await deleteModel(model.id)
    await load()
    announce(`已删除「${model.name}」。`)
  } catch (error) {
    announce(error.message, true)
  } finally {
    busyId.value = ''
  }
}
async function test(model) {
  testingId.value = model.id
  try {
    const result = await testModel(model.id)
    announce(`「${model.name}」${result.message}`)
  } catch (error) {
    announce(`「${model.name}」${error.message}`, true)
  } finally {
    testingId.value = ''
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
          <span class="eyebrow">MODEL CONNECTIONS</span>
          <h1>模型连接</h1>
        </div>
      </div>
      <div class="topbar-actions">
        <button class="btn" :disabled="loading" @click="load">刷新</button>
        <button class="btn btn-primary" @click="openCreate">新建模型连接</button>
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
      <p v-if="loading" class="runners-empty" role="status">正在载入模型连接…</p>
      <div v-else-if="!models.length" class="runners-empty">
        <div class="welcome-symbol">◇</div>
        <h2>还没有模型连接</h2>
        <p>模型连接保存接口地址与密钥，Runner 直接引用，无需重复填写。</p>
        <button class="btn btn-primary" @click="openCreate">创建第一个模型连接</button>
      </div>
      <div v-else class="runner-grid">
        <article v-for="model in models" :key="model.id" class="runner-card">
          <div class="runner-card-head">
            <h2>{{ model.name }}</h2>
            <span v-if="model.has_api_key" class="badge">已存密钥</span>
          </div>
          <p class="runner-card-meta">
            {{ model.base_url.replace(/^https?:\/\//, '')
            }}<template v-if="model.model"> · {{ model.model }}</template>
          </p>
          <p class="runner-card-meta">
            {{ model.streaming ? '流式输出' : '非流式输出' }} · 等待上限
            {{ model.timeout_seconds }} 秒
          </p>
          <p v-if="model.referenced_by.length" class="runner-card-meta model-refs">
            被引用：{{ model.referenced_by.join('、') }}
          </p>
          <div class="runner-card-actions">
            <button class="btn btn-sm" :disabled="testingId === model.id" @click="test(model)">
              {{ testingId === model.id ? '正在测试…' : '测试连接' }}
            </button>
            <button class="btn btn-sm" :disabled="busyId === model.id" @click="openEdit(model)">
              编辑
            </button>
            <button
              class="btn btn-sm btn-danger-ghost"
              :disabled="busyId === model.id || model.referenced_by.length > 0"
              :title="
                model.referenced_by.length ? '正被 Runner 使用，请先修改或删除这些 Runner' : ''
              "
              @click="remove(model)"
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
      :aria-label="editingId ? '编辑模型连接' : '新建模型连接'"
      @keydown="editorKeydown"
    >
      <div class="modal-card">
        <h2 class="modal-title">{{ editingId ? '编辑模型连接' : '新建模型连接' }}</h2>
        <p class="modal-subtitle">连接信息集中维护，修改后引用它的 Runner 立即生效。</p>
        <form novalidate @submit.prevent="submit">
          <div class="form-field">
            <label class="form-label" for="model-name">名称</label>
            <input
              id="model-name"
              ref="nameInput"
              v-model="form.name"
              class="input"
              maxlength="40"
              placeholder="例如：DeepSeek 线上"
              :disabled="saving"
            />
          </div>
          <div class="form-field">
            <label class="form-label" for="model-base-url">接口地址</label>
            <input
              id="model-base-url"
              v-model="form.base_url"
              class="input"
              placeholder="https://api.openai.com/v1"
              :disabled="saving"
            />
            <p class="form-hint">填写接口前缀，不要包含 /chat/completions。</p>
          </div>
          <div class="form-field">
            <label class="form-label" for="model-model">模型名称</label>
            <input
              id="model-model"
              v-model="form.model"
              class="input"
              placeholder="例如：gpt-4.1-mini"
              :disabled="saving"
            />
            <p class="form-hint">本地编排引擎必须填写；Dify 等远端平台可留空。</p>
          </div>
          <div class="form-field">
            <label class="form-label" for="model-api-key">API Key</label>
            <input
              id="model-api-key"
              v-model="form.api_key"
              class="input"
              type="password"
              autocomplete="new-password"
              :placeholder="editingId ? '已保存密钥，留空保持不变' : '填写密钥，本地服务可填 local'"
              :disabled="saving"
            />
          </div>
          <div class="form-field form-switch-row">
            <div>
              <label class="form-label" for="model-streaming">流式输出</label>
              <p class="form-hint">开启时逐步显示回复；关闭时等待完整回复。</p>
            </div>
            <input
              id="model-streaming"
              v-model="form.streaming"
              class="switch"
              type="checkbox"
              :disabled="saving"
            />
          </div>
          <div class="form-row" style="margin-top: 14px">
            <div class="form-field">
              <label class="form-label" for="model-timeout">单次等待时间（秒）</label>
              <input
                id="model-timeout"
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
              <label class="form-label" for="model-temperature">回答随机性</label>
              <input
                id="model-temperature"
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
            <button type="button" class="btn" :disabled="saving" @click="closeEditor">取消</button>
            <button type="submit" class="btn btn-primary" :disabled="saving">
              {{ saving ? '正在保存…' : editingId ? '保存修改' : '创建模型连接' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </main>
</template>
