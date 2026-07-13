<template>
  <div class="subscriptions-page">
    <!-- 顶部操作栏 -->
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left">
          <h2 class="page-title">
            <el-icon><StarFilled /></el-icon>
            演员订阅
          </h2>
          <el-tag type="info" effect="plain" size="small">
            共 {{ subscriptions.length }} 个订阅
          </el-tag>
          <el-tag v-if="totalNewMovies > 0" type="danger" effect="dark" size="small">
            {{ totalNewMovies }} 部新片
          </el-tag>
        </div>
        <div class="toolbar-right">
          <el-button type="primary" :loading="checkingAll" @click="checkAll">
            <el-icon><Refresh /></el-icon> 检测所有新片
          </el-button>
          <el-button @click="loadData">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 订阅列表 -->
    <div class="subs-grid" v-loading="loading">
      <div
        v-for="sub in subscriptions"
        :key="sub.id"
        class="sub-card"
        :class="{ 'has-new': sub.new_movie_count > 0 }"
      >
        <div class="sub-avatar-wrap" @click="goActor(sub.actor_id)">
          <img
            v-if="sub.actor_avatar"
            :src="getAvatarUrl(sub.actor_avatar)"
            :alt="sub.actor_name"
            class="sub-avatar"
            @error="handleAvatarError"
          />
          <div v-else class="sub-avatar-placeholder">
            {{ (sub.actor_name || '?').slice(0, 1) }}
          </div>
          <div v-if="sub.new_movie_count > 0" class="new-badge">
            +{{ sub.new_movie_count }}
          </div>
        </div>
        <div class="sub-info">
          <div class="sub-name" @click="goActor(sub.actor_id)">
            {{ sub.actor_name || '未知演员' }}
          </div>
          <div class="sub-meta">
            <span class="meta-item">
              <el-icon><Film /></el-icon>
              {{ sub.current_movie_count || 0 }} 部
            </span>
            <span v-if="sub.new_movie_count > 0" class="meta-item meta-new">
              <el-icon><Bell /></el-icon>
              {{ sub.new_movie_count }} 新
            </span>
            <span v-if="sub.last_checked_at" class="meta-item meta-time">
              {{ formatTime(sub.last_checked_at) }}
            </span>
          </div>
          <div class="sub-actions">
            <el-switch
              v-model="sub.notify_new_movie"
              size="small"
              active-text="通知"
              @change="updateNotify(sub)"
            />
            <el-button size="small" :loading="sub._checking" @click="checkOne(sub)">
              检测
            </el-button>
            <el-button size="small" type="danger" plain @click="unsub(sub)">
              取消订阅
            </el-button>
          </div>
        </div>
      </div>
      <el-empty v-if="!loading && !subscriptions.length" description="暂无订阅">
        <template #description>
          <p>暂无订阅</p>
          <el-button type="primary" @click="$router.push('/actors')">
            去演员列表订阅
          </el-button>
        </template>
      </el-empty>
    </div>

    <!-- 新片汇总 -->
    <el-card shadow="never" class="new-movies-card" v-if="newMovies.length > 0">
      <template #header>
        <div class="card-header">
          <span>
            <el-icon><Bell /></el-icon>
            订阅新片（{{ newMovies.length }}）
          </span>
          <el-button text @click="newMovies = []">清空</el-button>
        </div>
      </template>
      <div class="new-movies-grid">
        <div
          v-for="m in newMovies"
          :key="m.id"
          class="new-movie-card"
          @click="goPlay(m.id)"
        >
          <img
            v-if="m.cover_url"
            :src="getCoverUrl(m.cover_url)"
            :alt="m.code"
            class="new-movie-cover"
            @error="handleCoverError"
          />
          <div v-else class="new-movie-cover placeholder">
            <el-icon size="40"><Picture /></el-icon>
          </div>
          <div class="new-movie-info">
            <div class="new-movie-code">{{ m.code }}</div>
            <div class="new-movie-title">{{ m.title || '未命名' }}</div>
            <div class="new-movie-date" v-if="m.release_date">{{ m.release_date }}</div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  StarFilled, Refresh, Bell, Film, Picture
} from '@element-plus/icons-vue'
import {
  listSubscriptions, subscribeActor, unsubscribeActor, checkActorNewMovies,
  checkAllSubscriptions, listSubscriptionNewMovies
} from '@/api'
import { getServerBaseUrl, defaultCover, getFileProxyUrl } from '@/utils/media'

const router = useRouter()
const loading = ref(false)
const checkingAll = ref(false)
const subscriptions = ref([])
const newMovies = ref([])

const totalNewMovies = computed(() =>
  subscriptions.value.reduce((sum, s) => sum + (s.new_movie_count || 0), 0)
)

