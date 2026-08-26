<template>
  <div class="page movie-detail-page" v-loading="loading">
    <div v-if="movie" class="detail-wrapper">
      <header class="top-bar">
        <el-button text @click="router.push('/fc2/movies')">
          <el-icon><ArrowLeft /></el-icon> 返回 FC2 列表
        </el-button>
      </header>

      <section class="hero-title">
        <h1 class="page-title">{{ movie.title || '-' }}</h1>
        <div v-if="movie.tag" class="tag-line">{{ movie.tag }}</div>
      </section>

      <section class="detail-main">
        <div class="cover-col">
          <div class="cover-frame">
            <el-image
              v-if="coverUrl"
              :src="coverUrl"
              fit="cover"
              class="cover-img"
              :style="{ aspectRatio: '2 / 3' }"
              @error="onCoverError"
            />
            <div v-else class="cover-placeholder">
              <el-icon :size="48"><Film /></el-icon>
              <span>暂无封面</span>
            </div>
          </div>
          <div class="play-btn-wrap">
            <el-button type="primary" size="large" class="play-btn" @click="play">
              <el-icon><VideoPlay /></el-icon> 立即播放
            </el-button>
            <div v-if="movie.is_leak" class="version-badge badge-leak">泄露版</div>
            <div v-if="movie.is_4k" class="version-badge badge-4k">4K</div>
            <div v-if="movie.is_uncensored" class="version-badge badge-uncensored">无码</div>
            <div v-if="movie.is_chinese" class="version-badge badge-cn">中文</div>
            <div v-if="movie.is_break || movie.is_crack" class="version-badge badge-crack">破解</div>
          </div>
        </div>

        <div class="meta-col">
          <div class="info-list">
            <div v-if="movie.release_date" class="info-row"><label>发布日期</label><span>{{ movie.release_date }}</span></div>
            <div v-if="movie.duration" class="info-row"><label>时长</label><span>{{ fmtDuration(movie.duration) }}</span></div>
            <div v-if="movie.seller" class="info-row"><label>卖家</label><span>{{ movie.seller }}</span></div>
            <div v-if="movie.resolution" class="info-row"><label>分辨率</label><span>{{ movie.resolution }}</span></div>
            <div v-if="movie.file_size" class="info-row"><label>大小</label><span>{{ movie.file_size }}</span></div>
            <div v-if="movie.views !== null && movie.views !== undefined" class="info-row"><label>浏览</label><span>{{ movie.views.toLocaleString() }}</span></div>
            <div v-if="movie.likes !== null && movie.likes !== undefined" class="info-row"><label>喜欢</label><span>{{ movie.likes.toLocaleString() }}</span></div>
            <div v-if="movie.rating !== null && movie.rating !== undefined" class="info-row">
              <label>评分</label>
              <span class="star">{{ starDisplay(movie.rating) }} {{ (Number(movie.rating)).toFixed(1) }}/5</span>
            </div>
            <div v-if="movie.file_path" class="info-row"><label>本地路径</label><span class="path">{{ movie.file_path }}</span></div>
            <div v-if="movie.nfo_path" class="info-row"><label>NFO 路径</label><span class="path">{{ movie.nfo_path }}</span></div>
          </div>

          <div v-if="actorList.length" class="meta-block">
            <h3>演员</h3>
            <div class="chip-group">
              <span
                v-for="a in actorList"
                :key="a.id"
                class="chip chip-actor"
                @click="goActor(a.id)"
              >
                <img v-if="a.avatar_url" :src="a.avatar_url" class="chip-avatar" />
                {{ a.name }}
              </span>
            </div>
          </div>

          <div v-if="displayGenres.length" class="meta-block">
            <h3>类别</h3>
            <div class="chip-group">
              <span v-for="g in displayGenres" :key="g" class="chip chip-genre" @click="goFilteredList('genre', g)">
                {{ g }}
              </span>
            </div>
          </div>

          <div v-if="movie.genres" class="meta-block">
            <h3>标签</h3>
            <div class="chip-group">
              <span v-for="(gt, i) in movie.genres.slice(0, 12)" :key="i" class="chip chip-tag">{{ gt }}</span>
            </div>
          </div>

          <div class="meta-block">
            <h3>版本</h3>
            <div class="chip-group">
              <span v-if="movie.is_leak" class="chip chip-version v-leak">泄露</span>
              <span v-if="movie.is_4k" class="chip chip-version v-4k">4K</span>
              <span v-if="movie.is_uncensored" class="chip chip-version v-uncensored">无码</span>
              <span v-if="movie.is_chinese" class="chip chip-version v-cn">中文</span>
              <span v-if="movie.is_break || movie.is_crack" class="chip chip-version v-crack">破解</span>
              <span v-if="!movie.is_leak && !movie.is_4k && !movie.is_uncensored && !movie.is_chinese && !movie.is_break && !movie.is_crack" class="chip chip-version v-normal">普通</span>
            </div>
          </div>
        </div>
      </section>

      <section v-if="movie.plot" class="plot-section">
        <h2>简介</h2>
        <p>{{ movie.plot }}</p>
      </section>

      <section class="preview-section" v-if="showPreviewSection">
        <div class="section-head">
          <h2>预览图</h2>
          <div class="head-actions">
            <span class="meta-hint" v-if="previewMeta">{{ previewMeta }}</span>
            <el-button size="small" :loading="previewLoading" @click="loadPreviews(true)">
              <el-icon><RefreshRight /></el-icon> 刷新
            </el-button>
          </div>
        </div>

        <div v-if="previewLoading" class="preview-skeleton">
          <div v-for="i in 6" :key="i" class="skeleton-item"></div>
        </div>

        <div v-else-if="previewSrcList.length > 1" class="preview-grid">
          <div
            v-for="(img, i) in previewSrcList"
            :key="i"
            class="preview-item"
            :class="{ 'preview-cover': i === 0 }"
            @click="openLightbox(i)"
          >
            <el-image :src="img" fit="cover" class="preview-img" />
          </div>
        </div>

        <div v-else-if="!previewLoading" class="preview-empty">
          <el-empty description="暂无预览图，刮削后自动补充" :image-size="80" />
        </div>
      </section>

      <section class="actions-bar">
        <el-button @click="toggleFav" :icon="fav ? Star : Star">
          {{ fav ? '已收藏' : '收藏' }}
        </el-button>
        <el-button @click="openEditDialog"><el-icon><Edit /></el-icon> 编辑</el-button>
        <el-button @click="doScrape" :loading="scraping"><el-icon><Download /></el-icon> 刮削</el-button>
        <el-button @click="doReloadNfo" :loading="reloadingNfo"><el-icon><RefreshLeft /></el-icon> 从 NFO 重新导入</el-button>
        <el-button @click="doFaceCrop" :loading="cropping"><el-icon><Crop /></el-icon> AI 裁剪封面</el-button>
        <el-button @click="doRefillImages" :loading="refilling"><el-icon><Picture /></el-icon> 重新下载图片</el-button>
      </section>

      <section v-if="relatedActors.length" class="related-section">
        <h2>同演员作品</h2>
        <div class="related-grid">
          <div
            v-for="m in relatedActors.slice(0, 6)"
            :key="m.id"
            class="related-card"
            @click="goMovie(m.id)"
          >
            <div class="related-cover">
              <el-image :src="getRelatedCover(m)" fit="cover" />
            </div>
            <div class="related-info">
              <div class="related-title">{{ m.title }}</div>
              <div class="related-sub" v-if="m.release_date">{{ m.release_date }}</div>
            </div>
          </div>
        </div>
      </section>

      <el-dialog v-model="editDialogVisible" title="编辑影片信息" :width="640" @closed="onEditDialogClosed">
        <el-form :model="editForm" label-width="80px" v-if="editForm">
          <el-form-item label="标题"><el-input v-model="editForm.title" /></el-form-item>
          <el-form-item label="标签"><el-input v-model="editForm.tag" placeholder="FC2-xxxxxx" /></el-form-item>
          <el-form-item label="发布日期"><el-input v-model="editForm.release_date" /></el-form-item>
          <el-form-item label="时长"><el-input-number v-model="editForm.duration" :min="0" /></el-form-item>
          <el-form-item label="评分"><el-input-number v-model="editForm.rating" :min="0" :max="5" :precision="1" /></el-form-item>
          <el-form-item label="分辨率"><el-input v-model="editForm.resolution" /></el-form-item>
          <el-form-item label="卖家"><el-input v-model="editForm.seller" /></el-form-item>
          <el-form-item label="简介"><el-input v-model="editForm.plot" type="textarea" :rows="3" /></el-form-item>
          <el-form-item label="演员"><el-input v-model="editForm.actors_str" placeholder="逗号分隔" /></el-form-item>
          <el-form-item label="类别"><el-input v-model="editForm.genre_str" placeholder="逗号分隔" /></el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
        </template>
      </el-dialog>
    </div>

    <div v-else-if="!loading" class="empty-state">
      <el-empty description="影片不存在或已删除" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft, Film, VideoPlay, RefreshRight, Edit, Download, RefreshLeft,
  Crop, Picture, Star
} from '@element-plus/icons-vue'
import {
  getFc2Movie, updateFc2Movie, scrapeFc2Movie, reloadFc2MovieNfo,
  getRelatedMovies, getMovieActors, getFc2Previews, fc2FaceCrop,
  getFc2CoverUrl
} from '@/api/fc2'

