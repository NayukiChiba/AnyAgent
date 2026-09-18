<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import SettingField from '../components/SettingField.vue'
import { request } from '../api.js'
import '../settings.css'

const groups = ref([])
const selected = ref('model_config')
const form = ref({})
const baseline = ref('{}')
const clearApiKey = ref(false)
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const notice = ref('')
const failed = ref(false)
const errors = ref({})
const advanced = ref(false)
const group = computed(() => groups.value.find((item) => item.name === selected.value))
const dirty = computed(() => JSON.stringify(form.value) !== baseline.value || clearApiKey.value)
const working = computed(() => saving.value || testing.value)
const basicFields = computed(() => group.value?.fields.filter((field) => !field.advanced) || [])
const advancedFields = computed(() => group.value?.fields.filter((field) => field.advanced) || [])

function getValue(values, path) {
  return path.split('.').reduce((node, key) => node?.[key], values)
}
function setValue(values, path, value) {
  const keys = path.split('.')
  const node = keys.slice(0, -1).reduce((result, key) => (result[key] ??= {}), values)
  node[keys.at(-1)] = value
}
function loadForm(values = group.value.values) {
  form.value = Object.fromEntries(
    group.value.fields.map((field) => [field.path, getValue(values, field.path)]),
  )
  clearApiKey.value = false
  errors.value = {}
}
function discardAllowed() {
  return !dirty.value || window.confirm('有尚未保存的修改，确定放弃这些修改吗？')
}
async function reload() {
  if (!discardAllowed()) return
  loading.value = true
  notice.value = ''
  try {
    groups.value = (await request('/api/v1/settings')).groups
    loadForm()
    baseline.value = JSON.stringify(form.value)
    failed.value = false
  } catch (error) {
    failed.value = true
    notice.value = error.message
  } finally {
    loading.value = false
  }
}
function selectGroup(name) {
  if (name === selected.value || working.value || !discardAllowed()) return
  selected.value = name
  loadForm()
  baseline.value = JSON.stringify(form.value)
  notice.value = ''
  advanced.value = false
}
function undo() {
  loadForm()
  baseline.value = JSON.stringify(form.value)
  notice.value = ''
}
function defaults() {
  if (!window.confirm('将本组设置恢复为默认值，点击保存后才会写入。确定继续吗？')) return
  loadForm(group.value.defaults)
  notice.value = `默认值已填入，请检查后点击保存。${selected.value === 'model_config' ? '原密钥会保留，清除密钥需要单独选择。' : ''}`
  failed.value = false
}
function clearKey() {
  if (clearApiKey.value) {
    clearApiKey.value = false
    return
  }
  if (
    window.confirm(
      '清除密钥后模型将无法使用。请同时关闭“启用模型”，或改为填写新的密钥。确定标记清除吗？',
    )
  ) {
    clearApiKey.value = true
    form.value.api_key = ''
  }
}
async function save() {
  saving.value = true
  notice.value = ''
  errors.value = {}
  const values = JSON.parse(JSON.stringify(group.value.values))
  for (const [path, value] of Object.entries(form.value)) setValue(values, path, value)
  try {
    const result = await request(`/api/v1/settings/${selected.value}`, {
      method: 'PUT',
      body: JSON.stringify({
        values,
        revision: group.value.revision,
        clear_api_key: clearApiKey.value,
      }),
    })
    groups.value = groups.value.map((item) => (item.name === result.name ? result : item))
    loadForm()
    baseline.value = JSON.stringify(form.value)
    failed.value = false
    notice.value = `设置已保存。${result.apply_notice}`
  } catch (error) {
    failed.value = true
    notice.value = error.message
    errors.value = error.fields || {}
    if (group.value.fields.some((field) => field.advanced && errors.value[field.path]))
      advanced.value = true
    await nextTick()
    const first = Object.keys(errors.value)[0]
    document.getElementById(`setting-${first?.replaceAll('.', '-')}`)?.focus()
  } finally {
    saving.value = false
  }
}
async function testConnection() {
  testing.value = true
  notice.value = '正在测试，请稍候…'
  failed.value = false
  try {
    notice.value = (await request('/api/v1/settings/model_config/test', { method: 'POST' })).message
  } catch (error) {
    failed.value = true
    notice.value = error.message
  } finally {
    testing.value = false
  }
}
watch(
  () => form.value.api_key,
  (value) => {
    if (value) clearApiKey.value = false
  },
)
function beforeUnload(event) {
  if (dirty.value) {
    event.preventDefault()
    event.returnValue = ''
  }
}
onMounted(() => {
  reload()
  window.addEventListener('beforeunload', beforeUnload)
})
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
onBeforeRouteLeave(() => !working.value && discardAllowed())
</script>

