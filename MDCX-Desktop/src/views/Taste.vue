<template>
  <div class="taste-page">
    <h2>口味画像</h2>
    <p class="page-desc">
      基于你的真实行为（播放历史 / 收藏 / 观看状态）生成的厂商 · 演员 · 系列偏好画像，
      并据此推荐「你可能想看」。站点评分不参与计算。
    </p>

    <el-card shadow="never" class="toolbar-card">
      <el-select v-model="currentModule" style="width: 160px" @change="loadAll">
        <el-option label="全部模块" value="all" />
        <el-option v-for="m in moduleOptions" :key="m.value" :label="m.label" :value="m.value" />
      </el-select>
      <el-button :icon="Refresh" @click="loadAll" style="margin-left: 12px">刷新</el-button>
    </el-card>

    <!-- 空状态：无行为数据 -->
    <el-empty
      v-if="!loading && profile && profile.evidence_count === 0"
      description="还没有任何观看 / 收藏行为，先去看几部片，画像会自动生成"
    />

    <template v-else>
      <!-- 三维偏好 -->
      <el-row :gutter="16" class="dim-row" v-loading="loading">
        <el-col :span="8" v-for="dim in dimensions" :key="dim.key">
          <el-card shadow="hover" class="dim-card">
            <div class="dim-title">{{ dim.title }}（Top {{ topN }}）</div>
            <div v-for="item in profile[dim.key]" :key="item.name" class="dim-item">
              <span class="dim-name" :title="item.name">{{ item.name }}</span>
              <el-progress
                :percentage="Math.round(item.weight * 100)"
                :stroke-width="10" :show-text="false"
                class="dim-bar"
              />
            </div>
            <el-empty v-if="!profile[dim.key] || !profile[dim.key].length" :image-size="50" description="暂无" />
          </el-card>
        </el-col>
      </el-row>

      <!-- 推荐 -->
      <el-card shadow="never" class="rec-card">
        <div class="rec-head">
          <span class="rec-title">你可能想看</span>
          <span class="rec-count">共 {{ recommendTotal }} 部</span>
        </div>
        <div v-loading="recLoading" class="card-grid">
          <div v-for="item in recommends" :key="item.module + item.id" class="movie-card-item">
            <div class="cover" @click="goDetail(item)">
              <el-image v-if="item.cover_url" :src="item.cover_url" fit="cover" class="cover-img">
                <template #error><div class="no-cover">无封面</div></template>
              </el-image>
              <div v-else class="no-cover">无封面</div>
              <el-tag size="small" class="module-tag" effect="dark">{{ item.module_label }}</el-tag>
            </div>
            <div class="meta">
              <div class="code" @click="goDetail(item)">{{ item.code }}</div>
              <div class="title" :title="item.title">{{ item.title || '—' }}</div>
              <div class="reasons">
                <el-tag v-for="r in item.reasons" :key="r" size="small" type="info">{{ r }}</el-tag>
              </div>
            </div>
          </div>
        </div>
        <el-empty v-if="!recLoading && recommends.length === 0" :image-size="60" description="暂无匹配推荐" />
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { getTasteProfile, getTasteRecommend } from '@/api'

const router = useRouter()
const currentModule = ref('all')
const topN = 12
const dimensions = [
  { key: 'studios', title: '偏好的厂商' },
  { key: 'actors', title: '偏好的演员' },
  { key: 'series', title: '偏好的系列' },
]
const profile = ref(null)
const loading = ref(false)
const recommends = ref([])
const recommendTotal = ref(0)
const recLoading = ref(false)
const moduleOptions = [
  { label: 'JAV有码', value: 'jav' },
  { label: 'JAV无码', value: 'uncensored' },
  { label: 'FC2', value: 'fc2' },
  { label: 'PORNHUB', value: 'pornhub' },
  { label: '里番', value: 'anime' },
  { label: '欧美', value: 'western' },
  { label: '国产', value: 'chinese' },
]

const loadProfile = async () => {
  loading.value = true
  try {
    profile.value = await getTasteProfile(currentModule.value)
  } catch (e) { /* */ } finally { loading.value = false }
}
const loadRecommend = async () => {
  recLoading.value = true
  try {
    const d = await getTasteRecommend(currentModule.value, 48)
    recommends.value = d.items || []
    recommendTotal.value = d.total || 0
  } catch (e) { /* */ } finally { recLoading.value = false }
}
const loadAll = async () => { await Promise.all([loadProfile(), loadRecommend()]) }
const goDetail = (item) => router.push(`/${item.module}/movies/${item.id}`)

onMounted(loadAll)
</script>

<style scoped>
.taste-page { padding: 16px; }
.page-desc { color: var(--el-text-color-secondary); margin-bottom: 16px; }
.toolbar-card { margin-bottom: 16px; }
.dim-row { margin-bottom: 16px; }
.dim-card { border-radius: 8px; min-height: 260px; }
.dim-title { font-weight: 600; margin-bottom: 12px; }
.dim-item { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.dim-name {
  width: 90px; flex-shrink: 0; font-size: 12px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.dim-bar { flex: 1; }
.rec-card { border-radius: 8px; }
.rec-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.rec-title { font-weight: 600; }
.rec-count { color: var(--el-text-color-secondary); font-size: 13px; }
.card-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 14px;
}
.movie-card-item { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; overflow: hidden; }
.cover { position: relative; aspect-ratio: 2 / 3; background: #f5f7fa; cursor: pointer; }
.cover-img { width: 100%; height: 100%; }
.no-cover {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  color: #c0c4cc; font-size: 12px;
}
.module-tag { position: absolute; left: 6px; top: 6px; }
.meta { padding: 8px; }
.meta .code { font-weight: 600; font-size: 13px; cursor: pointer; }
.meta .title {
  font-size: 12px; color: var(--el-text-color-secondary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 2px 0 8px;
}
.reasons { display: flex; flex-wrap: wrap; gap: 4px; }
</style>
