<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import SettingField from '../components/SettingField.vue'
import RestartControl from '../components/RestartControl.vue'
import { request } from '../api.js'
import { announceFrontendConfig } from '../configSync.js'
import '../styles/settings.css'

const SYSTEM_PAGE = 'system'
/* 模型连接与执行引擎已由 Runner 档案接管，设置页不再展示这些字段；
   配置文件中的原字段保留，供旧版兼容模式派生档案。 */
const HIDDEN_GROUPS = new Set(['model_config'])
const HIDDEN_FIELDS = {
  langchain_config: new Set(['runner', 'coze_bot_id']),
}

const groups = ref([])
const selected = ref('frontend_config')
const forms = ref({})
const baselines = ref({})
const loading = ref(true)
const saving = ref(false)
const restarting = ref(false)
const notice = ref('')
const failed = ref(false)
const errors = ref({})

const systemGroups = computed(() => groups.value.filter((item) => item.apply_mode === 'restart'))
const navigationItems = computed(() => {
  const items = groups.value.filter((item) => item.apply_mode !== 'restart')
  if (systemGroups.value.length)
    items.push({
      name: SYSTEM_PAGE,
      title: '系统设置',
      restart_required: systemGroups.value.some((item) => item.restart_required),
    })
  return items
})
const visibleGroups = computed(() =>
  selected.value === SYSTEM_PAGE
    ? systemGroups.value
    : groups.value.filter((item) => item.name === selected.value),
)
const working = computed(() => saving.value || restarting.value)
const dirtyGroups = computed(() => visibleGroups.value.filter((item) => isGroupDirty(item)))
const dirty = computed(() => dirtyGroups.value.length > 0)
const restartPending = computed(() => systemGroups.value.some((item) => item.restart_required))
const frontendPreferences = computed(
  () => groups.value.find((item) => item.name === 'frontend_config')?.values,
)

