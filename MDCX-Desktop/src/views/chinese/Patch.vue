<template>
  <div class="chinese-patch">
    <div class="page-header">
      <h3>🇨🇳 国产 - 补丁刮削</h3>
      <p class="page-desc">对已入库的国产影片补充缺失的元数据字段</p>
    </div>
    <Patch module="chinese" />
  </div>
</template>

<script setup>
import Patch from '@/views/Patch.vue'
</script>
<style scoped>
.chinese-patch { max-width: 1200px; margin: 0 auto; }
.page-header { margin-bottom: 16px; }
.page-header h3 { margin: 0 0 4px; }
.page-desc { color: #999; font-size: 13px; margin: 0; }
</style>
