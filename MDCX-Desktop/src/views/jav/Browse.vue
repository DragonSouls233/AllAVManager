<template>
  <PageShell
    title="JAV 影片库"
    description="Peach 风浏览 · 封面 + 常驻元信息，点封面看详情 / 点 ▶ 直接播"
    padding="compact"
  >
    <!-- 工具条：搜索 / 排序 / 快速筛选 / 密度切换（密度对应 peach 的 JAV 卡片版式 big/small） -->
    <template #toolbar>
      <el-input
        v-model="keyword"
        placeholder="搜索番号 / 女优 / 标题..."
        clearable
        style="width: 260px"
        @keyup.enter="search"
        @clear="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-select v-model="sortBy" placeholder="排序" style="width: 160px" @change="onSortChange">
        <el-option label="默认（最新）" value="" />
        <el-option label="番号 ↑" value="code" />
        <el-option label="番号 ↓" value="-code" />
        <el-option label="发行日期 ↓" value="-release_date" />
        <el-option label="发行日期 ↑" value="release_date" />
        <el-option label="评分 ↓" value="-rating" />
        <el-option label="时长 ↓" value="-duration" />
      </el-select>

      <!-- 信息快速筛选（与影片库同义，仅作浏览过滤，不动刮削状态） -->
      <el-radio-group v-model="infoTab" size="default" @change="onInfoTabChange">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="chinese">有中文</el-radio-button>
        <el-radio-button value="uncensored">无码</el-radio-button>
        <el-radio-button value="hd_uncensored" title="高清无码（-LTX / -C-LTX）">高清无码</el-radio-button>
        <el-radio-button value="solo">单人</el-radio-button>
        <el-radio-button value="complete">信息全</el-radio-button>
        <el-radio-button value="incomplete">信息不全</el-radio-button>
      </el-radio-group>

      <div class="toolbar-spacer" />

      <el-tag v-if="store.total" type="info" effect="plain">{{ store.total }} 部</el-tag>

      <!-- Peach 风密度切换：小图 / 中图 / 大图，写入 <html> --tile，全局生效 -->
      <el-tooltip :content="`封面密度：${densityLabel}`" placement="top">
        <el-button @click="toggleDensity">
          <el-icon><Operation /></el-icon>
          {{ densityLabel }}
        </el-button>
      </el-tooltip>
    </template>

    <!-- 正文：海报墙（peach data-media-grid：封面 + 常驻元信息） -->
    <MediaGrid :items="store.movies" :loading="store.loading" cover-ratio="3 / 4">
      <template #default="{ item }">
        <article class="browse-card">
          <!-- 封面（peach data-jav-cover-box，圆角，hover 轻微放大） -->
          <!--
            🔴 这里**不能用原生 <a href="/jav/movies/xxx">**：本项目是 hash 路由
            （createWebHashHistory），原生 href 会触发一次真实的整页导航到该路径，
            页面会以「嵌套路径」重新加载 → index.html 里的相对 ./assets/… 解析成
            /jav/assets/… → 后端兜底返回 text/html → module script 被拒 → 白屏。
            所以只做 div + click（与 jav/Movies.vue 的写法一致），导航一律交给 router.push。
          -->
          <div
            class="cover"
            role="link"
            tabindex="0"
            :aria-label="`查看 ${item.code} 详情`"
            @click="goDetail(item.id)"
            @keydown.enter="goDetail(item.id)"
          >
            <img :src="getCoverSrc(item)" :alt="item.title" loading="lazy" @error="onCoverError" />
            <div class="cover-badges">
              <el-tag
                v-for="b in getMovieVersionBadges(item)"
                :key="b.text"
                size="small"
                :type="versionBadgeType(b.type)"
                effect="dark"
                class="ver-badge"
              >{{ b.text }}</el-tag>
            </div>
            <!-- 悬停浮现的播放键（peach 点封面原位播放） -->
            <button class="cover-play" type="button" :aria-label="`播放 ${item.code}`" @click.stop="goPlay(item.id)">
              <el-icon><VideoPlay /></el-icon>
            </button>
          </div>

          <!-- 常驻元信息（peach data-media-meta：code 粗体 + 标题 + byline + tags） -->
          <div class="meta">
            <h3 class="title" :title="`${item.code} · ${item.title || '标题未取得'}`">
              <b>{{ item.code }}</b> {{ item.title || '标题未取得' }}
            </h3>

            <div class="byline">
              <span v-if="item.actor" class="who" :title="item.actor">
                <el-icon><User /></el-icon>{{ actorName(item.actor.split(',')[0]) }}
                <span v-if="item.actor.split(',').length > 1" class="who-more">等 {{ item.actor.split(',').length }} 人</span>
              </span>
              <span v-if="item.release_date" class="release">
                <el-icon><Calendar /></el-icon>{{ String(item.release_date).slice(0, 10) }}
              </span>
              <span v-if="item.studio" class="studio" :title="item.studio">{{ item.studio }}</span>
            </div>

            <div class="tags">
              <el-tag v-if="item.rating" size="small" type="warning" effect="dark" class="score-chip">
                <el-icon><StarFilled /></el-icon>{{ item.rating }}
              </el-tag>
              <el-tag
                v-for="b in getMovieVersionBadges(item)"
                :key="'t'+b.text"
                size="small"
                :type="versionBadgeType(b.type)"
                effect="plain"
                class="ver-chip"
              >{{ b.text }}</el-tag>
            </div>
          </div>

          <!-- 操作行（peach data-jav-actions：查找资源 / 想要 → 这里映射为 播放 / 详情） -->
          <div class="actions">
            <el-button size="small" type="primary" @click="goPlay(item.id)">
              <el-icon><VideoPlay /></el-icon> 播放
            </el-button>
            <el-button size="small" @click="goDetail(item.id)">
              <el-icon><Document /></el-icon> 详情
            </el-button>
          </div>
        </article>
      </template>
    </MediaGrid>

    <!-- 页脚：分页 -->
    <template #footer>
      <!--
        分页沿用项目其余页面的写法（v-model + @current-change="loadMovies"）。
        经核实 Element Plus 的分页实现是**先** update:current-page（v-model 已写入）
        **后** current-change，所以在回调里读 store.page 拿到的就是新页码，写法成立。
        （此前怀疑过"并发顺序"问题，实为自写 QA 断言过早造成的误判，勿再改。）
      -->
      <el-pagination
        v-if="store.total > 0"
        v-model:current-page="store.page"
        v-model:page-size="store.pageSize"
        :page-sizes="[12, 24, 48, 96, 192, 240, 288]"
        :total="store.total"
        layout="total, sizes, prev, pager, next"
        @current-change="loadMovies"
        @size-change="onPageSizeChange"
      />
    </template>
  </PageShell>
