<template>
  <div class="actor-merge">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">
            <el-icon><UserFilled /></el-icon> 👥 演员合并管理
          </span>
          <el-tag type="info" size="small">参考 JavBoss MergeJavIdols</el-tag>
        </div>
      </template>

      <el-alert title="将同一个演员的重复条目合并为一个。被合并演员的名称会自动成为目标演员的「其他名称」(alias)，其所有影片关联自动迁移。" type="info" show-icon :closable="false" style="margin-bottom:16px" />

      <el-tabs v-model="activeTab">
        <el-tab-pane label="搜索合并" name="search">
          <div style="margin-bottom:16px">
            <el-input v-model="searchName" placeholder="输入演员名称搜索" clearable style="width:400px" @keyup.enter="search">
              <template #append>
                <el-button @click="search" :loading="searching">
                  <el-icon><Search /></el-icon> 搜索
                </el-button>
              </template>
            </el-input>
          </div>
          <el-table v-if="searchResult.length" :data="searchResult" stripe size="small">
            <el-table-column type="index" width="50" />
            <el-table-column prop="name" label="演员名" min-width="140" />
            <el-table-column prop="name_jp" label="日文名" width="120">
              <template #default="{ row }">{{ row.name_jp || '-' }}</template>
            </el-table-column>
            <el-table-column prop="alias" label="其他名称" min-width="180">
              <template #default="{ row }">{{ row.alias || '-' }}</template>
            </el-table-column>
            <el-table-column prop="similarity" label="相似度" width="100">
              <template #default="{ row }">
                <el-tag :type="row.similarity > 0.85 ? 'success' : row.similarity > 0.7 ? 'warning' : 'info'" size="small">
                  {{ (row.similarity * 100).toFixed(0) }}%
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="selectTarget(row)">选为目标</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!searching && !searchResult.length && searchName" description="未找到相似演员" />
        </el-tab-pane>

        <el-tab-pane label="指定ID合并" name="byid">
          <el-form label-width="140px" style="max-width:520px">
            <el-form-item label="目标演员 ID">
              <el-input-number v-model="form.canonical_id" :min="1" />
            </el-form-item>
            <el-form-item label="被合并演员 ID">
              <el-select v-model="form.source_ids" multiple filterable allow-create default-first-option placeholder="输入演员ID">
                <el-option v-for="id in form.source_ids" :key="id" :label="id" :value="id" />
              </el-select>
              <div style="font-size:12px;color:#999;margin-top:4px">可输入多个 ID，合并后其名称成为目标演员的其他名称</div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="execMerge" :loading="merging">
                <el-icon><Connection /></el-icon> 执行合并
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="其他名称管理" name="alias">
          <div style="margin-bottom:16px;display:flex;gap:8px;flex-wrap:wrap">
            <el-input v-model="aliasQuery" placeholder="输入演员名称或 ID 查询" clearable style="width:300px" @keyup.enter="queryActor">
              <template #append>
                <el-button @click="queryActor">
                  <el-icon><Search /></el-icon> 查询
                </el-button>
              </template>
            </el-input>
          </div>
          <el-card v-if="aliasActor" shadow="never" style="max-width:640px">
            <el-descriptions :column="2" size="small" border style="margin-bottom:12px">
              <el-descriptions-item label="ID">{{ aliasActor.id }}</el-descriptions-item>
              <el-descriptions-item label="名称">{{ aliasActor.name }}</el-descriptions-item>
              <el-descriptions-item label="日文名">{{ aliasActor.name_jp || '-' }}</el-descriptions-item>
              <el-descriptions-item label="英文名">{{ aliasActor.name_en || '-' }}</el-descriptions-item>
            </el-descriptions>
            <el-form label-width="100px">
              <el-form-item label="其他名称">
                <el-input v-model="aliasEdit" type="textarea" :rows="3" placeholder="逗号分隔，如：松本一香, 松本いちか, Ichika Matsumoto" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="saveAlias" :loading="savingAlias">保存其他名称</el-button>
                <el-button @click="fetchJavdb" :loading="fetchingJavdb">从 JAVDB 拉取</el-button>
              </el-form-item>
              <div v-if="javdbHint" style="font-size:12px;color:#e6a23c;margin-top:4px">{{ javdbHint }}</div>
              <div v-if="javdbAliases.length" style="margin-top:8px">
                <div style="font-size:12px;color:#999;margin-bottom:6px">JAVDB 返回的其他名称（点击填入）：</div>
                <el-tag v-for="a in javdbAliases" :key="a" closable style="margin:0 6px 6px 0" @close="javdbAliases = javdbAliases.filter(x => x !== a)">
                  {{ a }}
                </el-tag>
                <div style="margin-top:8px">
                  <el-button size="small" type="success" @click="applyJavdbAliases">全部填入</el-button>
                </div>
              </div>
            </el-form>
          </el-card>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-card v-if="selectedTarget" shadow="never" style="margin-top:16px">
      <template #header>
        <span class="card-title"><el-icon><UserFilled /></el-icon> 目标演员：{{ selectedTarget.name }}</span>
      </template>
      <el-descriptions :column="3" size="small" border style="margin-bottom:12px">
        <el-descriptions-item label="ID">{{ selectedTarget.id }}</el-descriptions-item>
        <el-descriptions-item label="名称">{{ selectedTarget.name }}</el-descriptions-item>
        <el-descriptions-item label="日文名">{{ selectedTarget.name_jp || '-' }}</el-descriptions-item>
        <el-descriptions-item label="其他名称" :span="2">{{ selectedTarget.alias || '无' }}</el-descriptions-item>
      </el-descriptions>
      <el-button size="small" :disabled="!selectedTarget.id" @click="loadCandidates">
        <el-icon><Search /></el-icon> 查找合并候选
      </el-button>
      <div v-if="candidates.length" style="margin-top:12px">
        <el-table :data="candidates" stripe size="small" @selection-change="rows => selectedCandidateRows = rows">
          <el-table-column type="selection" width="50" />
          <el-table-column prop="name" label="演员名" />
          <el-table-column prop="alias" label="其他名称" min-width="180">
            <template #default="{ row }">{{ row.alias || '-' }}</template>
          </el-table-column>
          <el-table-column prop="similarity" label="相似度" width="100">
            <template #default="{ row }">
              <el-tag :type="row.similarity > 0.85 ? 'success' : 'warning'" size="small">
                {{ (row.similarity * 100).toFixed(0) }}%
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <div style="margin-top:12px">
          <el-button type="primary" @click="mergeCandidates" :loading="merging" :disabled="!selectedCandidateRows.length">
            <el-icon><Connection /></el-icon> 合并选中 ({{ selectedCandidateRows.length }})
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card v-if="mergeResult" shadow="never" style="margin-top:16px">
      <template #header>
        <span class="card-title"><el-icon><CircleCheckFilled /></el-icon> 合并结果</span>
      </template>
      <el-result icon="success" :title="`合并成功：${mergeResult.canonical_name}`">
        <template #extra>
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="目标演员">{{ mergeResult.canonical_name }}</el-descriptions-item>
            <el-descriptions-item label="合并数量">{{ mergeResult.merged_names?.length }}</el-descriptions-item>
            <el-descriptions-item label="合并自" :span="2">{{ mergeResult.merged_names?.join(', ') }}</el-descriptions-item>
            <el-descriptions-item label="其他名称" :span="2">{{ mergeResult.aliases }}</el-descriptions-item>
            <el-descriptions-item label="影片更新" :span="2">{{ mergeResult.movies_updated }} 部</el-descriptions-item>
          </el-descriptions>
        </template>
      </el-result>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Connection, UserFilled, CircleCheckFilled } from '@element-plus/icons-vue'
