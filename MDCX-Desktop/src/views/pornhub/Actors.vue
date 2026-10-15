<template>
  <div class="module-actors">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索 PORNHub 演员..." clearable style="width: 300px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="searchActors">搜索</el-button>
      <el-button :loading="batchScraping" @click="batchScrape">批量增强刮削</el-button>
      <!--
        🔴 2026-10-14 补：原先演员库**没有任何头像刮削入口**，
        用户只能进详情页逐个点。后端 `POST /pornhub/actors/batch/download-avatars`
        与 api/store 封装（batchDownloadAvatars）**早就齐了**，只是 views 里零处调用
        ⇒ 纯粹漏了 UI。这里加一个独立按钮，不改动原有「批量增强刮削」入口。
      -->
      <el-button
        type="success"
        plain
        :loading="avatarScraping"
        @click="batchDownloadAvatars"
      >批量下载头像</el-button>
      <!--
        🔴 2026-10-15 补：从 PornSimilarityPlatform(models.db) 同步演员主页 URL。
        后端 POST /pornhub/actors/backfill-urls 已就绪，只补 profile_url 为空的演员，
        幂等：PSP 以后新增模特，点一次即可增量补齐。同样是独立按钮，不动原有入口。
      -->
      <el-button
        type="warning"
        plain
        :loading="urlSyncing"
        @click="syncActorUrls"
      >同步主页URL</el-button>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAvatarSrc } from '@/utils/media'
import { scrapeAllPornhubActorProfilesEnhanced, pornhubBackfillUrls } from '@/api/pornhub'

const router = useRouter()
const store = usePornhubStore()
const keyword = ref('')
const loading = ref(false)
const batchScraping = ref(false)
const avatarScraping = ref(false)
const urlSyncing = ref(false)
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
    actors.value = await store.loadActors()
    if (!store.actorNationality && !keyword.value) {
      allTotal.value = store.actorTotal
    }
  } finally {
    loading.value = false
  }
}

// 🔴 2026-10-14 修复「点第二页没反应」：
//   `loadActors()` 原先无条件执行 `store.actorPage = 1`，而 `onActorPageChange`
//   正好也调 `loadActors()` ⇒ 点第 2 页 → 页码刚被设成 2 → 立刻被重置回 1
//   → 又渲染第 1 页 ⇒ **看起来点了没反应**（死循环）。
//   正确做法：页码归 1 只发生在「筛选条件变化」时（换搜索词 / 换国籍 / 换每页条数），
//   翻页本身绝不能归 1。
function searchActors() {
  // 换搜索词回到第一页，否则会停在第 N 页而看不到结果
  store.actorPage = 1
  return loadActors()
}

// 分页：换页 / 换每页条数（2026-10-13 补齐分页组件，2026-10-14 修好换页失效）
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

// 批量下载头像（2026-10-14 新增 UI 入口，调用早已存在的后端接口）
// 后端是 BackgroundTasks 异步跑，接口立即返回 started ⇒ 只能提示"已启动"，
// 进度要看服务日志（logger.info「PORNHub 批量头像下载 完成: success=… failed=…」）。
async function syncActorUrls() {
  try {
    await ElMessageBox.confirm(
      '将从 PornSimilarityPlatform 的资料库同步每位演员的 PornHub 主页 URL' +
      '（只补齐缺失的，不会覆盖已有地址）。同步后演员详情页的「主页」链接可直接点击，' +
      '资料刮削也会直接使用该地址。是否继续？',
      '同步演员主页URL',
      { confirmButtonText: '开始同步', cancelButtonText: '取消', type: 'info' },
    )
  } catch {
    return  // 用户点了取消
  }

  urlSyncing.value = true
  try {
    const res = await pornhubBackfillUrls()
    const matched = res?.matched ?? 0
    const notFound = res?.not_found ?? 0
    if (matched > 0) {
      ElMessage.success(`已同步 ${matched} 位演员的主页URL`)
      setTimeout(() => loadActors(), 1500)
    } else if (res?.status === 'error') {
      ElMessage.error(`同步失败：${res.message || '外部资料库不可读'}`)
    } else {
      ElMessage.info(`没有需要同步的演员（未匹配 ${notFound} 位）`)
    }
  } catch (e) {
    ElMessage.error(`同步失败：${e?.message || e}`)
  } finally {
    urlSyncing.value = false
  }
}

async function batchDownloadAvatars() {
  try {
    await ElMessageBox.confirm(
      '将为**缺少头像**的演员批量下载头像（仅从 PornHub 资料页获取，不使用其他站点）。' +
      '任务在后台进行，数量较多时可能需要较长时间。是否继续？',
      '批量下载演员头像',
      { confirmButtonText: '开始下载', cancelButtonText: '取消', type: 'info' },
    )
  } catch {
    return  // 用户点了取消
  }

  avatarScraping.value = true
  try {
    // 传给后端的默认参数与 UI 文案对齐：只补缺失、限 2000 人
    const res = await store.batchDownloadAvatars({ only_missing: true, limit: 2000 })
    ElMessage.success(res?.message || '已启动批量头像下载（后台进行）')
    // 后台任务可能要跑很久，延迟后刷一次列表让新头像尽快显示
    setTimeout(() => loadActors(), 5000)
  } catch (e) {
    ElMessage.error(`启动头像下载失败：${e?.message || e}`)
  } finally {
    avatarScraping.value = false
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
