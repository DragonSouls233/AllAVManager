<template>
  <div class="western-actors">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索欧美演员..." clearable style="width: 300px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="store.actorPage = 1; loadActors()">搜索</el-button>
      <el-tag v-if="actors.length">共 {{ actors.length }} 位演员</el-tag>
    </div>

    <div class="actors-grid" v-loading="loading">
      <div v-for="actor in actors" :key="actor.id" class="actor-card" @click="goActorDetail(actor.id)">
        <div class="actor-avatar">
          <img :src="getAvatarSrc(actor)" alt="" @error="handleAvatarError">
        </div>
        <div class="actor-info">
          <div class="actor-name">{{ actor.name }}</div>
          <div class="actor-meta">
            <span v-if="actor.country" class="country">{{ actor.country }}</span>
            <span class="movies">{{ actor.movie_count }} 部作品</span>
          </div>
          <div class="source-tags">
            <el-tag size="mini" type="info" v-if="actor.source">{{ actor.source }}</el-tag>
            <el-tag size="mini" type="success" v-if="actor.gender">{{ actor.gender }}</el-tag>
          </div>
        </div>
      </div>
      <el-empty v-if="!loading && !actors.length" description="暂无欧美演员，请先扫描影片" />
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
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useWesternStore } from '@/stores/western'
import defaultAvatar from '@/assets/default-avatar.png'
import { getAvatarSrc } from '@/utils/media'

// 🔴 2026-10-13：补每页条数选择器。换条数必须回第 1 页，
// 否则可能停在一个不存在的页码上（如原本在第 5 页，改成 24 条/页后共 2 页）。

const router = useRouter()
const store = useWesternStore()
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
    console.error('western 演员加载失败:', e)
    actors.value = []
  } finally {
    loading.value = false
  }
}

function scrollTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function goActorDetail(id) {
  router.push(`/western/actors/${id}`)
}

function handleAvatarError(e) {
  e.target.src = defaultAvatar(e.target.alt || '?')
}

onMounted(loadActors)
</script>

<style scoped>
.actors-pagination { margin-top: 20px; display: flex; justify-content: center; }
.western-actors { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 20px; align-items: center; }
.actors-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px; }
.actor-card { cursor: pointer; text-align: center; padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px; transition: all 0.2s; }
.actor-card:hover { border-color: #409eff; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.actor-avatar { width: 120px; height: 120px; margin: 0 auto 8px; border-radius: 50%; overflow: hidden; }
.actor-avatar img { width: 100%; height: 100%; object-fit: cover; }
.actor-name { font-size: 14px; font-weight: bold; }
.actor-meta { display: flex; justify-content: center; gap: 6px; font-size: 11px; color: #999; margin-top: 4px; }
.source-tags { margin-top: 6px; display: flex; justify-content: center; gap: 4px; }
</style>
