<template>
  <section v-if="!loading && !error" class="cinema-page md-detail">
    <!-- 主信息卡 -->
    <div class="md-hero">
      <div class="md-cover-wrap">
        <img v-if="cover" v-cover-fit="COVER_AR.poster" class="md-cover" :src="cover" :alt="code" />
        <div v-else class="md-cover-empty">
          <el-icon><Picture /></el-icon>
        </div>
        <div v-if="viewStatus" class="md-status-ribbon" :class="`st-${viewStatus}`">
          {{ statusText }}
        </div>
      </div>

      <div class="md-info">
        <div class="md-title-row">
          <h1 class="md-title">{{ title }}</h1>
          <span class="md-code">{{ code }}</span>
        </div>

        <!-- 版本角标（无码/中文/破解/4K） -->
        <div v-if="badges.length" class="md-badges">
          <el-tag
            v-for="b in badges"
            :key="b.text"
            size="small"
            :type="badgeColor(b.type)"
            effect="dark"
            disable-transitions
          >{{ b.text }}</el-tag>
        </div>

        <!-- 元数据行 -->
        <dl class="md-meta">
          <template v-if="movie.release_date">
            <dt>发行</dt><dd>{{ String(movie.release_date).slice(0, 10) }}</dd>
          </template>
          <template v-if="movie.duration">
            <dt>时长</dt><dd>{{ fmtDuration(movie.duration) }}</dd>
          </template>
          <template v-if="movie.rating">
            <dt>评分</dt><dd class="md-rating">★ {{ Number(movie.rating).toFixed(1) }}</dd>
          </template>
          <template v-if="movie.maker || movie.studio">
            <dt>制作商</dt><dd>{{ movie.studio || movie.maker }}</dd>
          </template>
          <template v-if="movie.series">
            <dt>系列</dt>
            <dd class="md-link" @click="jumpSeries">{{ movie.series }}</dd>
          </template>
          <template v-if="movie.director">
            <dt>导演</dt><dd>{{ movie.director }}</dd>
          </template>
          <template v-if="movie.file_size">
            <dt>大小</dt><dd>{{ fmtBytes(movie.file_size) }}</dd>
          </template>
          <template v-if="movie.play_count">
            <dt>播放</dt><dd>{{ movie.play_count }} 次</dd>
          </template>
          <template v-if="lastPlay">
            <dt>上次</dt><dd class="md-link" @click="resumePlay">看到 {{ fmtPos(lastPlay) }}</dd>
          </template>
        </dl>

        <!-- 操作行 -->
        <div class="md-actions">
          <button class="md-btn primary" @click="playFrom(lastPlay ? lastPlay.position : 0)">
            <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
            <span v-if="lastPlay">继续播放 · {{ fmtPos(lastPlay) }}</span>
            <span v-else>播放</span>
          </button>
          <button v-if="lastPlay" class="md-btn" title="从头开始" @click="playFrom(0)">从头播放</button>

          <!-- 三态标记 -->
          <div class="md-mark" role="group">
            <button
              class="md-mark-btn"
              :class="{ on: viewStatus === 'wanted' }"
              title="想看"
              @click="cycleStatus('wanted')"
            >
              <svg viewBox="0 0 24 24"><path d="M12 17.3 5.8 21l1.6-7L2 9.2l7.2-.6L12 2l2.8 6.6 7.2.6-5.4 4.8 1.6 7z" /></svg>
              <span>想看</span>
            </button>
            <button
              class="md-mark-btn"
              :class="{ on: viewStatus === 'watched' }"
              title="标记为已看"
              @click="cycleStatus('watched')"
            >
              <svg viewBox="0 0 24 24"><path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z" /></svg>
              <span>已看</span>
            </button>
            <button
              v-if="viewStatus"
              class="md-mark-btn ghost"
              title="清除标记"
              @click="clearStatus"
            >
              <span>清除</span>
            </button>
          </div>
        </div>

        <!-- 类别 -->
        <div v-if="genreList.length" class="md-chips">
          <span class="md-chip-label">类别</span>
          <button
            v-for="g in genreList"
            :key="g"
            class="md-chip"
            @click="jumpGenre(g)"
          >{{ g }}</button>
        </div>
      </div>
    </div>

    <!-- 演员行 -->
    <div v-if="actorNames.length" class="md-actors">
      <div class="md-section-title">演员</div>
      <div class="md-actor-grid">
        <button v-for="a in actorNames" :key="a" class="md-actor" @click="jumpActor(a)">
          <img :src="actorAvatar(a)" alt="" @error="onActorImgError($event)" />
          <span>{{ a }}</span>
        </button>
      </div>
    </div>

    <!-- 简介 -->
    <div class="md-block">
      <div class="md-section-title">简介</div>
      <p v-if="plot" class="md-plot">{{ plot }}</p>
      <p v-else class="md-plot muted">暂无简介（可在 Web 管理端补全后刷新）</p>
    </div>

    <!-- 预览图 -->
    <div v-if="samples.length" class="md-block">
      <div class="md-section-title">预览</div>
      <div class="md-samples">
        <img v-for="(s, i) in samples" :key="i" :src="s" alt="" loading="lazy" />
      </div>
    </div>

    <!-- 相关推荐 -->
    <div v-if="hasRelated" class="md-block">
      <template v-for="sec in relatedSections" :key="sec.key">
        <div v-if="sec.items.length" class="md-related">
          <div class="md-section-title">{{ sec.title }}</div>
          <div class="md-related-scroll">
            <PosterCard
              v-for="m in sec.items"
              :key="`${sec.key}-${m.id}`"
              :movie="m"
              @open="goDetail"
              @play="goPlay"
            />
          </div>
        </div>
      </template>
    </div>
  </section>

  <!-- 骨架 -->
  <section v-else-if="loading" class="cinema-page">
    <div class="md-skeleton-cover" />
    <div class="md-skeleton-block">
      <div class="md-skeleton-line" style="width: 45%" />
      <div class="md-skeleton-line" style="width: 70%" />
      <div class="md-skeleton-line" style="width: 30%" />
    </div>
  </section>

  <!-- 错误/不存在 -->
  <section v-else class="cinema-page">
    <div class="cinema-empty">
      <div class="cinema-empty-icon">🎬</div>
      <div class="cinema-empty-text">{{ error }}</div>
      <el-button size="small" style="margin-top: 12px" @click="load">重试</el-button>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Picture } from '@element-plus/icons-vue'
