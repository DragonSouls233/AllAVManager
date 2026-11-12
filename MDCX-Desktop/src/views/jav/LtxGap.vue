<template>
  <div class="ltx-page">
    <header class="hdr">
      <div class="hdr-l">
        <h2>JAV · LTX 库</h2>
        <div class="sub">
          线上 <b>{{ onlineTotal }}</b> 部 / <b>{{ actorTotal }}</b> 演员 ·
          本地 LTX <b>{{ localTotal }}</b> ·
          <b class="warn">新演员 {{ newActorTotal }}</b>
          <span v-if="savedAt"> · 数据 {{ savedAt }}</span>
          <span v-if="syncHint" class="sync" :class="syncBad ? 'bad' : 'ok'"> · {{ syncHint }}</span>
        </div>
      </div>
      <div class="hdr-r">
        <el-input v-model="actorKw" class="search" placeholder="搜索演员" clearable>
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-checkbox v-model="onlyNew">只看本地没有</el-checkbox>
        <el-button type="primary" :loading="loading" @click="updateSnapshot">更新快照</el-button>
      </div>
    </header>

    <el-alert v-if="err" :title="err" type="error" :closable="false" show-icon class="err" />

    <div class="layout">
      <!-- 演员列表 -->
      <aside class="side" v-loading="loading">
        <div
          v-for="a in filteredActors"
          :key="a.name"
          class="actor"
          :class="{ active: a.name === current, 'is-new': a.is_new }"
          @click="selectActor(a.name)"
        >
          <span class="ava">
            <span class="ava-l">{{ (a.name || '?').slice(0, 1) }}</span>
            <img
              v-if="a.avatar"
              :src="a.avatar"
              loading="lazy"
              referrerpolicy="no-referrer"
              @error="$event.target.style.display = 'none'"
            />
          </span>
          <span class="meta">
            <span class="aname" :title="a.name">{{ a.name }}</span>
            <span class="abar">
              本地 <b :class="{ good: a.have > 0 }">{{ a.have }}</b> / {{ a.count }}
              <span class="dot" v-if="a.is_new">新</span>
            </span>
          </span>
        </div>
        <el-empty v-if="!loading && !filteredActors.length" description="无匹配演员" :image-size="56" />
      </aside>

      <!-- 作品网格 -->
      <section class="main">
        <div class="bar">
          <span class="cur">{{ current || '—' }}</span>
          <el-tag v-if="currentInfo && currentInfo.is_new" type="danger" size="small" effect="dark">本地没有</el-tag>
          <span class="muted">本地 {{ currentInfo ? currentInfo.have : 0 }} / 线上 {{ currentInfo ? currentInfo.count : 0 }}</span>
          <span class="grow" />
          <el-checkbox v-model="onlyMissingItems">只看缺失</el-checkbox>
          <el-select v-model="sortBy" size="small" style="width: 108px">
            <el-option label="日期 ↓" value="date" />
            <el-option label="评分 ↓" value="score" />
            <el-option label="番号 ↑" value="code" />
          </el-select>
          <el-button size="small" type="primary" plain :disabled="!missingLinksCount" @click="copyActorMissing">
            复制缺失链接（{{ missingLinksCount }}）
          </el-button>
        </div>

        <div class="scroll" v-loading="loadingActor">
          <div v-if="sortedItems.length" class="grid">
            <div v-for="it in sortedItems" :key="it.code" class="card">
              <div class="cover">
                <img
                  v-if="it.cover"
                  :src="it.cover"
                  loading="lazy"
                  referrerpolicy="no-referrer"
                  @error="$event.target.style.display = 'none'"
                />
                <span class="ph" v-else>{{ it.code.slice(0, 3) }}</span>
                <span class="badge-code" title="点击复制番号" @click="copyText(it.code)">{{ it.code }}</span>
                <span v-if="it.score" class="badge-score">★ {{ Number(it.score).toFixed(1) }}</span>
                <span class="badge-state" :class="it.owned ? 'own' : 'miss'">{{ it.owned ? '已拥有' : '缺失' }}</span>
              </div>
              <div class="body">
                <div class="title" :title="it.title">{{ it.title || it.code }}</div>
                <div class="meta2">
                  <span v-if="it.date">{{ it.date }}</span>
                  <span v-if="it.maker" class="maker">{{ it.maker }}</span>
                </div>
                <div class="acts">
                  <span class="kind" :class="kind(it)">{{ kindLabel(it) }}</span>
                  <span class="grow" />
                  <el-button v-if="it.links.length" text size="small" type="primary" @click="copyText(it.links.join('\n'))">复制链接</el-button>
                  <el-button v-if="it.jav_id" text size="small" @click="openLocal(it.jav_id)">打开本地</el-button>
                </div>
              </div>
            </div>
          </div>
          <el-empty v-else-if="!loadingActor" description="该演员暂无作品" />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { getLtxLibrary, getLtxActor, refreshLtxSnapshot } from '@/api/jav'

