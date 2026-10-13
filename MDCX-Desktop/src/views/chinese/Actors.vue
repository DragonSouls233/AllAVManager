<template>
  <div class="chinese-actors">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索国产演员..." clearable style="width: 300px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="search">搜索</el-button>
      <el-button type="success" @click="syncFolderActors">
        <el-icon><FolderOpened /></el-icon>
        从文件夹同步演员
      </el-button>
    </div>

    <div class="actors-grid" v-loading="loading">
      <div v-for="actor in actors" :key="actor.id" class="actor-card" @click="goActorDetail(actor.id)">
        <div class="actor-avatar">
          <img :src="getAvatarSrc(actor)" alt="" @error="handleAvatarError">
        </div>
        <div class="actor-info">
          <div class="actor-name">{{ actor.name }}</div>
          <div class="actor-movies">{{ actor.movie_count }} 部作品</div>
          <el-tag size="small" type="info" v-if="actor.source === 'folder'">来自文件夹</el-tag>
        </div>
      </div>
      <el-empty v-if="!loading && !actors.length" description="暂无国产演员，请先同步文件夹" />
    </div>

    <div class="pagination-wrap" v-if="total > pageSize">
      <el-pagination v-model:current-page="store.actorPage" v-model:page-size="store.actorPageSize"
        :total="store.actorTotal" :page-sizes="[24, 48, 96, 192, 480]" layout="total, sizes, prev, pager, next"
        @size-change="onActorPageSizeChange" @current-change="onActorPageChange" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useChineseStore } from '@/stores/chinese'
import defaultAvatar from '@/assets/default-avatar.png'
import { getAvatarSrc } from '@/utils/media'

const router = useRouter()
const store = useChineseStore()
const keyword = ref('')
const loading = ref(false)
const actors = ref([])

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
    // 2026-10-13：store.loadActors() 走服务端分页，返回当前页数组；
    // 总数从 store.actorTotal 取（后端 count 下推 SQL）
    actors.value = await store.loadActors()
    total.value = store.actorTotal
  } catch (e) {
    console.error('国产演员加载失败:', e)
    actors.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function search() {
  store.actorPage = 1
  loadActors()
}

function scrollTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function syncFolderActors() {
  loading.value = true
  try {
    await store.syncActors()
  } finally {
    loading.value = false
  }
}

function goActorDetail(id) {
  router.push(`/chinese/actors/${id}`)
}

function handleAvatarError(e) {
  e.target.src = defaultAvatar(e.target.alt || '?')
}

onMounted(loadActors)
</script>

<style scoped>
.chinese-actors { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 20px; align-items: center; flex-wrap: wrap; }
.actors-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px; }
.actor-card { cursor: pointer; text-align: center; padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px; transition: all 0.2s; }
.actor-card:hover { border-color: #409eff; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.actor-avatar { width: 120px; height: 120px; margin: 0 auto 8px; border-radius: 50%; overflow: hidden; }
.actor-avatar img { width: 100%; height: 100%; object-fit: cover; }
.actor-name { font-size: 14px; font-weight: bold; }
.actor-movies { font-size: 12px; color: #999; }
.pagination-wrap { margin-top: 20px; display: flex; justify-content: center; }
</style>