const route = useRoute()
const router = useRouter()

const movieId = computed(() => Number(route.params.id))
const movie = ref(null)
const loading = ref(true)
const coverError = ref(false)
const fav = ref(false)
const actorList = ref([])
const relatedActors = ref([])
const previewSource = ref('none')
const previewImages = ref([])
const previewCoverUrl = ref('')
const previewLoading = ref(false)

// ---------- 封面 ----------
const hasDbCover = computed(() => {
  const m = movie.value
  return m?.local_cover_path || m?.cover_path
})
const fallbackCoverUrl = computed(() => {
  if (!hasDbCover.value || coverError.value) return ''
  const m = movie.value
  const p = m.local_cover_path || m.cover_path
  if (p && p.startsWith('http')) return p
  return getFc2CoverUrl(movieId.value)
})
const coverUrl = computed(() => {
  if (previewCoverUrl.value) return previewCoverUrl.value
  return fallbackCoverUrl.value
})
const onCoverError = () => { coverError.value = true }

// ---------- 类别解析 ----------
const displayGenres = computed(() => {
  const g = movie.value?.genre
  if (!g) return []
  if (Array.isArray(g)) return g.slice(0, 12)
  if (typeof g === 'string') {
    try { const p = JSON.parse(g); if (Array.isArray(p)) return p.slice(0, 12) } catch {}
    return g.split(',').map(s => s.trim()).filter(Boolean).slice(0, 12)
  }
  return []
})