const router = useRouter()

const loading = ref(false)
const loadingActor = ref(false)
const err = ref('')
const actorKw = ref('')
const onlyNew = ref(false)
const onlyMissingItems = ref(false)
const sortBy = ref('date')

const onlineTotal = ref(0)
const actorTotal = ref(0)
const localTotal = ref(0)
const newActorTotal = ref(0)
const savedAt = ref('')
const syncStatus = ref(null)
const actors = ref([])
const current = ref('')
const currentItems = ref([])

/**
 * 同步状态文案。
 *
 * 老页头只显示 `savedAt`（= MAX(fetched_at)，数据入库时间），一旦同步失败它就
 * 停在旧日期，看着像「从来没自动同步过」——2026-11-09/10 的 429 限流正是如此。
 * 这里改成直说「上次同步 成功/失败 + 距今多久」，且超过 30 小时未成功就标红。
 */
const syncBad = computed(() => {
  const s = syncStatus.value
  if (!s) return false
  if (s.last_try_ok === false) return true
  return typeof s.stale_hours === 'number' && s.stale_hours > 30
})

const syncHint = computed(() => {
  const s = syncStatus.value
  if (!s || !s.last_try_at) return ''
  const ago = typeof s.stale_hours === 'number' ? `，已 ${s.stale_hours}h 未成功` : ''
  if (s.last_try_ok) return `上次同步 ${fmtTime(s.last_try_at)}`
  const why = s.last_http === 429 ? '远程限流 429' : s.last_error || '抓取失败'
  return `上次同步失败 ${fmtTime(s.last_try_at)}（${why}${ago}）`
})

function fmtTime(v) {
  // "2026-11-10T14:52:18" → "11-10 14:52"
  const m = String(v || '').match(/^\d{4}-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/)
  return m ? `${m[1]}-${m[2]} ${m[3]}:${m[4]}` : String(v || '')
}

const currentInfo = computed(() => actors.value.find((a) => a.name === current.value) || null)

const filteredActors = computed(() => {
  const q = actorKw.value.trim().toUpperCase()
  return actors.value.filter((a) => {
    if (onlyNew.value && !a.is_new) return false
    if (q && !a.name.toUpperCase().includes(q)) return false
    return true
  })
})

const sortedItems = computed(() => {
  let list = currentItems.value
  if (onlyMissingItems.value) list = list.filter((it) => !it.owned)
  const arr = [...list]
  if (sortBy.value === 'score') {
    arr.sort((a, b) => (Number(b.score) || 0) - (Number(a.score) || 0))
  } else if (sortBy.value === 'code') {
    arr.sort((a, b) => String(a.code).localeCompare(String(b.code)))
  } else {
    arr.sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
  }
  return arr
})

const missingLinksCount = computed(
  () => currentItems.value.filter((it) => !it.owned && it.links && it.links.length).length,
)