import { searchSimilarActors, mergeActors, updateActorAlias, fetchJavdbAliases, getActor } from '@/api'

const activeTab = ref('search')
const searchName = ref('')
const searching = ref(false)
const merging = ref(false)
const searchResult = ref([])
const selectedTarget = ref(null)
const candidates = ref([])
const selectedCandidateRows = ref([])
const mergeResult = ref(null)

const form = reactive({
  canonical_id: 1,
  source_ids: [],
})

const aliasQuery = ref('')
const aliasActor = ref(null)
const aliasEdit = ref('')
const savingAlias = ref(false)
const fetchingJavdb = ref(false)
const javdbAliases = ref([])
const javdbHint = ref('')

async function search() {
  if (!searchName.value.trim()) return
  searching.value = true
  try {
    const res = await searchSimilarActors({ name: searchName.value.trim() })
    searchResult.value = res.items || []
  } catch (e) {
    ElMessage.error('搜索失败: ' + (e.message || e))
  } finally {
    searching.value = false
  }
}

function selectTarget(row) {
  selectedTarget.value = row
  candidates.value = []
  selectedCandidateRows.value = []
}

async function loadCandidates() {
  if (!selectedTarget.value) return
  try {
    const res = await searchSimilarActors({ name: selectedTarget.value.name })
    candidates.value = (res.items || []).filter(c => c.id !== selectedTarget.value.id)
  } catch { }
}

