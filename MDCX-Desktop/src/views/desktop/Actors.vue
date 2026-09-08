<template>
  <section>
    <div class="cinema-page-head">
      <h1 class="cinema-page-title">演员</h1>
      <span class="cinema-page-count">{{ lib.currentLabel }} · {{ total }} 位</span>
    </div>

    <div class="cinema-filters">
      <el-input
        v-model="q"
        placeholder="搜索演员名 / 别名"
        clearable
        size="small"
        style="width: 240px"
        @input="onSearch"
      />
      <el-select v-model="sortMode" size="small" style="width: 170px" @change="reload">
        <el-option label="按名字（中文笔画）" value="name_asc" />
        <el-option label="按作品数 ↓" value="count_desc" />
      </el-select>
      <el-button
        size="small"
        :type="onlyAvatar ? 'primary' : 'default'"
        :plain="!onlyAvatar"
        @click="onlyAvatar = !onlyAvatar; reload()"
      >仅带头像</el-button>
    </div>

    <div v-if="error" class="cinema-empty">
      <div class="cinema-empty-icon">⚠️</div>
      <div class="cinema-empty-text">{{ error }}</div>
      <el-button size="small" style="margin-top: 12px" @click="reload">重试</el-button>
    </div>

    <div v-else-if="isAnime" class="cinema-empty">
      <div class="cinema-empty-icon">👤</div>
      <div class="cinema-empty-text">里番暂无独立的演员库（演员以文本标记保存在影片信息中）</div>
    </div>

    <div v-else-if="!loading && !actors.length" class="cinema-empty">
      <div class="cinema-empty-icon">👤</div>
      <div class="cinema-empty-text">{{ q ? `没有匹配「${q}」的演员` : `${lib.currentLabel} 暂无演员数据` }}</div>
    </div>

    <div v-else class="actor-wall">
      <template v-if="loading && !actors.length">
        <div v-for="n in 24" :key="`sk-${n}`" class="actor-skeleton" />
      </template>
      <button
        v-for="a in actors"
        :key="a.id"
        class="actor-cell"
        type="button"
        @click="openActor(a)"
      >
        <img
          class="actor-avatar"
          :src="avatarOf(a)"
          :alt="a.name"
          loading="lazy"
          @error="onAvatarErr($event, a)"
        />
        <span class="actor-name" :title="a.name">{{ a.name }}</span>
        <span class="actor-count">{{ a.movie_count ?? a.count ?? 0 }} 部</span>
      </button>
    </div>

    <div class="load-bar">
      <el-button v-if="hasMore" :loading="loading" size="small" text @click="loadMore">
        加载更多（{{ actors.length }}/{{ total }}）
      </el-button>
      <span v-else-if="total > 0" class="load-end">已到底部</span>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useLibraryStore } from '@/stores/library'
import { getActors } from '@/api'
import { getActorAvatarUrlById, defaultAvatar } from '@/utils/media'

const PAGE = 120
const router = useRouter()
const lib = useLibraryStore()

const actors = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const q = ref('')
const sortMode = ref('name_asc')
const onlyAvatar = ref(false)
const hasMore = ref(false)
let seq = 0
let searchTimer = null

const isAnime = computed(() => lib.currentModule === 'anime')

function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => reload(), 350)
}
function reload() {
  actors.value = []
  total.value = 0
  hasMore.value = false
  load()
}

async function loadMore() {
  if (loading.value || !hasMore.value) return
  await load()
}

async function load() {
  const s = ++seq
  loading.value = true
  error.value = ''
  try {
    const [sortBy, sortOrder] = sortMode.value === 'count_desc'
      ? ['movie_count', 'desc']
      : ['name', 'asc']
    const params = {
      module: lib.currentModule,
      search: q.value || undefined,
      sort_by: sortBy,
      sort_order: sortOrder,
      page: Math.floor(actors.value.length / PAGE) + 1,
      page_size: PAGE
    }
    if (onlyAvatar.value) params.has_avatar = true
    const res = await getActors(params)
    if (s !== seq) return
    const list = res?.items || []
    actors.value = actors.value.concat(list)
    total.value = res?.total ?? actors.value.length
    hasMore.value = actors.value.length < total.value
  } catch (e) {
    if (s !== seq) return
    error.value = e?.response?.status === 401 ? '登录已失效，请重新登录' : '加载演员失败，请检查服务器连接'
  } finally {
    if (s === seq) loading.value = false
  }
}

function avatarOf(a) {
  return getActorAvatarUrlById(a.id, lib.currentModule, a.updated_at || '')
}
function onAvatarErr(e, a) {
  e.target.src = defaultAvatar(a.name)
}

function openActor(a) {
  router.push({ path: `/actors/${a.id}`, query: { module: lib.currentModule } })
}

watch(() => lib.currentModule, reload)

onMounted(load)
</script>

<style scoped>
.actor-wall {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(108px, 1fr));
  gap: 14px 10px;
}
.actor-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 10px 4px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: transparent;
  color: var(--text-1);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, transform 0.15s;
}
.actor-cell:hover {
  background: var(--cinema-1);
  border-color: var(--cinema-line);
  transform: translateY(-2px);
}
.actor-avatar {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--cinema-2);
  border: 2px solid var(--cinema-line);
}
.actor-cell:hover .actor-avatar { border-color: var(--brand); }
.actor-name {
  max-width: 100%;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.actor-count { font-size: 11px; color: var(--text-3); }
.actor-skeleton {
  aspect-ratio: 1 / 1.3;
  border-radius: 12px;
  background: linear-gradient(90deg, var(--cinema-1) 25%, var(--cinema-2) 50%, var(--cinema-1) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
}
.load-bar { display: flex; justify-content: center; padding: 18px 0 8px; }
.load-end { font-size: 12px; color: var(--text-3); }
@keyframes shimmer { to { background-position: -200% 0; } }
</style>
