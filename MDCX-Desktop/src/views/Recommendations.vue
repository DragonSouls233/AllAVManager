<template>
  <div class="page recommendations-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><MagicStick /></el-icon>
          AI 智能推荐
        </h2>
        <span class="page-subtitle">
          基于观影历史、收藏与评分,个性化推荐你可能感兴趣的影片
        </span>
      </div>
      <div class="page-header-actions">
        <el-button type="primary" :loading="refreshing" @click="handleRefresh">
          <el-icon><Refresh /></el-icon> 刷新推荐
        </el-button>
      </div>
    </div>

    <!-- 个性化说明 -->
    <el-card shadow="never" class="info-card">
      <div class="info-row">
        <el-icon class="info-icon"><InfoFilled /></el-icon>
        <div class="info-text">
          系统已根据你最近的<strong>{{ stats.totalViewed }}</strong>次观影、
          <strong>{{ stats.totalFavorites }}</strong>次收藏、
          <strong>{{ stats.totalRatings }}</strong>次评分生成专属推荐。
          多观看、多收藏可让推荐更精准。
        </div>
      </div>
    </el-card>

    <!-- 主体:推荐卡片网格 -->
    <el-card shadow="never" class="grid-card" v-loading="loading">
      <template #header>
        <div class="card-header-bar">
          <div class="card-header-title">
            <el-icon><Star /></el-icon>
            为你推荐
            <el-tag size="small" effect="plain" style="margin-left: 8px">
              {{ recommendations.length }}
            </el-tag>
          </div>
          <el-radio-group v-model="sortBy" size="small" @change="applySort">
            <el-radio-button value="default">默认</el-radio-button>
            <el-radio-button value="score">按评分</el-radio-button>
            <el-radio-button value="reason">按理由</el-radio-button>
          </el-radio-group>
        </div>
      </template>

      <!-- 加载骨架屏 -->
      <div v-if="loading && !recommendations.length" class="skeleton-grid">
        <div v-for="n in 8" :key="'sk' + n" class="skeleton-card">
          <Skeleton :width="'100%'" :height="240" :rounded="8" />
          <Skeleton :width="'60%'" :height="14" :rounded="4" style="margin-top: 8px" />
          <Skeleton :width="'100%'" :height="12" :rounded="4" />
          <Skeleton :width="'40%'" :height="12" :rounded="4" />
        </div>
      </div>

      <!-- 推荐卡片网格 -->
      <div v-else-if="recommendations.length" class="rec-grid">
        <div
          v-for="rec in recommendations"
          :key="rec.id"
          class="rec-card"
          @click="goToMovie(rec.id)"
        >
          <div class="rec-cover-wrap">
            <img
              :src="getMovieCoverUrl(rec)"
              :alt="rec.code"
              class="rec-cover-img"
              decoding="async"
              loading="lazy"
              @error="(e) => onCoverError(e, rec)"
            />
            <RatingStars
              v-if="rec.score != null"
              :rating="rec.score"
              size="small"
              class="rec-rating"
            />
            <div class="rec-actions">
              <el-button
                circle
                size="small"
                type="primary"
                @click.stop="handlePlay(rec)"
              >
                <el-icon><VideoPlay /></el-icon>
              </el-button>
              <el-button
                circle
                size="small"
                @click.stop="handleFavorite(rec)"
              >
                <el-icon><Star /></el-icon>
              </el-button>
              <el-button
                circle
                size="small"
                @click.stop="handleDismiss(rec)"
              >
                <el-icon><CircleClose /></el-icon>
              </el-button>
            </div>
          </div>
          <div class="rec-body">
            <div class="rec-code">{{ rec.code }}</div>
            <div class="rec-title">{{ rec.title || '未命名' }}</div>
            <div class="rec-reason-list">
              <el-tag
                v-for="reason in parseReasons(rec)"
                :key="reason"
                size="small"
                effect="plain"
                :type="reasonTagType(reason)"
              >{{ reason }}</el-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <EmptyState
        v-else
        type="no-data"
        title="暂无推荐"
        description="多观看、收藏、评分影片,系统将为你建立偏好画像并生成专属推荐。"
      >
        <el-button type="primary" :loading="refreshing" @click="handleRefresh">
          <el-icon><Refresh /></el-icon> 立即生成推荐
        </el-button>
      </EmptyState>

      <!-- 分页 -->
      <div v-if="recommendations.length" class="pagination-bar">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next, total"
          background
          @current-change="onPageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  MagicStick, Refresh, InfoFilled, Star, VideoPlay, CircleClose
} from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import RatingStars from '@/components/RatingStars.vue'
import Skeleton from '@/components/Skeleton.vue'
import {
  getRecommendations, refreshRecommendations, dismissRecommendation
} from '@/api'
import { defaultCover, getMovieCoverUrl, getMoviePosterUrl, getMovieThumbUrl } from '@/utils/media'

const router = useRouter()

const recommendations = ref([])
const loading = ref(false)
const refreshing = ref(false)
const sortBy = ref('default')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

// 统计信息(若 API 返回则用,否则用 0 占位)
const stats = ref({
  totalViewed: 0,
  totalFavorites: 0,
  totalRatings: 0
})

