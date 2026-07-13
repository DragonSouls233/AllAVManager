<template>
  <div class="chinese-actors">
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索国产演员..."
        clearable
        style="width: 300px"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-button type="primary" @click="loadActors">搜索</el-button>
      <el-button type="success" @click="syncFolderActors">
        <el-icon><FolderOpened /></el-icon>
        从文件夹同步演员
      </el-button>
    </div>

    <div class="actors-grid" v-loading="loading">
      <div
        v-for="actor in actors"
        :key="actor.id"
        class="actor-card"
        @click="goActorDetail(actor.id)"
      >
        <div class="actor-avatar">
          <img :src="actor.avatar_url || defaultAvatar" alt="">
        </div>
        <div class="actor-info">
          <div class="actor-name">{{ actor.name }}</div>
          <div class="actor-movies">{{ actor.movie_count }} 部作品</div>
          <el-tag size="small" type="info" v-if="actor.source === 'folder'">来自文件夹</el-tag>
        </div>
      </div>
      <el-empty v-if="!loading && !actors.length" description="暂无国产演员，请先同步文件夹" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useChineseStore } from '@/stores/chinese'
import defaultAvatar from '@/assets/default-avatar.png'

const router = useRouter()
const store = useChineseStore()
const keyword = ref('')
const loading = ref(false)
const actors = ref([])

async function loadActors() {
  loading.value = true
  try {
    actors.value = await store.loadActors()
  } finally {
    loading.value = false
  }
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

onMounted(loadActors)
</script>

<style scoped>
.chinese-actors { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 20px; align-items: center; }
.actors-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px; }
.actor-card { cursor: pointer; text-align: center; padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px; transition: all 0.2s; }
.actor-card:hover { border-color: #409eff; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.actor-avatar { width: 120px; height: 120px; margin: 0 auto 8px; border-radius: 50%; overflow: hidden; }
.actor-avatar img { width: 100%; height: 100%; object-fit: cover; }
.actor-name { font-size: 14px; font-weight: bold; }
.actor-movies { font-size: 12px; color: #999; }
</style>
