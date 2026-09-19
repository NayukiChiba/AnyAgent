<script setup>
import { computed, ref } from 'vue'
import SettingSelect from './SettingSelect.vue'
const props = defineProps({
  field: { type: Object, required: true },
  idPrefix: { type: String, default: '' },
  modelValue: { required: true },
  error: { type: String, default: '' },
  disabled: Boolean,
  hasApiKey: Boolean,
  clearApiKey: Boolean,
})
const emit = defineEmits(['update:modelValue', 'clear-key'])
const revealed = ref(false)
const SECRET_MASK = '••••••••••••'
const id = computed(
  () =>
    `setting-${props.idPrefix ? `${props.idPrefix}-` : ''}${props.field.path.replaceAll('.', '-')}`,
)
const showingStoredSecret = computed(
  () =>
    props.field.control === 'password' &&
    props.hasApiKey &&
    !props.clearApiKey &&
    !props.modelValue,
)
const displayedValue = computed(() => (showingStoredSecret.value ? SECRET_MASK : props.modelValue))
function update(event) {
  const raw = event.target.value
  if (showingStoredSecret.value && raw === SECRET_MASK) return
  emit('update:modelValue', props.field.control === 'number' && raw !== '' ? Number(raw) : raw)
}
function focusSecret(event) {
  if (showingStoredSecret.value) event.target.select()
}
</script>

<template>
  <div
    class="setting-field"
    :class="{ 'field-invalid': error, 'switch-field': field.control === 'switch' }"
  >
    <div class="field-heading">
      <label :id="`${id}-label`" :for="id">{{ field.label }}</label>
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
    <SettingSelect
      v-else-if="field.control === 'select'"
      :id="id"
      :model-value="modelValue"
      :choices="field.choices"
      :disabled="disabled"
      :invalid="!!error"
      :labelledby="`${id}-label`"
      :describedby="`${id}-hint`"
      @update:model-value="emit('update:modelValue', $event)"
    />
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
        :value="displayedValue"
        :class="{ 'stored-secret': showingStoredSecret }"
        :disabled="disabled"
        autocomplete="new-password"
        :placeholder="clearApiKey ? '保存后将清除密钥' : '填写 API Key'"
        :aria-invalid="!!error"
        :aria-describedby="`${id}-hint`"
        @focus="focusSecret"
        @input="update"
      />
      <button
        type="button"
        :disabled="disabled || showingStoredSecret"
        @click="revealed = !revealed"
      >
        {{ showingStoredSecret ? '已隐藏' : revealed ? '隐藏' : '显示' }}
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
      <span>{{ clearApiKey ? '保存后将清除密钥' : '已保存密钥，使用掩码保护其内容' }}</span>
      <button type="button" :disabled="disabled" @click="emit('clear-key')">
        {{ clearApiKey ? '保留原密钥' : '清除已保存密钥' }}
      </button>
    </div>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
  </div>
</template>
