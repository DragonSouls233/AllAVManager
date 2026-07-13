<template>
  <div :class="['base-card', { 'glass-card': glass }]" :style="{ padding: padding }">
    <div v-if="title || $slots.header" class="base-card__header">
      <slot name="header">
        <span class="base-card__title">{{ title }}</span>
      </slot>
      <slot name="action" />
    </div>
    <div class="base-card__body">
      <slot />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  padding: { type: String, default: '16px' },
  glass: { type: Boolean, default: false }
})
</script>

<style scoped>
.base-card {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: var(--radius-lg, 12px);
  transition: box-shadow var(--transition-base, 0.25s);
}
.base-card:hover { box-shadow: var(--shadow-md, 0 4px 12px rgba(0,0,0,0.08)); }
.base-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.base-card__title { font-size: 16px; font-weight: 600; color: var(--text-primary, #303133); }
.base-card__body { width: 100%; }
</style>