function applyLibrary(lib) {
  onlineTotal.value = lib.online_total || 0
  actorTotal.value = lib.actor_total || 0
  localTotal.value = lib.local_total || 0
  newActorTotal.value = lib.new_actor_total || 0
  savedAt.value = (lib.snapshot && lib.snapshot.saved_at) || ''
  syncStatus.value = lib.snapshot || null
  actors.value = lib.actors || []
}

async function ensureLibrary() {
  try {
    return await getLtxLibrary()
  } catch (e) {
    if (e && e.response && e.response.status === 404) {
      await refreshLtxSnapshot()
      return await getLtxLibrary()
    }
    throw e
  }
}

async function loadActor(name) {
  if (!name) return
  loadingActor.value = true
  try {
    const res = await getLtxActor(name)
    currentItems.value = res.items || []
  } catch (e) {
    currentItems.value = []
  } finally {
    loadingActor.value = false
  }
}

async function loadLibrary() {
  loading.value = true
  err.value = ''
  try {
    applyLibrary(await ensureLibrary())
    if (!current.value || !actors.value.some((a) => a.name === current.value)) {
      current.value = actors.value.length ? actors.value[0].name : ''
    }
    await loadActor(current.value)
  } catch (e) {
    err.value = '加载失败：' + (e.message || e)
  } finally {
    loading.value = false
  }
}

function selectActor(name) {
  if (name === current.value) return
  current.value = name
  loadActor(name)
}

async function updateSnapshot() {
  loading.value = true
  err.value = ''
  try {
    const res = await refreshLtxSnapshot()
    applyLibrary(await getLtxLibrary())
    await loadActor(current.value)
    ElMessage.success('已更新快照：' + (res.count != null ? res.count + ' 部' : 'OK') + '，封面/头像后台更新中')
  } catch (e) {
    // 502 的 detail 里带真实原因（429 限流 / 代理不通），直接透出来比笼统提示有用
    const detail = (e && e.response && e.response.data && e.response.data.detail) || e.message || e
    err.value = '更新失败：' + detail
    // 失败也要刷新状态条，别让页头继续显示旧的成功时间
    try {
      applyLibrary(await getLtxLibrary())
    } catch (_) {
      /* 拉不到就保留原状态 */
    }
  } finally {
    loading.value = false
  }
}

function kind(it) {
  const l = (it.links && it.links[0]) || ''
  if (l.startsWith('ed2k://')) return 'ed2k'
  if (l.startsWith('magnet:')) return 'magnet'
  return 'other'
}
function kindLabel(it) {
  const k = kind(it)
  return k === 'ed2k' ? 'ED2K' : k === 'magnet' ? '磁力' : '链接'
}

async function copyText(text) {
  const t = String(text || '')
  if (!t) return
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(t)
    } else {
      const ta = document.createElement('textarea')
      ta.value = t
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.top = '-9999px'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    ElMessage.success('已复制')
  } catch (e) {
    ElMessage.error('复制失败：' + (e.message || e))
  }
}

function copyActorMissing() {
  const links = currentItems.value.filter((it) => !it.owned).flatMap((it) => it.links || [])
  if (!links.length) return
  copyText(links.join('\n'))
}

function openLocal(id) {
  if (id) router.push(`/jav/movies/${id}`)
}

onMounted(loadLibrary)
</script>

