<template>
  <div class="actor-merge">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">
            <el-icon><User /></el-icon> 🎬 演员合并管理
          </span>
          <div>
            <el-tag type="info" size="small">参考 JavBoss v1.9.0 女优合并</el-tag>
          </div>
        </div>
      </template>

      <el-alert title="将同一个演员的重复条目合并为一个。被合并的演员会成为目标演员的别名，所有影片关联自动迁移。" type="info" show-icon :closable="false" style="margin-bottom:16px" />

      <el-tabs v-model="activeTab">
        <!-- 方式一：搜索演员来合并 -->
        <el-tab-pane label="搜索合并" name="search">
          <div style="margin-bottom:16px">
            <el-input v-model="searchName" placeholder="输入演员名称搜索" clearable style="width:400px" @keyup.enter="searchActor">
              <template #append>
                <el-button @click="searchActor" :loading="searching">
                  <el-icon><Search /></el-icon> 搜索
                </el-button>
              </template>
            </el-input>
          </div>
          <el-table v-if="searchResult.length" :data="searchResult" stripe size="small" @row-click="selectTarget">
            <el-table-column type="index" width="50" />
            <el-table-column prop="name" label="演员名" />
            <el-table-column prop="alias" label="别名" min-width="200">
              <template #default="{ row }">{{ row.alias || '-' }}</template>
            </el-table-column>
            <el-table-column prop="movie_count" label="作品数" width="100" sortable />
            <el-table-column prop="similarity" label="相似度" width="100">
              <template #default="{ row }">
                <el-tag :type="row.similarity > 0.9 ? 'success' : row.similarity > 0.8 ? 'warning' : 'info'" size="small">
                  {{ (row.similarity * 100).toFixed(0) }}%
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click.stop="selectAsTarget(row)">选为目标</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!searching && !searchResult.length && searchName" description="未找到相似演员" />
        </el-tab-pane>

        <!-- 方式二：指定演员ID -->
        <el-tab-pane label="指定ID合并" name="byid">
          <el-form label-width="120px" style="max-width:500px">
            <el-form-item label="目标演员 ID">
              <el-input-number v-model="mergeForm.canonical_id" :min="1" />
            </el-form-item>
            <el-form-item label="被合并演员 ID">
              <el-select v-model="mergeForm.source_ids" multiple filterable allow-create default-first-option placeholder="输入演员ID">
                <el-option v-for="id in mergeForm.source_ids" :key="id" :label="id" :value="id" />
              </el-select>
              <div style="font-size:12px;color:#999;margin-top:4px">可输入多个 ID，用逗号分隔</div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="executeMerge" :loading="merging">
                <el-icon><Connection /></el-icon> 执行合并
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 合并详情 -->
    <el-card shadow="never" style="margin-top:16px" v-if="selectedActor">
      <template #header>
        <span class="card-title"><el-icon><UserFilled /></el-icon> 目标演员：{{ selectedActor.name }}</span>
      </template>
      <div style="margin-bottom:12px">
        <el-descriptions :column="3" size="small" border>
          <el-descriptions-item label="ID">{{ selectedActor.id }}</el-descriptions-item>
          <el-descriptions-item label="名称">{{ selectedActor.name }}</el-descriptions-item>
          <el-descriptions-item label="作品数">{{ selectedActor.movie_count }}</el-descriptions-item>
          <el-descriptions-item label="别名" :span="3">{{ selectedActor.alias || '无' }}</el-descriptions-item>
        </el-descriptions>
      </div>
      <div v-if="candidates.length" class="candidate-section">
        <h4 style="margin-bottom:8px">相似演员（推荐合并候选）</h4>
        <el-table :data="candidates" stripe size="small">
          <el-table-column type="selection" width="50" />
          <el-table-column prop="name" label="演员名" />
          <el-table-column prop="alias" label="别名" min-width="180">
            <template #default="{ row }">{{ row.alias || '-' }}</template>
          </el-table-column>
          <el-table-column prop="movie_count" label="作品数" width="80" sortable />
          <el-table-column prop="similarity" label="相似度" width="100">
            <template #default="{ row }">
              <el-tag :type="row.similarity > 0.9 ? 'success' : row.similarity > 0.8 ? 'warning' : 'info'" size="small">
                {{ (row.similarity * 100).toFixed(0) }}%
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <div style="margin-top:12px">
          <el-button type="primary" @click="mergeSelectedCandidates" :loading="merging" :disabled="!selectedCandidates.length">
            <el-icon><Connection /></el-icon> 合并选中 ({{ selectedCandidates.length }})
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 合并结果 -->
    <el-card shadow="never" style="margin-top:16px" v-if="mergeResult">
      <template #header>
        <span class="card-title"><el-icon><CircleCheckFilled /></el-icon> 合并结果</span>
      </template>
      <el-result icon="success" :title="`合并成功：${mergeResult.canonical_name}`">
        <template #extra>
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="目标演员">{{ mergeResult.canonical_name }}</el-descriptions-item>
            <el-descriptions-item label="合并数量">{{ mergeResult.merged_names?.length }}</el-descriptions-item>
            <el-descriptions-item label="合并演员" :span="2">{{ mergeResult.merged_names?.join(', ') }}</el-descriptions-item>
            <el-descriptions-item label="当前别名" :span="2">{{ mergeResult.aliases }}</el-descriptions-item>
            <el-descriptions-item label="总作品数" :span="2">{{ mergeResult.total_movies }}</el-descriptions-item>
          </el-descriptions>
        </template>
      </el-result>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, User, UserFilled, Connection, CircleCheckFilled } from '@element-plus/icons-vue'
