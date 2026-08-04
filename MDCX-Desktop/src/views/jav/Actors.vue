<template>
  <div class="module-actors">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索演员..." clearable style="width: 300px"
        @keyup.enter="search" @clear="search">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="search">搜索</el-button>
    </div>

    <!-- 作品数分类 Tab -->
    <div class="filter-bar">
      <el-radio-group v-model="movieCountFilter" @change="onFilterChange">
        <el-radio-button label="multi">多作品（默认页）</el-radio-button>
        <el-radio-button label="single">素人 / 单作品</el-radio-button>
        <el-radio-button label="all">全部</el-radio-button>
      </el-radio-group>
      <div class="threshold">
        <span class="muted">多作品阈值</span>
        <el-input-number v-model="minMoviesForFilter" :min="1" :max="20" :step="1"
          size="small" controls-position="right" @change="onFilterChange" />
        <span class="muted">部（≥此值归“多作品”，其余归“素人”）</span>
      </div>
    </div>

    <div class="actors-grid" v-loading="loading">
      <div v-for="actor in actors" :key="actor.id" class="actor-card" @click="goActorDetail(actor.id)">
        <div class="actor-avatar">
          <img :src="getAvatarSrc(actor)" :alt="actor.name" @error="handleAvatarError">
        </div>
        <div class="actor-info">
          <div class="actor-name">{{ actor.name }}</div>
          <div class="actor-movies">{{ actor.movie_count }} 部作品</div>
          <el-tag size="small" type="info" v-if="actor.source === 'scraper'">来自爬虫</el-tag>
        </div>
      </div>
      <el-empty v-if="!loading && !actors.length" description="暂无演员，请先扫描影片" />
    </div>

    <div class="pagination-wrap" v-if="total > pageSize">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize"
        :total="total" :page-sizes="[60, 120, 240]" layout="total, sizes, prev, pager, next"
        @size-change="handleSizeChange" @current-change="loadActors" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import defaultAvatar from '@/assets/default-avatar.png'
import { getAvatarSrc } from '@/utils/media'
import { getJavActors } from '@/api/jav'

const router = useRouter()
const keyword = ref('')
const loading = ref(false)
const actors = ref([])
const page = ref(1)
const pageSize = ref(60)
const total = ref(0)

// 作品数分类
const movieCountFilter = ref('multi')
const minMoviesForFilter = ref(2)

async function loadActors() {
  loading.value = true
  try {
    const res = await getJavActors()
    // API 返回的可能是数组或 {items, total}
    if (Array.isArray(res)) {
      actors.value = res
      total.value = res.length
    } else {
      actors.value = res.items || []
      total.value = res.total || 0
    }
  } catch (e) {
    ElMessage.error('加载演员列表失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  loadActors()
}

function onFilterChange() {
  page.value = 1
  loadActors()
}

function handleSizeChange(val) {
  pageSize.value = val
  page.value = 1
  loadActors()
}

function goActorDetail(id) {
  router.push(`/jav/actors/${id}`)
}

function handleAvatarError(e) {
  e.target.src = defaultAvatar(e.target.alt || '?')
}

onMounted(loadActors)
</script>

<style scoped>
.module-actors { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 12px; align-items: center; flex-wrap: wrap; }
.filter-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.threshold { display: flex; align-items: center; gap: 6px; }
.muted { color: #909399; font-size: 12px; }
.actors-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px; }
.actor-card { cursor: pointer; text-align: center; padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px; transition: all 0.2s; }
.actor-card:hover { border-color: #409eff; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.actor-avatar { width: 120px; height: 120px; margin: 0 auto 8px; border-radius: 50%; overflow: hidden; }
.actor-avatar img { width: 100%; height: 100%; object-fit: cover; }
.actor-name { font-size: 14px; font-weight: bold; }
.actor-movies { font-size: 12px; color: #999; }
.pagination-wrap { margin-top: 20px; display: flex; justify-content: center; }
</style>
