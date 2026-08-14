<template>
  <div class="folder-check">
    <el-alert type="info" :closable="false" show-icon class="page-tip">
      <template #title>
        文件夹归属检测：演员文件夹里存放的一定是该演员的作品。很多素人企划片的
        <code>movies.actor</code> 只写了「佚名 / 素人名 / 艺名」，导致演员页作品数少于文件夹里的实际文件数。
        本页扫描全部 JAV 有码文件夹，找出「文件夹归属演员未写入作品」的影片，可一键回填。
        <b>前置校验</b>：目录名必须是「已收录演员名」才会被采纳——素人、原作改編、催眠系列、
        经典名录 等系列/收藏目录不参与本功能，避免把系列名误当演员回填。
      </template>
    </el-alert>

    <div class="toolbar">
      <el-input v-model="actorFilter" placeholder="按演员筛选（如：森日向子）" clearable
        style="width: 240px" @keyup.enter="search" @clear="search">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" :loading="loading" @click="search">
        <el-icon><Search /></el-icon> 检测
      </el-button>
      <el-button type="success" :loading="filling" @click="fillAll">
        <el-icon><Check /></el-icon> 一键回填全部（{{ summary.total_movies }} 部）
      </el-button>
      <el-button type="warning" plain :disabled="!actorFilter" :loading="filling" @click="fillActor">
        <el-icon><Check /></el-icon> 仅回填「{{ actorFilter }}」相关
      </el-button>
      <span class="muted">回填后自动重算演员作品数</span>
    </div>

    <el-row :gutter="12" class="stat-row">
      <el-col :span="8">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value">{{ summary.total_movies }}</div>
          <div class="stat-label">有差异影片（文件夹归属 ≠ actor 字段）</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value">{{ summary.actor_count }}</div>
          <div class="stat-label">涉及演员数</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="stat-card">
          <template #header>
            <span class="stat-label">缺失最多的演员（点击筛选）</span>
          </template>
          <div class="top-actors">
            <el-tag v-for="a in summary.top_actors" :key="a.name" class="top-tag" effect="plain"
              :type="actorFilter === a.name ? 'primary' : 'info'" @click="pickActor(a.name)">
              {{ a.name }} · {{ a.count }}
            </el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-table :data="pageItems" v-loading="loading" border stripe class="diff-table">
      <el-table-column prop="code" label="番号" width="130">
        <template #default="{ row }">
          <span class="code" @click="goMovie(row.id)">{{ row.code }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="title" label="标题" min-width="260" show-overflow-tooltip />
      <el-table-column prop="actor" label="当前 actor" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.actor">{{ row.actor }}</span>
          <el-tag v-else size="small" type="info" effect="plain">空</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="folder_actors" label="文件夹归属演员" min-width="180">
        <template #default="{ row }">
          <el-tag v-for="n in row.folder_actors" :key="n" size="small" class="folder-tag">{{ n }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="missing" label="缺失（待回填）" min-width="160">
        <template #default="{ row }">
          <el-tag v-for="n in row.missing" :key="n" size="small" type="danger" class="folder-tag">{{ n }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="success" plain @click="fillMovie(row)">回填</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-wrap" v-if="total > pageSize">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize"
        :total="total" :page-sizes="[20, 50, 100, 200]" layout="total, sizes, prev, pager, next"
        @size-change="page = 1" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Search } from '@element-plus/icons-vue'
import { fillJavFolderCheck, getJavFolderCheck } from '@/api/jav'

const router = useRouter()
const loading = ref(false)
const filling = ref(false)
const actorFilter = ref('')
const items = ref([])
const summary = reactive({ total_movies: 0, actor_count: 0, top_actors: [] })
const page = ref(1)
const pageSize = ref(20)

const total = computed(() => items.value.length)
const pageItems = computed(() => items.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))

async function search() {
  loading.value = true
  try {
    const res = await getJavFolderCheck({ actor: actorFilter.value || undefined })
    items.value = res.items || []
    Object.assign(summary, res.summary || {})
    page.value = 1
  } catch (e) {
    ElMessage.error('检测失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function pickActor(name) {
  actorFilter.value = name
  search()
}

async function runFill(payload, confirmMsg) {
  if (confirmMsg) {
    await ElMessageBox.confirm(confirmMsg, '确认回填', { type: 'warning' })
  }
  filling.value = true
  try {
    const res = await fillJavFolderCheck(payload)
    ElMessage.success('回填任务已启动（后台执行，稍后重新检测确认）')
    setTimeout(() => search(), 3000)
  } catch (e) {
    ElMessage.error('回填失败：' + (e?.message || e))
  } finally {
    filling.value = false
  }
}

function fillAll() {
  if (!summary.total_movies) { ElMessage.info('暂无差异项'); return }
  runFill({}, `确认一键回填全部 ${summary.total_movies} 部影片？\n将把文件夹归属演员追加写入 actor 字段，并重算演员作品数。`)
}

function fillActor() {
  const name = actorFilter.value.trim()
  if (!name) return
  const cnt = items.value.length
  runFill({ actor: name }, `确认仅回填「${name}」相关的 ${cnt} 部影片？`)
}

async function fillMovie(row) {
  await ElMessageBox.confirm(
    `确认回填「${row.code}」？将追加写入：${row.missing.join('、')}`,
    '确认回填', { type: 'warning' }
  )
  await runFill({ actor: row.missing[0] }, '')
}

function goMovie(id) {
  router.push(`/jav/movies/${id}`)
}

onMounted(search)
</script>

<style scoped>
.page-tip { margin-bottom: 12px; }
.toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.muted { color: #909399; font-size: 12px; }
.stat-row { margin-bottom: 12px; }
.stat-card { text-align: center; }
.stat-value { font-size: 28px; font-weight: 600; color: #409eff; }
.stat-label { font-size: 13px; color: #909399; margin-top: 4px; }
.top-actors { max-height: 120px; overflow-y: auto; text-align: left; }
.top-tag { margin: 2px 4px 2px 0; cursor: pointer; }
.code { color: #409eff; cursor: pointer; font-weight: 600; }
.folder-tag { margin-right: 4px; }
.diff-table { width: 100%; }
.pagination-wrap { margin-top: 12px; display: flex; justify-content: flex-end; }
</style>
