<template>
  <section>
    <div class="cinema-page-head">
      <h1 class="cinema-page-title">{{ title }}</h1>
      <span class="cinema-page-count">{{ lib.currentLabel }}</span>
    </div>
    <div class="cinema-empty">
      <div class="cinema-empty-icon">{{ icon }}</div>
      <div class="cinema-empty-text">{{ desc }}</div>
      <div class="cinema-empty-hint">{{ stage }} 阶段实现</div>
    </div>
  </section>
</template>

<script setup>
import { useLibraryStore } from '@/stores/library'

defineProps({
  title: { type: String, required: true },
  icon: { type: String, default: '🚧' },
  desc: { type: String, default: '该页面正在建设中' },
  stage: { type: String, default: 'P1' }
})

const lib = useLibraryStore()
</script>

<style scoped>
.cinema-empty-hint {
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-3);
  opacity: 0.7;
}
</style>
