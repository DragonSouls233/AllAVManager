<template>
  <div class="actress-collection">
    <!-- 顶部统计栏 -->
    <div class="stats-bar">
      <div class="stat-item" v-for="s in statsList" :key="s.label">
        <span class="stat-value">{{ s.value }}</span>
        <span class="stat-label">{{ s.label }}</span>
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <el-input
        v-model="searchKeyword"
        placeholder="搜索女优..."
        clearable
        style="width: 260px"
        @clear="fetchActresses"
        @keyup.enter="fetchActresses"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>

      <el-select v-model="tierFilter" placeholder="分级" clearable style="width: 100px" @change="fetchActresses">
        <el-option label="全部" :value="0" />
        <el-option label="Tier 1" :value="1" />
        <el-option label="Tier 2" :value="2" />
        <el-option label="Tier 3" :value="3" />
        <el-option label="Tier 4" :value="4" />
        <el-option label="Tier 5" :value="5" />
      </el-select>

      <el-checkbox v-model="favoriteOnly" label="仅收藏" @change="fetchActresses" />

      <el-button :icon="Refresh" @click="fetchActresses">刷新</el-button>
      <el-button type="primary" :icon="Download" :loading="syncing" @click="syncFromDB">
        从数据库同步
      </el-button>
    </div>

    <!-- 女优网格 -->
    <div v-loading="loading" class="actress-grid">
      <div v-for="a in actresses" :key="a.name" class="actress-card" :class="{ favorite: a.favorite }">
        <!-- 头像 -->
        <div class="actress-avatar">
          <el-avatar :size="80" :src="a.avatar_url || a.cover_url" shape="square">
            {{ a.name.slice(0, 1) }}
          </el-avatar>
        </div>

        <!-- 信息 -->
        <div class="actress-info">
          <div class="actress-name">{{ a.name }}</div>
          <div class="actress-meta">
            <span>{{ a.movie_count }} 部</span>
            <span v-if="a.studio">{{ a.studio }}</span>
          </div>
          <div class="actress-tags">
            <el-tag v-if="a.favorite" size="small" type="danger">收藏</el-tag>
            <el-tag size="small" :type="tierType(a.tier)">T{{ a.tier }}</el-tag>
            <el-tag v-if="a.module" size="small">{{ a.module }}</el-tag>
          </div>
        </div>

        <!-- 操作 -->
        <div class="actress-actions">
          <el-tooltip :content="a.favorite ? '取消收藏' : '收藏'" placement="top">
            <el-button
              :icon="a.favorite ? StarFilled : Star"
              :type="a.favorite ? 'warning' : 'default'"
              size="small"
              circle
              @click="toggleFavorite(a)"
            />
          </el-tooltip>
          <el-dropdown trigger="click" @command="(tier) => setTier(a, tier)">
            <el-button size="small" circle :icon="Sort">T</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="t in 5" :key="t" :command="t">
                  Tier {{ t }} {{ a.tier === t ? '✓' : '' }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>

      <!-- 空状态 -->
      <el-empty v-if="!actresses.length && !loading" description="暂无女优数据" />
    </div>

    <!-- 分页 -->
    <div v-if="total > 20" class="pagination">
      <el-pagination
        v-model:current-page="page"
        :page-size="20"
        :total="total"
        layout="prev, pager, next"
        @current-change="fetchActresses"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Search, Refresh, Download, Star, StarFilled, Sort,
} from '@element-plus/icons-vue'

import {
  getActresses,
  getActressStats,
  syncActresses,
  setActressFavorite,
  setActressTier,
} from '@/api/actresses'

const actresses = ref([])
const loading = ref(false)
const syncing = ref(false)
const total = ref(0)
const page = ref(1)
const searchKeyword = ref('')
const tierFilter = ref(0)
const favoriteOnly = ref(false)
const stats = ref({})
const statsList = ref([
  { label: '总计', value: 0 },
  { label: '收藏', value: 0 },
  { label: '模块数', value: 0 },
])

function tierType(tier) {
  const map = { 1: 'danger', 2: 'warning', 3: '', 4: 'info', 5: 'info' }
  return map[tier] || 'info'
}

async function fetchActresses() {
  loading.value = true
  try {
    const res = await getActresses({
      keyword: searchKeyword.value,
      tier: tierFilter.value === 0 ? undefined : tierFilter.value,
      favorite_only: favoriteOnly.value || undefined,
      sort_by: 'movie_count',
    })
    actresses.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error('获取女优列表失败: ' + (e.message || e))
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const res = await getActressStats()
    stats.value = res
    statsList.value = [
      { label: '总计', value: res.total || 0 },
      { label: '收藏', value: res.favorites || 0 },
      { label: '模块数', value: Object.keys(res.by_module || {}).length },
    ]
  } catch (e) {
    // ignore
  }
}

async function syncFromDB() {
  syncing.value = true
  try {
    const res = await syncActresses()
    ElMessage.success('同步完成: ' + JSON.stringify(res.stats))
    await fetchStats()
    await fetchActresses()
  } catch (e) {
    ElMessage.error('同步失败: ' + (e.message || e))
  } finally {
    syncing.value = false
  }
}

async function toggleFavorite(actress) {
  const newVal = !actress.favorite
  try {
    await setActressFavorite(actress.name, newVal)
    actress.favorite = newVal
    ElMessage.success(newVal ? '已收藏' : '已取消收藏')
    await fetchStats()
  } catch (e) {
    ElMessage.error('操作失败: ' + (e.message || e))
  }
}

async function setTier(actress, tier) {
  try {
    await setActressTier(actress.name, tier)
    actress.tier = tier
    ElMessage.success(`已设置 ${actress.name} 为 Tier ${tier}`)
  } catch (e) {
    ElMessage.error('设置失败: ' + (e.message || e))
  }
}

onMounted(async () => {
  await fetchStats()
  await fetchActresses()
})
</script>

<style scoped>
.actress-collection { padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.stats-bar { display: flex; gap: 24px; padding: 12px 20px; background: var(--el-bg-color-overlay); border-radius: 8px; border: 1px solid var(--el-border-color-light); }
.stat-item { display: flex; flex-direction: column; align-items: center; }
.stat-value { font-size: 22px; font-weight: 700; color: var(--el-color-primary); }
.stat-label { font-size: 12px; color: var(--el-text-color-secondary); }
.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.actress-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.actress-card { display: flex; align-items: center; gap: 12px; padding: 12px; background: var(--el-bg-color-overlay); border-radius: 8px; border: 1px solid var(--el-border-color-light); transition: all .2s; }
.actress-card.favorite { border-color: var(--el-color-warning); background: var(--el-color-warning-light-9); }
.actress-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); }
.actress-info { flex: 1; min-width: 0; }
.actress-name { font-size: 14px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.actress-meta { font-size: 12px; color: var(--el-text-color-secondary); margin: 2px 0; display: flex; gap: 8px; }
.actress-tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; }
.actress-actions { display: flex; flex-direction: column; gap: 4px; }
.pagination { display: flex; justify-content: center; }
</style>
