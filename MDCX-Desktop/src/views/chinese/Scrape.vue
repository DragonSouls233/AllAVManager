<template>
  <div class="chinese-scrape">
    <div class="page-header">
      <h3>🇨🇳 国产 - 刮削管理</h3>
      <p class="page-desc">管理国产内容的刮削源、LLM 配置和降级策略</p>
    </div>
    <el-alert title="国产模块使用独有的刮削策略：文件夹演员识别 → LLM 智能兜底 → 5级降级（麻豆/91/直播/自拍/其他）。具体爬虫和站点管理参考站点注册表。" type="info" show-icon :closable="false" style="margin-bottom:16px" />
    <el-button @click="$router.push('/sites')" type="primary">
      <el-icon><Connection /></el-icon> 前往站点注册表
    </el-button>
  </div>
</template>

<script setup>
</script>
<style scoped>
.chinese-scrape { max-width: 900px; margin: 0 auto; }
.page-header { margin-bottom: 16px; }
.page-header h3 { margin: 0 0 4px; }
.page-desc { color: #999; font-size: 13px; margin: 0; }
</style>
