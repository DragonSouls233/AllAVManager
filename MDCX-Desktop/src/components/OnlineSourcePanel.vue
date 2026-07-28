<template>
  <!--
    在线播放源搜索面板
    按番号搜索多站 M3U8 播放源，一键切换
  -->
  <div class="online-source-panel">
    <div class="source-header">
      <el-icon :size="16"><VideoCamera /></el-icon>
      <span>在线播放源（{{ sources.length }} 个站点）</span>
      <el-button
        size="small"
        type="primary"
        :loading="searching"
        :icon="Search"
        @click="search"
        style="margin-left: auto;"
      >
        {{ searching ? '搜索中...' : '搜索播放源' }}
      </el-button>
    </div>

    <div v-if="!sources.length && !searching" class="source-empty">
      <el-empty description="点击「搜索播放源」查找在线播出" :image-size="40" />
    </div>

    <div v-if="error" class="source-error">
      <el-alert :title="error" type="warning" show-icon :closable="false" />
    </div>

    <div v-if="sources.length" class="source-list">
      <div
        v-for="(src, idx) in sources"
        :key="idx"
        class="source-item"
        :class="{ active: currentUrl === src.url }"
        @click="$emit('select', src)"
      >
        <div class="source-site">
          <span class="site-badge" :class="src.site">{{ src.site }}</span>
          <span class="source-quality">{{ src.quality || '自动' }}</span>
        </div>
        <div class="source-url-text">{{ src.url.slice(0, 50) }}...</div>
        <div v-if="src.note" class="source-note">{{ src.note }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * 在线播放源搜索面板
 *
 * 依赖后端 GET /api/mcp/stream/search?code={code}
 * 点击源时 emit('select', { url, site, is_hls })
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, VideoCamera } from '@element-plus/icons-vue'
import { searchOnlineSource } from '@/api/mcp_stream'

const props = defineProps({
  code: { type: String, default: '' },
  currentUrl: { type: String, default: '' },
})

const emit = defineEmits(['select'])

const sources = ref([])
const searching = ref(false)
const error = ref('')

async function search() {
  if (!props.code) {
    ElMessage.warning('请先选择影片')
    return
  }
  searching.value = true
  error.value = ''
  sources.value = []

  try {
    const res = await searchOnlineSource(props.code)
    if (res?.sources?.length) {
      sources.value = res.sources
      ElMessage.success(`找到 ${res.sources.length} 个播放源`)
    } else {
      error.value = res?.error || '未找到播放源'
    }
  } catch (e) {
    error.value = '搜索失败: ' + (e.message || e)
  } finally {
    searching.value = false
  }
}
</script>

<style scoped>
.online-source-panel {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 12px;
  background: var(--el-bg-color-overlay);
}
.source-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 600;
}
.source-empty { padding: 10px 0; }
.source-error { margin-bottom: 8px; }
.source-list { display: flex; flex-direction: column; gap: 6px; }
.source-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all .15s;
}
.source-item:hover { background: var(--el-fill-color-light); }
.source-item.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.source-site { display: flex; align-items: center; gap: 6px; }
.site-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  text-transform: uppercase;
}
.site-badge.missav { background: #e74c3c; }
.site-badge.jable { background: #3498db; }
.site-badge.av01 { background: #2ecc71; }
.site-badge.javgg { background: #9b59b6; }
.site-badge.javtrailers { background: #e67e22; }
.site-badge.\37 mmtv { background: #1abc9c; }
.source-quality { font-size: 12px; color: var(--el-text-color-secondary); }
.source-url-text { font-size: 11px; color: var(--el-text-color-placeholder); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source-note { font-size: 11px; color: var(--el-color-warning); }
</style>
