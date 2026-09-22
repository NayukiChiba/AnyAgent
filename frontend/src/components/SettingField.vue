<script setup>
import { computed } from 'vue'
import SettingSelect from './SettingSelect.vue'
const props = defineProps({
  field: { type: Object, required: true },
  idPrefix: { type: String, default: '' },
  modelValue: { required: true },
  error: { type: String, default: '' },
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue'])
const id = computed(
  () =>
    `setting-${props.idPrefix ? `${props.idPrefix}-` : ''}${props.field.path.replaceAll('.', '-')}`,
)
function update(event) {
  const raw = event.target.value
  emit('update:modelValue', props.field.control === 'number' && raw !== '' ? Number(raw) : raw)
}
</script>

<template>
  <div
    class="setting-field"
    :class="{ 'field-invalid': error, 'switch-field': field.control === 'switch' }"
  >
    <div class="field-heading">
      <label :id="`${id}-label`" :for="id">{{ field.label }}</label>
      <span v-if="field.control === 'switch'" class="switch-state">{{
        modelValue ? '已开启' : '已关闭'
      }}</span>
    </div>
    <input
      v-if="field.control === 'switch'"
      :id="id"
      class="switch"
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
      class="textarea"
      :value="modelValue"
      rows="5"
      :disabled="disabled"
      :aria-invalid="!!error"
      :aria-describedby="`${id}-hint`"
      @input="update"
    />
    <input
      v-else
      :id="id"
      class="input"
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
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
  </div>
</template>