function getValue(values, path) {
  return path.split('.').reduce((node, key) => node?.[key], values)
}
function setValue(values, path, value) {
  const keys = path.split('.')
  const node = keys.slice(0, -1).reduce((result, key) => (result[key] ??= {}), values)
  node[keys.at(-1)] = value
}
function valuesFor(item, values = item.values) {
  return Object.fromEntries(item.fields.map((field) => [field.path, getValue(values, field.path)]))
}
function fillGroup(item, values = item.values) {
  forms.value[item.name] = valuesFor(item, values)
  errors.value[item.name] = {}
}
function loadGroup(item) {
  fillGroup(item)
  baselines.value[item.name] = JSON.stringify(forms.value[item.name])
}
function isGroupDirty(item) {
  return JSON.stringify(forms.value[item.name]) !== baselines.value[item.name]
}
function discardAllowed() {
  return !dirty.value || window.confirm('有尚未保存的修改，确定放弃这些修改吗？')
}
function sanitizeGroup(item) {
  return {
    ...item,
    fields: item.fields.filter((field) => !HIDDEN_FIELDS[item.name]?.has(field.path)),
  }
}
async function reload() {
  if (!discardAllowed()) return
  loading.value = true
  notice.value = ''
  try {
    const all = (await request('/api/v1/settings')).groups
    groups.value = all.filter((item) => !HIDDEN_GROUPS.has(item.name)).map(sanitizeGroup)
    for (const item of groups.value) loadGroup(item)
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
  for (const item of visibleGroups.value) loadGroup(item)
  selected.value = name
  notice.value = ''
}
function undo() {
  for (const item of visibleGroups.value) loadGroup(item)
  notice.value = ''
}
function defaults(item) {
  if (!window.confirm(`将“${item.title}”恢复为默认值，点击保存后才会写入。确定继续吗？`)) return
  fillGroup(item, item.defaults)
  notice.value = `“${item.title}”默认值已填入，请检查后点击保存。`
  failed.value = false
}
function replaceGroup(result) {
  const sanitized = sanitizeGroup(result)
  groups.value = groups.value.map((item) => (item.name === result.name ? sanitized : item))
  loadGroup(sanitized)
}
async function focusFirstError(item) {
  await nextTick()
  const first = Object.keys(errors.value[item.name] || {})[0]
  document.getElementById(`setting-${item.name}-${first?.replaceAll('.', '-')}`)?.focus()
}
async function save() {
  const pending = [...dirtyGroups.value]
  if (!pending.length) return
  saving.value = true
  notice.value = ''
  failed.value = false
  let savedCount = 0
  try {
    for (const item of pending) {
      errors.value[item.name] = {}
      const values = JSON.parse(JSON.stringify(item.values))
      for (const [path, value] of Object.entries(forms.value[item.name]))
        setValue(values, path, value)
      try {
        const result = await request(`/api/v1/settings/${item.name}`, {
          method: 'PUT',
          body: JSON.stringify({ values, revision: item.revision }),
        })
        replaceGroup(result)
        if (result.name === 'frontend_config') announceFrontendConfig(result.revision)
        savedCount++
      } catch (error) {
        failed.value = true
        errors.value[item.name] = error.fields || {}
        notice.value = `${savedCount ? `已保存 ${savedCount} 组设置；` : ''}${error.message}`
        await focusFirstError(item)
        return
      }
    }
    const applyNotice =
      selected.value === SYSTEM_PAGE
        ? '系统设置已保存，需要重启服务后生效。'
        : groups.value.find((item) => item.name === selected.value)?.apply_notice
    notice.value = `设置已保存。${applyNotice || ''}`
  } finally {
    saving.value = false
  }
}
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
  <div class="workspace settings-workspace">
    <aside class="sidebar settings-sidebar">
      <RouterLink class="brand" to="/" aria-label="AnyAgent 首页"
        ><span class="brand-mark">A</span>AnyAgent</RouterLink
      >
      <RouterLink to="/" class="nav-item">← 返回聊天</RouterLink>
      <div class="settings-caption">设置分类</div>
      <nav class="sidebar-nav" aria-label="设置分类">
        <button
          v-for="item in navigationItems"
          :key="item.name"
          class="nav-item"
          :class="{ active: item.name === selected }"
          :disabled="working"
          @click="selectGroup(item.name)"
        >
          {{ item.title }}<span v-if="item.restart_required" class="pending-badge">待重启</span>
        </button>
      </nav>
      <div class="sidebar-footer">
        <RouterLink to="/runners" class="nav-item">Runner 管理</RouterLink>
        <p class="sidebar-note">设置保存在本机，重新打开网页也不会丢失。</p>
      </div>
    </aside>

    <main class="main settings-main">
      <header class="topbar">
        <div class="topbar-title">
          <div>
            <span class="eyebrow">ANYAGENT SETTINGS</span>
            <h1>设置</h1>
          </div>
        </div>
        <div class="topbar-actions">
          <button class="btn btn-sm" :disabled="loading || working" @click="reload">
            重新载入
          </button>
        </div>
      </header>
      <div v-if="dirty" class="settings-dirty-banner" role="status">已修改配置，请点击保存</div>
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
        <form v-if="visibleGroups.length && !loading" novalidate @submit.prevent="save">
          <h2 v-if="selected === SYSTEM_PAGE" class="system-page-title">系统设置</h2>
          <p v-if="selected === SYSTEM_PAGE" class="system-page-intro restart-required-notice">
            <b>需要重启服务</b>这里的设置会改变服务运行方式，保存后统一重启服务生效。
            <strong v-if="restartPending">当前有已保存的设置等待重启。</strong>
          </p>
          <section v-for="item in visibleGroups" :key="item.name" class="settings-group-card">
            <div class="group-heading">
              <div>
                <h2>{{ item.title }}</h2>
                <span v-if="isGroupDirty(item)" class="change-state unsaved">未保存</span>
              </div>
              <button
                type="button"
                class="btn btn-ghost btn-sm group-default"
                :disabled="working"
                @click="defaults(item)"
              >
                恢复{{ item.title }}默认值
              </button>
            </div>
            <p class="group-description">{{ item.description }}</p>
            <p v-if="selected !== SYSTEM_PAGE" class="apply-notice hot-reload-notice">
              <b>热更新</b>{{ item.apply_notice }}
            </p>
            <SettingField
              v-for="field in item.fields"
              :key="`${item.name}-${field.path}`"
              v-model="forms[item.name][field.path]"
              :field="field"
              :id-prefix="item.name"
              :error="errors[item.name]?.[field.path]"
              :disabled="working"
            />
          </section>
          <div class="settings-action-dock" aria-label="设置操作">
            <span class="action-summary">
              {{
                dirty
                  ? `${dirtyGroups.length} 组修改尚未保存`
                  : restartPending
                    ? '已保存修改等待重启'
                    : '设置已同步'
              }}
            </span>
            <button type="button" class="btn btn-sm" :disabled="working || !dirty" @click="undo">
              撤销修改
            </button>
            <button
              type="submit"
              class="btn btn-primary save-settings"
              :disabled="working || !dirty"
            >
              {{ saving ? '正在保存…' : '保存设置' }}
            </button>
            <RestartControl
              v-if="frontendPreferences"
              :preferences="frontendPreferences"
              :disabled="saving || dirty"
              :pending="restartPending"
              @busy="restarting = $event"
            />
          </div>
        </form>
      </div>
    </main>
  </div>
</template>