</template>

<script setup>
/**
 * JAV 浏览（Peach 风）—— 海报墙 + 封面下常驻元信息 + 点击即播。
 *
 * 卡片结构对齐 peach 的 jav-page.tsx（data-media-card / data-jav-cover-box / data-media-meta /
 * data-jav-actions）：圆角封面 + 番号粗体标题 + 女优/日期 byline + 评分/版本标签 + 操作行。
 * 与 jav/Movies.vue（管理视图：扫描 / 批量刮削 / 补图）并存：这里只做「看」，不挂写操作，
 * 复用同一份 useJavStore 数据。
 *
 * 复用项目已有的 peach 设计语言：
 *   - MediaGrid（卡片网格，列宽读全局 --tile）
 *   - PageShell（页头 / 工具条 / 正文 / 页脚四槽）
 *   - utils/density.js（密度写 <html>，切密度不改动任何组件；对应 peach 的 JAV 卡片版式 big/small）
 */
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useJavStore } from '@/stores/jav'
import { getCoverSrc, getMovieVersionBadges, versionBadgeType } from '@/utils/media'
import { cycleDensity, currentDensity, applyDensity, DENSITY_LABELS } from '@/utils/density'
import MediaGrid from '@/components/base/MediaGrid.vue'
import PageShell from '@/components/base/PageShell.vue'

const router = useRouter()
const route = useRoute()
const store = useJavStore()

const keyword = ref('')
const sortBy = ref('')
const infoTab = ref('')
const densityLabel = ref(DENSITY_LABELS[currentDensity()] || '中图')

// 路由 query 跳转筛选（系列 / 片商 / 类别 / 番号前缀），与 Movies.vue 同义
function routeFilterParams() {
  const q = route.query
  const p = {}
  if (q.series) p.series = String(q.series)
  if (q.maker) p.maker = String(q.maker)
  if (q.genre) p.genre = String(q.genre)
  if (q.code_prefix) p.code_prefix = String(q.code_prefix)
  return p
}

// ============== 状态缓存（sessionStorage） ==============
// 从详情页 / 播放页返回时恢复用户之前浏览的页码和数据，体验接近 peach 的「进来接着看」。
const _CACHE_KEY = 'jav_browse_cache'
function _cacheKey() {
  const p = routeFilterParams()
  return `${_CACHE_KEY}:${keyword.value}:${sortBy.value}:${infoTab.value}:${Object.keys(p).sort().map(k => `${k}:${p[k]}`).join('|')}:${store.pageSize}`
}
function _saveCache() {
  try {
    sessionStorage.setItem(_cacheKey(), JSON.stringify({ items: store.movies, page: store.page, total: store.total }))
  } catch { /* quota exceeded */ }
}
function _restoreCache() {
  try {
    const c = JSON.parse(sessionStorage.getItem(_cacheKey()))
    if (!c || !c.items?.length) return false
    store.movies = c.items
    store.page = c.page || 1
    store.total = c.total || 0
    return true
  } catch { return false }
}