// ---------- 预览图 ----------
const showPreviewSection = computed(() => previewLoading.value || previewSrcList.value.length > 0 || previewSource.value === 'none')
const previewSrcList = computed(() => gallery.value.map(i => i.src))
const gallery = computed(() => {
  const list = []
  const seen = new Set()
  const push = (src, isCover = false) => {
    if (!src || seen.has(src)) return
    seen.add(src)
    list.push({ src, isCover })
  }
  if (previewCoverUrl.value) push(previewCoverUrl.value, true)
  else if (hasDbCover.value) push(fallbackCoverUrl.value, true)
  for (const u of previewImages.value) push(u)
  return list
})
const previewMeta = computed(() => {
  const n = previewImages.value.length
  if (!n) return ''
  return previewSource.value === 'local' ? `本地 ${n} 张` : `远程外链 ${n} 张`
})

const loadPreviews = async (refresh = false) => {
  try {
    previewLoading.value = true
    previewSource.value = 'loading'
    const res = await getFc2Previews(movieId.value, refresh)
    previewSource.value = res?.source || 'none'
    previewImages.value = Array.isArray(res?.images) ? res.images : []
    previewCoverUrl.value = res?.cover_url || ''
  } catch (e) {
    previewSource.value = 'none'
    previewImages.value = []
    previewCoverUrl.value = ''
  } finally {
    previewLoading.value = false
  }
}

// ---------- 操作 ----------
const scraping = ref(false)
const doScrape = async () => {
  scraping.value = true
  try {
    await scrapeFc2Movie(movieId.value, false)
    ElMessage.success('刮削完成')
    await load()
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '刮削失败'
    ElMessage.error(msg)
  } finally { scraping.value = false }
}

const reloadingNfo = ref(false)
const doReloadNfo = async () => {
  reloadingNfo.value = true
  try {
    const res = await reloadFc2MovieNfo(movieId.value)
    const applied = (res?.applied_fields) || []
    ElMessage.success(`已从 NFO 导入 ${applied.length} 个字段`)
    await load()
  } catch (e) {
    ElMessage.error(`失败: ${e?.response?.data?.detail || e?.message}`)
  } finally { reloadingNfo.value = false }
}

const cropping = ref(false)
const doFaceCrop = async () => {
  cropping.value = true
  try {
    await fc2FaceCrop(movieId.value)
    ElMessage.success('AI 裁剪完成')
    coverError.value = false
    await load()
  } catch (e) {
    ElMessage.error(`失败: ${e?.response?.data?.detail || e?.message}`)
  } finally { cropping.value = false }
}

