<template>
  <div class="movie-detail" v-loading="loading">
    <div class="detail-header">
      <el-button text @click="goBack"><el-icon><ArrowLeft /></el-icon> 返回 PORNHub 列表</el-button>
      <div class="header-actions">
        <el-button type="primary" @click="play" :disabled="!canPlay">
          <el-icon><VideoPlay /></el-icon> 播放
        </el-button>
        <el-button type="success" @click="downloadVideo" :loading="downloading">
          <el-icon><Download /></el-icon> 下载
        </el-button>
        <el-tag v-if="movie && !canPlay" type="danger" size="small">视频文件不存在</el-tag>
      </div>
    </div>
    <div v-if="movie" class="detail-content">
      <div class="cover-section"><img :src="coverSrc" :alt="movie.title" @error="onCoverError"></div>
      <div class="info-section">
        <h1>{{ movie.title || movie.code }}</h1>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="番号">{{ movie.code }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ movie.source || '-' }}</el-descriptions-item>
          <el-descriptions-item label="演员">{{ movie.actor || '-' }}</el-descriptions-item>
          <el-descriptions-item label="时长">{{ movie.duration ? movie.duration + '分钟' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="评分">{{ movie.rating ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ movie.status }}</el-descriptions-item>
          <el-descriptions-item label="文件路径" :span="2">{{ movie.file_path || '-' }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="movie.plot" class="desc"><h3>简介</h3><p>{{ movie.plot }}</p></div>
        <div v-if="movie.genre" class="tags-section"><el-tag type="info">{{ movie.genre }}</el-tag></div>
        <div v-if="movie.actors && movie.actors.length" class="actors-section">
          <h3>演员</h3>
          <div class="actors-grid">
            <div v-for="a in movie.actors" :key="a.id" class="actor-chip" @click="goActorDetail(a.id)">
              <img :src="pornhubActorAvatarUrl(a.id)" alt="" @error="onActorError">
              <span>{{ a.name }}</span>
            </div>
          </div>
        </div>
        <div class="action-bar">
          <el-button size="small" type="warning" :loading="scraping" @click="startScrape">
            <el-icon><Refresh /></el-icon> 刮削补充
          </el-button>
          <el-button size="small" type="info" @click="startNfoReload">
            <el-icon><Document /></el-icon> 从 NFO 重新导入
          </el-button>
          <el-button size="small" type="primary" @click="openGraphql">
            <el-icon><DataAnalysis /></el-icon> GraphQL 详情
          </el-button>
        </div>
      </div>
    </div>

    <el-drawer v-model="showGraphqlDrawer" title="GraphQL 视频详情" size="560" :direction="'rtl'">
      <div v-loading="graphqlLoading">
        <div v-if="graphqlData">
          <el-descriptions :column="1" border size="small" style="margin-bottom: 16px">
            <el-descriptions-item label="Title">{{ graphqlData.title }}</el-descriptions-item>
            <el-descriptions-item label="Duration">{{ graphqlData.duration }}s</el-descriptions-item>
            <el-descriptions-item label="Views">{{ graphqlData.views }}</el-descriptions-item>
            <el-descriptions-item label="Rating">{{ graphqlData.rating }}</el-descriptions-item>
            <el-descriptions-item label="Likes">{{ graphqlData.likes }}</el-descriptions-item>
            <el-descriptions-item label="Dislikes">{{ graphqlData.dislikes }}</el-descriptions-item>
            <el-descriptions-item label="Publish Date">{{ graphqlData.publish_date }}</el-descriptions-item>
            <el-descriptions-item label="Thumbnail">{{ graphqlData.thumbnail }}</el-descriptions-item>
            <el-descriptions-item label="Description" :span="2"><p>{{ graphqlData.description }}</p></el-descriptions-item>
          </el-descriptions>

          <div v-if="graphqlData.tags && graphqlData.tags.length" class="graphql-section">
            <h4>Tags</h4>
            <el-tag v-for="t in graphqlData.tags" :key="t" size="small" type="info" style="margin: 2px">{{ t }}</el-tag>
          </div>

          <div v-if="graphqlData.categories && graphqlData.categories.length" class="graphql-section">
            <h4>Categories</h4>
            <el-tag v-for="c in graphqlData.categories" :key="c" size="small" type="success" style="margin: 2px">{{ c }}</el-tag>
          </div>

          <div v-if="graphqlData.performer_names && graphqlData.performer_names.length" class="graphql-section">
            <h4>Performers</h4>
            <el-tag v-for="p in graphqlData.performer_names" :key="p" size="small" type="warning" style="margin: 2px">{{ p }}</el-tag>
          </div>

          <div v-if="graphqlData.media_definitions && graphqlData.media_definitions.length" class="graphql-section">
            <h4>Available Streams</h4>
            <el-table :data="graphqlData.media_definitions" size="mini" stripe>
              <el-table-column prop="quality_label" label="Quality" width="120" />
              <el-table-column prop="container_type" label="Container" width="100" />
              <el-table-column prop="video_codec" label="Codec" width="100" />
              <el-table-column prop="file_size" label="Size" />
              <el-table-column label="URL" width="100" align="center">
                <template #default="row">
                  <el-button size="mini" text type="primary" @click="copyUrl(row.file)">复制</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div v-if="graphqlData.hls_master" class="graphql-section">
            <h4>HLS Master</h4>
            <el-text style="word-break: break-all; font-family: monospace; font-size: 12px">{{ graphqlData.hls_master }}</el-text>
            <el-button size="small" type="primary" style="margin-top: 8px" @click="copyUrl(graphqlData.hls_master)">复制 URL</el-button>
          </div>

          <div v-if="!graphqlData.tags?.length && !graphqlData.media_definitions?.length" class="graphql-section">
            <el-empty description="该视频暂无 GraphQL 详情数据" />
          </div>
        </div>
        <el-empty v-else-if="!graphqlLoading" description="暂无数据" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getPornhubMovie, scrapePornhubMovie, reloadPornhubMovieNfo, pornhubActorAvatarUrl, pornhubGraphqlVideo, pornhubVideoDownload } from '@/api/pornhub'
import { getCoverSrc } from '@/utils/media'
import { ElMessage } from 'element-plus'
import { VideoPlay, Refresh, Document, DataAnalysis, Download } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const movie = ref(null)
const loading = ref(true)
const scraping = ref(false)
const downloading = ref(false)
const showGraphqlDrawer = ref(false)
const graphqlLoading = ref(false)
const graphqlData = ref(null)
const coverSrc = computed(() => getCoverSrc(movie.value))
const canPlay = computed(() => movie.value && movie.value.file_path)

function goBack() { router.push('/pornhub') }
function goActorDetail(id) { router.push({ name: 'PornhubActorDetail', params: { id } }) }
function play() {
  if (!canPlay.value) { ElMessage.warning('该影片没有关联视频文件'); return }
  router.push({ path: `/play/${route.params.id}`, query: { module: 'pornhub' } })
}
function onCoverError(e) {
  e.target.src = 'data:image/svg+xml;charset=utf-8,%3Csvg xmlns="http://www.w3.org/2000/svg" width="320" height="450"%3E%3Crect width="320" height="450" fill="%23111827"/%3E%3C/svg%3E'
}
function onActorError(e) { e.target.style.display = 'none' }

async function startScrape() {
  scraping.value = true
  try {
    const res = await scrapePornhubMovie(route.params.id)
    ElMessage.success(res.message || '刮削完成')
    movie.value = await getPornhubMovie(route.params.id)
  } catch (e) { ElMessage.error('刮削失败: ' + (e.message || '未知错误')) }
  finally { scraping.value = false }
}
async function startNfoReload() {
  try {
    const res = await reloadPornhubMovieNfo(route.params.id)
    ElMessage.success(res.message || 'NFO 重载完成')
  } catch (e) { ElMessage.error('NFO 重载失败: ' + (e.message || '未知错误')) }
}

async function downloadVideo() {
  if (!movie.value?.code) { ElMessage.warning('无视频 code'); return }
  downloading.value = true
  try {
    const res = await pornhubVideoDownload(movie.value.code)
    ElMessage.success(res?.message || '下载已后台启动')
  } catch (e) { ElMessage.error('下载启动失败: ' + (e.message || '未知错误')) }
  finally { downloading.value = false }
}

async function openGraphql() {
  if (!movie.value?.code) { ElMessage.warning('无视频 code'); return }
  showGraphqlDrawer.value = true
  graphqlData.value = null
  graphqlLoading.value = true
  try {
    const res = await pornhubGraphqlVideo(movie.value.code)
    graphqlData.value = res
    if (!res?.title && !res?.media_definitions?.length) {
      ElMessage.info('该视频暂无 GraphQL 数据')
    }
  } catch (e) { ElMessage.error('GraphQL 详情获取失败: ' + (e.message || '未知错误')) }
  finally { graphqlLoading.value = false }
}

function copyUrl(text) {
  if (!text) return
  navigator.clipboard.writeText(text).then(() => ElMessage.success('已复制到剪贴板')).catch(() => ElMessage.error('复制失败'))
}

onMounted(async () => {
  try { movie.value = await getPornhubMovie(route.params.id) }
  finally { loading.value = false }
})
</script>

<style scoped>
.movie-detail { padding: 20px; }
.detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.detail-content { display: flex; gap: 24px; }
.cover-section { flex-shrink: 0; width: 350px; }
.cover-section img { width: 100%; border-radius: 8px; }
.info-section { flex: 1; }
.info-section h1 { font-size: 18px; margin-bottom: 16px; }
.desc { margin-top: 16px; }
.desc h3 { font-size: 14px; margin-bottom: 8px; }
.desc p { line-height: 1.6; color: #666; font-size: 13px; }
.tags-section { margin-top: 12px; display: flex; gap: 6px; flex-wrap: wrap; }
.actors-section { margin-top: 16px; }
.actors-section h3 { font-size: 14px; margin-bottom: 10px; color: #333; }
.actors-grid { display: flex; gap: 10px; flex-wrap: wrap; }
.actor-chip { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 20px; background: #f5f7fa; cursor: pointer; transition: background .2s; }
.actor-chip:hover { background: #e8ecf0; }
.actor-chip img { width: 28px; height: 28px; border-radius: 50%; object-fit: cover; }
.actor-chip span { font-size: 13px; color: #555; }
.action-bar { margin-top: 20px; display: flex; gap: 8px; }
.graphql-section { margin-top: 16px; }
.graphql-section h4 { font-size: 14px; margin-bottom: 8px; color: #333; }
.graphql-section p { font-size: 12px; color: #666; line-height: 1.5; }
</style>
