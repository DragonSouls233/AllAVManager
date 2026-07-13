<template>
  <div class="rating-stars" :class="sizeClass" v-if="rating != null">
    <el-icon><Star /></el-icon>
    <span>{{ Number(rating).toFixed(1) }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Star } from '@element-plus/icons-vue'

const props = defineProps({
  rating: { type: [Number, String, null], default: null },
  size: { type: String, default: 'normal' } // normal | small | large
})

const sizeClass = computed(() => `size-${props.size}`)
</script>

<style scoped>
.rating-stars {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: rgba(0, 0, 0, 0.7);
  color: #f7ba2a;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 10px;
  backdrop-filter: blur(4px);
}

.size-small {
  font-size: 11px;
}

.size-normal {
  font-size: 12px;
}

.size-large {
  font-size: 14px;
  padding: 4px 12px;
}
</style>
