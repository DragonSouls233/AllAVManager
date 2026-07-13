<template>
  <button
    :class="['base-btn', `base-btn--${variant}`, `base-btn--${size}`, { 'is-block': block, 'is-disabled': disabled }]"
    :disabled="disabled"
    @click="handleClick"
  >
    <el-icon v-if="icon" class="base-btn__icon"><component :is="icon" /></el-icon>
    <span class="base-btn__text"><slot /></span>
  </button>
</template>

<script setup>
/**
 * BaseButton 基础按钮组件
 * 对应 MDCX-UI-Design-Complete.md §3.5.1
 * 变体:primary / secondary / ghost / danger / link
 * 尺寸:sm (32px) / md (36px) / lg (44px)
 */
const props = defineProps({
  variant: { type: String, default: 'primary' }, // primary/secondary/ghost/danger/link
  size: { type: String, default: 'md' },          // sm/md/lg
  disabled: { type: Boolean, default: false },
  block: { type: Boolean, default: false },
  icon: { type: [String, Object, Function], default: null }
})
const emit = defineEmits(['click'])
function handleClick(e) {
  if (props.disabled) return
  emit('click', e)
}
</script>

<style scoped>
.base-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  font-family: var(--font-family-sans);
  font-weight: var(--font-weight-medium);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  user-select: none;
  white-space: nowrap;
  text-decoration: none;
}

/* === 焦点轮廓（WCAG AA §7.2.2）=== */
.base-btn:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}
.base-btn:focus:not(:focus-visible) {
  outline: none;
}

/* === 变体 === */
.base-btn--primary {
  background: var(--primary-color);
  color: var(--color-text-inverse);
}
.base-btn--primary:hover:not(.is-disabled) {
  background: var(--primary-dark);
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.base-btn--secondary {
  background: var(--bg-card);
  color: var(--text-regular);
  border-color: var(--border-color);
}
.base-btn--secondary:hover:not(.is-disabled) {
  border-color: var(--primary-color);
  color: var(--primary-color);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

.base-btn--ghost {
  background: transparent;
  color: var(--text-regular);
}
.base-btn--ghost:hover:not(.is-disabled) {
  background: var(--bg-page);
  color: var(--text-primary);
}

.base-btn--danger {
  background: var(--danger-color);
  color: var(--color-text-inverse);
}
.base-btn--danger:hover:not(.is-disabled) {
  filter: brightness(1.1);
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.base-btn--link {
  background: transparent;
  color: var(--primary-color);
  border: none;
  padding: 0;
  height: auto;
}
.base-btn--link:hover:not(.is-disabled) {
  color: var(--primary-dark);
  text-decoration: underline;
}

/* === 尺寸（§3.5.1 sm 32px / md 36px / lg 44px）=== */
.base-btn--sm { padding: 6px 12px; font-size: var(--font-size-sm); height: 32px; }
.base-btn--md { padding: 8px 16px; font-size: var(--font-size-base); height: 36px; }
.base-btn--lg { padding: 12px 24px; font-size: var(--font-size-lg); height: 44px; }

/* === 状态 === */
.base-btn.is-disabled,
.base-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}
.is-block {
  display: flex;
  width: 100%;
  justify-content: center;
}

/* === 图标 === */
.base-btn__icon {
  font-size: inherit;
  display: inline-flex;
  align-items: center;
}
</style>
