<template>
  <div class="module-actors">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索 PORNHub 演员..." clearable style="width: 300px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="loadActors">搜索</el-button>
      <el-button :loading="batchScraping" @click="batchScrape">批量增强刮削</el-button>
    </div>

    <div class="actors-grid" v-loading="loading">
      <div v-for="actor in actors" :key="actor.id" class="actor-card" @click="goActorDetail(actor.id)">
        <div class="actor-avatar">
          <img :src="getAvatarSrc(actor)" alt="" @error="handleAvatarError">
        </div>
        <div class="actor-info">
          <div class="actor-name">{{ actor.name }}</div>
          <div class="actor-movies">{{ actor.movie_count }} 部作品</div>
          <div v-if="actor.total_views" class="actor-views">▶ {{ formatViews(actor.total_views) }}</div>
          <div v-if="actor.nationality" class="actor-nationality">
            <el-tag size="mini" type="info">{{ actor.nationality }}</el-tag>
          </div>
          <div v-if="actor.profile_status" class="actor-status">
            <el-tag size="mini" :type="profileStatusType(actor.profile_status)">{{ profileStatusText(actor.profile_status) }}</el-tag>
          </div>
          <div v-if="actor.completeness && Object.keys(actor.completeness).length" class="actor-completeness">
            <el-tag v-for="(val, key) in actor.completeness" :key="key" :size="'mini'" :type="val ? 'success' : 'info'" style="margin: 1px">
              {{ completenessLabel(key) }}
            </el-tag>
          </div>
        </div>
      </div>
      <el-empty v-if="!loading && !actors.length" description="暂无 PORNHub 演员，请先扫描影片" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { usePornhubStore } from '@/stores/pornhub'
import { ElMessage } from 'element-plus'
import { getAvatarSrc } from '@/utils/media'
import { scrapeAllPornhubActorProfilesEnhanced } from '@/api/pornhub'

const router = useRouter()
const store = usePornhubStore()
const keyword = ref('')
const loading = ref(false)
const batchScraping = ref(false)
const actors = ref([])

async function loadActors() {
  loading.value = true
  try {
    store.actorSearch = keyword.value
    actors.value = await store.loadActors()
  } finally {
    loading.value = false
  }
}

async function batchScrape() {
  batchScraping.value = true
  try {
    await scrapeAllPornhubActorProfilesEnhanced()
    ElMessage.success('已启动批量演员资料/头像刮削（后台进行）')
  } catch (e) {
    ElMessage.error('启动失败')
  } finally {
    batchScraping.value = false
  }
}

function profileStatusType(status) {
  const map = { scraped: 'success', pending: 'info', failed: 'danger', partial: 'warning' }
  return map[status] || 'info'
}

function profileStatusText(status) {
  const map = { scraped: '已刮削', pending: '待刮削', failed: '失败', partial: '部分' }
  return map[status] || status
}

function formatViews(n) {
  if (!n) return '0'
  if (n >= 1000000000) return (n / 1000000000).toFixed(1) + 'B'
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}

const COMPLETENESS_LABELS = {
  photo_url: '头像',
  bio: '简介',
  profile_url: '主页',
  aliases: '别名',
  birthplace: '出生地',
  background: '背景',
  country: '国家',
  nationality: '国籍',
}
function completenessLabel(key) {
  return COMPLETENESS_LABELS[key] || key
}

function goActorDetail(id) {
  router.push(`/pornhub/actors/${id}`)
}

function handleAvatarError(e) {
  e.target.src = 'data:image/svg+xml;charset=utf-8,%3Csvg xmlns="http://www.w3.org/2000/svg" width="120" height="120"%3E%3Crect width="120" height="120" fill="%23111827"/%3E%3Ctext x="60" y="66" text-anchor="middle" font-size="40" fill="%23666"%3E%3F%3C/text%3E%3C/svg%3E'
}

onMounted(loadActors)
</script>

<style scoped>
.module-actors { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 20px; align-items: center; }
.actors-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; }
.actor-card { cursor: pointer; text-align: center; padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px; transition: all 0.2s; }
.actor-card:hover { border-color: #409eff; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.actor-avatar { width: 120px; height: 120px; margin: 0 auto 8px; border-radius: 50%; overflow: hidden; }
.actor-avatar img { width: 100%; height: 100%; object-fit: cover; }
.actor-name { font-size: 14px; font-weight: bold; margin-bottom: 4px; }
.actor-movies { font-size: 12px; color: #999; margin-bottom: 2px; }
.actor-views { font-size: 11px; color: #e6a23c; margin-bottom: 4px; }
.actor-completeness { display: flex; flex-wrap: wrap; justify-content: center; gap: 2px; margin-top: 4px; }
</style>
