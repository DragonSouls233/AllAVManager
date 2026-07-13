<template>
  <div class="tags">
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-input v-model="searchKey" placeholder="搜索标签..." clearable style="width: 220px">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </div>
        <div class="toolbar-right">
          <el-button type="success" plain @click="syncFromMovies" :loading="syncing">
            <el-icon><Refresh /></el-icon> 从影片同步
          </el-button>
          <el-button type="primary" @click="showCreate">
            <el-icon><Plus /></el-icon> 新建标签
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="filteredTags" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="name" label="名称" min-width="180">
          <template #default="{ row }">
            <el-tag>{{ row.name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="category" label="分类" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.category" size="small" type="info">{{ row.category }}</el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="movie_count" label="关联影片数" width="120" sortable>
          <template #default="{ row }">
            <el-link type="primary" @click="showMovies(row)">{{ row.movie_count || 0 }}</el-link>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="editTag(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="deleteAction(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination" v-if="total > 0">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadTags"
        />
      </div>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dialog.visible" :title="dialog.id ? '编辑标签' : '新建标签'" width="480px">
      <el-form label-width="100px" :model="dialog.form">
        <el-form-item label="名称">
          <el-input v-model="dialog.form.name" placeholder="标签名称" />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="dialog.form.category" placeholder="例如：genre、studio、series" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveAction" :loading="dialog.loading">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus } from '@element-plus/icons-vue'
import { getTags, createTag, updateTag, deleteTag, syncTagsFromMovies } from '@/api'
import { useRouter } from 'vue-router'

const router = useRouter()
const loading = ref(false)
const syncing = ref(false)
const tags = ref([])
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const searchKey = ref('')

const filteredTags = computed(() => {
  if (!searchKey.value) return tags.value
  const key = searchKey.value.toLowerCase()
  return tags.value.filter(t =>
    (t.name || '').toLowerCase().includes(key)
  )
})

const loadTags = async () => {
  loading.value = true
  try {
    const res = await getTags({ page: page.value, page_size: pageSize.value })
    tags.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    console.error('加载标签失败:', e)
    ElMessage.error(`加载标签失败: ${e?.message || '网络错误或服务未启动'}`)
  } finally {
    loading.value = false
  }
}

const dialog = ref({ visible: false, loading: false, id: null, form: { name: '', category: '' } })

const showCreate = () => {
  dialog.value = { visible: true, loading: false, id: null, form: { name: '', category: '' } }
}

const editTag = (row) => {
  dialog.value = {
    visible: true, loading: false, id: row.id,
    form: { name: row.name, category: row.category || '' }
  }
}

const saveAction = async () => {
  if (!dialog.value.form.name) {
    ElMessage.warning('请输入名称')
    return
  }
  dialog.value.loading = true
  try {
    if (dialog.value.id) {
      await updateTag(dialog.value.id, dialog.value.form)
    } else {
      await createTag(dialog.value.form)
    }
    ElMessage.success('保存成功')
    dialog.value.visible = false
    loadTags()
  } catch (e) { ElMessage.error(`保存失败: ${e?.message || '未知错误'}`) }
  finally { dialog.value.loading = false }
}

const deleteAction = (row) => {
  ElMessageBox.confirm(`确认删除标签「${row.name}」？`, '提示', { type: 'warning' })
    .then(async () => {
      try {
        await deleteTag(row.id)
        ElMessage.success('已删除')
        loadTags()
      } catch (e) { ElMessage.error(`删除失败: ${e?.message || '未知错误'}`) }
    }).catch(() => {})
}

const syncFromMovies = async () => {
  syncing.value = true
  try {
    await syncTagsFromMovies()
    ElMessage.success('同步完成')
    loadTags()
  } catch (e) { console.error(e) }
  finally { syncing.value = false }
}

const showMovies = (row) => {
  router.push({ path: '/movies', query: { tag_id: row.id } })
}

onMounted(() => {
  loadTags()
})
</script>

<style scoped>
.tags { display: flex; flex-direction: column; gap: 16px; }
.toolbar-card, .table-card { border-radius: 10px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.toolbar-left, .toolbar-right { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.text-muted { color: #c0c4cc; }
.pagination { margin-top: 16px; display: flex; justify-content: center; }
</style>
