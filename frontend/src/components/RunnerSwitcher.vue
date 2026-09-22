<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { activateProfile, listProfiles } from '../api.js'

const props = defineProps({
  disabled: Boolean,
})
const emit = defineEmits(['changed', 'failed'])
const router = useRouter()

const root = ref(null)
const trigger = ref(null)
const open = ref(false)
const switching = ref(false)
const profiles = ref([])
const activeId = ref(null)

const active = computed(() => profiles.value.find((item) => item.id === activeId.value) || null)

async function load() {
  try {
    const data = await listProfiles()
    profiles.value = data.profiles
    activeId.value = data.active
  } catch (error) {
    emit('failed', error.message)
  }
}
async function toggle() {
  if (props.disabled || switching.value) return
  open.value = !open.value
  if (open.value) await load()
}
async function choose(profile) {
  if (profile.id === activeId.value) {
    open.value = false
    trigger.value?.focus()
    return
  }
  switching.value = true
  try {
    await activateProfile(profile.id)
    activeId.value = profile.id
    open.value = false
    trigger.value?.focus()
    emit('changed', profile)
  } catch (error) {
    emit('failed', error.message)
  } finally {
    switching.value = false
  }
}
function manage() {
  open.value = false
  router.push('/runners')
}
function onKeydown(event) {
  if (event.key === 'Escape' && open.value) {
    open.value = false
    trigger.value?.focus()
  }
}
function onPointerDown(event) {
  if (!root.value?.contains(event.target)) open.value = false
}
onMounted(() => {
  load()
  document.addEventListener('pointerdown', onPointerDown)
})
onBeforeUnmount(() => document.removeEventListener('pointerdown', onPointerDown))
</script>

<template>
  <div ref="root" class="runner-switcher" :class="{ open }" @keydown="onKeydown">
    <button
      ref="trigger"
      type="button"
      class="runner-trigger"
      aria-label="切换 Runner"
      :aria-expanded="open"
      :disabled="disabled || switching"
      @click="toggle"
    >
      <template v-if="active">
        <span class="type-badge" :data-type="active.type">{{ active.type }}</span>
        <span class="runner-name"
          >{{ active.name
          }}<span class="runner-sub"
            >{{ active.base_url.replace(/^https?:\/\//, '')
            }}<template v-if="active.model"> · {{ active.model }}</template></span
          ></span
        >
      </template>
      <span v-else class="runner-name empty">{{ switching ? '正在切换…' : '未启用 Runner' }}</span>
      <svg class="chevron" aria-hidden="true" width="14" height="14" viewBox="0 0 24 24">
        <path
          d="m6 9 6 6 6-6"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>
    <div v-if="open" class="runner-menu" aria-label="Runner 列表">
      <p v-if="!profiles.length" class="menu-empty">还没有 Runner，先创建一个。</p>
      <button
        v-for="profile in profiles"
        :key="profile.id"
        type="button"
        class="runner-option"
        :disabled="switching"
        :aria-current="profile.id === activeId ? 'true' : undefined"
        @click="choose(profile)"
      >
        <span class="type-badge" :data-type="profile.type">{{ profile.type }}</span>
        <span class="runner-option-name">{{ profile.name }}</span>
        <span v-if="profile.id === activeId" class="check" aria-label="当前启用">✓</span>
      </button>
      <button type="button" class="runner-option manage-item" @click="manage">管理 Runner…</button>
    </div>
  </div>
</template>