async function execMerge() {
  if (!form.canonical_id || !form.source_ids.length) {
    ElMessage.warning('请填写目标演员 ID 和被合并演员 ID')
    return
  }
  merging.value = true
  try {
    const res = await mergeActors({
      canonical_id: form.canonical_id,
      source_ids: form.source_ids,
    })
    if (res.error) { ElMessage.error(res.error); return }
    mergeResult.value = res
    ElMessage.success(`合并成功：${res.merged_names?.length} 个演员已合并`)
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.message || e))
  } finally {
    merging.value = false
  }
}

async function mergeCandidates() {
  if (!selectedTarget.value || !selectedCandidateRows.value.length) return
  merging.value = true
  try {
    const res = await mergeActors({
      canonical_id: selectedTarget.value.id,
      source_ids: selectedCandidateRows.value.map(c => c.id),
    })
    if (res.error) { ElMessage.error(res.error); return }
    mergeResult.value = res
    ElMessage.success(`合并成功：${res.merged_names?.length} 个演员已合并`)
    candidates.value = []
    selectedCandidateRows.value = []
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.message || e))
  } finally {
    merging.value = false
  }
}

async function queryActor() {
  const q = aliasQuery.value.trim()
  if (!q) return
  aliasActor.value = null
  aliasEdit.value = ''
  javdbAliases.value = []
  javdbHint.value = ''
  try {
    let actor = null
    if (/^\d+$/.test(q)) {
      actor = await getActor(parseInt(q))
    } else {
      const res = await searchSimilarActors({ name: q, threshold: 0.9 })
      const exact = (res.items || []).find(i => i.name === q || i.name_jp === q)
      actor = exact ? await getActor(exact.id) : null
    }
    if (actor) {
      aliasActor.value = actor
      aliasEdit.value = actor.alias || ''
    } else {
      ElMessage.warning('未找到该演员')
    }
  } catch (e) {
    ElMessage.error('查询失败: ' + (e.message || e))
  }
}

async function saveAlias() {
  if (!aliasActor.value) return
  savingAlias.value = true
  try {
    const res = await updateActorAlias(aliasActor.value.id, { alias: aliasEdit.value })
    aliasActor.value.alias = res.alias
    ElMessage.success('其他名称已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || e))
  } finally {
    savingAlias.value = false
  }
}

async function fetchJavdb() {
  if (!aliasActor.value) return
  fetchingJavdb.value = true
  javdbHint.value = ''
  javdbAliases.value = []
  try {
    const res = await fetchJavdbAliases(aliasActor.value.id)
    if (res.status === 'error') {
      javdbHint.value = res.message || 'JAVDB 拉取失败'
    } else if (res.status === 'empty') {
      javdbHint.value = 'JAVDB 未返回其他名称，可手动填写'
    } else {
      javdbAliases.value = res.aliases || []
      if (!javdbAliases.value.length) javdbHint.value = 'JAVDB 未返回其他名称，可手动填写'
    }
  } catch (e) {
    javdbHint.value = 'JAVDB 拉取失败: ' + (e.message || e)
  } finally {
    fetchingJavdb.value = false
  }
}

function applyJavdbAliases() {
  if (!aliasEdit.value) {
    aliasEdit.value = javdbAliases.value.join(', ')
  } else {
    const existing = new Set(aliasEdit.value.split(',').map(s => s.trim()).filter(Boolean))
    const added = javdbAliases.value.filter(a => !existing.has(a))
    aliasEdit.value = [...existing, ...added].join(', ')
  }
  javdbAliases.value = []
  ElMessage.success('已填入，点击「保存其他名称」生效')
}
</script>

<style scoped>
.actor-merge { padding: 20px 24px; }
.card-header { display: flex; align-items: center; gap: 8px; }
.card-title { font-size: 16px; font-weight: 500; display: flex; align-items: center; gap: 4px; }
</style>