const sortedRecommendations = computed(() => {
  if (sortBy.value === 'score') {
    return [...recommendations.value].sort((a, b) =>
      (b.score || 0) - (a.score || 0)
    )
  }
  if (sortBy.value === 'reason') {
    return [...recommendations.value].sort((a, b) =>
      parseReasons(a).length - parseReasons(b).length
    )
  }
  return recommendations.value
})

function parseReasons(rec) {
  if (Array.isArray(rec.reasons)) return rec.reasons.slice(0, 3)
  if (rec.reason) return [rec.reason]
  const types = []
  if (rec.same_actors) types.push('常看演员')
  if (rec.same_tags) types.push('兴趣标签')
  if (rec.same_series) types.push('同系列')
  if (rec.same_studio) types.push('同厂商')
  return types.length ? types : ['智能推荐']
}

function reasonTagType(reason) {
  if (reason.includes('演员')) return 'primary'
  if (reason.includes('标签')) return 'warning'
  if (reason.includes('系列')) return 'success'
  if (reason.includes('厂商')) return 'info'
  return ''
}

function applySort() {
  // 排序后立即重新赋值,触发响应式更新
  recommendations.value = sortedRecommendations.value
}

async function loadRecommendations() {
  loading.value = true
  try {
    const res = await getRecommendations(pageSize.value)
    const items = res.items || res || []
    recommendations.value = items
    total.value = res.total || items.length
    if (res.stats) {
      stats.value = { ...stats.value, ...res.stats }
    }
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function handleRefresh() {
  refreshing.value = true
  try {
    await refreshRecommendations()
    await loadRecommendations()
    ElMessage.success('推荐已刷新')
  } catch (e) {
    console.error(e)
  } finally {
    refreshing.value = false
  }
}

async function handleDismiss(rec) {
  try {
    await dismissRecommendation(rec.id)
    recommendations.value = recommendations.value.filter(r => r.id !== rec.id)
    total.value = Math.max(0, total.value - 1)
    ElMessage.success('已记录你的偏好')
  } catch (e) {
    console.error(e)
  }
}

function handlePlay(rec) {
  router.push(`/movie/${rec.id}`)
}

function handleFavorite(rec) {
  router.push(`/movie/${rec.id}?favorite=1`)
}

function goToMovie(id) {
  router.push(`/movie/${id}`)
}

// 封面三级回退:cover/file → poster/file → thumb/file → 占位图
function onCoverError(e, rec) {
  const img = e.target
  const stage = parseInt(img.dataset.cs || '0', 10)
  if (stage === 0) {
    img.dataset.cs = '1'
    img.src = getMoviePosterUrl(rec)
  } else if (stage === 1) {
    img.dataset.cs = '2'
    img.src = getMovieThumbUrl(rec)
  } else {
    img.dataset.cs = '3'
    img.src = defaultCover(rec?.code)
  }
}

function onPageChange(p) {
  page.value = p
  loadRecommendations()
}

onMounted(loadRecommendations)
</script>

<style scoped>
.recommendations-page {
  gap: var(--gap-md);
}

.info-card {
  border-radius: var(--radius-md) !important;
  border-left: 4px solid var(--primary-color) !important;
  background: var(--brand-gradient-soft);
}

.info-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.info-icon {
  font-size: 18px;
  color: var(--primary-color);
  flex-shrink: 0;
}

.info-text {
  font-size: var(--font-size-sm);
  color: var(--text-regular);
  line-height: 1.6;
}

.info-text strong {
  color: var(--primary-color);
  font-weight: 600;
  margin: 0 2px;
}

.grid-card {
  border-radius: var(--radius-md) !important;
}

.card-header-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.card-header-title {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-weight: 600;
  font-size: var(--font-size-md);
  color: var(--text-primary);
}

/* 骨架屏网格 */
.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--gap-md);
}

.skeleton-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* 推荐卡片网格 */
.rec-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--gap-md);
}

.rec-card {
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  overflow: hidden;
  cursor: pointer;
  transition: all var(--transition-base);
}

.rec-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-hover);
  border-color: var(--primary-light);
}

.rec-cover-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 2 / 3;
  background: var(--bg-page);
  overflow: hidden;
}

.rec-cover-img {
  width: 100%;
  height: 100%;
  transition: transform 0.4s ease;
}

.rec-card:hover .rec-cover-img {
  transform: scale(1.04);
}

.rec-rating {
  position: absolute;
  top: 8px;
  left: 8px;
}

.rec-actions {
  position: absolute;
  bottom: 8px;
  left: 0;
  right: 0;
  display: flex;
  justify-content: center;
  gap: var(--gap-sm);
  opacity: 0;
  transition: opacity var(--transition-fast);
  background: linear-gradient(to top, rgba(0, 0, 0, 0.6), transparent);
  padding: 16px 8px 8px;
}

.rec-card:hover .rec-actions {
  opacity: 1;
}

.rec-body {
  padding: var(--gap-sm);
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.rec-code {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--primary-color);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rec-title {
  font-size: var(--font-size-xs);
  color: var(--text-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  min-height: 32px;
}

.rec-reason-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: auto;
  padding-top: var(--gap-xs);
}

.pagination-bar {
  margin-top: var(--gap-md);
  display: flex;
  justify-content: center;
}

@media (max-width: 640px) {
  .rec-grid,
  .skeleton-grid {
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: var(--gap-sm);
  }
}
</style>
