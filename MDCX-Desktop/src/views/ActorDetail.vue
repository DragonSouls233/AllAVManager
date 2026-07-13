<template>
  <div class="actor-detail" v-loading="loading">
    <el-button class="back-button" @click="router.back()">
      <el-icon><ArrowLeft /></el-icon>
      返回
    </el-button>

    <el-card v-if="actor" class="profile-card">
      <div class="profile">
        <div class="profile-avatar" @click="triggerAvatarUpload" title="点击更换头像">
          <img :src="getActorAvatarUrl(actor)" :alt="actor.name" @error="handleAvatarError">
          <div class="avatar-overlay">
            <el-icon><Camera /></el-icon>
            <span>更换</span>
          </div>
        </div>
        <input
          ref="avatarInputRef"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          style="display:none"
          @change="onAvatarFileChange"
        />
        <div class="profile-info">
          <div class="profile-name" @dblclick="copyActorName" title="双击复制演员名">{{ actor.name }}</div>
          <div v-if="actor.name_jp" class="profile-subtitle">{{ actor.name_jp }}</div>
          <div class="profile-meta">
            <el-tag type="primary">{{ movieTotal }} 部作品</el-tag>
            <el-tag v-if="actor.cup" type="success">{{ actor.cup }} Cup</el-tag>
            <el-tag v-if="actor.height" type="info">{{ actor.height }} cm</el-tag>
            <el-tag v-if="actor.age" type="warning">{{ actor.age }} 岁</el-tag>
          </div>
          <div class="profile-actions">
            <el-button
              :type="subscribed ? 'warning' : 'primary'"
              :loading="subscribing"
              @click="toggleSubscribe"
            >
              <el-icon><StarFilled v-if="subscribed" /><Star v-else /></el-icon>
              {{ subscribed ? '已订阅' : '订阅' }}
            </el-button>
            <el-button v-if="subscribed" text @click="checkNewMovies" :loading="checking">
              <el-icon><Bell /></el-icon> 检测新片
            </el-button>
            <el-button text type="danger" size="small" @click="deleteAvatar" :loading="avatarDeleting">
              <el-icon><Delete /></el-icon> 删除头像
            </el-button>
            <el-tag v-if="newMovieCount > 0" type="danger" effect="dark" size="small">
              {{ newMovieCount }} 部新片
            </el-tag>
          </div>
          <div class="profile-grid">
            <div v-if="actor.birth_date"><span>生日</span>{{ actor.birth_date }}</div>
            <div v-if="actor.zodiac"><span>星座</span>{{ actor.zodiac }}</div>
            <div v-if="actor.debut_year"><span>出道年份</span>{{ actor.debut_year }}</div>
            <div v-if="actor.birthplace"><span>出生地</span>{{ actor.birthplace }}</div>
            <div v-if="actor.bust"><span>胸围</span>{{ actor.bust }}</div>
            <div v-if="actor.waist"><span>腰围</span>{{ actor.waist }}</div>
            <div v-if="actor.hip"><span>臀围</span>{{ actor.hip }}</div>
          </div>

          <!-- 社交账号（v3.4 新增） -->
          <div v-if="actor.social_links" class="profile-social">
            <a
              v-for="(url, platform) in actor.social_links"
              :key="platform"
              :href="url"
              target="_blank"
              rel="noopener noreferrer"
              class="social-link"
            >
              <el-icon><Link /></el-icon>
              {{ socialLabel(platform) }}
            </a>
          </div>

          <!-- 演员标签（v3.4 新增） -->
          <div class="profile-tags">
            <div class="tags-header">
              <span class="tags-title">演员标签</span>
              <el-button text size="small" @click="openTagDialog">
                <el-icon><Plus /></el-icon> 添加
              </el-button>
            </div>
            <div class="tags-list">
              <el-tag
                v-for="tag in actorTags"
                :key="tag.id"
                :color="tag.color"
                closable
                :effect="tag.color ? 'dark' : 'light'"
                @close="removeTag(tag)"
                class="actor-tag"
              >
                {{ tag.name }}
              </el-tag>
              <span v-if="!actorTags.length" class="tags-empty">暂无标签，点击"添加"创建（如"业界第一"/"传奇"）</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <el-card class="movies-card">
      <template #header>
        <div class="card-header">
          <el-tabs v-model="activeTab" class="view-tabs" @tab-change="handleTabChange">
            <el-tab-pane label="作品列表" name="list" />
            <el-tab-pane label="时间线" name="timeline" />
          </el-tabs>
        </div>
      </template>

      <!-- 作品列表视图 -->
      <div v-if="activeTab === 'list'">
        <div class="movies-grid" v-loading="moviesLoading">
          <div v-for="movie in movies" :key="movie.id" class="movie-card" @click="goDetail(movie.id)">
            <div class="movie-cover">
              <img :src="getMovieCoverUrl(movie)" :alt="movie.code" @error="(e) => handleCoverError(e, movie)">
              <div class="movie-play">
                <el-icon size="36"><VideoPlay /></el-icon>
              </div>
            </div>
            <div class="movie-info">
              <div class="movie-code">{{ movie.code }}</div>
              <div class="movie-title">{{ movie.title || '未命名' }}</div>
              <div v-if="movie.release_date" class="movie-date">{{ movie.release_date }}</div>
            </div>
          </div>
          <el-empty v-if="!moviesLoading && !movies.length" description="暂无作品" />
        </div>

        <div v-if="movieTotal > 0" class="pagination">
          <el-pagination
            v-model:current-page="page"
            :page-size="pageSize"
            :total="movieTotal"
            layout="total, prev, pager, next"
            @current-change="loadMovies"
          />
        </div>
      </div>

      <!-- 时间线视图（v3.4 新增） -->
      <div v-else class="timeline-view" v-loading="timelineLoading">
        <div v-if="timeline && timeline.total > 0" class="timeline-content">
          <!-- 统计概览 -->
          <div class="timeline-summary">
            <el-tag type="primary">共 {{ timeline.total }} 部作品</el-tag>
            <el-tag v-if="timeline.year_range[0]" type="success">
              {{ timeline.year_range[0] }} - {{ timeline.year_range[1] }}
            </el-tag>
            <el-tag v-if="timeline.debut_year" type="warning">出道: {{ timeline.debut_year }}</el-tag>
            <el-tag v-if="timeline.years.length" type="info">活跃 {{ timeline.years.length }} 年</el-tag>
          </div>

          <!-- 年份柱状图（纯 CSS 实现） -->
          <div class="timeline-chart">
            <div
              v-for="y in timeline.years"
              :key="y.year"
              class="chart-bar-wrapper"
              :class="{ active: selectedYear === y.year }"
              @click="selectYear(y.year)"
            >
              <div class="chart-bar-count">{{ y.count }}</div>
              <div
                class="chart-bar"
                :style="{ height: barHeight(y.count) + '%' }"
                :title="`${y.year}年: ${y.count}部`"
              ></div>
              <div class="chart-bar-label">{{ y.year }}</div>
            </div>
          </div>
          <div class="chart-hint">点击柱子查看该年作品</div>

          <!-- 选中年份的作品列表 -->
          <div v-if="selectedYearDetails" class="year-movies">
            <div class="year-header">
              <span class="year-title">{{ selectedYearDetails.year }} 年</span>
              <el-tag>{{ selectedYearDetails.count }} 部</el-tag>
            </div>
            <div class="year-movies-grid">
              <div
                v-for="movie in selectedYearDetails.movies"
                :key="movie.id"
                class="movie-card-mini"
                @click="goDetail(movie.id)"
              >
                <div class="mini-cover">
                  <img :src="getMovieCoverUrl(movie)" :alt="movie.code" @error="(e) => handleCoverError(e, movie)">
                </div>
                <div class="mini-info">
                  <div class="mini-code">{{ movie.code }}</div>
                  <div class="mini-title">{{ movie.title || '未命名' }}</div>
                  <div v-if="movie.release_date" class="mini-date">{{ movie.release_date }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 未知年份作品 -->
          <div v-if="timeline.unknown" class="year-movies unknown-year">
            <div class="year-header">
              <span class="year-title">未知年份</span>
              <el-tag type="info">{{ timeline.unknown.count }} 部</el-tag>
            </div>
            <div class="year-movies-grid">
              <div
                v-for="movie in timeline.unknown.movies"
                :key="movie.id"
                class="movie-card-mini"
                @click="goDetail(movie.id)"
              >
                <div class="mini-cover">
                  <img :src="getMovieCoverUrl(movie)" :alt="movie.code" @error="(e) => handleCoverError(e, movie)">
                </div>
                <div class="mini-info">
                  <div class="mini-code">{{ movie.code }}</div>
                  <div class="mini-title">{{ movie.title || '未命名' }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无作品时间线数据" />
      </div>
    </el-card>

    <!-- 添加标签对话框 -->
    <el-dialog v-model="showTagDialog" title="添加演员标签" width="420px">
      <el-form @submit.prevent="addTag">
        <el-form-item label="标签名">
          <el-input
            v-model="newTagName"
            placeholder='如"业界第一"/"传奇"/"国民老婆"'
            maxlength="50"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="颜色">
          <el-color-picker v-model="newTagColor" />
          <el-button text @click="newTagColor = ''">清除</el-button>
        </el-form-item>
        <el-form-item v-if="popularTags.length" label="热门">
          <div class="popular-tags">
            <el-tag
              v-for="pt in popularTags"
              :key="pt.name"
              class="popular-tag"
              @click="newTagName = pt.name"
            >
              {{ pt.name }} ({{ pt.usage_count }})
            </el-tag>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showTagDialog = false">取消</el-button>
        <el-button type="primary" :loading="tagAdding" @click="addTag">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, VideoPlay, Star, StarFilled, Bell, Link, Plus, Camera, Delete } from '@element-plus/icons-vue'
import {
  getActor, getActorMovies, getActorTimeline,
  getActorTags, addActorTag, deleteActorTag, getPopularActorTags,
  listSubscriptions, subscribeActor, unsubscribeActor, checkActorNewMovies,
  uploadActorAvatar, deleteActorAvatar
} from '@/api'
import { defaultAvatar, defaultCover, getActorAvatarUrl, getMovieCoverUrl, getMoviePosterUrl, getMovieThumbUrl } from '@/utils/media'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const moviesLoading = ref(false)
const actor = ref(null)
const movies = ref([])
const movieTotal = ref(0)
const page = ref(1)
const pageSize = ref(24)

// 视图切换
const activeTab = ref('list')

// 时间线（v3.4 新增）
const timeline = ref(null)
const timelineLoading = ref(false)
const selectedYear = ref(null)
const selectedYearDetails = computed(() => {
  if (!timeline.value || !selectedYear.value) return null
  return timeline.value.details.find(d => d.year === selectedYear.value) || null
})

// 演员标签（v3.4 新增）
const actorTags = ref([])
const showTagDialog = ref(false)
const newTagName = ref('')
const newTagColor = ref('')
const tagAdding = ref(false)
const popularTags = ref([])

// 订阅
const subscribed = ref(false)
const subscribing = ref(false)
const checking = ref(false)
const newMovieCount = ref(0)

const handleAvatarError = (event) => {
  event.target.src = defaultAvatar(event.target.alt)
}

const handleCoverError = (event, movie) => {
  const img = event.target
  // 三级回退:主封面(cover/file) → poster/file → thumb/file → 占位图
  const stage = parseInt(img.dataset.cs || '0', 10)
  if (stage === 0) {
    img.dataset.cs = '1'
    img.src = getMoviePosterUrl(movie)
  } else if (stage === 1) {
    img.dataset.cs = '2'
    img.src = getMovieThumbUrl(movie)
  } else {
    img.dataset.cs = '3'
    img.src = defaultCover(movie?.code)
  }
}

// 社交账号平台显示名（v3.4 新增）
const socialLabel = (platform) => {
  const map = {
    twitter: 'Twitter', instagram: 'Instagram', facebook: 'Facebook',
    youtube: 'YouTube', linkedin: 'LinkedIn', official: '官方网站',
  }
  return map[platform] || platform
}

// 柱状图高度百分比（v3.4 新增）
const barHeight = (count) => {
  if (!timeline.value || !timeline.value.years.length) return 0
  const max = Math.max(...timeline.value.years.map(y => y.count))
  return Math.max(8, (count / max) * 100)
}

const selectYear = (year) => {
  selectedYear.value = selectedYear.value === year ? null : year
}

const loadActor = async () => {
  loading.value = true
  try {
    const res = await getActor(route.params.id)
    actor.value = res.actor
    movieTotal.value = res.movie_count || 0
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const loadMovies = async () => {
  moviesLoading.value = true
  try {
    const res = await getActorMovies(route.params.id, {
      page: page.value,
      page_size: pageSize.value
    })
    movies.value = res.items || []
    movieTotal.value = res.total || movieTotal.value
  } catch (e) {
    console.error(e)
  } finally {
    moviesLoading.value = false
  }
}

// 加载时间线（v3.4 新增）
const loadTimeline = async () => {
  timelineLoading.value = true
  try {
    const res = await getActorTimeline(route.params.id)
    timeline.value = res
    // 默认选中作品最多的年份
    if (res.years && res.years.length) {
      const top = [...res.years].sort((a, b) => b.count - a.count)[0]
      selectedYear.value = top.year
    }
  } catch (e) {
    console.error(e)
  } finally {
    timelineLoading.value = false
  }
}

// 标签管理（v3.4 新增）
const loadTags = async () => {
  try {
    const res = await getActorTags(route.params.id)
    actorTags.value = res || []
  } catch (e) {
    console.error(e)
  }
}

const loadPopularTags = async () => {
  try {
    const res = await getPopularActorTags({ limit: 20 })
    popularTags.value = res.items || []
  } catch (e) {
    // 静默
  }
}

const openTagDialog = () => {
  newTagName.value = ''
  newTagColor.value = ''
  showTagDialog.value = true
  if (!popularTags.value.length) {
    loadPopularTags()
  }
}

const addTag = async () => {
  if (!newTagName.value.trim()) {
    ElMessage.warning('请输入标签名')
    return
  }
  tagAdding.value = true
  try {
    const tag = await addActorTag(route.params.id, {
      name: newTagName.value.trim(),
      color: newTagColor.value || null,
    })
    actorTags.value.push(tag)
    newTagName.value = ''
    newTagColor.value = ''
    showTagDialog.value = false
    ElMessage.success('标签已添加')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '添加失败')
  } finally {
    tagAdding.value = false
  }
}

const removeTag = async (tag) => {
  try {
    await ElMessageBox.confirm(`删除标签"${tag.name}"?`, '确认', { type: 'warning' })
    await deleteActorTag(route.params.id, tag.id)
    actorTags.value = actorTags.value.filter(t => t.id !== tag.id)
    ElMessage.success('标签已删除')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

// 检查订阅状态
const checkSubscribed = async () => {
  try {
    const res = await listSubscriptions()
    const actorId = parseInt(route.params.id)
    const found = (res.items || []).find(s => s.actor_id === actorId)
    subscribed.value = !!found
    if (found) newMovieCount.value = found.new_movie_count || 0
  } catch (e) {
    // 静默
  }
}

const toggleSubscribe = async () => {
  subscribing.value = true
  try {
    const actorId = parseInt(route.params.id)
    if (subscribed.value) {
      await unsubscribeActor(actorId)
      subscribed.value = false
      newMovieCount.value = 0
      ElMessage.success('已取消订阅')
    } else {
      await subscribeActor({ actor_id: actorId, notify_new_movie: true })
      subscribed.value = true
      ElMessage.success('已订阅，有新片时将通知')
    }
  } catch (e) {
    ElMessage.error('操作失败')
  } finally {
    subscribing.value = false
  }
}

const checkNewMovies = async () => {
  checking.value = true
  try {
    const res = await checkActorNewMovies(route.params.id)
    newMovieCount.value = res.new_count || 0
    if (res.new_count > 0) {
      ElMessage.success(`检测到 ${res.new_count} 部新片`)
    } else {
      ElMessage.info('暂无新片')
    }
  } catch (e) {
    ElMessage.error('检测失败')
  } finally {
    checking.value = false
  }
}

const goDetail = (id) => {
  router.push(`/movie/${id}`)
}

// v4.1 C6: 双击复制演员名
const copyActorName = async () => {
  const name = actor.value?.name
  if (!name) return
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(name)
    } else {
      const ta = document.createElement('textarea')
      ta.value = name
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    ElMessage.success(`已复制演员名:${name}`)
  } catch (e) {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

// 头像编辑
const avatarInputRef = ref(null)
const avatarUploading = ref(false)
const avatarDeleting = ref(false)

const triggerAvatarUpload = () => {
  avatarInputRef.value?.click()
}

const onAvatarFileChange = async (event) => {
  const file = event.target.files?.[0]
  if (!file) return
  const validTypes = ['image/jpeg', 'image/png', 'image/webp']
  if (!validTypes.includes(file.type)) {
    ElMessage.warning('仅支持 JPG/PNG/WebP 格式')
    event.target.value = ''
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning('图片大小不能超过 10MB')
    event.target.value = ''
    return
  }
  avatarUploading.value = true
  try {
    await uploadActorAvatar(route.params.id, file)
    ElMessage.success('头像已更新')
    // 刷新头像缓存
    if (actor.value) {
      actor.value._avatar_ts = Date.now()
    }
    // 重新加载演员信息
    await loadActor()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '上传失败')
  } finally {
    avatarUploading.value = false
    event.target.value = ''
  }
}

const deleteAvatar = async () => {
  try {
    await ElMessageBox.confirm('确定要删除当前头像吗？删除后将显示默认头像。', '确认', { type: 'warning' })
  } catch (e) {
    return
  }
  avatarDeleting.value = true
  try {
    await deleteActorAvatar(route.params.id)
    ElMessage.success('头像已删除')
    if (actor.value) {
      actor.value.avatar_url = null
      actor.value._avatar_ts = Date.now()
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  } finally {
    avatarDeleting.value = false
  }
}

// 切换 Tab 时懒加载（v3.4 新增）
const handleTabChange = (name) => {
  if (name === 'timeline' && !timeline.value) {
    loadTimeline()
  }
}

onMounted(() => {
  loadActor()
  loadMovies()
  loadTags()
  checkSubscribed()
})
</script>

<style scoped>
.actor-detail {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.back-button {
  width: fit-content;
}

.profile-card,
.movies-card {
  border-radius: 12px;
}

.profile {
  display: flex;
  gap: 24px;
  align-items: center;
}

.profile-avatar {
  width: 140px;
  height: 140px;
  border-radius: 50%;
  overflow: hidden;
  background: #eef2ff;
  flex-shrink: 0;
  position: relative;
  cursor: pointer;
}

.profile-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.profile-avatar:hover .avatar-overlay {
  opacity: 1;
}

.avatar-overlay {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.2s;
  color: #fff;
  font-size: 13px;
}

.avatar-overlay .el-icon {
  font-size: 24px;
}

.profile-info {
  flex: 1;
  min-width: 0;
}

.profile-name {
  font-size: 32px;
  font-weight: 700;
  color: #111827;
}

.profile-subtitle {
  margin-top: 6px;
  color: #6b7280;
}

.profile-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.profile-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
}

.profile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
  margin-top: 18px;
  color: #374151;
}

.profile-grid span {
  display: block;
  color: #9ca3af;
  font-size: 12px;
  margin-bottom: 2px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.count {
  color: #909399;
  font-size: 13px;
}

.movies-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 20px;
  min-height: 260px;
}

.movie-card {
  cursor: pointer;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  border: 1px solid #ebeef5;
  transition: transform 0.2s, box-shadow 0.2s;
}

.movie-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.14);
}

.movie-cover {
  position: relative;
  height: 240px;
  background: #eee;
}

.movie-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.movie-play {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: rgba(0, 0, 0, 0.45);
  opacity: 0;
  transition: opacity 0.2s;
}

.movie-card:hover .movie-play {
  opacity: 1;
}

.movie-info {
  padding: 10px;
}

.movie-code {
  font-weight: 700;
  color: #409eff;
}

.movie-title {
  margin-top: 4px;
  color: #303133;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.movie-date {
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
}

.pagination {
  display: flex;
  justify-content: center;
  margin-top: 20px;
}

/* v3.4 新增：社交账号 */
.profile-social {
  display: flex;
  gap: 12px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.social-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #409eff;
  font-size: 13px;
  text-decoration: none;
  padding: 4px 10px;
  border: 1px solid #d9ecff;
  border-radius: 4px;
  background: #ecf5ff;
}
.social-link:hover {
  background: #409eff;
  color: #fff;
}

/* v3.4 新增：演员标签 */
.profile-tags {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px dashed #e4e7ed;
}
.tags-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.tags-title {
  font-size: 13px;
  color: #606266;
  font-weight: 600;
}
.tags-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}
.actor-tag {
  margin: 0;
}
.tags-empty {
  color: #c0c4cc;
  font-size: 12px;
}
.popular-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.popular-tag {
  cursor: pointer;
}

/* v3.4 新增：视图切换 Tab */
.view-tabs {
  flex: 1;
}
.view-tabs :deep(.el-tabs__header) {
  margin: 0;
}

/* v3.4 新增：时间线视图 */
.timeline-view {
  min-height: 300px;
}
.timeline-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.timeline-summary {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.timeline-chart {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 200px;
  padding: 12px 8px;
  background: #fafbfc;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  overflow-x: auto;
}
.chart-bar-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  min-width: 40px;
  height: 100%;
  cursor: pointer;
  padding: 0 2px;
  border-radius: 4px;
  transition: background 0.2s;
}
.chart-bar-wrapper:hover {
  background: rgba(64, 158, 255, 0.08);
}
.chart-bar-wrapper.active {
  background: rgba(64, 158, 255, 0.15);
}
.chart-bar-count {
  font-size: 12px;
  color: #606266;
  margin-bottom: 4px;
  font-weight: 600;
}
.chart-bar {
  width: 24px;
  background: linear-gradient(180deg, #409eff 0%, #79bbff 100%);
  border-radius: 3px 3px 0 0;
  min-height: 8px;
  transition: height 0.3s;
}
.chart-bar-wrapper.active .chart-bar {
  background: linear-gradient(180deg, #e6a23c 0%, #f3d19e 100%);
}
.chart-bar-label {
  font-size: 11px;
  color: #909399;
  margin-top: 4px;
}
.chart-hint {
  text-align: center;
  color: #c0c4cc;
  font-size: 12px;
  margin-top: -8px;
}

/* 时间线年份作品列表 */
.year-movies {
  border-top: 1px solid #ebeef5;
  padding-top: 16px;
}
.year-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.year-title {
  font-size: 18px;
  font-weight: 700;
  color: #303133;
}
.unknown-year .year-title {
  color: #909399;
}
.year-movies-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}
.movie-card-mini {
  display: flex;
  gap: 8px;
  padding: 8px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  cursor: pointer;
  transition: box-shadow 0.2s;
}
.movie-card-mini:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}
.mini-cover {
  width: 60px;
  height: 80px;
  flex-shrink: 0;
  border-radius: 4px;
  overflow: hidden;
  background: #f5f7fa;
}
.mini-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.mini-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.mini-code {
  font-weight: 700;
  color: #409eff;
  font-size: 13px;
}
.mini-title {
  margin-top: 2px;
  color: #606266;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.mini-date {
  margin-top: 2px;
  color: #c0c4cc;
  font-size: 11px;
}
</style>