const getAvatarUrl = (avatar) => {
  if (/^https?:\/\//i.test(avatar)) return avatar
  return getFileProxyUrl(avatar)
}

const getCoverUrl = (cover) => {
  if (/^https?:\/\//i.test(cover)) return cover
  return getFileProxyUrl(cover)
}

const handleAvatarError = (e) => {
  e.target.style.display = 'none'
}

const handleCoverError = (e) => {
  e.target.src = defaultCover('MDCX')
}

const formatTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = (now - d) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return `${Math.floor(diff / 86400)}天前`
}

const loadData = async () => {
  loading.value = true
  try {
    const [subRes, newRes] = await Promise.all([
      listSubscriptions(),
      listSubscriptionNewMovies({ limit: 50 })
    ])
    subscriptions.value = (subRes.items || []).map(s => ({ ...s, _checking: false }))
    newMovies.value = newRes.items || []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const checkOne = async (sub) => {
  sub._checking = true
  try {
    const res = await checkActorNewMovies(sub.actor_id)
    sub.new_movie_count = res.new_count || 0
    if (res.new_count > 0) {
      ElMessage.success(`检测到 ${res.new_count} 部新片`)
      const newItems = res.new_movies || []
      // 合并到 newMovies（去重）
      const existingIds = new Set(newMovies.value.map(m => m.id))
      for (const m of newItems) {
        if (!existingIds.has(m.id)) newMovies.value.unshift(m)
      }
    } else {
      ElMessage.info('暂无新片')
    }
  } catch (e) {
    ElMessage.error('检测失败')
  } finally {
    sub._checking = false
  }
}

const checkAll = async () => {
  checkingAll.value = true
  try {
    const res = await checkAllSubscriptions()
    ElMessage.success(`检测完成：${res.checked || 0} 个订阅，新增 ${res.new_total || 0} 部`)
    await loadData()
  } catch (e) {
    ElMessage.error('检测失败')
  } finally {
    checkingAll.value = false
  }
}

const updateNotify = async (sub) => {
  try {
    await subscribeActor({
      actor_id: sub.actor_id,
      notify_new_movie: sub.notify_new_movie
    })
    ElMessage.success(sub.notify_new_movie ? '已开启通知' : '已关闭通知')
  } catch (e) {
    sub.notify_new_movie = !sub.notify_new_movie
    ElMessage.error('更新失败')
  }
}

const unsub = async (sub) => {
  try {
    await ElMessageBox.confirm(
      `确定取消订阅「${sub.actor_name}」吗？`,
      '取消订阅',
      { type: 'warning' }
    )
    await unsubscribeActor(sub.actor_id)
    subscriptions.value = subscriptions.value.filter(s => s.id !== sub.id)
    ElMessage.success('已取消订阅')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('操作失败')
  }
}

const goActor = (id) => router.push(`/actors/${id}`)
const goPlay = (id) => router.push(`/movie/${id}`)

onMounted(() => loadData())
</script>

<style scoped>
.subscriptions-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.toolbar-card {
  border-radius: 8px !important;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.page-title {
  margin: 0;
  font-size: 18px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-right {
  display: flex;
  gap: 8px;
}

/* 订阅卡片网格 */
.subs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
  min-height: 200px;
}

.sub-card {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 8px;
  transition: all 0.2s;
}

.sub-card:hover {
  border-color: var(--primary-color);
  box-shadow: var(--shadow-sm);
}

.sub-card.has-new {
  border-color: #f97316;
  background: linear-gradient(135deg, rgba(249, 115, 22, 0.05), transparent);
}

.sub-avatar-wrap {
  position: relative;
  cursor: pointer;
  flex-shrink: 0;
}

.sub-avatar,
.sub-avatar-placeholder {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--primary-color);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: 600;
}

.new-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  background: #ef4444;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 10px;
  min-width: 20px;
  text-align: center;
}

.sub-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.sub-name {
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  color: var(--text-primary);
}

.sub-name:hover {
  color: var(--primary-color);
}

.sub-meta {
  display: flex;
  gap: 10px;
  font-size: 12px;
  color: var(--text-secondary);
  flex-wrap: wrap;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 3px;
}

.meta-new {
  color: #f97316;
  font-weight: 600;
}

.meta-time {
  opacity: 0.7;
}

.sub-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  flex-wrap: wrap;
}

/* 新片汇总 */
.new-movies-card {
  border-radius: 8px !important;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.new-movies-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.new-movie-card {
  cursor: pointer;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  overflow: hidden;
  transition: transform 0.15s;
}

.new-movie-card:hover {
  transform: translateY(-2px);
}

.new-movie-cover {
  width: 100%;
  aspect-ratio: 2 / 3;
  object-fit: cover;
  background: #1a1a2e;
}

.new-movie-cover.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-placeholder);
}

.new-movie-info {
  padding: 6px 8px;
}

.new-movie-code {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary-color);
}

.new-movie-title {
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.new-movie-date {
  font-size: 10px;
  color: var(--text-placeholder);
  margin-top: 2px;
}
</style>