const refilling = ref(false)
const doRefillImages = async () => {
  refilling.value = true
  try {
    const res = await scrapeFc2Movie(movieId.value, true)
    ElMessage.success('图片重新下载完成')
    coverError.value = false
    await load()
  } catch (e) {
    ElMessage.error(`失败: ${e?.response?.data?.detail || e?.message}`)
  } finally { refilling.value = false }
}

const toggleFav = async () => {
  fav.value = !fav.value
  ElMessage.success(fav.value ? '已收藏' : '已取消收藏')
}

const play = () => {
  router.push(`/play/${movieId.value}?module=fc2`)
}

const goActor = (id) => {
  if (!id) return
  router.push(`/fc2/actors/${id}`)
}

const goMovie = (id) => router.push(`/fc2/movies/${id}`)

const goFilteredList = (key, value) => {
  if (!value) return
  router.push(`/fc2/movies?${key}=${encodeURIComponent(value)}`)
}

const getRelatedCover = (m) => {
  if (m?.cover_url) return m.cover_url
  if (m?.local_cover_path) return m.local_cover_path
  return getFc2CoverUrl(m.id)
}

const fmtDuration = (d) => {
  if (typeof d === 'number' && d > 0) {
    if (d >= 60) return `${Math.floor(d)} 分钟`
    return `${d} 秒`
  }
  return d ? String(d) : '-'
}
const starDisplay = (r) => {
  const n = Math.round(Number(r) * 2) / 2
  const full = Math.floor(n)
  const half = n % 1 !== 0 ? '½' : ''
  return '★'.repeat(full) + half
}

// ---------- 编辑弹窗 ----------
const editDialogVisible = ref(false)
const saving = ref(false)
const editForm = ref(null)

const openEditDialog = () => {
  const m = movie.value
  if (!m) return
  editForm.value = {
    title: m.title || '',
    tag: m.tag || '',
    release_date: m.release_date || '',
    duration: m.duration ?? 0,
    rating: m.rating ?? 0,
    resolution: m.resolution || '',
    seller: m.seller || '',
    plot: m.plot || '',
    actors_str: (actorList.value || []).map(a => a.name || a).join(', '),
    genre_str: Array.isArray(m.genre) ? m.genre.join(', ') : (m.genre || ''),
  }
  editDialogVisible.value = true
}
const onEditDialogClosed = () => { editForm.value = null }

const saveEdit = async () => {
  if (!editForm.value) return
  saving.value = true
  try {
    const f = editForm.value
    await updateFc2Movie(movieId.value, {
      title: f.title,
      tag: f.tag,
      release_date: f.release_date || null,
      duration: f.duration > 0 ? f.duration : null,
      rating: f.rating > 0 ? f.rating : null,
      resolution: f.resolution || null,
      seller: f.seller || null,
      plot: f.plot || null,
      actors_str: f.actors_str,
      genre: f.genre_str ? f.genre_str.split(',').map(s => s.trim()).filter(Boolean) : null,
    })
    ElMessage.success('保存成功')
    editDialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(`保存失败: ${e?.response?.data?.detail || e?.message}`)
  } finally { saving.value = false }
}

const openLightbox = (i) => {
  window.open(previewSrcList.value[i], '_blank')
}

// ---------- 加载 ----------
const load = async () => {
  if (!Number.isFinite(movieId.value) || movieId.value <= 0) {
    loading.value = false
    return
  }
  loading.value = true
  coverError.value = false
  previewSource.value = 'none'
  previewImages.value = []
  previewCoverUrl.value = ''
  try {
    const res = await getFc2Movie(movieId.value)
    movie.value = res
    // 演员
    try {
      const actorsRes = await getMovieActors(movieId.value)
      actorList.value = Array.isArray(actorsRes) ? actorsRes : (actorsRes?.items || [])
    } catch { actorList.value = [] }
    // 预览图（不阻塞）
    loadPreviews()
    // 相关推荐
    try {
      const relData = await getRelatedMovies(movieId.value).catch(() => null)
      const actors = (relData?.actor_movies || []).slice(0, 6)
      const genres = (relData?.genre_movies || []).slice(0, 6)
      relatedActors.value = actors.length ? actors : genres
    } catch { relatedActors.value = [] }
  } catch {
    movie.value = null
  } finally {
    loading.value = false
  }
}

onMounted(() => { load() })
watch(movieId, () => { load() })
</script>

<style scoped>
.movie-detail-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px 24px 80px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.detail-wrapper { display: flex; flex-direction: column; gap: 20px; }