import PosterCard from '@/components/cinema/PosterCard.vue'
import { useLibraryStore } from '@/stores/library'
import { getServerBaseUrl, getCoverSrc, defaultAvatar, getMovieVersionBadges } from '@/utils/media'
import { normMedia, decorateMovies } from '@/utils/browse'
import {
  getModuleMovie, getModuleRelated, getMovieViewStatus, setMovieViewStatus,
  getViewingHistory
} from '@/api'
import { getAnimeMovie, getAnimeSeriesMovies, getAnimeMovies } from '@/api/anime'
import { vCoverFit, COVER_AR } from '@/utils/coverFit'

const route = useRoute()
const router = useRouter()
const lib = useLibraryStore()

const module = computed(() => String(route.params.module || 'jav'))
const movieId = computed(() => Number(route.params.id))

const loading = ref(true)
const error = ref('')
const movie = ref(null)
const related = ref({ actor_movies: [], series_movies: [], genre_movies: [], maker_movies: [] })
const viewStatus = ref('')
const lastPlay = ref(null) // { position, progress, played_at, duration }

const code = computed(() => movie.value?.code || '')
const title = computed(() => movie.value?.title || movie.value?.code || '未命名')
const badges = computed(() => getMovieVersionBadges(movie.value))
const plot = computed(() => movie.value?.plot_short || movie.value?.plot || '')
const actorNames = computed(() => {
  const fromText = Array.isArray(movie.value?.actor_names) ? movie.value.actor_names : []
  const fromJoin = (movie.value?.actors || []).map((a) => a.name).filter(Boolean)
  const seen = new Set()
  const out = []
  for (const n of [...fromText, ...fromJoin]) {
    if (n && !seen.has(n)) { seen.add(n); out.push(n) }
  }
  return out.slice(0, 12)
})
const genreList = computed(() => Array.isArray(movie.value?.genre) ? movie.value.genre : [])
const samples = computed(() => {
  const raw = Array.isArray(movie.value?.sample_images) ? movie.value.sample_images : []
  return raw.map((s) => normMedia(s)).filter(Boolean)
})
const cover = computed(() => {
  if (!movie.value) return ''
  const decorated = decorateMovies([movie.value], module.value)[0]
  // 通用 /movies/{id} 返回的 cover_url 可直接用；优先 getCoverSrc 走模块封面白名单端点
  return getCoverSrc(decorated) || ''
})
const statusText = computed(() => ({ watched: '已看', wanted: '想看', browsed: '看过' })[viewStatus.value] || '')