function search() {
  store.page = 1
  loadMovies()
}
function onSortChange() {
  store.page = 1
  loadMovies()
}
function onInfoTabChange() {
  store.page = 1
  loadMovies()
}
function onPageSizeChange() {
  store.page = 1
  loadMovies()
}

// 兜底剥离历史脏数据格式 {'name': 'xx'}
function actorName(s) {
  const t = String(s || '').trim()
  const m = t.match(/\{'name':\s*'([^']*)'\}/)
  return m ? m[1] : t
}

function loadMovies() {
  const params = { keyword: keyword.value || undefined, ...routeFilterParams() }
  if (sortBy.value) params.sort = sortBy.value
  if (infoTab.value === 'chinese') params.is_chinese = 1
  else if (infoTab.value === 'uncensored') params.is_uncensored = 1
  else if (infoTab.value === 'hd_uncensored') params.is_hd_uncensored = 1
  else if (infoTab.value === 'solo') params.solo = 1
  else if (infoTab.value === 'complete') params.info_state = 'complete'
  else if (infoTab.value === 'incomplete') params.info_state = 'incomplete'
  return store.loadMovies(params)
}

function goDetail(id) {
  router.push(`/jav/movies/${id}`)
}
function goPlay(id) {
  // Play 路由按 id 取影片并自行解析 module_type，JAV 直接可播
  router.push(`/play/${id}`)
}

function onCoverError(e) {
  e.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 150"><rect fill="%23333" width="100" height="150"/><text x="50" y="80" text-anchor="middle" fill="%23666" font-size="12">无封面</text></svg>'
}

function toggleDensity() {
  const next = cycleDensity()
  densityLabel.value = DENSITY_LABELS[next] || '中图'
}

// 路由 query 变化（详情页点系列 / 片商 / 类别跳转）时重新加载
let _lastQueryKey = JSON.stringify(route.query)
watch(() => route.query, (val) => {
  const key = JSON.stringify(val)
  if (key !== _lastQueryKey) {
    _lastQueryKey = key
    store.page = 1
    loadMovies()
  }
})

onMounted(() => {
  // 确保全局 --tile 已就绪（首屏若还没设过，按当前档位补一次）
  applyDensity()
  if (!_restoreCache()) loadMovies()
})

onBeforeUnmount(() => {
  _saveCache()
})
</script>

<style scoped>
.toolbar-spacer {
  flex: 1 1 auto;
}

/* ===== Peach 风海报卡（data-media-card） ===== */
.browse-card {
  display: flex;
  flex-direction: column;
  background: var(--bg-elevated, #1f1f23);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.browse-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.5);
}

/* 封面（data-jav-cover-box，圆角，peach rounded-2lg） */
.cover {
  position: relative;
  display: block;
  aspect-ratio: 3 / 4;
  width: 100%;
  overflow: hidden;
  background: var(--bg-tertiary, #2a2a30);
  cursor: pointer;
}
.cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.25s ease;
}
.browse-card:hover .cover img {
  transform: scale(1.05);
}

.cover-badges {
  position: absolute;
  top: 6px;
  left: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-width: calc(100% - 12px);
  pointer-events: none;
}
.cover-badges .ver-badge {
  border: none;
}

/* 悬停浮现的播放键。
   🔴 必须贴角放置，**不能居中**：居中会正好占住封面中心——那是用户最习惯点
   「看详情」的位置，点了会变成播放，与页面说明「点封面看详情 / 点 ▶ 直接播」矛盾。
   移到右下角后：封面（含中心）= 看详情，▶ = 播放，两条互不干扰。 */
.cover-play {
  position: absolute;
  right: 8px;
  bottom: 8px;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  display: grid;
  place-items: center;
  font-size: 22px;
  cursor: pointer;
  opacity: 0;
  transform: scale(0.85);
  transition: opacity 0.18s ease, transform 0.18s ease, background 0.18s ease;
}
.cover-play :deep(.el-icon) {
  font-size: 24px;
}
.browse-card:hover .cover-play {
  opacity: 1;
  transform: scale(1);
}
.cover-play:hover {
  background: var(--el-color-primary, #409eff);
}

/* 常驻元信息（data-media-meta） */
.meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 10px 4px;
  min-width: 0;
}
.title {
  margin: 0;
  font-size: 13px;
  line-height: 1.35;
  color: var(--text-primary, #eee);
  font-weight: 400;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.title b {
  font-weight: 700;
  color: #ffd479;
}
.byline {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary, #aaa);
  min-width: 0;
}
.byline .el-icon {
  margin-right: 3px;
  vertical-align: -1px;
}
.byline .who {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.byline .who-more {
  margin-left: 2px;
  opacity: 0.8;
}
.byline .studio {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.tags .score-chip :deep(.el-icon) {
  margin-right: 2px;
  vertical-align: -1px;
}

/* 操作行（data-jav-actions） */
.actions {
  display: flex;
  gap: 8px;
  padding: 8px 10px 12px;
  margin-top: auto;
}
.actions .el-button {
  flex: 1;
}
</style>
