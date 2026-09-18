<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
const props = defineProps({
  id: { type: String, required: true },
  modelValue: { type: String, required: true },
  choices: { type: Array, required: true },
  labelledby: { type: String, required: true },
  describedby: { type: String, default: undefined },
  disabled: Boolean,
  invalid: Boolean,
})
const emit = defineEmits(['update:modelValue'])
const root = ref(null)
const trigger = ref(null)
const opened = ref(false)
const active = ref(0)
const chosen = computed(
  () => props.choices.find((item) => item.value === props.modelValue)?.label || '请选择',
)
function open() {
  if (props.disabled) return
  active.value = Math.max(
    0,
    props.choices.findIndex((item) => item.value === props.modelValue),
  )
  opened.value = true
}
function choose(index) {
  emit('update:modelValue', props.choices[index].value)
  opened.value = false
  trigger.value?.focus()
}
function key(event) {
  if (props.disabled) return
  if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(event.key)) {
    event.preventDefault()
    if (!opened.value) {
      open()
      return
    }
    if (event.key === 'ArrowDown')
      active.value = Math.min(active.value + 1, props.choices.length - 1)
    if (event.key === 'ArrowUp') active.value = Math.max(active.value - 1, 0)
    if (event.key === 'Home') active.value = 0
    if (event.key === 'End') active.value = props.choices.length - 1
    if (event.key === 'Enter' || event.key === ' ') choose(active.value)
    document
      .getElementById(`${props.id}-option-${active.value}`)
      ?.scrollIntoView({ block: 'nearest' })
  } else if (event.key === 'Escape' || event.key === 'Tab') opened.value = false
}
function outside(event) {
  if (!root.value?.contains(event.target)) opened.value = false
}
watch(
  () => props.disabled,
  (value) => {
    if (value) opened.value = false
  },
)
onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))
</script>

<template>
  <div
    ref="root"
    class="setting-select"
    :class="{ 'select-open': opened }"
    @focusout="!root.contains($event.relatedTarget) && (opened = false)"
  >
    <button
      :id="id"
      ref="trigger"
      type="button"
      role="combobox"
      class="select-trigger"
      :disabled="disabled"
      :aria-expanded="opened"
      aria-haspopup="listbox"
      :aria-controls="`${id}-listbox`"
      :aria-labelledby="labelledby"
      :aria-describedby="describedby"
      :aria-invalid="invalid"
      :aria-activedescendant="opened ? `${id}-option-${active}` : undefined"
      @click="opened ? (opened = false) : open()"
      @keydown="key"
    >
      <span>{{ chosen }}</span
      ><svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24">
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
    <ul
      v-if="opened"
      :id="`${id}-listbox`"
      role="listbox"
      :aria-labelledby="labelledby"
      class="select-menu"
    >
      <li
        v-for="(choice, index) in choices"
        :id="`${id}-option-${index}`"
        :key="choice.value"
        role="option"
        :aria-selected="choice.value === modelValue"
        :class="{ highlighted: index === active }"
        @pointermove="active = index"
        @pointerdown.prevent
        @click="choose(index)"
      >
        {{ choice.label }}<span v-if="choice.value === modelValue" aria-hidden="true">✓</span>
      </li>
    </ul>
  </div>
</template>