.top-bar { display: flex; align-items: center; }
.top-bar .el-button { color: #666; }

.hero-title {
  padding: 16px 0 8px;
  border-bottom: 1px solid #eee;
}
.page-title {
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 4px;
  color: #222;
}
.tag-line {
  font-size: 13px;
  color: #999;
}

.detail-main {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 32px;
}

.cover-col { display: flex; flex-direction: column; gap: 12px; }
.cover-frame { width: 200px; }
.cover-img {
  width: 200px;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.1);
}
.cover-placeholder {
  width: 200px;
  aspect-ratio: 2/3;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: #f5f5f5;
  border-radius: 8px;
  color: #bbb;
  font-size: 13px;
}

.play-btn-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.play-btn { flex: 1; min-width: 140px; }
.version-badge {
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.badge-leak { background: #fff3e0; color: #e65100; }
.badge-4k { background: #e3f2fd; color: #1565c0; }
.badge-uncensored { background: #fce4ec; color: #c62828; }
.badge-cn { background: #e8f5e9; color: #2e7d32; }
.badge-crack { background: #f3e5f5; color: #6a1b9a; }

.meta-col { display: flex; flex-direction: column; gap: 16px; }

.info-list { display: flex; flex-direction: column; gap: 8px; padding: 12px 16px; background: #fafafa; border-radius: 8px; }
.info-row {
  display: flex;
  align-items: center;
  font-size: 14px;
}
.info-row label {
  display: inline-block;
  width: 72px;
  color: #888;
  flex-shrink: 0;
}
.info-row .path {
  color: #555;
  font-family: 'SF Mono', Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}
.info-row .star { color: #f5a623; }

.meta-block { display: flex; flex-direction: column; gap: 8px; }
.meta-block h3 {
  font-size: 14px;
  font-weight: 600;
  color: #555;
  margin: 0;
}
.chip-group { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 14px;
  font-size: 12px;
  background: #f0f0f0;
  color: #555;
  cursor: default;
  transition: background 0.15s;
}
.chip-actor { cursor: pointer; gap: 4px; }
.chip-actor:hover { background: #e0e7ff; color: #3b82f6; }
.chip-genre { cursor: pointer; }
.chip-genre:hover { background: #dbeafe; color: #2563eb; }
.chip-avatar {
  width: 16px; height: 16px; border-radius: 50%; margin-right: 2px;
}
.chip-version { font-weight: 500; }
.v-leak { background: #fff3e0; color: #e65100; }
.v-4k { background: #e3f2fd; color: #1565c0; }
.v-uncensored { background: #fce4ec; color: #c62828; }
.v-cn { background: #e8f5e9; color: #2e7d32; }
.v-crack { background: #f3e5f5; color: #6a1b9a; }
.v-normal { background: #f5f5f5; color: #999; }

.plot-section {
  padding: 16px 20px;
  background: #fafafa;
  border-radius: 8px;
}
.plot-section h2 { font-size: 15px; font-weight: 600; margin: 0 0 8px; color: #333; }
.plot-section p { font-size: 14px; line-height: 1.7; color: #555; margin: 0; }

.preview-section {
  padding: 16px 20px;
  background: #fafafa;
  border-radius: 8px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.section-head h2 { font-size: 15px; font-weight: 600; margin: 0; color: #333; }
.head-actions { display: flex; align-items: center; gap: 8px; }
.meta-hint { font-size: 12px; color: #999; }

.preview-skeleton { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; }
.skeleton-item {
  aspect-ratio: 16/9;
  background: #e8e8e8;
  border-radius: 6px;
  animation: pulse 1.5s infinite ease-in-out;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

.preview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}
.preview-item {
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}
.preview-item:hover {
  transform: scale(1.02);
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
}
.preview-item.preview-cover {
  outline: 2px solid #3b82f6;
  outline-offset: -2px;
}
.preview-img {
  width: 100%;
  aspect-ratio: 16/9;
  display: block;
}

.preview-empty { padding: 20px 0; }

.actions-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 20px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.06);
}

.related-section {
  padding: 16px 20px;
  background: #fafafa;
  border-radius: 8px;
}
.related-section h2 { font-size: 15px; font-weight: 600; margin: 0 0 12px; color: #333; }
.related-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}
.related-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  transition: background 0.15s;
}
.related-card:hover { background: #f0f0f0; }
.related-cover { width: 100%; aspect-ratio: 2/3; border-radius: 6px; overflow: hidden; }
.related-cover .el-image { width: 100%; height: 100%; }
.related-info { display: flex; flex-direction: column; gap: 2px; }
.related-title { font-size: 13px; font-weight: 500; color: #333; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.related-sub { font-size: 11px; color: #999; }

.empty-state { padding: 60px 0; text-align: center; }
</style>