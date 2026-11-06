<template>
  <div class="module-actors">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索 FC2 演员..." clearable style="width: 300px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="store.actorPage = 1; loadActors()">搜索</el-button>
    </div>

    <div class="actors-grid" v-loading="loading">
      <div v-for="actor in actors" :key="actor.id" class="actor-card" @click="goActorDetail(actor.id)">
        <div class="actor-avatar">
          <img :src="getAvatarSrc(actor)" alt="" @error="handleAvatarError">
        </div>
        <div class="actor-info">
          <div class="actor-name">{{ actor.name }}</div>
          <div class="actor-movies">{{ actor.movie_count }} 部作品</div>
        </div>
      </div>
      <el-empty v-if="!loading && !actors.length" description="暂无 FC2 演员，请先扫描影片" />
    </div>

    <!-- 🔴 2026-10-13：补分页（对齐 JAV 有码/国产）-->
    <div class="actors-pagination" v-if="store.actorTotal > 0">
      <el-pagination v-model:current-page="store.actorPage" v-model:page-size="store.actorPageSize"
        :total="store.actorTotal" :page-sizes="[24, 48, 96, 192, 480]"
        layout="total, sizes, prev, pager, next"
        @size-change="onActorPageSizeChange" @current-change="onActorPageChange" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useFc2Store } from '@/stores/fc2'
import defaultAvatar from '@/assets/default-avatar.png'
import { getAvatarSrc } from '@/utils/media'

// 🔴 2026-10-13：补每页条数选择器。换条数必须回第 1 页，
// 否则可能停在一个不存在的页码上（如原本在第 5 页，改成 24 条/页后共 2 页）。

const router = useRouter()
const store = useFc2Store()
const keyword = ref('')
const loading = ref(false)
const actors = ref([])

// 演员分页（服务端）。后端 /actors 已支持 skip/limit + count，
// 换页/换每页条数直接重新请求，不再前端切片。
function onActorPageChange() {
  loadActors()
}
function onActorPageSizeChange() {
  store.actorPage = 1
  loadActors()
}
async function loadActors() {
  loading.value = true
  try {
    actors.value = await store.loadActors()
  } catch (e) {
    console.error('fc2 演员加载失败:', e)
    actors.value = []
  } finally {
    loading.value = false
  }
}

function scrollTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function goActorDetail(id) {
  router.push(`/fc2/actors/${id}`)
}

function handleAvatarError(e) {
  e.target.src = defaultAvatar(e.target.alt || '?')
}

onMounted(loadActors)
</script>

<style scoped>
.actors-pagination { margin-top: 20px; display: flex; justify-content: center; }
.module-actors { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 20px; align-items: center; }
.actors-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 18px; }
.actor-card { cursor: pointer; text-align: center; padding: 14px 12px 12px; border: 1px solid var(--hairline, var(--border-color)); border-radius: 14px; background: var(--bg-card); box-shadow: var(--shadow-kpi); transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease; }
.actor-card:hover { transform: translateY(-3px); border-color: var(--card-border-hover); box-shadow: var(--shadow-card); }
.actor-avatar { width: 112px; height: 112px; margin: 0 auto 10px; border-radius: 50%; overflow: hidden; background: var(--bg-hover); box-shadow: 0 4px 14px -6px rgba(16,24,40,0.35); }
.actor-avatar img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 0.3s ease; }
.actor-card:hover .actor-avatar img { transform: scale(1.05); }
.actor-name { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.actor-movies { font-size: 12px; color: #999; }
</style>