<template>
  <div class="settings-workspace">
    <aside class="settings-sidebar">
      <RouterLink class="brand" to="/"><span class="brand-mark">A</span>AnyAgent</RouterLink>
      <RouterLink to="/" class="back-chat">← 返回聊天</RouterLink>
      <div class="settings-caption">设置</div>
      <nav aria-label="设置分类">
        <button
          v-for="item in groups"
          :key="item.name"
          :class="{ active: item.name === selected }"
          :disabled="working"
          @click="selectGroup(item.name)"
        >
          {{ item.title }}<span v-if="item.restart_required">待重启</span>
        </button>
      </nav>
      <p class="settings-storage">设置会保存在本机，重新打开网页也不会丢失。</p>
    </aside>
    <main class="settings-main">
      <header class="settings-topbar">
        <div>
          <span class="eyebrow">ANYAGENT SETTINGS</span>
          <h1>设置</h1>
        </div>
        <button class="icon-button" :disabled="loading || working" @click="reload">重新载入</button>
      </header>
      <div class="settings-content">
        <p v-if="loading" role="status">正在载入设置…</p>
        <div
          v-if="notice"
          class="settings-notice"
          :class="{ error: failed }"
          :role="failed ? 'alert' : 'status'"
        >
          {{ notice }}
        </div>
        <form v-if="group && !loading" novalidate @submit.prevent="save">
          <div class="group-heading">
            <h2>{{ group.title }}</h2>
            <span class="change-state">{{ dirty ? '有未保存的修改' : '已同步' }}</span>
          </div>
          <p class="group-description">{{ group.description }}</p>
          <div v-if="selected === 'model_config'" class="setup-guide">
            <strong>连接你的第一个模型</strong>
            <p>① 填写服务商提供的接口信息　② 开启模型并保存　③ 测试连接，然后返回聊天</p>
          </div>
          <p class="apply-notice">
            {{ group.apply_notice
            }}<strong v-if="group.restart_required"> 已保存新设置，等待重启服务。</strong>
          </p>
          <SettingField
            v-for="field in basicFields"
            :key="`${selected}-${field.path}`"
            :field="field"
            v-model="form[field.path]"
            :error="errors[field.path]"
            :disabled="working"
            :has-api-key="group.has_api_key"
            :clear-api-key="clearApiKey"
            @clear-key="clearKey"
          />
          <details
            v-if="advancedFields.length"
            :open="advanced"
            class="advanced-settings"
            @toggle="advanced = $event.target.open"
          >
            <summary>高级设置 <span>首次使用通常无需修改</span></summary>
            <SettingField
              v-for="field in advancedFields"
              :key="`${selected}-${field.path}`"
              :field="field"
              v-model="form[field.path]"
              :error="errors[field.path]"
              :disabled="working"
            />
          </details>
          <div class="settings-actions">
            <button type="submit" class="save-settings" :disabled="working || !dirty">
              {{ saving ? '正在保存…' : '保存设置' }}
            </button>
            <button type="button" class="icon-button" :disabled="working || !dirty" @click="undo">
              撤销修改
            </button>
            <button type="button" class="text-button" :disabled="working" @click="defaults">
              恢复本组默认值
            </button>
          </div>
          <div v-if="selected === 'model_config'" class="connection-test">
            <button
              type="button"
              class="icon-button"
              :disabled="working || dirty || !group.values.enabled"
              @click="testConnection"
            >
              {{ testing ? '正在测试…' : '测试已保存的连接' }}
            </button>
            <p>
              {{
                dirty
                  ? '请先保存修改，再测试最新的模型连接。'
                  : '测试会发起一次简短模型调用，可能产生少量费用，不会写入聊天记录。'
              }}
            </p>
          </div>
        </form>
      </div>
    </main>
  </div>
</template>
