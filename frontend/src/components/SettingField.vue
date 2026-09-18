<script setup>
import { computed, ref } from 'vue'
const props = defineProps({
  field: { type: Object, required: true },
  modelValue: { required: true },
  error: { type: String, default: '' },
  disabled: Boolean,
  hasApiKey: Boolean,
  clearApiKey: Boolean,
})
const emit = defineEmits(['update:modelValue', 'clear-key'])
const revealed = ref(false)
const id = computed(() => `setting-${props.field.path.replaceAll('.', '-')}`)
function update(event) {
  const raw = event.target.value
  emit('update:modelValue', props.field.control === 'number' && raw !== '' ? Number(raw) : raw)
}
</script>

<template>
  <div class="setting-field" :class="{ 'field-invalid': error }">
    <div class="field-heading">
      <label :for="id">{{ field.label }}</label>
      <span v-if="field.control === 'switch'">{{ modelValue ? '已开启' : '已关闭' }}</span>
    </div>
    <input
      v-if="field.control === 'switch'"
      :id="id"
      class="setting-toggle"
      type="checkbox"
      :checked="modelValue"
      :disabled="disabled"
      :aria-describedby="`${id}-hint`"
      @change="emit('update:modelValue', $event.target.checked)"
    />
    <select
      v-else-if="field.control === 'select'"
      :id="id"
      :value="modelValue"
      :disabled="disabled"
      :aria-invalid="!!error"
      :aria-describedby="`${id}-hint`"
      @change="update"
    >
      <option v-for="choice in field.choices" :key="choice.value" :value="choice.value">
        {{ choice.label }}
      </option>
    </select>
    <textarea
      v-else-if="field.control === 'textarea'"
      :id="id"
      :value="modelValue"
      rows="5"
      :disabled="disabled"
      :aria-invalid="!!error"
      :aria-describedby="`${id}-hint`"
      @input="update"
    />
    <div v-else-if="field.control === 'password'" class="secret-input">
      <input
        :id="id"
        :type="revealed ? 'text' : 'password'"
        :value="modelValue"
        :disabled="disabled"
        autocomplete="new-password"
        :placeholder="hasApiKey && !clearApiKey ? '密钥已保存，留空保留' : '填写 API Key'"
        :aria-invalid="!!error"
        :aria-describedby="`${id}-hint`"
        @input="update"
      />
      <button type="button" :disabled="disabled" @click="revealed = !revealed">
        {{ revealed ? '隐藏' : '显示' }}
      </button>
    </div>
    <input
      v-else
      :id="id"
      :type="field.control === 'number' ? 'number' : 'text'"
      :value="modelValue"
      :min="field.min"
      :max="field.max"
      :step="field.step"
      :disabled="disabled"
      :aria-invalid="!!error"
      :aria-describedby="`${id}-hint`"
      autocomplete="off"
      @input="update"
    />
    <p :id="`${id}-hint`" class="field-hint">
      {{ field.hint }}
      <span v-if="field.min != null && field.max != null"
        >范围：{{ field.min }}–{{ field.max }}。</span
      >
      <span v-else-if="field.min != null">至少为 {{ field.min }}。</span>
    </p>
    <div v-if="field.control === 'password' && hasApiKey" class="secret-actions">
      <span>{{ clearApiKey ? '保存后将清除密钥' : '已保存密钥，网页不会显示其内容' }}</span>
      <button type="button" :disabled="disabled" @click="emit('clear-key')">
        {{ clearApiKey ? '保留原密钥' : '清除已保存密钥' }}
      </button>
    </div>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
  </div>
</template>
