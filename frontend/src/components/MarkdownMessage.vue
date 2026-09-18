<script setup>
import { computed, ref, watch } from 'vue'
import { renderMarkdown } from '../markdown.js'
import '../markdown.css'

const props = defineProps({ content: { type: String, default: '' } })
const html = computed(() => renderMarkdown(props.content))
const copyNotice = ref('')
watch(
  () => props.content,
  () => {
    copyNotice.value = ''
  },
)
async function copyCode(event) {
  const button = event.target.closest?.('.markdown-copy')
  if (!button) return
  const code = button.closest('.markdown-code')?.querySelector('pre code')
  if (!code) return
  try {
    await navigator.clipboard.writeText(code.textContent)
    copyNotice.value = '代码已复制'
  } catch {
    copyNotice.value = '复制失败，请选中代码后手动复制。'
  }
}
</script>

<template>
  <div class="markdown-body">
    <div @click="copyCode" v-html="html"></div>
    <p v-if="copyNotice" class="markdown-copy-notice" role="status">{{ copyNotice }}</p>
  </div>
</template>
