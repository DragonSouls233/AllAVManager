<template>
  <div class="movie-detail" v-loading="loading">
    <div class="top-bar">
      <el-button text @click="router.back()">
        <el-icon><ArrowLeft /></el-icon> 返回
      </el-button>
    </div>

    <!-- 标题置顶 -->
    <div class="hero-title" v-if="movie">
      <h1 class="hero-h1">
        <span class="hero-code" v-if="showCode && movie.code">{{ movie.code }}</span>
        <span class="hero-divider" v-if="showCode && movie.code && movie.title">—</span>
        <span class="hero-text">{{ movie.title }}</span>
      </h1>
      <div class="hero-subtitle" v-if="movie.original_title || movie.title_jp">
        <span v-if="movie.original_title">{{ movie.original_title }}</span>
        <span v-if="movie.title_jp" class="jp-title">{{ movie.title_jp }}</span>
      </div>
    </div>

    <!-- 主区域 -->
    <div class="detail-main" v-if="movie">
      <div class="cover-col">
        <div class="cover-wrap">
          <img :src="coverUrl" :alt="movie.code" @error="onCoverError" />
        </div>
      </div>

      <div class="info-col">
        <dl class="meta-list">
          <template v-if="showCode">
            <dt>番号</dt>
            <dd>
              <span class="code-parts">
                <a class="link-val" @click="goFilteredList('search', codePrefix)">{{ codePrefix }}</a>
                <span v-if="codeSuffix">-{{ codeSuffix }}</span>
              </span>
            </dd>
          </template>

          <template v-if="moduleType === 'chinese'">
            <dt>演员</dt>
            <dd>
              <div class="actor-chips">
                <span v-for="a in actorList" :key="a" class="link-val" @click="goActorSearch(a)">{{ a }}</span>
                <span v-if="!actorList.length">-</span>
              </div>
            </dd>
          </template>

          <dt>日期</dt><dd>{{ movie.release_date || '-' }}</dd>
          <dt>时长</dt><dd>{{ fmtDuration(movie.duration) }}</dd>

          <dt v-if="movie.director">导演</dt>
          <dd v-if="movie.director">
            <span class="link-val" @click="goFilteredList('maker', movie.director)">{{ movie.director }}</span>
          </dd>

          <dt>片商</dt>
          <dd>
            <span v-if="movie.maker || movie.studio" class="link-val" @click="goFilteredList('maker', movie.maker || movie.studio)">
              {{ movie.maker || movie.studio }}
            </span>
            <span v-else>-</span>
          </dd>

          <dt v-if="movie.series">系列</dt>
          <dd v-if="movie.series">
            <span class="link-val" @click="goFilteredList('series', movie.series)">{{ movie.series }}</span>
          </dd>

          <dt>评分</dt><dd>
            <template v-if="movie.rating">
              <span class="stars">★{{ starDisplay(movie.rating) }}☆</span>
              <span class="rating-num">{{ Number(movie.rating).toFixed(1) }}分</span>
            </template>
            <span v-else>-</span>
          </dd>

          <dt>类别</dt><dd>
            <a v-for="(g, idx) in displayGenres" :key="idx" class="link-tag genre-link" @click="goFilteredList('search', g)">{{ g }}</a>
            <span v-if="!displayGenres.length">-</span>
          </dd>

          <dt v-if="displayTags.length">标签</dt>
          <dd v-if="displayTags.length">
            <a v-for="(t, idx) in displayTags" :key="idx" class="link-tag tag-link" @click="goFilteredList('tag_id', t.id)">{{ t.name }}</a>
          </dd>

          <template v-if="moduleType !== 'chinese'">
            <dt>演员</dt>
            <dd>
              <div class="actor-chips">
                <span v-for="a in actorList" :key="a.id || a" class="actor-link link-val" @click="goActor(a.id || a)">{{ a.name || a }}</span>
                <span v-if="!actorList.length">-</span>
              </div>
            </dd>
          </template>
        </dl>

        <!-- 播放按钮 -->
        <div class="play-box" v-if="movie.file_path" @click="play">
          <el-icon class="play-icon"><VideoPlay /></el-icon>
          <span>播放</span>
        </div>
      </div>
    </div>

    <!-- 内容简介 -->
    <section class="plot-section" v-if="movie && movie.plot">
      <h3 class="sec-title">简介</h3>
      <div class="plot-text">{{ movie.plot }}</div>
    </section>

    <!-- 预览：第一张为封面，后续为本地剧照 -->
    <section class="preview-section" v-if="movie">
      <h3 class="sec-title">
        <span>预览</span>
        <span class="sec-meta" v-if="previewMeta">{{ previewMeta }}</span>
        <el-button class="sec-action" text size="small" :loading="previewLoading" @click="loadPreviews(true)">
          <el-icon><Refresh /></el-icon> 重新扫描
        </el-button>
      </h3>

      <div v-if="previewLoading && !gallery.length" class="preview-skeleton">
        <div v-for="n in 6" :key="n" class="skeleton-item" />
      </div>

      <div v-else-if="gallery.length" class="preview-grid">
        <div
          v-for="(item, idx) in gallery"
          :key="item.src"
          class="preview-item"
          :class="{ 'is-cover': item.isCover }"
        >
          <el-image
            :src="item.src"
            fit="cover"
            :preview-src-list="previewSrcList"
            :initial-index="idx"
            loading="lazy"
            hide-on-click-modal
            preview-teleported
          >
            <template #error>
              <div class="preview-error"><el-icon><PictureFilled /></el-icon></div>
            </template>
            <template #placeholder>
              <div class="preview-loading"><el-icon class="is-loading"><Loading /></el-icon></div>
            </template>
          </el-image>
          <span v-if="item.isCover" class="preview-badge">封面</span>
        </div>
      </div>

      <div v-else class="media-empty">
        <el-icon :size="32"><PictureFilled /></el-icon>
        <p v-if="previewSource === 'remote'">仅有远程外链预览图（易被防盗链拦截），建议重新刮削下载到本地</p>
        <p v-else>本地暂无预览图，请刮削该影片以下载封面与剧照</p>
      </div>
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
      <el-checkbox v-model="forceScrape" size="small" style="margin-left:4px" title="勾选后跳过缓存">强制</el-checkbox>
      <el-button @click="reloadNfo" :loading="reloadingNfo">
        <el-icon><DocumentCopy /></el-icon> 从 NFO 重新导入
      </el-button>
    </div>

    <!-- TA們還出演過 -->
    <section class="related-section" v-if="related.actor_movies.length">
      <h3 class="sec-title">TA們還出演過</h3>
      <div class="related-grid">
        <div v-for="m in related.actor_movies" :key="m.id" class="related-card" @click="goMovie(m.id)">
          <div class="related-cover"><img :src="getRelatedCover(m)" :alt="m.code" loading="lazy" /></div>
          <div class="related-info"><span class="related-code">{{ m.code }}</span><span class="related-title" :title="m.title">{{ m.title }}</span></div>
        </div>
      </div>
    </section>

    <!-- 同系列 -->
    <section class="related-section" v-if="related.series_movies.length">
      <h3 class="sec-title">同系列推薦</h3>
      <div class="related-grid">
        <div v-for="m in related.series_movies" :key="m.id" class="related-card" @click="goMovie(m.id)">
          <div class="related-cover"><img :src="getRelatedCover(m)" :alt="m.code" loading="lazy" /></div>
          <div class="related-info"><span class="related-code">{{ m.code }}</span><span class="related-title" :title="m.title">{{ m.title }}</span></div>
        </div>
      </div>
    </section>

    <!-- 同類別 -->
    <section class="related-section" v-if="related.genre_movies.length">
      <h3 class="sec-title">同類別推薦</h3>
      <div class="related-grid">
        <div v-for="m in related.genre_movies" :key="m.id" class="related-card" @click="goMovie(m.id)">
          <div class="related-cover"><img :src="getRelatedCover(m)" :alt="m.code" loading="lazy" /></div>
          <div class="related-info"><span class="related-code">{{ m.code }}</span><span class="related-title" :title="m.title">{{ m.title }}</span></div>
        </div>
      </div>
    </section>

    <!-- 编辑弹窗 -->
    <el-dialog v-model="editDialogVisible" title="编辑影片元数据" width="780px" :close-on-click-modal="false" @closed="onEditDialogClosed">
      <el-form v-if="editForm" :model="editForm" label-width="100px" label-position="right">
        <el-form-item label="番号" v-if="showCode">
          <el-input v-model="editForm.code">
            <template #append><el-tag size="small">修改需唯一</el-tag></template>
          </el-input>
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="editForm.title" /></el-form-item>
        <el-form-item label="原标题"><el-input v-model="editForm.original_title" /></el-form-item>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="发行日期"><el-input v-model="editForm.release_date" placeholder="YYYY-MM-DD" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="时长(分)"><el-input-number v-model="editForm.duration" :min="0" :max="9999" controls-position="right" style="width:100%" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="评分"><el-input-number v-model="editForm.rating" :min="0" :max="10" :step="0.1" :precision="1" controls-position="right" style="width:100%" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="导演"><el-input v-model="editForm.director" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="片商"><el-input v-model="editForm.maker" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="制作商"><el-input v-model="editForm.studio" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="系列"><el-input v-model="editForm.series" /></el-form-item>
        <el-form-item label="类别"><el-input v-model="editForm.genre_str" placeholder="逗号分隔" /></el-form-item>
        <el-form-item label="演员"><el-input v-model="editForm.actors_str" type="textarea" :rows="2" placeholder="逗号分隔" /></el-form-item>
        <el-form-item label="简介"><el-input v-model="editForm.plot" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="视频路径"><el-input v-model="editForm.file_path" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-empty v-if="!loading && !movie" description="未找到该影片" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft, VideoPlay, Star, StarFilled, MagicStick,
  PictureFilled, Loading, Edit, DocumentCopy, Refresh
} from '@element-plus/icons-vue'
import { getMovieCoverUrl, defaultCover, getFileProxyUrl, getServerBaseUrl } from '@/utils/media'
import http from '@/api'