<style scoped>
.ltx-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  /* 覆盖全局 .main-content > * 的 24px padding 与 1440px 居中：贴左、满宽 */
  max-width: none !important;
  margin: 0 !important;
  padding: 8px 12px 10px 0 !important;
  box-sizing: border-box;
}
.hdr {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.hdr h2 {
  margin: 0 0 5px;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}
.hdr .sub {
  font-size: 13px;
  color: var(--text-secondary);
}
.hdr .sub b {
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.hdr .sub .warn {
  color: var(--el-color-warning);
}
.hdr .sub .sync.ok {
  color: var(--text-secondary);
}
.hdr .sub .sync.bad {
  color: var(--el-color-danger);
  font-weight: 500;
}
.hdr-r {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.hdr-r .search {
  width: 200px;
}
.err {
  margin-bottom: 10px;
}
.layout {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 16px;
}

/* ---------- 演员列表 ---------- */
.side {
  width: 288px;
  flex-shrink: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: 12px;
  background: var(--bg-card, #fff);
  padding: 8px;
}
.actor {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 8px;
  border-radius: 10px;
  cursor: pointer;
  transition: background-color 0.12s;
}
.actor:hover {
  background: var(--hover-layer, #f5f7fa);
}
.actor.active {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
}
.actor.is-new .aname {
  color: var(--el-color-danger);
}
.ava {
  position: relative;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  flex-shrink: 0;
  overflow: hidden;
  background: linear-gradient(135deg, #dfe4ee, #c9d1e0);
  display: flex;
  align-items: center;
  justify-content: center;
}
.ava-l {
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
}
.ava img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.actor .meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.aname {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.abar {
  font-size: 11.5px;
  color: var(--text-secondary);
  margin-top: 1px;
}
.abar b {
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.abar b.good {
  color: var(--el-color-success);
}
.dot {
  margin-left: 6px;
  color: #fff;
  background: var(--el-color-danger);
  border-radius: 3px;
  padding: 0 4px;
  font-size: 10px;
}

/* ---------- 作品区 ---------- */
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-shrink: 0;
}
.bar .cur {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.bar .muted {
  font-size: 12px;
  color: var(--text-secondary);
}
.grow {
  flex: 1;
}
.scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 2px 4px 8px 2px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(236px, 1fr));
  gap: 18px;
  align-content: start;
}
.card {
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: 12px;
  overflow: hidden;
  background: var(--bg-card, #fff);
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
}
.card:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 24px -10px rgba(0, 0, 0, 0.22);
  border-color: var(--card-border-hover, var(--border-color));
}
.cover {
  position: relative;
  aspect-ratio: 2 / 3;
  background: linear-gradient(135deg, #eef1f6, #dde3ee);
}
.cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* DVD 展开图正面在右 ⇒ 右对齐，露出正面 */
  object-position: right center;
  display: block;
}
.ph {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #b6becd;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 1px;
}
.badge-code {
  position: absolute;
  left: 8px;
  top: 8px;
  font-size: 11.5px;
  font-family: var(--font-mono, monospace);
  background: rgba(0, 0, 0, 0.62);
  color: #fff;
  padding: 2px 7px;
  border-radius: 6px;
  cursor: pointer;
}
.badge-score {
  position: absolute;
  right: 8px;
  top: 8px;
  font-size: 11px;
  background: rgba(245, 158, 11, 0.92);
  color: #fff;
  padding: 2px 6px;
  border-radius: 6px;
  font-variant-numeric: tabular-nums;
}
.badge-state {
  position: absolute;
  left: 8px;
  bottom: 8px;
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 6px;
  color: #fff;
}
.badge-state.own {
  background: rgba(16, 185, 129, 0.94);
}
.badge-state.miss {
  background: rgba(239, 68, 68, 0.94);
}
.body {
  padding: 8px 10px 9px;
}
.title {
  font-size: 12.5px;
  line-height: 1.4;
  color: var(--text-regular);
  height: 2.8em;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.meta2 {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-placeholder);
  display: flex;
  gap: 8px;
  overflow: hidden;
  white-space: nowrap;
}
.meta2 .maker {
  overflow: hidden;
  text-overflow: ellipsis;
}
.acts {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.kind {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  color: #fff;
}
.kind.ed2k {
  background: var(--el-color-success);
}
.kind.magnet {
  background: var(--el-color-primary);
}
.kind.other {
  background: var(--text-placeholder);
}
</style>
