<template>
  <div class="ltx-mirror">
    <header class="topbar">
      <div class="ttl">
        <h2>JAV · LTX 库</h2>
        <div class="sub">
          线上 <b>{{ onlineTotal }}</b> 部 / <b>{{ actorTotal }}</b> 演员 ·
          本地 LTX <b>{{ localTotal }}</b> ·
          <b class="warn">新演员 {{ newActorTotal }}</b>
          <span v-if="savedAt"> · 快照 {{ savedAt }}</span>
        </div>
      </div>
      <div class="actions">
        <el-input v-model="actorKw" placeholder="搜索演员" clearable style="width: 180px">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-checkbox v-model="onlyNew">只看本地没有</el-checkbox>
        <el-button type="primary" :loading="loading" @click="updateSnapshot">更新快照</el-button>
      </div>
    </header>

    <el-alert v-if="err" :title="err" type="error" :closable="false" show-icon style="margin-bottom: 10px" />

    <div class="body">
      <aside class="actors" v-loading="loading">
        <div
          v-for="a in filteredActors"
          :key="a.name"
          class="actor"
          :class="{ active: a.name === current, 'is-new': a.is_new }"
          @click="selectActor(a.name)"
        >
          <img v-if="a.avatar" class="ava" :src="a.avatar" loading="lazy" @error="$event.target.style.visibility='hidden'" />
          <span v-else class="ava ava-empty">{{ (a.name || '?').slice(0, 1) }}</span>
          <span class="aname" :title="a.name">{{ a.name }}</span>
          <span class="acount">{{ a.count }}</span>
          <span class="astat" :class="{ good: a.have > 0 }">{{ a.have }}/{{ a.count }}</span>
        </div>
        <el-empty v-if="!loading && !filteredActors.length" description="无匹配演员" :image-size="60" />
      </aside>

      <main class="mainpane">
        <div class="grid-head">
          <span class="cur">{{ current || '—' }}</span>
          <el-tag v-if="currentInfo && currentInfo.is_new" type="danger" size="small">本地没有</el-tag>
          <span class="muted">本地 {{ currentInfo ? currentInfo.have : 0 }} / 线上 {{ currentInfo ? currentInfo.count : 0 }}</span>
          <el-checkbox v-model="onlyMissingItems">只看缺失</el-checkbox>
          <el-button
            size="small"
            type="primary"
            plain
            :disabled="!missingLinksCount"
            @click="copyActorMissing"
          >
            复制该演员缺失链接（{{ missingLinksCount }}）
          </el-button>
        </div>

        <div class="grid" v-loading="loadingActor">
          <div v-for="it in filteredItems" :key="it.code" class="card">
            <div class="cover">
              <img
                v-if="it.cover"
                :src="it.cover"
                loading="lazy"
                referrerpolicy="no-referrer"
                @error="$event.target.style.visibility='hidden'"
              />
              <span v-else class="cover-empty" />
              <span class="code-badge" title="点击复制番号" @click="copyText(it.code)">{{ it.code }}</span>
              <span v-if="!it.owned" class="miss-badge">缺失</span>
              <span v-else class="own-badge">已拥有</span>
            </div>
            <div class="cinfo">
              <div class="ctitle" :title="it.title">{{ it.title || it.code }}</div>
              <div class="cactions">
                <span class="link-kind" :class="kind(it)">{{ kindLabel(it) }}</span>
                <el-button v-if="it.links.length" text size="small" type="primary" @click="copyText(it.links.join('\n'))">
                  复制链接
                </el-button>
              </div>
            </div>
          </div>
          <el-empty v-if="!loadingActor && !filteredItems.length" description="该演员暂无作品" />
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { getLtxLibrary, getLtxActor, refreshLtxSnapshot } from '@/api/jav'

const loading = ref(false)
const loadingActor = ref(false)
const err = ref('')
const actorKw = ref('')
const onlyNew = ref(false)
const onlyMissingItems = ref(false)

