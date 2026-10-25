<template>
  <div class="wants-page">
    <div class="page-header">
      <h2>想要清单</h2>
      <p class="desc">还没找到的片子先记在这里（按番号，大小写不敏感）。「检查入库情况」会实时查各模块影片库，标出已入库的、已出中字版的、以及本地有旧版可替换的。</p>
    </div>

    <el-card shadow="never" class="add-card">
      <el-form :inline="true" :model="form" @submit.prevent="onAdd">
        <el-form-item>
          <el-input v-model="form.code" placeholder="番号，如 SSIS-001" style="width:180px" clearable @keyup.enter="onAdd" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.title" placeholder="备注标题（可选）" style="width:200px" clearable @keyup.enter="onAdd" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.note" placeholder="备注（可选）" style="width:220px" clearable @keyup.enter="onAdd" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.priority">想要</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Plus" :loading="adding" @click="onAdd">添加</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <el-radio-group v-model="statusFilter" size="small" @change="loadList">
        <el-radio-button label="wanted">想要中</el-radio-button>
        <el-radio-button label="found">已找到</el-radio-button>
        <el-radio-button label="dropped">已放弃</el-radio-button>
        <el-radio-button label="">全部</el-radio-button>
      </el-radio-group>
      <div class="toolbar-right">
        <el-tooltip content="实时查询各模块影片库：标出已入库 / 已出中字版 / 本地有旧版可替换" placement="top">
          <el-button :icon="Refresh" :loading="checking" @click="onCheck">检查入库情况</el-button>
        </el-tooltip>
      </div>
    </div>

    <el-card shadow="never" class="list-card">
      <el-table :data="items" size="small" stripe v-loading="loading" empty-text="清单为空，先在上方添加番号">
        <el-table-column prop="code" label="番号" width="130">
          <template #default="{ row }">
            <span class="code">{{ row.code }}</span>
            <el-tag v-if="row.priority" type="danger" size="small" effect="dark" style="margin-left:6px">想要</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.title || '—' }}</template>
        </el-table-column>
        <el-table-column label="入库情况" width="240">
          <template #default="{ row }">
            <template v-if="row.checked">
              <el-tag v-if="row.in_library" type="success" size="small" effect="plain">已入库 · {{ moduleLabel(row.in_library) }}</el-tag>
              <el-tag v-else type="info" size="small" effect="plain">未入库</el-tag>
              <el-tag v-if="row.chinese_available" type="warning" size="small" style="margin-left:4px">有中字版</el-tag>
              <el-tag v-if="row.upgrade_candidate" type="danger" size="small" style="margin-left:4px">可替换旧版</el-tag>
            </template>
            <span v-else class="muted">未检查</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.note || '—' }}</template>
        </el-table-column>
        <el-table-column label="磁链" width="70">
          <template #default="{ row }">
            <el-tooltip v-if="row.magnet" :content="row.magnet" placement="top">
              <el-tag type="success" size="small" effect="plain">已存</el-tag>
            </el-tooltip>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="记录时间" width="110">
          <template #default="{ row }">
            <span class="muted">{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status !== 'found'" text type="success" size="small" @click="onMarkFound(row)">标记找到</el-button>
            <el-button v-if="row.status === 'found'" text type="primary" size="small" @click="onReopen(row)">重新想要</el-button>
            <el-button text type="danger" size="small" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getWants, checkWants, addWant, updateWant, deleteWant } from '@/api'

const statusFilter = ref('wanted')
const items = ref([])
const loading = ref(false)
const adding = ref(false)
const checking = ref(false)
const form = reactive({ code: '', title: '', note: '', priority: false })

const moduleLabels = {
  jav: 'JAV', fc2: 'FC2', uncensored: '无码',
  chinese: '国产', western: '欧美', pornhub: 'PH',
}
function moduleLabel(m) { return moduleLabels[m] || m }

function statusLabel(s) {
  return { wanted: '想要中', found: '已找到', dropped: '已放弃' }[s] || s
}
function statusType(s) {
  return { wanted: 'warning', found: 'success', dropped: 'info' }[s] || 'info'
}
function formatDate(iso) {
  if (!iso) return '—'
  return String(iso).slice(0, 10)
}

async function loadList() {
  loading.value = true
  try {
    const data = await getWants(statusFilter.value || undefined)
    items.value = (data?.items || []).map(i => ({ ...i, checked: false }))
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function onAdd() {
  const code = form.code.trim()
  if (!code) {
    ElMessage.warning('先填番号')
    return
  }
  adding.value = true
  try {
    await addWant({
      code,
      title: form.title.trim() || null,
      note: form.note.trim() || null,
      priority: form.priority ? 1 : 0,
    })
    ElMessage.success(`已记录 ${code.toUpperCase()}`)
    form.code = ''
    form.title = ''
    form.note = ''
    form.priority = false
    await loadList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  } finally {
    adding.value = false
  }
}

async function onCheck() {
  checking.value = true
  try {
    const data = await checkWants()
    const checked = data?.items || []
    // 以 check 结果为准（含当前筛选外的条目只做覆盖，不新增）
    const byId = new Map(checked.map(i => [i.id, i]))
    items.value = items.value.map(i => {
      const c = byId.get(i.id)
      return c ? { ...c, checked: true } : i
    })
    const upgrade = checked.filter(i => i.upgrade_candidate).length
    const chinese = checked.filter(i => i.chinese_available).length
    if (upgrade > 0) {
      ElMessage.warning(`检查完成：${upgrade} 部可替换中字版，${chinese} 部已有中字版入库`)
    } else if (chinese > 0) {
      ElMessage.success(`检查完成：${chinese} 部已有中字版入库`)
    } else {
      ElMessage.success('检查完成，暂无中字版线索')
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '检查失败')
  } finally {
    checking.value = false
  }
}

async function onMarkFound(row) {
  try {
    await updateWant(row.id, { status: 'found' })
    ElMessage.success(`${row.code} 已标记为找到`)
    await loadList()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

async function onReopen(row) {
  try {
    await updateWant(row.id, { status: 'wanted' })
    await loadList()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`删除「${row.code}」？`, '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
    await deleteWant(row.id)
    ElMessage.success('已删除')
    await loadList()
  } catch (e) {
    if (e !== 'cancel' && e?.message !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

onMounted(loadList)
</script>

<style scoped>
.wants-page { max-width: 1200px; margin: 0 auto; }
.page-header h2 { font-size: 20px; font-weight: 600; margin-bottom: 6px; }
.page-header .desc { color: #909399; font-size: 13px; margin-bottom: 20px; line-height: 1.6; }
.add-card { margin-bottom: 16px; }
.toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px;
}
.list-card { min-height: 300px; }
.code { font-family: var(--font-mono, monospace); font-size: 12px; font-weight: 500; }
.muted { color: #909399; font-size: 12px; }
</style>
