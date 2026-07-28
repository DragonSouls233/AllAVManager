<template>
  <div class="studio-merge">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">
            <el-icon><OfficeBuilding /></el-icon> 🏢 片商合并管理
          </span>
          <el-tag type="info" size="small">参考 JavBoss v1.9.0 片商别名管理</el-tag>
        </div>
      </template>

      <el-alert title="将同一个片商的重复条目合并为一个。被合并的片商会成为目标片商的别名，所有影片关联自动迁移。" type="info" show-icon :closable="false" style="margin-bottom:16px" />

      <el-tabs v-model="activeTab">
        <el-tab-pane label="搜索合并" name="search">
          <div style="margin-bottom:16px">
            <el-input v-model="searchName" placeholder="输入片商名称搜索" clearable style="width:400px" @keyup.enter="search">
              <template #append>
                <el-button @click="search" :loading="searching">
                  <el-icon><Search /></el-icon> 搜索
                </el-button>
              </template>
            </el-input>
          </div>
          <el-table v-if="searchResult.length" :data="searchResult" stripe size="small">
            <el-table-column type="index" width="50" />
            <el-table-column prop="name" label="片商名" />
            <el-table-column prop="name_jp" label="日文名" />
            <el-table-column prop="alias" label="别名" min-width="180">
              <template #default="{ row }">{{ row.alias || '-' }}</template>
            </el-table-column>
            <el-table-column prop="movie_count" label="作品数" width="100" sortable />
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
          <el-empty v-if="!searching && !searchResult.length && searchName" description="未找到相似片商" />
        </el-tab-pane>

        <el-tab-pane label="指定ID合并" name="byid">
          <el-form label-width="140px" style="max-width:500px">
            <el-form-item label="目标片商 ID">
              <el-input-number v-model="form.canonical_id" :min="1" />
            </el-form-item>
            <el-form-item label="被合并片商 ID">
              <el-select v-model="form.source_ids" multiple filterable allow-create default-first-option placeholder="输入片商ID">
                <el-option v-for="id in form.source_ids" :key="id" :label="id" :value="id" />
              </el-select>
              <div style="font-size:12px;color:#999;margin-top:4px">可输入多个 ID</div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="execMerge" :loading="merging">
                <el-icon><Connection /></el-icon> 执行合并
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-card v-if="selectedTarget" shadow="never" style="margin-top:16px">
      <template #header>
        <span class="card-title"><el-icon><UserFilled /></el-icon> 目标片商：{{ selectedTarget.name }}</span>
      </template>
      <el-descriptions :column="3" size="small" border style="margin-bottom:12px">
        <el-descriptions-item label="ID">{{ selectedTarget.id }}</el-descriptions-item>
        <el-descriptions-item label="名称">{{ selectedTarget.name }}</el-descriptions-item>
        <el-descriptions-item label="作品数">{{ selectedTarget.movie_count }}</el-descriptions-item>
        <el-descriptions-item label="日文名">{{ selectedTarget.name_jp || '-' }}</el-descriptions-item>
        <el-descriptions-item label="别名" :span="2">{{ selectedTarget.alias || '无' }}</el-descriptions-item>
      </el-descriptions>
      <el-button size="small" :disabled="!selectedTarget.id" @click="loadCandidates">
        <el-icon><Search /></el-icon> 查找合并候选
      </el-button>
      <div v-if="candidates.length" style="margin-top:12px">
        <el-table :data="candidates" stripe size="small">
          <el-table-column type="selection" width="50" />
          <el-table-column prop="name" label="片商名" />
          <el-table-column prop="alias" label="别名" min-width="180">
            <template #default="{ row }">{{ row.alias || '-' }}</template>
          </el-table-column>
          <el-table-column prop="movie_count" label="作品数" width="80" sortable />
          <el-table-column prop="similarity" label="相似度" width="100">
            <template #default="{ row }">
              <el-tag :type="row.similarity > 0.85 ? 'success' : 'warning'" size="small">
                {{ (row.similarity * 100).toFixed(0) }}%
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <div style="margin-top:12px">
          <el-button type="primary" @click="mergeCandidates" :loading="merging" :disabled="!selectedCandidates.length">
            <el-icon><Connection /></el-icon> 合并选中 ({{ selectedCandidates.length }})
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
            <el-descriptions-item label="目标片商">{{ mergeResult.canonical_name }}</el-descriptions-item>
            <el-descriptions-item label="合并数量">{{ mergeResult.merged_names?.length }}</el-descriptions-item>
            <el-descriptions-item label="合并自" :span="2">{{ mergeResult.merged_names?.join(', ') }}</el-descriptions-item>
            <el-descriptions-item label="别名" :span="2">{{ mergeResult.aliases }}</el-descriptions-item>
          </el-descriptions>
        </template>
      </el-result>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, OfficeBuilding, Connection, UserFilled, CircleCheckFilled } from '@element-plus/icons-vue'
import { searchSimilarStudios, mergeStudios } from '@/api'
import { getStudio } from '@/api'

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

const selectedCandidates = computed(() => selectedCandidateRows.value)

async function search() {
  if (!searchName.value.trim()) return
  searching.value = true
  try {
    const res = await searchSimilarStudios(searchName.value.trim())
    searchResult.value = res.items || []
  } catch (e) {
    ElMessage.error('搜索失败: ' + (e.message || e))
  } finally {
    searching.value = false
  }
}

async function selectTarget(row) {
  selectedTarget.value = row
  candidates.value = []
  selectedCandidateRows.value = []
}

async function loadCandidates() {
  if (!selectedTarget.value) return
  try {
    const res = await searchSimilarStudios(selectedTarget.value.name)
    candidates.value = (res.items || []).filter(c => c.id !== selectedTarget.value.id)
  } catch { }
}

async function execMerge() {
  if (!form.canonical_id || !form.source_ids.length) {
    ElMessage.warning('请填写目标片商 ID 和被合并片商 ID')
    return
  }
  merging.value = true
  try {
    const res = await mergeStudios({
      canonical_id: form.canonical_id,
      source_ids: form.source_ids,
    })
    if (res.error) { ElMessage.error(res.error); return }
    mergeResult.value = res
    ElMessage.success(`合并成功：${res.merged_names?.length} 个片商已合并`)
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.message || e))
  } finally {
    merging.value = false
  }
}

async function mergeCandidates() {
  if (!selectedTarget.value || !selectedCandidateRows.value.length) return
  await ElMessageBox.confirm(
    `确认将 ${selectedCandidateRows.value.length} 个片商合并到 ${selectedTarget.value.name}？`,
    '确认合并',
    { confirmButtonText: '合并', cancelButtonText: '取消', type: 'warning' }
  )
  merging.value = true
  try {
    const res = await mergeStudios({
      canonical_id: selectedTarget.value.id,
      source_ids: selectedCandidateRows.value.map(r => r.id),
    })
    if (res.error) { ElMessage.error(res.error); return }
    mergeResult.value = res
    selectedTarget.value = null
    candidates.value = []
    selectedCandidateRows.value = []
    ElMessage.success(`合并成功：${res.merged_names?.length} 个片商已合并`)
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.message || e))
  } finally {
    merging.value = false
  }
}
</script>

<style scoped>
.studio-merge { max-width: 1200px; margin: 0 auto; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 15px; }
</style>
