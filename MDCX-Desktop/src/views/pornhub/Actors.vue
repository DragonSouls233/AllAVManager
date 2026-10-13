<template>
  <div class="module-actors">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索 PORNHub 演员..." clearable style="width: 300px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="loadActors">搜索</el-button>
      <el-button :loading="batchScraping" @click="batchScrape">批量增强刮削</el-button>
    </div>

    <!-- 国籍选择 TAB：国籍 = 扫描时记录的媒体根下顶级文件夹名（如 N:\澳大利亚\xxx → 澳大利亚） -->
    <div class="nationality-tabs">
      <span class="nat-label">国籍</span>
      <button
        class="nat-tab"
        :class="{ active: !store.actorNationality }"
        @click="selectNationality('')"
      >全部<span v-if="allTotal" class="nat-count">{{ allTotal }}</span></button>
      <button
        v-for="n in sortedNationalities"
        :key="n.nationality"
        class="nat-tab"
        :class="{ active: store.actorNationality === n.nationality }"
        @click="selectNationality(n.nationality)"
      >{{ n.nationality }}<span class="nat-count">{{ n.count }}</span></button>
      <span v-if="!natLoading && !nationalities.length" class="nat-empty">
        暂无国籍数据，请先扫描影片
      </span>
    </div>

    <div class="actors-grid" v-loading="loading || natLoading">
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

    <!-- 🔴 2026-10-13：本页原先缺分页组件，832 位演员只能看到前 24 位、无法翻页 -->
    <div class="actors-pagination" v-if="store.actorTotal > 0">
      <el-pagination
        v-model:current-page="store.actorPage"
        v-model:page-size="store.actorPageSize"
        :page-sizes="[24, 48, 96, 192, 480]"
        :total="store.actorTotal"
        layout="total, sizes, prev, pager, next"
        @current-change="onActorPageChange"
        @size-change="onActorPageSizeChange"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
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

// 国籍 TAB
const nationalities = ref([])
const natLoading = ref(false)
// 「全部」的人数：只在无任何筛选（无国籍、无关键词）时记录，避免随搜索词漂移
const allTotal = ref(0)

// 后端已按人数倒序，这里再兜一层排序，保证 TAB 顺序稳定
const sortedNationalities = computed(() =>
  [...nationalities.value].sort((a, b) => (b.count || 0) - (a.count || 0) ||
    String(a.nationality).localeCompare(String(b.nationality), 'zh'))
)

async function loadNationalityTabs() {
  natLoading.value = true
  try {
    const list = await store.loadNationalities()
    nationalities.value = Array.isArray(list) ? list : []
  } catch (e) {
    nationalities.value = []
  } finally {
    natLoading.value = false
  }
}

function selectNationality(nat) {
  if (store.actorNationality === nat) return
  store.actorNationality = nat
  // 换国籍必须回第一页，否则会停在第 N 页而看不到该国籍的演员
  store.actorPage = 1
  loadActors()
}

async function loadActors() {
  loading.value = true
  try {
    store.actorSearch = keyword.value
    // 换搜索词时回到第一页，否则会停在第 N 页而看不到结果
    store.actorPage = 1
    actors.value = await store.loadActors()
    if (!store.actorNationality && !keyword.value) {
      allTotal.value = store.actorTotal
    }
  } finally {
    loading.value = false
  }
}

// 分页：换页 / 换每页条数（2026-10-13 补齐，原先本页完全没有分页组件，
// 832 位演员只显示前 24 位且无法翻页）
function onActorPageChange() {
  loadActors()
}
function onActorPageSizeChange() {
  store.actorPage = 1
  loadActors()
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

onMounted(async () => {
  // 国籍 TAB 与演员列表并行加载，互不阻塞
  await Promise.all([loadNationalityTabs(), loadActors()])
})
</script>

<style scoped>
.module-actors { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 20px; align-items: center; }
.actors-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; }
.nationality-tabs { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 16px; }
.nat-label { font-size: 13px; color: #909399; margin-right: 2px; flex-shrink: 0; }
.nat-tab {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 5px 12px; font-size: 13px; line-height: 1;
  border: 1px solid #dcdfe6; border-radius: 14px;
  background: #fff; color: #606266; cursor: pointer;
  transition: all 0.2s; white-space: nowrap;
}
.nat-tab:hover { border-color: #409eff; color: #409eff; }
.nat-tab.active { background: #409eff; border-color: #409eff; color: #fff; }
.nat-tab.active .nat-count { background: rgba(255,255,255,0.25); color: #fff; }
.nat-count {
  font-size: 11px; padding: 1px 6px; border-radius: 8px;
  background: #f0f2f5; color: #909399;
}
.nat-empty { font-size: 12px; color: #c0c4cc; }
.actors-pagination { margin-top: 20px; display: flex; justify-content: center; }
.actor-card { cursor: pointer; text-align: center; padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px; transition: all 0.2s; }
.actor-card:hover { border-color: #409eff; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.actor-avatar { width: 120px; height: 120px; margin: 0 auto 8px; border-radius: 50%; overflow: hidden; }
.actor-avatar img { width: 100%; height: 100%; object-fit: cover; }
.actor-name { font-size: 14px; font-weight: bold; margin-bottom: 4px; }
.actor-movies { font-size: 12px; color: #999; margin-bottom: 2px; }
.actor-views { font-size: 11px; color: #e6a23c; margin-bottom: 4px; }
.actor-completeness { display: flex; flex-wrap: wrap; justify-content: center; gap: 2px; margin-top: 4px; }
</style>
