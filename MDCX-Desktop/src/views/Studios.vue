<template>
  <div class="studios-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h2>制片厂 / 厂商管理</h2>
      <p class="subtitle">集中管理制作商与片商 · 从已有影片自动同步 · 查看作品库</p>
    </div>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ total || 0 }}</div>
          <div class="stat-label">厂商总数</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value text-success">{{ totalMovies }}</div>
          <div class="stat-label">关联作品总数</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ topStudio || '—' }}</div>
          <div class="stat-label">作品最多的厂商</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 操作栏 -->
    <div class="action-bar">
      <el-input
        v-model="keyword"
        placeholder="搜索厂商名称..."
        clearable
        style="width: 280px"
        @keyup.enter="search"
        @clear="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="search"><el-icon><Search /></el-icon> 搜索</el-button>
      <el-button type="success" @click="openCreate">
        <el-icon><Plus /></el-icon> 新建厂商
      </el-button>
      <el-button @click="openSync" :loading="syncing">
        <el-icon><Refresh /></el-icon> 从影片同步
      </el-button>
    </div>

    <!-- 厂商列表 -->
    <el-card shadow="never" class="list-card">
      <el-table :data="studios" v-loading="loading" stripe style="width: 100%">
        <el-table-column label="ID" prop="id" width="70" />
        <el-table-column label="名称" prop="name" min-width="160" show-overflow-tooltip />
        <el-table-column label="日文名" prop="name_jp" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="muted">{{ row.name_jp || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="作品数" prop="movie_count" width="110" sortable>
          <template #default="{ row }">
            <el-tag size="small" type="primary">{{ row.movie_count || 0 }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="openDetail(row)">详情</el-button>
            <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" link @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无厂商" />
        </template>
      </el-table>

      <div class="pagination" v-if="total > 0">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadData"
        />
      </div>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑厂商' : '新建厂商'" width="480px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="厂商名称（唯一）" maxlength="80" />
        </el-form-item>
        <el-form-item label="日文名">
          <el-input v-model="form.name_jp" placeholder="可选，日文片商名" maxlength="80" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 厂商详情抽屉 -->
    <el-drawer v-model="detailVisible" :title="`${detailStudio.name} · 作品库`" size="560px">
      <div v-loading="detailLoading">
        <el-descriptions :column="2" border size="small" class="detail-desc">
          <el-descriptions-item label="厂商名">{{ detailStudio.name }}</el-descriptions-item>
          <el-descriptions-item label="日文名">{{ detailStudio.name_jp || '—' }}</el-descriptions-item>
          <el-descriptions-item label="作品总数">{{ detailMovieCount }}</el-descriptions-item>
        </el-descriptions>

        <h4 class="recent-title">最近 10 部作品</h4>
        <div class="recent-movies">
          <div v-for="m in recentMovies" :key="m.id" class="recent-item">
            <div class="recent-cover" v-if="m.cover_url">
              <img :src="m.cover_url" :alt="m.title" @error="onCoverError" />
            </div>
            <div class="recent-cover placeholder" v-else>
              <el-icon><Film /></el-icon>
            </div>
            <div class="recent-info">
              <div class="recent-code">{{ m.code }}</div>
              <div class="recent-name">{{ m.title || '未命名' }}</div>
              <div class="recent-date muted" v-if="m.release_date">{{ m.release_date }}</div>
            </div>
          </div>
          <el-empty v-if="!recentMovies.length" description="暂无作品" :image-size="80" />
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus, Refresh, Film } from '@element-plus/icons-vue'
import {
  getStudios, getStudio, createStudio, updateStudio, deleteStudio,
  syncStudiosFromMovies
} from '@/api'

const loading = ref(false)
const saving = ref(false)
const syncing = ref(false)
const detailLoading = ref(false)

const studios = ref([])
const total = ref(0)
const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)

const totalMovies = computed(() =>
  studios.value.reduce((sum, s) => sum + (s.movie_count || 0), 0)
)
const topStudio = computed(() => {
  if (!studios.value.length) return '—'
  const top = studios.value.reduce((a, b) => (b.movie_count > a.movie_count ? b : a), studios.value[0])
  return top.movie_count > 0 ? top.name : '—'
})

// 新建/编辑
const dialogVisible = ref(false)
const editingId = ref(null)
const form = reactive({ name: '', name_jp: '' })

// 详情
const detailVisible = ref(false)
const detailStudio = ref({})
const detailMovieCount = ref(0)
const recentMovies = ref([])

async function loadData() {
  loading.value = true
  try {
    const res = await getStudios({
      page: page.value,
      page_size: pageSize.value,
      search: keyword.value || undefined
    })
    studios.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  loadData()
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', name_jp: '' })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, { name: row.name, name_jp: row.name_jp || '' })
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写厂商名称')
    return
  }
  saving.value = true
  try {
    const payload = { name: form.name.trim(), name_jp: form.name_jp || null }
    if (editingId.value) {
      await updateStudio(editingId.value, payload)
      ElMessage.success('已更新')
    } else {
      await createStudio(payload)
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    loadData()
  } catch (e) {
    // 409 等由拦截器提示
  } finally {
    saving.value = false
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除厂商「${row.name}」吗？该操作不会删除影片，但会解除关联关系。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await deleteStudio(row.id)
    ElMessage.success('已删除')
    loadData()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

function openSync() {
  ElMessageBox.confirm(
    '将从现有影片的 maker / studio 字段中提取唯一厂商名并批量创建，同时刷新作品计数。已存在的厂商会自动跳过。是否继续？',
    '从影片同步厂商',
    { type: 'info', confirmButtonText: '开始同步', cancelButtonText: '取消' }
  ).then(async () => {
    syncing.value = true
    try {
      const res = await syncStudiosFromMovies()
      ElMessage.success(`同步完成：新建 ${res.studios_created} 个，跳过 ${res.studios_skipped} 个已存在`)
      loadData()
    } catch (e) {
      // 拦截器已提示
    } finally {
      syncing.value = false
    }
  }).catch(() => {})
}

async function openDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  detailStudio.value = { name: row.name, name_jp: row.name_jp }
  recentMovies.value = []
  detailMovieCount.value = row.movie_count || 0
  try {
    const res = await getStudio(row.id)
    detailStudio.value = res.studio || detailStudio.value
    detailMovieCount.value = res.movie_count || 0
    recentMovies.value = res.recent_movies || []
  } catch (e) {
    // 拦截器已提示
  } finally {
    detailLoading.value = false
  }
}

function onCoverError(e) {
  e.target.style.display = 'none'
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.studios-page {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0 0 4px 0;
  font-size: 22px;
}

.subtitle {
  margin: 0;
  color: #909399;
  font-size: 13px;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  text-align: center;
  padding: 10px 0;
}

.stat-value {
  font-size: 22px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0 8px;
}

.text-success {
  color: #67c23a;
}

.stat-label {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}

.action-bar {
  margin-bottom: 16px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.list-card {
  margin-bottom: 20px;
}

.muted {
  color: #c0c4cc;
}

.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}

.recent-title {
  margin: 16px 0 12px;
  font-size: 15px;
}

.recent-movies {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.recent-item {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 8px;
  border-radius: 8px;
  background: var(--el-fill-color-light, #f5f7fa);
}

.recent-cover {
  width: 56px;
  height: 78px;
  border-radius: 6px;
  overflow: hidden;
  flex-shrink: 0;
  background: #e9e9eb;
  display: flex;
  align-items: center;
  justify-content: center;
}

.recent-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.recent-cover.placeholder .el-icon {
  font-size: 22px;
  color: #c0c4cc;
}

.recent-info {
  min-width: 0;
}

.recent-code {
  font-weight: 600;
  color: #303133;
}

.recent-name {
  font-size: 13px;
  color: #606266;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-date {
  font-size: 12px;
  margin-top: 2px;
}
</style>
