<template>
  <div class="alphabet-bar" v-if="alphabet && alphabet.length">
    <span class="alpha-title">{{ title }}</span>
    <div class="alpha-list">
      <button
        v-for="g in alphabet"
        :key="g.letter"
        class="alpha-btn"
        :class="{ active: selectedLetter === g.letter, disabled: g.count === 0 }"
        :disabled="g.count === 0"
        @click="onSelect(g.letter)"
      >
        <span class="alpha-letter">{{ g.letter }}</span>
        <span class="alpha-count" v-if="g.count > 0">{{ g.count }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  alphabet: { type: Array, default: () => [] },
  selectedLetter: { type: String, default: '' },
  title: { type: String, default: '番号首字母' }
})

const emit = defineEmits(['select'])

const onSelect = (letter) => {
  emit('select', letter)
}
</script>

<style scoped>
.alphabet-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-card);
  border-radius: 8px;
  box-shadow: var(--shadow-sm);
  flex-wrap: wrap;
}

.alpha-title {
  font-size: 13px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.alpha-list {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.alpha-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  padding: 4px 6px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-regular);
  cursor: pointer;
  transition: all 0.15s;
}

.alpha-btn:hover:not(.disabled) {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.alpha-btn.active {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: #fff;
}

.alpha-btn.disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.alpha-letter {
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
}

.alpha-count {
  font-size: 10px;
  opacity: 0.7;
  line-height: 1;
  margin-top: 2px;
}
</style>