const route = useRoute()
const router = useRouter()

// ---------- 模块检测 ----------
const MODULE_MAP = {
  'jav': 'jav', 'fc2': 'fc2', 'uncensored': 'uncensored',
  'western': 'western', 'pornhub': 'pornhub', 'chinese': 'chinese'
}
const moduleType = computed(() => {
  const seg = route.path.split('/')
  const m = seg[1]
  return MODULE_MAP[m] || 'jav'
})
const showCode = computed(() => moduleType.value !== 'chinese')
const movieId = computed(() => Number(route.params.id))

// ---------- 动态加载 API ----------
const apiRef = shallowRef(null)
async function loadApi () {
  const name = moduleType.value
  if (name === 'jav') {
    const m = await import('@/api/jav')
    apiRef.value = {
      get: m.getJavMovie,
      update: m.updateJavMovie,
      scrape: m.scrapeJavMovie ?? m.scrapeMovie,
      reloadNfo: m.reloadJavMovieNfo ?? m.reloadMovieNfo,
    }
  } else if (name === 'fc2') {
    const m = await import('@/api/fc2')
    apiRef.value = {
      get: m.getFc2Movie,
      update: m.updateFc2Movie,
      scrape: m.scrapeFc2Movie,
      reloadNfo: m.reloadFc2MovieNfo,
    }
  } else if (name === 'uncensored') {
    const m = await import('@/api/uncensored')
    apiRef.value = {
      get: m.getUncensoredMovie,
      update: m.updateUncensoredMovie,
      scrape: m.scrapeUncensoredMovie,
      reloadNfo: m.reloadUncensoredMovieNfo,
    }
  } else if (name === 'western') {
    const m = await import('@/api/western')
    apiRef.value = {
      get: m.getWesternMovie,
      update: m.updateWesternMovie,
      scrape: m.scrapeWesternMovie,
      reloadNfo: m.reloadWesternMovieNfo,
    }
  } else if (name === 'pornhub') {
    const m = await import('@/api/pornhub')
    apiRef.value = {
      get: m.getPornhubMovie,
      update: m.updatePornhubMovie,
      scrape: m.scrapePornhubMovie,
      reloadNfo: m.reloadPornhubMovieNfo,
    }
  } else if (name === 'chinese') {
    const m = await import('@/api/chinese')
    apiRef.value = {
      get: m.getChineseMovie,
      update: m.updateChineseMovie,
      scrape: m.scrapeChineseMovie,
      reloadNfo: m.reloadChineseMovieNfo,
    }
  }
}