const relatedSections = computed(() => {
  const decorate = (list) => decorateMovies(list || [], module.value)
  return [
    { key: 'actor', title: '同演员作品', items: decorate(related.value.actor_movies) },
    { key: 'series', title: '同系列', items: decorate(related.value.series_movies) },
    { key: 'genre', title: '同类别', items: decorate(related.value.genre_movies) },
    { key: 'maker', title: '同制作商', items: decorate(related.value.maker_movies) }
  ]
})
const hasRelated = computed(() =>
  ['actor_movies', 'series_movies', 'genre_movies', 'maker_movies'].some((k) => related.value[k]?.length)
)

function badgeColor(type) {
  return { chinese: 'danger', leak: 'danger', uncensored: 'warning', uc: 'warning', '4k': 'success' }[type] || 'info'
}

function fmtDuration(sec) {
  if (!sec) return ''
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return h ? `${h}h ${m}m` : `${m}m`
}

function fmtBytes(n) {
  const v = Number(n) || 0
  if (v >= 1 << 30) return `${(v / (1 << 30)).toFixed(1)} GB`
  if (v >= 1 << 20) return `${(v / (1 << 20)).toFixed(0)} MB`
  return `${Math.round(v / 1024)} KB`
}

function fmtPos(rec) {
  const p = Number(rec.position || 0)
  const h = Math.floor(p / 3600)
  const m = Math.floor((p % 3600) / 60)
  const s = Math.floor(p % 60)
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h ? `${h}:${mm}:${ss}` : `${m}:${ss}`
}

function actorAvatar(name) {
  // 演员头像需 actor_id；文本名场景仅能显示名字占位图，避免错误 id 撞图
  const joined = (movie.value?.actors || []).find((a) => a.name === name)
  if (joined?.id && joined.id > 0) {
    return `${getServerBaseUrl()}/api/v1/modules/${module.value}/actors/${joined.id}/avatar/file`
  }
  return defaultAvatar(name)
}

function onActorImgError(e) {
  e.target.src = defaultAvatar()
}

/* ===== 播放 / 续播 ===== */
function playFrom(start) {
  router.push({ path: `/mpv/${module.value}/${movieId.value}`, query: { start } })
}

function resumePlay() {
  playFrom(lastPlay.value?.position || 0)
}

/* ===== 三态标记 ===== */
async function cycleStatus(next) {
  // 点已选中的状态 = 取消
  const target = viewStatus.value === next ? null : next
  try {
    await setMovieViewStatus(movieId.value, target, module.value)
    viewStatus.value = target || ''
  } catch (e) {
    // 静默失败：保持原状态（如服务器旧版无该模块支持）
  }
}

async function clearStatus() {
  await cycleStatus(viewStatus.value)
}

/* ===== 跳转 ===== */
function jumpActor(name) {
  lib.setModule(module.value)
  lib.applyFilter({ actor: name })
  router.push('/library')
}

function jumpGenre(genre) {
  lib.setModule(module.value)
  lib.applyFilter({ genre })
  router.push('/library')
}

function jumpSeries() {
  lib.setModule(module.value)
  lib.applyFilter({ series: movie.value?.series })
  router.push('/library')
}

function goDetail(m) {
  const mod = m.module_type || module.value
  router.push(`/movie/${mod}/${m.id}`)
}

function goPlay(m) {
  const mod = m.module_type || module.value
  router.push(`/mpv/${mod}/${m.id}`)
}

/* ===== 数据加载 ===== */
// anime 独立 DB/路由：genre 列是 JSON 数组字符串，actor 是逗号分隔文本 → 与通用端点同口径解析
function parseGenreField(raw) {
  if (Array.isArray(raw)) return raw.map((x) => String(x).trim()).filter(Boolean)
  if (raw == null || raw === '') return []
  const s = String(raw).trim()
  if (s.startsWith('[')) {
    try {
      const arr = JSON.parse(s)
      if (Array.isArray(arr)) return arr.map((x) => String(x).trim()).filter(Boolean)
    } catch (e) { /* 落入分隔符解析 */ }
  }
  return s.split(/[,，、|;；]/).map((x) => x.trim()).filter(Boolean)
}

function parseActorField(raw) {
  if (Array.isArray(raw)) return raw.map((x) => String(x).trim()).filter(Boolean)
  if (raw == null || raw === '') return []
  return String(raw).split(/[,，、/|;；\n]/).map((x) => x.trim()).filter(Boolean)
}

