<template>
  <div class="wikipedia-actresses">
    <el-card shadow="never">
      <template #header>
        <span class="card-title">
          <el-icon><Reading /></el-icon> 📖 维基女优 · 日本AV女優
        </span>
      </template>

      <el-alert
        title="数据实时抓取自中文维基百科分类「Category:日本AV女優」，覆盖约 200 位有独立条目的女优。点击卡片可跳转维基百科页面查看详情。"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 12px"
      />

      <div class="filter-bar">
        <el-input
          v-model="keyword"
          placeholder="搜索女优名（本地过滤）"
          clearable
          style="width: 260px"
        />
        <div class="spacer" />
        <el-button :loading="loading" @click="reload">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>

      <!-- 女优网格 -->
      <div v-loading="loading" class="grid">
        <a
          v-for="item in filtered"
          :key="item.pageid || item.title"
          :href="item.url"
          target="_blank"
          rel="noopener"
          class="actress-card"
        >
          <el-image
            v-if="item.thumbnail"
            :src="item.thumbnail"
            fit="cover"
            class="actress-avatar"
          >
            <template #error>
              <div class="avatar-placeholder">{{ item.title.charAt(0) }}</div>
            </template>
          </el-image>
          <div v-else class="avatar-placeholder">{{ item.title.charAt(0) }}</div>
          <div class="actress-name" :title="item.title">{{ displayName(item.title) }}</div>
        </a>
      </div>

      <el-empty v-if="!loading && !filtered.length" description="未找到匹配的女优" />

      <div class="pager">
        <el-button :disabled="!hasMore || loading" @click="loadMore" :loading="loadingMore">
          <el-icon><Plus /></el-icon> 加载更多（已显示 {{ items.length }}）
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Reading, Refresh, Plus } from '@element-plus/icons-vue'
import { getWikipediaActressCategory } from '@/api'

const loading = ref(false)
const loadingMore = ref(false)
const items = ref([])
const continueToken = ref(null)
const hasMore = ref(false)
const keyword = ref('')

async function load() {
  loading.value = true
  try {
    const res = await getWikipediaActressCategory({ limit: 200 })
    items.value = res.items || []
    continueToken.value = res.continue || null
    hasMore.value = !!res.has_more
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (!continueToken.value) return
  loadingMore.value = true
  try {
    const res = await getWikipediaActressCategory({
      limit: 200,
      continue_token: continueToken.value,
    })
    const seen = new Set(items.value.map((i) => i.title))
    for (const it of res.items || []) {
      if (!seen.has(it.title)) items.value.push(it)
    }
    continueToken.value = res.continue || null
    hasMore.value = !!res.has_more
  } finally {
    loadingMore.value = false
  }
}

function reload() {
  items.value = []
  continueToken.value = null
  hasMore.value = false
  load()
}

// 去掉消歧义后缀：AIKA (AV女優) -> AIKA
function displayName(title) {
  const idx = title.indexOf(' (')
  return idx > 0 ? title.slice(0, idx) : title
}

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return items.value
  return items.value.filter((i) => i.title.toLowerCase().includes(kw))
})

load()
</script>

<style scoped>
.wikipedia-actresses { max-width: 1100px; margin: 0 auto; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 15px; }
.filter-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.spacer { flex: 1; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 12px;
  min-height: 120px;
}

.actress-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  text-decoration: none;
  color: var(--el-text-color-primary);
  transition: all 0.15s;
}
.actress-card:hover {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  transform: translateY(-2px);
}

.actress-avatar {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: block;
}
.avatar-placeholder {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 26px;
  font-weight: 600;
}

.actress-name {
  font-size: 13px;
  text-align: center;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pager { display: flex; justify-content: center; margin-top: 16px; }
</style>