import { searchSimilarActors, mergeJavActors, getMergeCandidates } from '@/api/jav'

const activeTab = ref('search')
const searchName = ref('')
const searching = ref(false)
const merging = ref(false)
const searchResult = ref([])
const selectedActor = ref(null)
const candidates = ref([])
const mergeResult = ref(null)
const selectedCandidateRows = ref([])

const mergeForm = reactive({
  canonical_id: 1,
  source_ids: [],
})

const selectedCandidates = computed(() => selectedCandidateRows.value)

async function searchActor() {
  if (!searchName.value.trim()) return
  searching.value = true
  try {
    const res = await searchSimilarActors(searchName.value.trim())
    searchResult.value = res.items || []
    if (!searchResult.value.length) {
      ElMessage.info('未找到相似演员')
    }
  } catch (e) {
    ElMessage.error('搜索失败: ' + (e.message || e))
  } finally {
    searching.value = false
  }
}

function selectAsTarget(actor) {
  selectedActor.value = actor
  loadMergeCandidates(actor.id)
}

async function selectTarget(row) {
  selectedActor.value = row
  loadMergeCandidates(row.id)
}

async function loadMergeCandidates(actorId) {
  try {
    const res = await getMergeCandidates(actorId)
    candidates.value = res.candidates || []
  } catch (e) {
    candidates.value = []
  }
}

async function executeMerge() {
  if (!mergeForm.canonical_id || !mergeForm.source_ids.length) {
    ElMessage.warning('请填写目标演员ID和被合并演员ID')
    return
  }
  merging.value = true
  try {
    const res = await mergeJavActors({
      canonical_id: mergeForm.canonical_id,
      source_ids: mergeForm.source_ids,
    })
    if (res.error) {
      ElMessage.error(res.error)
      return
    }
    mergeResult.value = res
    ElMessage.success(`合并成功：${res.merged_names?.length} 个演员合并到 ${res.canonical_name}`)
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.message || e))
  } finally {
    merging.value = false
  }
}

async function mergeSelectedCandidates() {
  if (!selectedActor.value || !selectedCandidateRows.value.length) return

  await ElMessageBox.confirm(
    `确认将 ${selectedCandidateRows.value.length} 个演员合并到 ${selectedActor.value.name}？`,
    '确认合并',
    { confirmButtonText: '合并', cancelButtonText: '取消', type: 'warning' }
  )

  merging.value = true
  try {
    const res = await mergeJavActors({
      canonical_id: selectedActor.value.id,
      source_ids: selectedCandidateRows.value.map(r => r.id),
    })
    if (res.error) {
      ElMessage.error(res.error)
      return
    }
    mergeResult.value = res
    selectedActor.value = null
    candidates.value = []
    selectedCandidateRows.value = []
    ElMessage.success(`合并成功：${res.merged_names?.length} 个演员合并到 ${res.canonical_name}`)
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.message || e))
  } finally {
    merging.value = false
  }
}
</script>

<style scoped>
.actor-merge { max-width: 1200px; margin: 0 auto; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 15px; }
.candidate-section { padding-top: 16px; border-top: 1px solid var(--el-border-color-lighter); }
</style>