// anime 无通用 related 端点：优先同系列集数列表；该系列只有当前 1 部时回退同制作商新作
async function loadAnimeRelated(mv) {
  const out = { actor_movies: [], series_movies: [], genre_movies: [], maker_movies: [] }
  try {
    if (mv?.series_id) {
      const res = await getAnimeSeriesMovies(mv.series_id).catch(() => null)
      const sibs = (res?.items || []).filter((x) => x.id !== mv.id)
      if (sibs.length) {
        out.series_movies = sibs.slice(0, 60)
        return out
      }
    }
    if (mv?.maker) {
      const r = await getAnimeMovies({ maker: mv.maker, limit: 25 }).catch(() => null)
      out.maker_movies = (r?.items || []).filter((x) => x.id !== mv.id).slice(0, 24)
    }
  } catch (e) { /* 忽略：无推荐也不影响详情 */ }
  return out
}

async function load() {
  loading.value = true
  error.value = ''
  const mod = module.value
  const id = movieId.value
  try {
    // anime 是独立 DB + 独立 /anime/* 路由，走专用端点；其余模块走通用 /movies/{id}?module=
    let mv = null
    let rel = null
    if (mod === 'anime') {
      mv = await getAnimeMovie(id).catch(() => null)
      if (mv) {
        mv.module_type = 'anime'
        if (!Array.isArray(mv.genre)) mv.genre = parseGenreField(mv.genre)
        if (!Array.isArray(mv.actor_names)) mv.actor_names = parseActorField(mv.actor_names ?? mv.actor)
        rel = await loadAnimeRelated(mv)
      }
    } else {
      const [m, r] = await Promise.all([
        getModuleMovie(id, mod).catch(() => null),
        getModuleRelated(id, mod).catch(() => null)
      ])
      mv = m
      rel = r
    }

    movie.value = mv || null
    if (!mv) {
      error.value = '影片不存在或已被移除'
      return
    }
    // 通用详情端点返回的模块影片，补 module_type 供 getCoverSrc 拼封面
    if (!movie.value.module_type) movie.value.module_type = mod
    related.value = { actor_movies: [], series_movies: [], genre_movies: [], maker_movies: [], ...(rel || {}) }

    const [vs, hist] = await Promise.all([
      getMovieViewStatus(id, mod).catch(() => null),
      getViewingHistory({ movie_id: id, module: mod, limit: 1 }).catch(() => null)
    ])
    viewStatus.value = vs?.view_status || ''

    // 续播点：取最近一次「未看完」的进度
    const recs = hist?.items || []
    const r = recs.find((x) => !x.completed && x.progress > 0.02 && x.progress < 0.98)
    if (r) {
      const totalSec = movie.value?.duration || r.total_duration || 0
      lastPlay.value = {
        position: r.duration_watched || Math.round((r.progress || 0) * totalSec),
        progress: r.progress || 0,
        played_at: r.played_at || null
      }
    }
  } catch (e) {
    error.value = e?.response?.status === 401 ? '登录已失效，请重新登录' : '加载详情失败，请检查服务器连接'
  } finally {
    loading.value = false
  }
}

// 详情页内点相关推荐/同系列集数会变路由参数而不重建组件 → watch 重新加载
watch([module, movieId], () => { load() })

load()
</script>

<style scoped>
.md-detail {
  padding-bottom: 48px;
}

/* ===== Hero ===== */
.md-hero {
  display: flex;
  gap: 22px;
  margin-bottom: 26px;
}

.md-cover-wrap {
  position: relative;
  flex: 0 0 228px;
  width: 228px;
  /* 承载"封面自适应"的模糊底线（见 utils/coverFit.js），裁掉模糊层的溢出部分 */
  border-radius: 12px;
  overflow: hidden;
}