// ---------- 数据 ----------
const movie = ref(null)
const loading = ref(false)
const scraping = ref(false)
const fav = ref(false)
const coverError = ref(false)
const related = ref({ actor_movies: [], series_movies: [], genre_movies: [] })

const codePrefix = computed(() => {
  const c = movie.value?.code || ''
  const m = c.match(/^([A-Za-z]+)-/)
  return m ? m[1] : c
})
const codeSuffix = computed(() => {
  const c = movie.value?.code || ''
  const m = c.match(/^[A-Za-z]+-(.+)/)
  return m ? m[1] : ''
})

// 演员列表：统一为数组
const actorList = computed(() => {
  const m = movie.value
  if (!m) return []
  // western 返回 actors 数组
  if (Array.isArray(m.actors)) return m.actors
  // chinese 返回 folder_based_actors
  if (Array.isArray(m.folder_based_actors)) return m.folder_based_actors
  // 其他返回 actor 逗号分隔字符串
  if (typeof m.actor === 'string' && m.actor.trim()) {
    return m.actor.split(',').map(s => ({ name: s.trim(), id: s.trim() })).filter(a => a.name)
  }
  if (typeof m.actor === 'string' && m.actor.trim()) {
    return [{ name: m.actor, id: m.actor }]
  }
  return []
})

