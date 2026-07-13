<template>
  <div class="base-input">
    <label v-if="label" class="base-input__label">{{ label }}</label>
    <el-input
      :model-value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      :type="type"
      :clearable="clearable"
      @update:model-value="handleInput"
    />
  </div>
</template>

<script setup>
const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  label: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  type: { type: String, default: 'text' },
  clearable: { type: Boolean, default: true }
})
const emit = defineEmits(['update:modelValue'])
function handleInput(val) { emit('update:modelValue', val) }
</script>

<style scoped>
.base-input { margin-bottom: 12px; }
.base-input__label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  color: var(--text-regular, #606266);
  font-weight: 500;
}
</style>
