<template>
  <div class="movie-detail" v-loading="loading">
    <!-- 返回按钮 -->
    <div class="top-bar">
      <el-button text @click="router.back()">
        <el-icon><ArrowLeft /></el-icon> 返回
      </el-button>
    </div>

    <!-- 标题置顶 -->
    <div class="hero-title" v-if="movie">
      <h1 class="hero-h1">
        <span class="hero-code">{{ movie.code }}</span>
        <span class="hero-divider" v-if="movie.title">—</span>
        <span class="hero-text">{{ movie.title }}</span>
      </h1>
      <div class="hero-subtitle" v-if="movie.original_title || movie.title_jp">
        <span v-if="movie.original_title">{{ movie.original_title }}</span>
        <span v-if="movie.title_jp" class="jp-title">{{ movie.title_jp }}</span>
      </div>
    </div>

    <!-- 主区域 -->
    <div class="detail-main" v-if="movie">
      <!-- 左侧：大��面 -->
      <div class="cover-col">
        <div class="cover-wrap">
          <img :src="coverUrl" :alt="movie.code" @error="onCoverError" />
        </div>
      </div>

      <!-- 右侧：元信息 -->
      <div class="info-col">
        <!-- 键值对元数据 -->
        <dl class="meta-list">
          <dt>番号</dt>
          <dd>
            <span class="code-parts">
              <a class="link-val" @click="goFilteredList('search', codePrefix)">{{ codePrefix }}</a>
              <span v-if="codeSuffix">-{{ codeSuffix }}</span>
            </span>
          </dd>

          <dt>日期</dt><dd>{{ movie.release_date || '-' }}</dd>

          <dt>时长</dt><dd>{{ fmtDuration(movie.duration) }}</dd>

          <dt>导演</dt>
          <dd>
            <span v-if="movie.director" class="link-val" @click="goFilteredList('maker', movie.director)">{{ movie.director }}</span>
            <span v-else>-</span>
          </dd>

          <dt>片商</dt>
          <dd>
            <span v-if="movie.maker || movie.studio" class="link-val" @click="goFilteredList('maker', movie.maker || movie.studio)">
              {{ movie.maker || movie.studio }}
            </span>
            <span v-else>-</span>
          </dd>

          <dt>系列</dt><dd>
            <span v-if="movie.series" class="link-val" @click="goFilteredList('series', movie.series)">
              {{ movie.series }}
            </span>
            <span v-else>-</span>
          </dd>

          <dt>評分</dt><dd>
            <template v-if="movie.rating">
              <span class="stars">★{{ starDisplay(movie.rating) }}☆</span>
              <span class="rating-num">{{ Number(movie.rating).toFixed(1) }}分</span>
            </template>
            <span v-else>-</span>
          </dd>

          <dt>類別</dt><dd>
            <a
              v-for="(g, idx) in displayGenres"
              :key="idx"
              class="link-tag genre-link"
              @click="goFilteredList('search', g)"
            >{{ g }}</a>
            <span v-if="!displayGenres.length">-</span>
          </dd>

          <dt>標籤</dt><dd>
            <a
              v-for="(t, idx) in displayTags"
              :key="idx"
              class="link-tag tag-link"
              @click="goFilteredList('tag_id', t.id)"
            >{{ t.name }}</a>
            <span v-if="!displayTags.length">-</span>
          </dd>

          <dt>演員</dt><dd>
            <div class="actor-chips">
              <span
                v-for="a in movie.actors"
                :key="a.id"
                class="actor-link link-val"
                @click="goActor(a.id)"
              >{{ a.name }}</span>
              <span v-if="!movie.actors?.length">-</span>
            </div>
          </dd>
        </dl>

        <!-- 播放按钮 -->
        <div class="play-box" @click="play">
          <el-icon class="play-icon"><VideoPlay /></el-icon>
          <span>播放</span>
        </div>
      </div>
    </div>

    <!-- 预览图 -->
    <section class="preview-section" v-if="movie && sampleImages.length">
      <h3 class="sec-title">预览图</h3>
      <div class="preview-grid">
        <div v-for="(src, idx) in gallery" :key="idx" class="preview-item">
          <el-image
            :src="src"
            fit="cover"
            :preview-src-list="gallery"
            :initial-index="idx"
            loading="lazy"
            hide-on-click-modal
          >
            <template #error>
              <div class="preview-error"><el-icon><PictureFilled /></el-icon></div>
            </template>
            <template #placeholder>
              <div class="preview-loading"><el-icon class="is-loading"><Loading /></el-icon></div>
            </template>
          </el-image>
        </div>
      </div>
    </section>

    <!-- 简介 -->
    <section class="plot-section" v-if="movie && movie.plot">
      <h3 class="sec-title">简介</h3>
      <div class="plot-text">{{ movie.plot }}</div>
    </section>

    <!-- 操作栏 -->
    <div class="actions-bar" v-if="movie">
      <el-button :type="fav ? 'warning' : 'default'" @click="toggleFav">
        <el-icon><StarFilled v-if="fav" /><Star v-else /></el-icon>
        {{ fav ? '已收藏' : '收藏' }}
      </el-button>
      <el-button type="primary" @click="openEditDialog">
        <el-icon><Edit /></el-icon> 编辑元数据
      </el-button>
      <el-button @click="scrape" :loading="scraping">
        <el-icon><MagicStick /></el-icon> {{ forceScrape ? '强制重新刮削' : '刮削补充' }}
      </el-button>
      <el-checkbox v-model="forceScrape" size="small" style="margin-left:4px" title="勾选后跳过 NFO 缓存">强制</el-checkbox>
      <el-button @click="reloadNfo" :loading="reloadingNfo">
        <el-icon><DocumentCopy /></el-icon> 从 NFO 重新导入
      </el-button>
      <el-button @click="rescanFiles" :loading="rescanning" type="warning" plain>
        <el-icon><FolderOpened /></el-icon> 重新扫描文件
      </el-button>
    </div>

    <!-- ===== 推荐区 ===== -->

    <!-- TA(們)還出演過 -->
    <section class="related-section" v-if="related.actor_movies.length">
      <h3 class="sec-title">TA(們)還出演過</h3>
      <div class="related-grid">
        <div
          v-for="m in related.actor_movies"
          :key="m.id"
          class="related-card"
          @click="goMovie(m.id)"
        >
          <div class="related-cover">
            <img :src="getRelatedCover(m)" :alt="m.code" loading="lazy" />
          </div>
          <div class="related-info">
            <span class="related-code">{{ m.code }}</span>
            <span class="related-title" :title="m.title">{{ m.title }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 你可能也喜歡（同系列） -->
    <section class="related-section" v-if="related.series_movies.length">
      <h3 class="sec-title">你可能也喜歡</h3>
      <div class="related-grid">
        <div
          v-for="m in related.series_movies"
          :key="m.id"
          class="related-card"
          @click="goMovie(m.id)"
        >
          <div class="related-cover">
            <img :src="getRelatedCover(m)" :alt="m.code" loading="lazy" />
          </div>
          <div class="related-info">
            <span class="related-code">{{ m.code }}</span>
            <span class="related-title" :title="m.title">{{ m.title }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 同類別推薦 -->
    <section class="related-section" v-if="related.genre_movies.length">
      <h3 class="sec-title">同類別推薦</h3>
      <div class="related-grid">
        <div
          v-for="m in related.genre_movies"
          :key="m.id"
          class="related-card"
          @click="goMovie(m.id)"
        >
          <div class="related-cover">
            <img :src="getRelatedCover(m)" :alt="m.code" loading="lazy" />
          </div>
          <div class="related-info">
            <span class="related-code">{{ m.code }}</span>
            <span class="related-title" :title="m.title">{{ m.title }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 编辑弹窗 -->
    <el-dialog
      v-model="editDialogVisible"
      title="编辑影片元数据"
      width="780px"
      :close-on-click-modal="false"
      @closed="onEditDialogClosed"
    >
      <el-form v-if="editForm" :model="editForm" label-width="100px" label-position="right">
        <el-form-item label="番号">
          <el-input v-model="editForm.code" placeholder="如 ABP-001">
            <template #append>
              <el-tag size="small" type="info">修改需唯一</el-tag>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="editForm.title" placeholder="主标题" />
        </el-form-item>
        <el-form-item label="原标题">
          <el-input v-model="editForm.original_title" placeholder="原始标题(原语言)" />
        </el-form-item>
        <el-form-item label="日文标题">
          <el-input v-model="editForm.title_jp" placeholder="日文标题(可选)" />
        </el-form-item>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="发行日期">
              <el-input v-model="editForm.release_date" placeholder="YYYY-MM-DD" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="时长(分)">
              <el-input-number v-model="editForm.duration" :min="0" :max="9999" controls-position="right" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="评分">
              <el-input-number v-model="editForm.rating" :min="0" :max="10" :step="0.1" :precision="1" controls-position="right" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="导演">
              <el-input v-model="editForm.director" placeholder="导演(逗号分隔多导演)" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="片商">
              <el-input v-model="editForm.maker" placeholder="发行商 / Maker" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="制作商">
              <el-input v-model="editForm.studio" placeholder="制作商(不存在则自动创建)" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="系列">
          <el-input v-model="editForm.series" placeholder="系列(不存在则自动创建)" />
        </el-form-item>

        <el-form-item label="类别">
          <el-input v-model="editForm.genre_str" placeholder="逗号分隔, 如: 中文字幕, 高清, 巨乳" />
        </el-form-item>

        <el-form-item label="标签">
          <el-input v-model="editForm.tag_str" placeholder="逗号分隔(可选)" />
        </el-form-item>

        <el-form-item label="演员">
          <el-input v-model="editForm.actors_str" type="textarea" :rows="2" placeholder="演员名,逗号分隔(不存在则自动创建)" />
        </el-form-item>

        <el-form-item label="简介">
          <el-input v-model="editForm.plot" type="textarea" :rows="3" placeholder="详细简介" />
        </el-form-item>

        <el-form-item label="短简介">
          <el-input v-model="editForm.plot_short" type="textarea" :rows="2" placeholder="一句话简介(outline)" />
        </el-form-item>

        <el-form-item label="视频路径">
          <el-input v-model="editForm.file_path" placeholder="视频文件完整路径" />
        </el-form-item>

        <el-row :gutter="12">
          <el-col :span="6"><el-form-item label="有码"><el-switch v-model="editForm.is_mosaic" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="无码"><el-switch v-model="editForm.is_uncensored" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="中字"><el-switch v-model="editForm.is_chinese" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="破解"><el-switch v-model="editForm.is_leak" /></el-form-item></el-col>
        </el-row>

        <el-alert v-if="syncNfoEnabled" type="info" :closable="false" show-icon style="margin-top:8px">
          勾选「同步 NFO」后,保存时会把最新字段回写到 <code>movie.nfo</code>(同步给 Emby/Jellyfin/Kodi)。
        </el-alert>
      </el-form>

      <template #footer>
        <el-checkbox v-model="syncNfoEnabled" style="margin-right: 12px">同步 NFO</el-checkbox>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-empty v-if="!loading && !movie" description="未找到该影片" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft, VideoPlay, Star, StarFilled, MagicStick,
  PictureFilled, Loading, Edit, DocumentCopy, FolderOpened
} from '@element-plus/icons-vue'
import {
  getMovie, updateMovie, reloadMovieNfo,
  scrapeMovie, checkFavorite, addFavoriteItem, removeFavoriteItem, getFavoriteGroups,
  autoLinkFiles, getRelatedMovies
} from '@/api'
import { getMovieCoverUrl, defaultCover, getFileProxyUrl } from '@/utils/media'

const route = useRoute()
const router = useRouter()
const movieId = computed(() => Number(route.params.id))
const movie = ref(null)
const loading = ref(false)
const scraping = ref(false)
const fav = ref(false)
const coverError = ref(false)
const related = ref({ actor_movies: [], series_movies: [], genre_movies: [] })

const codePrefix = computed(() => {
  const code = movie.value?.code || ''
  const m = code.match(/^([A-Za-z]+)-/)
  return m ? m[1] : code
})
const codeSuffix = computed(() => {
  const code = movie.value?.code || ''
  const m = code.match(/^[A-Za-z]+-(.+)/)
  return m ? m[1] : ''
})

/* ---- 封面 ---- */
const hasDbCover = computed(() => !!(movie.value && movie.value.cover_url))
const toDisplayUrl = (s) => {
  if (!s || typeof s !== 'string') return ''
  if (/^https?:\/\//i.test(s)) return s
  return getFileProxyUrl(s)
}
const coverUrl = computed(() => {
  if (!movie.value?.id) return defaultCover(movie.value?.code)
  if (coverError.value) {
    if (sampleImages.value.length) return toDisplayUrl(sampleImages.value[0])
    return defaultCover(movie.value?.code)
  }
  if (hasDbCover.value) return getMovieCoverUrl(movie.value)
  if (sampleImages.value.length) return toDisplayUrl(sampleImages.value[0])
  return defaultCover(movie.value?.code)
})
const gallery = computed(() => {
  const list = []
  if (hasDbCover.value) list.push(getMovieCoverUrl(movie.value))
  for (const s of sampleImages.value) {
    const u = toDisplayUrl(s)
    if (u && !list.includes(u)) list.push(u)
  }
  if (!list.length) list.push(coverUrl.value)
  return list
})
const onCoverError = () => { coverError.value = true }

const sampleImages = computed(() => {
  const arr = movie.value?.sample_images
  if (!arr || !Array.isArray(arr)) return []
  return arr.filter(s => s && typeof s === 'string' && s.trim())
})
const displayGenres = computed(() => {
  const g = movie.value?.genre
  if (!g) return []
  if (Array.isArray(g)) return g.slice(0, 12)
  if (typeof g === 'string') {
    try {
      const parsed = JSON.parse(g)
      if (Array.isArray(parsed)) return parsed.slice(0, 12)
    } catch { /* fallthrough */ }
    return g.split(',').map(s => s.trim()).filter(Boolean).slice(0, 12)
  }
  return []
})
const displayTags = computed(() => {
  const tags = movie.value?.tags
  if (Array.isArray(tags) && tags.length) return tags.slice(0, 20)
  const tagStr = movie.value?.tag
  if (Array.isArray(tagStr)) return tagStr.map((t, i) => ({ id: i, name: t, is_user: false }))
  return []
})

const load = async () => {
  loading.value = true
  coverError.value = false
  try {
    const [res, rel] = await Promise.all([
      getMovie(movieId.value),
      getRelatedMovies(movieId.value).catch(() => ({ actor_movies: [], series_movies: [], genre_movies: [] }))
    ])
    movie.value = res
    related.value = rel
    checkFav()
  } catch {
    movie.value = null
  } finally {
    loading.value = false
  }
}

const play = () => router.push(`/play/${movieId.value}`)
const goActor = (id) => router.push(`/actors/${id}`)
const goMovie = (id) => router.push(`/movie/${id}`)

const goFilteredList = (key, value) => {
  if (!value) return
  const encoded = encodeURIComponent(value)
  switch (key) {
    case 'maker':
      router.push(`/movies?maker=${encoded}`)
      break
    case 'series':
      router.push(`/movies?series=${encoded}`)
      break
    case 'studio':
      router.push(`/movies?studio=${encoded}`)
      break
    case 'tag_id':
      router.push(`/movies?tag_ids=${value}`)
      break
    case 'search':
      router.push(`/movies?search=${encoded}`)
      break
    default:
      router.push(`/movies?${key}=${encoded}`)
  }
}

const getRelatedCover = (m) => getMovieCoverUrl(m)

const fmtDuration = (d) => {
  if (typeof d === 'number' && d > 0) {
    if (d >= 60) return `${Math.floor(d)} 分鐘`
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

const checkFav = async () => {
  try {
    const check = await checkFavorite('movie', movieId.value)
    const data = check.items ? check : (check.data || check)
    fav.value = data.in_favorites || false
  } catch { fav.value = false }
}
const toggleFav = async () => {
  try {
    if (fav.value) {
      const check = await checkFavorite('movie', movieId.value)
      const data = check.items ? check : (check.data || check)
      if (data.groups && data.groups.length) {
        await removeFavoriteItem(data.groups[0].group_id, movieId.value)
        fav.value = false; ElMessage.success('已取消收藏')
      }
    } else {
      const res = await getFavoriteGroups('movie')
      const groups = res.items ? res : (res.data || res)
      let groupId = groups.length ? groups[0].id : null
      if (!groupId) {
        const { createFavoriteGroup } = await import('@/api')
        const ng = await createFavoriteGroup('默认收藏', 'movie')
        groupId = (ng.items ? ng : (ng.data || ng)).id
      }
      await addFavoriteItem(groupId, movieId.value)
      fav.value = true; ElMessage.success('已收藏')
    }
  } catch { ElMessage.error('操作失败') }
}

const forceScrape = ref(false)
const scrape = async () => {
  scraping.value = true
  try {
    const res = await scrapeMovie(movieId.value, forceScrape.value)
    const src = res && res.source
    ElMessage.success(src === 'nfo_cache' ? '已从 NFO 缓存恢复' : '已从外部站点刮削完成')
    await load()
  } catch { /* 拦截器提示 */ } finally { scraping.value = false }
}

const rescanning = ref(false)
const rescanFiles = async () => {
  rescanning.value = true
  try {
    await autoLinkFiles()
    ElMessage.success('已重新扫描文件并关联视频')
    await load()
  } catch { /* */ } finally { rescanning.value = false }
}

const reloadingNfo = ref(false)
const reloadNfo = async () => {
  reloadingNfo.value = true
  try {
    const res = await reloadMovieNfo(movieId.value)
    const applied = (res && res.applied_fields) || []
    ElMessage.success(`已从 NFO 重新导入 ${applied.length} 个字段`)
    await load()
  } catch (e) {
    ElMessage.error(`失败: ${e?.response?.data?.detail || e?.message}`)
  } finally { reloadingNfo.value = false }
}

/* ---- 编辑弹窗 ---- */
const editDialogVisible = ref(false)
const saving = ref(false)
const syncNfoEnabled = ref(true)
const editForm = ref(null)

const openEditDialog = () => {
  const m = movie.value
  if (!m) return
  const _arr = (v) => {
    if (v == null) return []
    if (Array.isArray(v)) return v
    if (typeof v === 'string') {
      try { const p = JSON.parse(v); if (Array.isArray(p)) return p } catch {}
      return v.split(',').map(s => s.trim()).filter(Boolean)
    }
    return []
  }
  editForm.value = {
    code: m.code || '',
    title: m.title || '',
    original_title: m.original_title || '',
    title_jp: m.title_jp || '',
    release_date: m.release_date || '',
    duration: m.duration ?? 0,
    rating: m.rating ?? 0,
    director: m.director || '',
    maker: m.maker || '',
    studio: m.studio || '',
    series: m.series || '',
    genre_str: _arr(m.genre).join(', '),
    tag_str: _arr(m.tag).join(', '),
    actors_str: (m.actors || []).map(a => a.name).join(', '),
    plot: m.plot || '',
    plot_short: m.plot_short || '',
    file_path: m.file_path || '',
    is_mosaic: !!m.is_mosaic,
    is_uncensored: !!m.is_uncensored,
    is_chinese: !!m.is_chinese,
    is_leak: !!m.is_leak,
  }
  editDialogVisible.value = true
}

const onEditDialogClosed = () => { editForm.value = null }

const saveEdit = async () => {
  saving.value = true
  try {
    const f = editForm.value
    if (!f) return
    const body = {
      code: f.code,
      title: f.title || null,
      original_title: f.original_title || null,
      title_jp: f.title_jp || null,
      release_date: f.release_date || null,
      duration: f.duration || null,
      rating: f.rating || null,
      director: f.director || null,
      maker: f.maker || null,
      studio: f.studio || null,
      series: f.series || null,
      genre: f.genre_str || null,
      tag: f.tag_str || null,
      actors: f.actors_str || null,
      plot: f.plot || null,
      plot_short: f.plot_short || null,
      file_path: f.file_path || null,
      is_mosaic: f.is_mosaic,
      is_uncensored: f.is_uncensored,
      is_chinese: f.is_chinese,
      is_leak: f.is_leak,
    }
    if (syncNfoEnabled.value) body.sync_nfo = true
    await updateMovie(movieId.value, body)
    ElMessage.success('保存成功')
    editDialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(`保存失败: ${e?.response?.data?.detail || e?.message}`)
  } finally { saving.value = false }
}

onMounted(() => { load() })
</script>

<style scoped>
.movie-detail { max-width: 1200px; margin: 0 auto; padding: 12px 16px 32px; }

.top-bar { margin-bottom: 8px; }

/* ---- 标题置顶 ---- */
.hero-title { margin-bottom: 20px; padding: 20px 0 16px; border-bottom: 2px solid var(--el-border-color-light); }
.hero-h1 { margin: 0; font-size: 24px; font-weight: 700; line-height: 1.4; color: var(--el-text-color-primary); display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
.hero-code { color: var(--el-color-primary); font-family: 'Courier New', monospace; letter-spacing: 1px; }
.hero-divider { color: var(--el-text-color-secondary); }
.hero-text { font-weight: 400; }
.hero-subtitle { margin-top: 6px; font-size: 14px; color: var(--el-text-color-secondary); display: flex; gap: 12px; }
.jp-title { font-family: 'Yu Gothic', 'Hiragino Kaku Gothic ProN', sans-serif; }

.detail-main { display: flex; gap: 24px; margin-bottom: 24px; }
.cover-col { flex: 0 0 320px; }
.cover-wrap { position: relative; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,.12); aspect-ratio: 2/3; background: var(--el-bg-color-page); }
.cover-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
.info-col { flex: 1; min-width: 0; }

.meta-list { display: grid; grid-template-columns: 72px 1fr; gap: 10px 12px; margin: 0 0 16px; }
.meta-list dt { font-weight: 600; color: var(--el-text-color-regular); font-size: 14px; }
.meta-list dd { margin: 0; color: var(--el-text-color-primary); font-size: 14px; line-height: 1.6; }

.link-val { color: var(--el-color-primary); cursor: pointer; transition: opacity .2s; }
.link-val:hover { opacity: .75; text-decoration: underline; }
.link-tag { display: inline-block; margin: 2px 4px 2px 0; padding: 2px 10px; border-radius: 4px; font-size: 12px; cursor: pointer; text-decoration: none; transition: opacity .2s; white-space: nowrap; }
.link-tag:hover { opacity: .75; }
.genre-link { background: var(--el-color-info-light-9); color: var(--el-color-info); border: 1px solid var(--el-color-info-light-5); }
.tag-link { background: var(--el-color-success-light-9); color: var(--el-color-success); border: 1px solid var(--el-color-success-light-5); }

.actor-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.actor-link { color: var(--el-color-primary); cursor: pointer; font-size: 14px; transition: opacity .2s; }
.actor-link:hover { opacity: .75; text-decoration: underline; }
.actor-link + .actor-link::before { content: '·'; margin-right: 6px; color: var(--el-text-color-disabled); cursor: default; text-decoration: none; }

.code-parts { display: inline-flex; align-items: baseline; gap: 0; }
.stars { color: #e6a23c; letter-spacing: 1px; }
.rating-num { color: var(--el-text-color-secondary); font-size: 13px; margin-left: 6px; }

.play-box { display: inline-flex; align-items: center; gap: 8px; padding: 10px 28px; background: var(--el-color-primary); color: #fff; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: 600; transition: opacity .2s; margin-top: 8px; }
.play-box:hover { opacity: .85; }
.play-icon { font-size: 22px; }

.preview-section, .plot-section, .related-section { margin-bottom: 24px; }
.sec-title { font-size: 18px; font-weight: 700; margin: 0 0 12px; padding-bottom: 8px; border-bottom: 2px solid var(--el-color-primary); color: var(--el-text-color-primary); }

.preview-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.preview-item { border-radius: 6px; overflow: hidden; aspect-ratio: 16/10; background: var(--el-bg-color-page); }
.preview-item :deep(.el-image) { width: 100%; height: 100%; }
.preview-error, .preview-loading { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--el-text-color-disabled); }

.plot-text { font-size: 14px; line-height: 1.8; color: var(--el-text-color-regular); }

.actions-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 24px; padding: 12px; background: var(--el-bg-color-page); border-radius: 8px; }

/* ---- 推荐区 ---- */
.related-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
.related-card { cursor: pointer; border-radius: 8px; overflow: hidden; transition: transform .2s, box-shadow .2s; background: var(--el-bg-color-page); }
.related-card:hover { transform: translateY(-3px); box-shadow: 0 6px 16px rgba(0,0,0,.15); }
.related-cover { aspect-ratio: 2/3; overflow: hidden; background: var(--el-fill-color); }
.related-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.related-info { padding: 6px 8px; }
.related-code { font-size: 12px; font-weight: 700; color: var(--el-color-primary); display: block; }
.related-title { font-size: 12px; color: var(--el-text-color-regular); display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 2px; }

/* 响应式 */
@media (max-width: 768px) {
  .detail-main { flex-direction: column; }
  .cover-col { flex: none; max-width: 240px; margin: 0 auto; }
  .hero-h1 { font-size: 18px; }
  .related-grid { grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); }
}
</style>