// ---------- 封面 ----------
const hasDbCover = computed(() => {
  const m = movie.value
  if (!m) return false
  // 模块影片（有 module_type）：只要有 id，就直接走后端 /cover/file 端点
  if (m.id && m.module_type) return true
  // 主数据库影片：检查 cover_url 是否有值
  return !!(m.cover_url && typeof m.cover_url === 'string')
})
const toDisplayUrl = (s) => {
  if (!s || typeof s !== 'string') return ''
  if (/^https?:\/\//i.test(s)) return s
  return getFileProxyUrl(s)
}
const sampleImages = computed(() => {
  const arr = movie.value?.sample_images
  if (!arr || !Array.isArray(arr)) return []
  return arr.filter(s => s && typeof s === 'string' && s.trim())
})
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
const onCoverError = () => { coverError.value = true }

// ---------- 预览图（本地优先） ----------
// 后端 /api/v1/previews/{module}/{id} 会扫描
//   {data_base}/movies/{module}/{code}/extrafanart/
// 并把本地文件通过代理端点暴露出来，彻底绕开 DMM/javbus 的防盗链。
const previewLoading = ref(false)
const previewSource = ref('none')   // local | remote | none
const previewImages = ref([])       // 后端返回的图片 URL 列表
const previewCoverUrl = ref('')     // 本地主封面大图（fanart 优先）

const absUrl = (u) => {
  if (!u) return ''
  if (/^https?:\/\//i.test(u) || u.startsWith('data:')) return u
  return `${getServerBaseUrl()}${u}`
}

const loadPreviews = async (refresh = false) => {
  const mod = moduleType.value
  const id = movieId.value
  if (!mod || !id) return
  previewLoading.value = true
  try {
    const res = await http.get(`/previews/${mod}/${id}`, {
      params: refresh ? { refresh: true } : undefined,
    })
    previewSource.value = res?.source || 'none'
    previewImages.value = Array.isArray(res?.images) ? res.images : []
    previewCoverUrl.value = res?.cover || ''
    if (refresh) {
      ElMessage.success(
        previewSource.value === 'local'
          ? `已扫描到 ${previewImages.value.length} 张本地预览图`
          : '本地未找到预览图'
      )
    }
  } catch {
    // 接口不可用时回退到 DB 中的 sample_images
    previewSource.value = sampleImages.value.length ? 'remote' : 'none'
    previewImages.value = sampleImages.value.map(toDisplayUrl).filter(Boolean)
    previewCoverUrl.value = ''
  } finally {
    previewLoading.value = false
  }
}

// 画廊：第一张固定为封面，后续为预览图
const gallery = computed(() => {
  const list = []
  const seen = new Set()

  const push = (src, isCover = false) => {
    if (!src || seen.has(src)) return
    seen.add(src)
    list.push({ src, isCover })
  }

  // 1) 封面：优先本地主封面大图，否则退回模块封面端点
  if (previewCoverUrl.value) push(absUrl(previewCoverUrl.value), true)
  else if (hasDbCover.value) push(getMovieCoverUrl(movie.value), true)

  // 2) 预览图
  for (const u of previewImages.value) push(absUrl(u))

  return list
})

const previewSrcList = computed(() => gallery.value.map(i => i.src))

const previewMeta = computed(() => {
  const n = previewImages.value.length
  if (!n) return ''
  return previewSource.value === 'local' ? `本地 ${n} 张` : `远程外链 ${n} 张`
})

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
const displayTags = computed(() => {
  const tags = movie.value?.tags
  if (Array.isArray(tags) && tags.length) return tags.slice(0, 20)
  const tagStr = movie.value?.tag
  if (Array.isArray(tagStr)) return tagStr.map((t, i) => ({ id: i, name: t }))
  return []
})

// ---------- 加载 ----------
const load = async () => {
  loading.value = true
  coverError.value = false
  previewSource.value = 'none'
  previewImages.value = []
  previewCoverUrl.value = ''
  try {
    if (!apiRef.value) await loadApi()
    const api = apiRef.value
    if (!api) return
    const res = await api.get(movieId.value)
    movie.value = res
    checkFav()
    // 加载本地预览图（不阻塞主流程）
    loadPreviews()
    // 加载相关推荐：模块影片走模块自身的 /related 端点，主库走通用 /related
    try {
      const mod = moduleType.value
      if (mod && MODULE_MAP[mod]) {
        const modApi = await import(`@/api/${mod}.js`)
        if (modApi.getRelatedMovies) {
          const relData = await modApi.getRelatedMovies(movieId.value).catch(() => null)
          if (relData) related.value = relData
        }
      } else {
        const { getRelatedMovies } = await import('@/api')
        const relData = await getRelatedMovies(movieId.value).catch(() => null)
        if (relData) related.value = relData
      }
    } catch {}
  } catch {
    movie.value = null
  } finally {
    loading.value = false
  }
}

// ---------- 导航 ----------
const play = () => {
  const mod = moduleType.value
  if (mod) {
    router.push({ path: `/play/${movieId.value}`, query: { module: mod } })
  } else {
    router.push(`/play/${movieId.value}`)
  }
}
const goActor = (id) => {
  if (!id) return
  const name = moduleType.value
  router.push(`/${name}/actors/${id}`)
}
const goActorSearch = (name) => {
  if (!name) return
  router.push(`/${moduleType.value}/movies?search=${encodeURIComponent(name)}`)
}
const goMovie = (id) => router.push(`/${moduleType.value}/movies/${id}`)

const goFilteredList = (key, value) => {
  if (!value) return
  const name = moduleType.value
  const encoded = encodeURIComponent(value)
  const base = `/${name}/movies`
  switch (key) {
    case 'maker': router.push(`${base}?maker=${encoded}`); break
    case 'series': router.push(`${base}?series=${encoded}`); break
    case 'tag_id': router.push(`${base}?tag_ids=${value}`); break
    case 'search': router.push(`${base}?search=${encoded}`); break
    default: router.push(`${base}?${key}=${encoded}`)
  }
}

const getRelatedCover = (m) => getMovieCoverUrl(m)

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

// ---------- 收藏 ----------
const checkFav = async () => {
  try {
    const { checkFavorite } = await import('@/api')
    const check = await checkFavorite('movie', movieId.value)
    const data = check.items ? check : (check.data || check)
    fav.value = data.in_favorites || false
  } catch { fav.value = false }
}
const toggleFav = async () => {
  try {
    const { checkFavorite, addFavoriteItem, removeFavoriteItem, getFavoriteGroups } = await import('@/api')
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

// ---------- 刮削 ----------
const forceScrape = ref(false)
const scrape = async () => {
  scraping.value = true
  try {
    const api = apiRef.value
    if (api?.scrape) {
      await api.scrape(movieId.value, forceScrape.value)
    }
    ElMessage.success('刮削完成')
    await load()
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message
    if (msg) ElMessage.error(msg)
  } finally { scraping.value = false }
}

const reloadingNfo = ref(false)
const reloadNfo = async () => {
  reloadingNfo.value = true
  try {
    const api = apiRef.value
    if (api?.reloadNfo) {
      const res = await api.reloadNfo(movieId.value)
      const applied = (res?.applied_fields) || []
      ElMessage.success(`已从 NFO 导入 ${applied.length} 个字段`)
      await load()
    }
  } catch (e) {
    ElMessage.error(`失败: ${e?.response?.data?.detail || e?.message}`)
  } finally { reloadingNfo.value = false }
}

// ---------- 编辑 ----------
const editDialogVisible = ref(false)
const saving = ref(false)
const editForm = ref(null)

const openEditDialog = () => {
  const m = movie.value
  if (!m) return
  editForm.value = {
    code: m.code || '',
    title: m.title || '',
    original_title: m.original_title || '',
    release_date: m.release_date || '',
    duration: m.duration ?? 0,
    rating: m.rating ?? 0,
    director: m.director || '',
    maker: m.maker || '',
    studio: m.studio || '',
    series: m.series || '',
    genre_str: Array.isArray(m.genre) ? m.genre.join(', ') : (m.genre || ''),
    actors_str: actorList.value.map(a => a.name || a).join(', '),
    plot: m.plot || '',
    file_path: m.file_path || '',
  }
  editDialogVisible.value = true
}
const onEditDialogClosed = () => { editForm.value = null }

const saveEdit = async () => {
  saving.value = true
  try {
    const f = editForm.value
    if (!f) return
    const api = apiRef.value
    if (!api?.update) return
    await api.update(movieId.value, {
      code: f.code, title: f.title || null,
      original_title: f.original_title || null,
      release_date: f.release_date || null,
      duration: f.duration || null,
      rating: f.rating || null,
      director: f.director || null,
      maker: f.maker || null,
      studio: f.studio || null,
      series: f.series || null,
      genre: f.genre_str || null,
      actors: f.actors_str || null,
      plot: f.plot || null,
      file_path: f.file_path || null,
    })
    ElMessage.success('保存成功')
    editDialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(`保存失败: ${e?.response?.data?.detail || e?.message}`)
  } finally { saving.value = false }
}

// 路由参数变化时重新加载（Vue Router 复用了同一组件实例）
watch(movieId, () => { load() })
// 模块切换时重置 API 缓存，确保 loadApi 加载正确的模块接口
watch(moduleType, () => { apiRef.value = null })

onMounted(() => { load() })
</script>

<style scoped>
.movie-detail { max-width: 1200px; margin: 0 auto; padding: 12px 16px 32px; }
.top-bar { margin-bottom: 8px; }
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
.link-tag { display: inline-block; margin: 2px 4px 2px 0; padding: 2px 10px; border-radius: 4px; font-size: 12px; cursor: pointer; transition: opacity .2s; white-space: nowrap; }
.link-tag:hover { opacity: .75; }
.genre-link { background: var(--el-color-info-light-9); color: var(--el-color-info); border: 1px solid var(--el-color-info-light-5); }
.tag-link { background: var(--el-color-success-light-9); color: var(--el-color-success); border: 1px solid var(--el-color-success-light-5); }
.actor-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.actor-link { color: var(--el-color-primary); cursor: pointer; font-size: 14px; }
.actor-link:hover { opacity: .75; text-decoration: underline; }
.actor-link + .actor-link::before { content: '·'; margin-right: 6px; color: var(--el-text-color-disabled); cursor: default; text-decoration: none; }
.code-parts { display: inline-flex; align-items: baseline; gap: 0; }
.stars { color: #e6a23c; letter-spacing: 1px; }
.rating-num { color: var(--el-text-color-secondary); font-size: 13px; margin-left: 6px; }
.play-box { display: inline-flex; align-items: center; gap: 8px; padding: 10px 28px; background: var(--el-color-primary); color: #fff; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: 600; transition: opacity .2s; margin-top: 8px; }
.play-box:hover { opacity: .85; }
.play-icon { font-size: 22px; }
.preview-section, .plot-section, .related-section { margin-bottom: 24px; }
.sec-title { display: flex; align-items: center; gap: 10px; font-size: 18px; font-weight: 700; margin: 0 0 12px; padding-bottom: 8px; border-bottom: 2px solid var(--el-color-primary); color: var(--el-text-color-primary); }
.sec-meta { font-size: 12px; font-weight: 500; color: var(--el-text-color-secondary); padding: 2px 8px; border-radius: 10px; background: var(--el-fill-color-light); }
.sec-action { margin-left: auto; font-weight: 500; }

/* 预览网格：第一张封面跨两列突出显示 */
.preview-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
.preview-item {
  position: relative; border-radius: 8px; overflow: hidden; aspect-ratio: 16/10;
  background: var(--el-fill-color-light); cursor: zoom-in;
  transition: transform .3s cubic-bezier(.16,1,.3,1), box-shadow .3s cubic-bezier(.16,1,.3,1);
}
.preview-item:hover { transform: translateY(-3px) scale(1.015); box-shadow: 0 10px 24px rgba(0,0,0,.18); z-index: 2; }
.preview-item.is-cover { grid-column: span 2; grid-row: span 2; aspect-ratio: 16/10; outline: 2px solid var(--el-color-primary); outline-offset: -2px; }
.preview-item :deep(.el-image) { width: 100%; height: 100%; display: block; }
.preview-item :deep(.el-image__inner) { transition: transform .4s cubic-bezier(.16,1,.3,1); }
.preview-item:hover :deep(.el-image__inner) { transform: scale(1.04); }
.preview-badge {
  position: absolute; left: 8px; top: 8px; z-index: 3;
  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; letter-spacing: .5px;
  color: #fff; background: var(--el-color-primary); box-shadow: 0 2px 6px rgba(0,0,0,.25);
}
.preview-error, .preview-loading { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--el-text-color-disabled); }

/* 骨架屏 */
.preview-skeleton { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
.skeleton-item { aspect-ratio: 16/10; border-radius: 8px; background: linear-gradient(90deg, var(--el-fill-color-light) 25%, var(--el-fill-color) 37%, var(--el-fill-color-light) 63%); background-size: 400% 100%; animation: sk 1.4s ease infinite; }
@keyframes sk { 0% { background-position: 100% 50% } 100% { background-position: 0 50% } }

/* 空状态 */
.media-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding: 40px 16px; border: 1px dashed var(--el-border-color); border-radius: 8px; color: var(--el-text-color-secondary); background: var(--el-fill-color-lighter); }
.media-empty p { margin: 0; font-size: 13px; }
.plot-text { font-size: 14px; line-height: 1.8; color: var(--el-text-color-regular); }
.actions-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 24px; padding: 12px; background: var(--el-bg-color-page); border-radius: 8px; }
.related-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
.related-card { cursor: pointer; border-radius: 8px; overflow: hidden; transition: transform .2s, box-shadow .2s; background: var(--el-bg-color-page); }
.related-card:hover { transform: translateY(-3px); box-shadow: 0 6px 16px rgba(0,0,0,.15); }
.related-cover { aspect-ratio: 2/3; overflow: hidden; background: var(--el-fill-color); }
.related-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.related-info { padding: 6px 8px; }
.related-code { font-size: 12px; font-weight: 700; color: var(--el-color-primary); display: block; }
.related-title { font-size: 12px; color: var(--el-text-color-regular); display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 2px; }
@media (max-width: 768px) {
  .detail-main { flex-direction: column; }
  .cover-col { flex: none; max-width: 240px; margin: 0 auto; }
  .hero-h1 { font-size: 18px; }
  .related-grid { grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); }
  .preview-grid, .preview-skeleton { grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .preview-item.is-cover { grid-column: span 2; grid-row: auto; }
  .preview-item:hover { transform: none; box-shadow: none; }
}
</style>
