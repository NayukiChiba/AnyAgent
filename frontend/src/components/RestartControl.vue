<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { request } from '../api.js'
import '../restart.css'
const props = defineProps({ preferences: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['busy'])
const supported = ref(false)
const restarting = ref(false)
const message = ref('')
const failed = ref(false)
const target = ref('')
let controller
let timer
let timeoutTimer
let wake
let disposed = false
const explanation = computed(() =>
  supported.value
    ? '重新加载已保存的设置，内存聊天记录将清空。'
    : '通过 main.py 启动服务后可在此重启。',
)
async function restart() {
  if (!window.confirm('确定重启整个服务吗？正在进行的对话会停止，内存聊天记录会清空。')) return
  restarting.value = true
  failed.value = false
  emit('busy', true)
  controller = new AbortController()
  try {
    const result = await request('/api/v1/system/restart', {
      method: 'POST',
      signal: controller.signal,
    })
    const next = new URL(location.href)
    next.port = String(result.port)
    next.pathname = '/settings'
    next.search = ''
    target.value = next.href
    message.value = '正在重启，请保持此页面打开…'
    const deadline = Date.now() + props.preferences.restart_wait_timeout_seconds * 1000
    timeoutTimer = setTimeout(
      () => controller.abort(),
      props.preferences.restart_wait_timeout_seconds * 1000,
    )
    while (Date.now() < deadline && !controller.signal.aborted) {
      await new Promise((resolve) => {
        wake = resolve
        timer = setTimeout(
          resolve,
          Math.min(props.preferences.restart_poll_interval_ms, deadline - Date.now()),
        )
      })
      if (controller.signal.aborted) break
      try {
        const response = await fetch(new URL('/api/v1/system', next), {
          signal: controller.signal,
          cache: 'no-store',
        })
        const status = await response.json()
        if (response.ok && status.ready && status.instance_id !== result.instance_id) {
          message.value = '重启完成，正在重新打开设置…'
          location.assign(next.href)
          return
        }
      } catch (error) {
        if (error.name === 'AbortError') break
        // The listener is temporarily unavailable while the process is replaced.
      }
    }
    if (disposed) return
    failed.value = true
    message.value = '暂时无法确认重启结果，请通过下方地址重新打开。若仍不可用，请查看服务运行窗口。'
  } catch (error) {
    if (error.name === 'AbortError') return
    failed.value = true
    message.value = error.message
  } finally {
    clearTimeout(timeoutTimer)
    wake = undefined
    restarting.value = false
    emit('busy', false)
  }
}
onMounted(async () => {
  try {
    supported.value = (await request('/api/v1/system')).restart_available
  } catch {
    supported.value = false
  }
})
onBeforeUnmount(() => {
  disposed = true
  controller?.abort()
  clearTimeout(timer)
  clearTimeout(timeoutTimer)
  wake?.()
})
</script>

<template>
  <section class="restart-panel" aria-label="服务重启">
    <div>
      <strong>重启服务</strong>
      <p>{{ explanation }}</p>
    </div>
    <button
      type="button"
      class="restart-button"
      :disabled="disabled || !supported || restarting"
      @click="restart"
    >
      {{ restarting ? '正在重启…' : '重启服务' }}
    </button>
    <p
      v-if="message"
      class="restart-feedback"
      :class="{ error: failed }"
      :role="failed ? 'alert' : 'status'"
    >
      {{ message }}<a v-if="failed && target" :href="target">重新打开设置 ↗</a>
    </p>
  </section>
</template>
