<template>
  <div class="actor-from-folder">
    <el-tag
      v-for="actor in actors"
      :key="actor"
      type="success"
      size="small"
      style="margin: 2px"
      closable
      @close="$emit('remove', actor)"
    >
      <el-icon style="margin-right: 2px"><User /></el-icon>
      {{ actor }}
    </el-tag>
    <span v-if="!actors?.length" class="empty-text">未识别到文件夹演员</span>
  </div>
</template>

<script setup>
defineProps({
  actors: { type: Array, default: () => [] }
})
defineEmits(['remove'])
</script>

<style scoped>
.actor-from-folder { display: flex; flex-wrap: wrap; gap: 2px; }
.empty-text { font-size: 12px; color: #ccc; }
</style>