.md-cover {
  width: 100%;
  aspect-ratio: 2 / 3;
  object-fit: cover;
  border-radius: 12px;
  border: 1px solid var(--cinema-line, #2a2f3a);
  background: #11151d;
  box-shadow: 0 10px 34px rgba(0, 0, 0, 0.5);
}

.md-cover-empty {
  width: 100%;
  aspect-ratio: 2 / 3;
  border-radius: 12px;
  background: #11151d;
  border: 1px solid var(--cinema-line, #2a2f3a);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-3, #6b7280);
  font-size: 40px;
}

.md-status-ribbon {
  position: absolute;
  left: 10px;
  top: 10px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
}
.md-status-ribbon.st-watched { background: rgba(52, 211, 153, 0.9); }
.md-status-ribbon.st-wanted { background: rgba(255, 176, 32, 0.92); }
.md-status-ribbon.st-browsed { background: rgba(107, 114, 128, 0.85); }

.md-info { flex: 1; min-width: 0; }

.md-title-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}
.md-title {
  margin: 0;
  font-size: 21px;
  line-height: 1.35;
  color: var(--text-1, #e5e7eb);
  font-weight: 700;
}
.md-code {
  font-size: 12.5px;
  color: var(--brand, #00a3ff);
  font-family: Consolas, monospace;
  white-space: nowrap;
}

.md-badges { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }

.md-meta {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 4px 18px;
  margin: 14px 0 0;
}
.md-meta dt {
  font-size: 11px;
  color: var(--text-3, #6b7280);
  grid-column: 1;
}
.md-meta dd {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-2, #9ca3af);
  grid-column: 2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.md-meta .md-rating { color: var(--accent, #ffb020); font-weight: 600; }
.md-link { cursor: pointer; color: var(--brand, #00a3ff); }
.md-link:hover { text-decoration: underline; }

/* ===== 操作行 ===== */
.md-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 18px;
  flex-wrap: wrap;
}
.md-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--cinema-line, #2a2f3a);
  background: #171c26;
  color: var(--text-1, #e5e7eb);
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, transform 0.1s;
}
.md-btn svg { width: 15px; height: 15px; fill: currentColor; }
.md-btn:hover { background: #1e2530; border-color: #3a4150; }
.md-btn:active { transform: scale(0.97); }
.md-btn.primary {
  background: var(--brand, #00a3ff);
  border-color: var(--brand, #00a3ff);
  color: #fff;
  font-weight: 600;
}
.md-btn.primary:hover { background: #1fb0ff; }

.md-mark { display: inline-flex; gap: 6px; margin-left: 4px; }
.md-mark-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--cinema-line, #2a2f3a);
  background: transparent;
  color: var(--text-3, #6b7280);
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.md-mark-btn svg { width: 13px; height: 13px; fill: currentColor; }
.md-mark-btn:hover { color: var(--text-1); background: #171c26; }
.md-mark-btn.on { color: #0b0e14; border-color: transparent; }
.md-mark-btn.on[title='想看'] { background: var(--accent, #ffb020); }
.md-mark-btn.on[title='标记为已看'] { background: #34d399; }
.md-mark-btn.ghost { color: var(--text-3); }
.md-mark-btn.ghost:hover { color: #ff8b8b; }

/* ===== 类别 chips ===== */
.md-chips {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  flex-wrap: wrap;
}
.md-chip-label { font-size: 11px; color: var(--text-3, #6b7280); }
.md-chip {
  border: 1px solid var(--cinema-line, #2a2f3a);
  background: transparent;
  color: var(--text-2, #9ca3af);
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s;
}
.md-chip:hover { border-color: var(--brand, #00a3ff); color: var(--brand, #00a3ff); }

/* ===== 演员 ===== */
.md-actors { margin: 22px 0; }
.md-actor-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 10px;
}
.md-actor {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  width: 76px;
  border: none;
  background: transparent;
  color: var(--text-2, #9ca3af);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}
.md-actor img {
  width: 62px;
  height: 62px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--cinema-line, #2a2f3a);
  background: #171c26;
  transition: border-color 0.15s, transform 0.15s;
}
.md-actor:hover img { border-color: var(--brand, #00a3ff); transform: translateY(-2px); }
.md-actor span {
  width: 76px;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== 通用块 ===== */
.md-block { margin-top: 26px; }
.md-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-2, #9ca3af);
  letter-spacing: 0.4px;
  margin-bottom: 12px;
  padding-left: 9px;
  border-left: 3px solid var(--brand, #00a3ff);
}
.md-plot {
  margin: 0;
  font-size: 13px;
  line-height: 1.9;
  color: var(--text-2, #9ca3af);
  white-space: pre-wrap;
  max-width: 980px;
}
.md-plot.muted { color: var(--text-3, #6b7280); }

.md-samples {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}
.md-samples img {
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--cinema-line, #2a2f3a);
  cursor: zoom-in;
}

/* ===== 推荐行 ===== */
.md-related { margin-bottom: 22px; }
.md-related-scroll {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
  gap: 14px;
}

/* ===== 骨架 ===== */
.md-skeleton-cover {
  width: 228px;
  aspect-ratio: 2 / 3;
  border-radius: 12px;
  background: linear-gradient(100deg, #131720 40%, #1a2029 50%, #131720 60%);
  background-size: 200% 100%;
  animation: md-shimmer 1.2s infinite;
}
.md-skeleton-block { margin-top: 24px; }
.md-skeleton-line {
  height: 14px;
  border-radius: 6px;
  background: linear-gradient(100deg, #131720 40%, #1a2029 50%, #131720 60%);
  background-size: 200% 100%;
  animation: md-shimmer 1.2s infinite;
  margin-bottom: 12px;
}
@keyframes md-shimmer {
  to { background-position: -200% 0; }
}
</style>
