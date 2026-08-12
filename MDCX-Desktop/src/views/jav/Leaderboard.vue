<template>
  <div class="leaderboard">
    <el-card shadow="never">
      <template #header>
        <span class="card-title">
          <el-icon><DataAnalysis /></el-icon> 🔥 AV联盟 实时人气榜单
        </span>
      </template>

      <!-- 筛选区 -->
      <div class="filter-bar">
        <el-radio-group v-model="kind" @change="reload">
          <el-radio-button value="all">全女优榜</el-radio-button>
          <el-radio-button value="new">新人榜</el-radio-button>
        </el-radio-group>

        <el-select v-model="period" style="width: 140px" @change="reload">
          <el-option label="24小时" value="24h" />
          <el-option label="3日" value="3d" />
          <el-option label="30日" value="30d" />
          <el-option label="年度" value="year" />
          <el-option label="新着" value="newest" />
          <el-option label="全部" value="all" />
        </el-select>

        <el-select v-model="tag" placeholder="全部标签" clearable style="width: 140px" @change="reload">
          <el-option v-for="t in tags" :key="t.id" :label="t.name" :value="t.id" />
        </el-select>

        <div class="spacer" />

        <!-- 演员新作检测 -->
        <el-input
          v-model="searchName"
          placeholder="输入演员名，检测 AV联盟 新作"
          clearable
          style="width: 260px"
          @keyup.enter="checkWorks"
        >
          <template #append>
            <el-button @click="checkWorks" :loading="checking">
              <el-icon><Search /></el-icon> 新作检测
            </el-button>
          </template>
        </el-input>
      </div>

      <el-alert
        title="榜单实时抓取自 av-league.com，每次请求均为最新数据。点击演员名可跳转站内详情页。"
        type="info"
        show-icon
        :closable="false"
        style="margin: 12px 0"
      />

      <!-- 榜单表格 -->
      <el-table v-loading="loading" :data="items" stripe size="small">
        <el-table-column label="排名" width="70" align="center">
          <template #default="{ row }">
            <span :class="['rank-badge', { top: row.rank <= 3 }]">{{ row.rank }}</span>
          </template>
        </el-table-column>
        <el-table-column label="头像" width="90" align="center">
          <template #default="{ row }">
            <el-avatar :src="fullUrl(row.avatar_url)" :size="48" shape="square">
              {{ row.name?.slice(0, 1) }}
            </el-avatar>
          </template>
        </el-table-column>
        <el-table-column label="演员名">
          <template #default="{ row }">
            <a :href="row.actress_url" target="_blank" rel="noopener" class="actress-link">
              {{ row.name }}
            </a>
          </template>
        </el-table-column>
        <el-table-column label="票数" width="120" align="right">
          <template #default="{ row }">
            <span class="score">{{ row.score.toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="checkWorks(row.name)">
              <el-icon><Search /></el-icon> 新作
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          :page-size="60"
          :current-page="page"
          @current-change="onPage"
        />
      </div>
    </el-card>

    <!-- 新作检测弹窗 -->
    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="720px" top="6vh">
      <template v-if="worksResult">
        <div v-if="worksResult.actor" class="actor-head">
          <el-avatar :src="fullUrl(worksResult.actor.avatar_url)" :size="56" shape="square" />
          <div>
            <div class="actor-name">{{ worksResult.actor.name }}</div>
            <div class="actor-meta">
              检测到 {{ worksResult.total }} 部近期作品 ·
              <span class="new-highlight">{{ worksResult.new_count }} 部本地未收录</span>
            </div>
          </div>
        </div>

        <el-empty v-if="!worksResult.works.length" description="未获取到作品" />

        <div v-else class="works-grid">
          <div v-for="w in worksResult.works" :key="w.work_id" class="work-card">
            <el-image
              :src="fullUrl(w.cover_url)"
              fit="cover"
              class="work-cover"
              :preview-src-list="[fullUrl(w.cover_url)]"
              preview-teleported
            >
              <template #error>
                <div class="cover-placeholder">无封面</div>
              </template>
            </el-image>
            <div class="work-info">
              <div class="work-title" :title="w.title">{{ w.title || '（无标题）' }}</div>
              <div class="work-date">{{ w.release_date || '未知发售日' }}</div>
              <div class="work-row">
                <el-tag size="small" type="info" class="work-code">{{ w.code || '未识别番号' }}</el-tag>
                <el-tag size="small" :type="w.has_local ? 'success' : 'warning'">
                  {{ w.has_local ? '已收录' : '新作' }}
                </el-tag>
              </div>
            </div>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { DataAnalysis, Search } from '@element-plus/icons-vue'
import { getAvLeagueLeaderboard, getAvLeagueActorWorks } from '@/api'

const AV_LEAGUE_BASE = 'https://www.av-league.com'

// 榜单标签（ctag ID，来源于站点标签页）
const tags = [
  { id: 27, name: '巨乳' },
  { id: 19, name: '美少女' },
  { id: 50, name: '20代' },
  { id: 1, name: '可爱系' },
]

const kind = ref('all')
const period = ref('3d')
const tag = ref(null)
const page = ref(1)

const loading = ref(false)
const items = ref([])
const total = ref(0)

// 新作检测
const checking = ref(false)
const searchName = ref('')
const dialogVisible = ref(false)
const worksResult = ref(null)
const dialogTitle = computed(() =>
  worksResult.value?.actor ? `${worksResult.value.actor.name} · AV联盟 新作检测` : '新作检测'
)

function fullUrl(url) {
  if (!url) return ''
  return url.startsWith('http') ? url : `${AV_LEAGUE_BASE}${url}`
}

async function load() {
  loading.value = true
  try {
    const params = { kind: kind.value, period: period.value, page: page.value }
    if (tag.value) params.tag = tag.value
    const res = await getAvLeagueLeaderboard(params)
    items.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function onPage(p) {
  page.value = p
  load()
}

async function checkWorks(name) {
  const target = name || searchName.value
  if (!target || !target.trim()) return
  checking.value = true
  try {
    const res = await getAvLeagueActorWorks({ name: target.trim(), limit: 15, module: 'jav' })
    worksResult.value = res
    dialogVisible.value = true
  } catch (e) {
    worksResult.value = { actor: null, total: 0, new_count: 0, works: [] }
    dialogVisible.value = true
  } finally {
    checking.value = false
  }
}

load()
</script>

<style scoped>
.leaderboard { max-width: 1100px; margin: 0 auto; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 15px; }
.filter-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.spacer { flex: 1; }

.rank-badge {
  display: inline-block;
  min-width: 26px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-weight: 600;
}
.rank-badge.top { background: #fde2a8; color: #8a5a00; }

.actress-link { color: var(--el-color-primary); text-decoration: none; font-weight: 500; }
.actress-link:hover { text-decoration: underline; }
.score { font-weight: 600; color: #e05b5b; }

.pager { display: flex; justify-content: flex-end; margin-top: 12px; }

.actor-head { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--el-border-color-lighter); }
.actor-name { font-size: 17px; font-weight: 700; }
.actor-meta { color: var(--el-text-color-secondary); font-size: 13px; margin-top: 2px; }
.new-highlight { color: #e05b5b; font-weight: 600; }

.works-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; max-height: 56vh; overflow-y: auto; padding-right: 4px; }
.work-card { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; overflow: hidden; }
.work-cover { width: 100%; height: 200px; display: block; }
.cover-placeholder { width: 100%; height: 200px; display: flex; align-items: center; justify-content: center; background: var(--el-fill-color-light); color: var(--el-text-color-secondary); font-size: 13px; }
.work-info { padding: 8px; }
.work-title { font-size: 13px; line-height: 1.4; height: 36px; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.work-date { font-size: 12px; color: var(--el-text-color-secondary); margin: 4px 0 6px; }
.work-row { display: flex; gap: 4px; align-items: center; justify-content: space-between; }
.work-code { font-family: monospace; max-width: 120px; overflow: hidden; text-overflow: ellipsis; }
</style>