const onlineTotal = ref(0)
const actorTotal = ref(0)
const localTotal = ref(0)
const newActorTotal = ref(0)
const savedAt = ref('')
const actors = ref([])
const current = ref('')
const currentItems = ref([])

const currentInfo = computed(() => actors.value.find((a) => a.name === current.value) || null)
const filteredActors = computed(() => {
  const q = actorKw.value.trim().toUpperCase()
  return actors.value.filter((a) => {
    if (onlyNew.value && !a.is_new) return false
    if (q && !a.name.toUpperCase().includes(q)) return false
    return true
  })
})
const filteredItems = computed(() =>
  onlyMissingItems.value ? currentItems.value.filter((it) => !it.owned) : currentItems.value,
)
const missingLinksCount = computed(
  () => currentItems.value.filter((it) => !it.owned && it.links && it.links.length).length,
)

function applyLibrary(lib) {
  onlineTotal.value = lib.online_total || 0
  actorTotal.value = lib.actor_total || 0
  localTotal.value = lib.local_total || 0
  newActorTotal.value = lib.new_actor_total || 0
  savedAt.value = (lib.snapshot && lib.snapshot.saved_at) || ''
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
    ElMessage.success('已更新快照：' + (res.count != null ? res.count + ' 部' : 'OK') + '，封面/头像后台下载中')
  } catch (e) {
    err.value = '更新失败：' + (e.message || e) + '（需服务器内置代理能访问外网）'
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

onMounted(loadLibrary)
</script>

<style scoped>
.ltx-mirror {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px 20px;
  box-sizing: border-box;
}
.topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
  flex-shrink: 0;
}
.ttl h2 {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}
.ttl .sub {
  font-size: 12.5px;
  color: var(--text-secondary);
}
.ttl .sub b {
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.ttl .sub .warn {
  color: var(--el-color-warning);
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
}
.actors {
  width: 232px;
  flex-shrink: 0;
  overflow-y: auto;
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: var(--radius-card, 10px);
  background: var(--bg-card, #fff);
  padding: 6px;
}
.actor {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
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
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
  background: var(--hover-layer);
}
.ava-empty {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--text-secondary);
}
.aname {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}
.acount {
  font-size: 11px;
  color: var(--text-placeholder);
  font-variant-numeric: tabular-nums;
}
.astat {
  font-size: 11px;
  color: var(--text-placeholder);
  font-variant-numeric: tabular-nums;
  min-width: 38px;
  text-align: right;
}
.astat.good {
  color: var(--el-color-success);
}
.mainpane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.grid-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  flex-shrink: 0;
}
.grid-head .cur {
  font-weight: 600;
  color: var(--text-primary);
}
.grid-head .muted {
  font-size: 12px;
  color: var(--text-secondary);
}
.grid {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(158px, 1fr));
  gap: 12px;
  align-content: start;
  padding-right: 4px;
}
.card {
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: 10px;
  overflow: hidden;
  background: var(--bg-card, #fff);
  display: flex;
  flex-direction: column;
}
.cover {
  position: relative;
  aspect-ratio: 2 / 3;
  background: var(--hover-layer);
}
.cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.cover-empty {
  display: block;
  width: 100%;
  height: 100%;
}
.code-badge {
  position: absolute;
  left: 6px;
  top: 6px;
  font-size: 11px;
  font-family: var(--font-mono, monospace);
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  padding: 1px 6px;
  border-radius: 4px;
  cursor: pointer;
}
.miss-badge,
.own-badge {
  position: absolute;
  right: 6px;
  top: 6px;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  color: #fff;
}
.miss-badge {
  background: var(--el-color-danger);
}
.own-badge {
  background: var(--el-color-success);
}
.cinfo {
  padding: 6px 8px;
}
.ctitle {
  font-size: 12px;
  color: var(--text-regular);
  line-height: 1.35;
  height: 2.7em;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.cactions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}
.link-kind {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 3px;
  color: #fff;
}
.link-kind.ed2k {
  background: var(--el-color-success);
}
.link-kind.magnet {
  background: var(--el-color-primary);
}
.link-kind.other {
  background: var(--text-placeholder);
}
</style>
