<template>
  <div class="pl-page">
    <div class="page-header">
      <h2>播放列表</h2>
      <p class="desc">把已入库的片子排成连播队列（JAV 和 PORNHUB 可以混排）。播放时按顺序传给 mpv 连播；没有文件或文件已失效的条目会自动跳过。</p>
    </div>

    <div class="pl-body">
      <!-- 左：列表 -->
      <div class="pl-side">
        <div class="side-head">
          <span>我的列表</span>
          <el-button text type="primary" :icon="Plus" @click="openCreate">新建</el-button>
        </div>
        <el-menu :default-active="String(currentId)" class="pl-menu" @select="onSelect">
          <el-menu-item v-for="p in playlists" :key="p.id" :index="String(p.id)">
            <el-icon><Collection /></el-icon>
            <template #title>
              <div class="pl-item-title">
                <span class="pl-name">{{ p.name }}</span>
                <span class="pl-count">{{ p.item_count }} 部</span>
              </div>
            </template>
          </el-menu-item>
        </el-menu>
        <el-empty v-if="!playlists.length && !loading" description="还没有列表" :image-size="60" />
      </div>

      <!-- 右：当前列表条目 -->
      <div class="pl-main">
        <template v-if="current">
          <div class="main-head">
            <div class="head-left">
              <h3>{{ current.name }}</h3>
              <span class="head-desc" v-if="current.description">{{ current.description }}</span>
              <el-button text type="primary" size="small" :icon="EditPen" @click="openRename" />
              <el-button text type="danger" size="small" :icon="Delete" @click="onDeleteList" />
            </div>
            <div class="head-right">
              <el-button type="primary" :icon="VideoPlay" :loading="playing" @click="onPlay">
                连播（{{ playableCount }}）
              </el-button>
            </div>
          </div>

          <el-table :data="current.items" size="small" stripe v-loading="loading"
            empty-text="列表为空——在下方按番号添加，或到影片详情页加片" row-key="id">
            <el-table-column label="序" width="50" type="index" />
            <el-table-column prop="code" label="番号" width="140">
              <template #default="{ row }">
                <span class="code">{{ row.code || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">{{ row.title || '—' }}</template>
            </el-table-column>
            <el-table-column label="模块" width="70">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ moduleLabel(row.module) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="文件" width="150">
              <template #default="{ row }">
                <el-tag v-if="row.missing" type="danger" size="small" effect="plain">无文件</el-tag>
                <el-tag v-else-if="row.file_exists === false" type="warning" size="small" effect="plain">文件已失效</el-tag>
                <span v-else class="muted">就绪</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="130" fixed="right">
              <template #default="{ row, $index }">
                <el-button text size="small" :disabled="$index === 0" @click="onMove(row, -1)">上移</el-button>
                <el-button text size="small" :disabled="$index === current.items.length - 1" @click="onMove(row, 1)">下移</el-button>
                <el-button text type="danger" size="small" @click="onRemove(row)">移除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="add-by-code">
            <span class="abc-label">按番号添加：</span>
            <el-select v-model="addForm.module" size="small" style="width:90px">
              <el-option v-for="(label, key) in moduleLabels" :key="key" :label="label" :value="key" />
            </el-select>
            <el-input
              v-model="addForm.code"
              size="small"
              placeholder="输入番号，如 SSIS-001"
              style="width:200px; margin-left:8px"
              clearable
              @keyup.enter="onAddByCode"
            />
            <el-button size="small" type="primary" :loading="adding" style="margin-left:8px" @click="onAddByCode">添加</el-button>
            <span class="abc-hint">从各模块影片库里按番号查找（精确匹配）</span>
          </div>
        </template>
        <el-empty v-else description="左侧选择或新建一个列表" />
      </div>
    </div>

    <!-- 新建/重命名对话框 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '重命名列表' : '新建播放列表'" width="420px">
      <el-form :model="dialogForm" label-width="70px">
        <el-form-item label="名称" required>
          <el-input v-model="dialogForm.name" placeholder="列表名，如「周末连播」" maxlength="50" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="dialogForm.description" type="textarea" :rows="2" placeholder="可选" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSaveDialog">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Plus, Collection, EditPen, Delete, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listPlaylists, createPlaylist, updatePlaylist, deletePlaylist,
  getPlaylist, addPlaylistItem, removePlaylistItem, movePlaylistItem, playPlaylist,
  getMovies,
} from '@/api'

const moduleLabels = { jav: 'JAV', fc2: 'FC2', uncensored: '无码', chinese: '国产', western: '欧美', pornhub: 'PH' }
function moduleLabel(m) { return moduleLabels[m] || m }

const playlists = ref([])
const current = ref(null)
const loading = ref(false)
const playing = ref(false)
const dialogVisible = ref(false)
const editing = ref(false)
const saving = ref(false)
const dialogForm = ref({ name: '', description: '' })
const addForm = ref({ code: '', module: 'jav' })
const adding = ref(false)

const currentId = computed(() => current.value?.id || '')
const playableCount = computed(() =>
  (current.value?.items || []).filter(i => !i.missing && i.file_exists !== false).length
)

async function loadList() {
  loading.value = true
  try {
    const data = await listPlaylists()
    playlists.value = data?.items || []
    // 保持选中，或默认选第一个
    if (current.value) {
      const still = playlists.value.find(p => p.id === current.value.id)
      if (!still) current.value = null
      else await selectPlaylist(current.value.id)
    } else if (playlists.value.length && !current.value) {
      await selectPlaylist(playlists.value[0].id)
    }
  } catch (e) {
    ElMessage.error('加载列表失败')
  } finally {
    loading.value = false
  }
}

async function selectPlaylist(id) {
  loading.value = true
  try {
    const data = await getPlaylist(id)
    // 逐条补文件存在性（后端 resolve 才做，这里用轻量提示）
    current.value = data
  } catch (e) {
    ElMessage.error('加载列表详情失败')
  } finally {
    loading.value = false
  }
}

function onSelect(id) {
  selectPlaylist(Number(id))
}

function openCreate() {
  editing.value = false
  dialogForm.value = { name: '', description: '' }
  dialogVisible.value = true
}

function openRename() {
  if (!current.value) return
  editing.value = true
  dialogForm.value = { name: current.value.name, description: current.value.description || '' }
  dialogVisible.value = true
}

async function onSaveDialog() {
  const name = dialogForm.value.name.trim()
  if (!name) {
    ElMessage.warning('先填列表名')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await updatePlaylist(current.value.id, { name, description: dialogForm.value.description })
      ElMessage.success('已保存')
    } else {
      const p = await createPlaylist({ name, description: dialogForm.value.description })
      ElMessage.success(`已创建「${p.name}」`)
    }
    dialogVisible.value = false
    await loadList()
    if (!editing.value && playlists.value.length) {
      const created = playlists.value.find(p => p.name === name)
      if (created) await selectPlaylist(created.id)
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function onDeleteList() {
  if (!current.value) return
  try {
    await ElMessageBox.confirm(
      `删除列表「${current.value.name}」？列表里的条目会一起删掉，影片本身不受影响。`,
      '确认删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await deletePlaylist(current.value.id)
    ElMessage.success('已删除')
    current.value = null
    await loadList()
  } catch (e) {
    if (e !== 'cancel' && e?.message !== 'cancel') ElMessage.error('删除失败')
  }
}

async function onMove(row, direction) {
  try {
    await movePlaylistItem(row.id, direction)
    await selectPlaylist(current.value.id)
    await loadListCounts()
  } catch (e) {
    ElMessage.error('移动失败')
  }
}

async function loadListCounts() {
  try {
    const data = await listPlaylists()
    playlists.value = data?.items || []
  } catch { /* 刷新条目数失败不打断 */ }
}

async function onRemove(row) {
  try {
    await removePlaylistItem(row.id)
    await selectPlaylist(current.value.id)
    await loadListCounts()
  } catch (e) {
    ElMessage.error('移除失败')
  }
}

async function onPlay() {
  if (!current.value) return
  playing.value = true
  try {
    const res = await playPlaylist(current.value.id)
    let msg = `已启动连播：${res.file_count || 0} 部`
    if (res.skipped > 0) msg += `（跳过 ${res.skipped} 部无文件/失效条目）`
    ElMessage.success(msg)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '连播启动失败')
  } finally {
    playing.value = false
  }
}

// 按番号添加：先查模块库拿 movie_id（search 模糊查 + 前端 code 精确匹配），再加进列表
async function onAddByCode() {
  if (!current.value) {
    ElMessage.warning('先选择或新建一个列表')
    return
  }
  const code = addForm.value.code.trim()
  if (!code) {
    ElMessage.warning('先输入番号')
    return
  }
  adding.value = true
  try {
    // search 是模糊匹配（标题/番号都搜），前端再按 code 精确过滤
    const res = await getMovies({ module: addForm.value.module, search: code, page_size: 50 })
    const items = res?.items || []
    const target = String(code).toUpperCase()
    const found = items.find(m => String(m.code || '').toUpperCase() === target)
    if (!found) {
      ElMessage.warning(`模块「${moduleLabel(addForm.value.module)}」里找不到番号 ${target}（只匹配已入库影片）`)
      return
    }
    await addPlaylistItem(current.value.id, { module: addForm.value.module, movie_id: found.id })
    ElMessage.success(`已添加 ${code.toUpperCase()}`)
    addForm.value.code = ''
    await selectPlaylist(current.value.id)
    await loadListCounts()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  } finally {
    adding.value = false
  }
}

onMounted(loadList)
</script>

<style scoped>
.pl-page { max-width: 1200px; margin: 0 auto; }
.page-header h2 { font-size: 20px; font-weight: 600; margin-bottom: 6px; }
.page-header .desc { color: #909399; font-size: 13px; margin-bottom: 20px; line-height: 1.6; }
.pl-body { display: flex; gap: 16px; align-items: flex-start; }
.pl-side {
  width: 240px; flex-shrink: 0; background: #fff; border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04); padding: 12px;
}
.side-head {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 13px; font-weight: 500; color: var(--text-secondary);
  padding: 0 4px 8px; border-bottom: 1px solid var(--border-color, #ebeef5);
  margin-bottom: 8px;
}
.pl-menu { border: none; }
.pl-item-title { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.pl-name { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 130px; }
.pl-count { font-size: 11px; color: #909399; flex-shrink: 0; }
.pl-main { flex: 1; background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.04); padding: 16px; min-height: 400px; }
.main-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.head-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.head-left h3 { font-size: 16px; font-weight: 600; margin: 0; }
.head-desc { font-size: 12px; color: #909399; }
.code { font-family: var(--font-mono, monospace); font-size: 12px; }
.muted { color: #909399; font-size: 12px; }
.add-by-code {
  margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--border-color, #ebeef5);
  display: flex; align-items: center; flex-wrap: wrap; gap: 4px;
}
.abc-label { font-size: 12px; color: var(--text-secondary); }
.abc-hint { font-size: 11px; color: #909399; margin-left: 8px; }
</style>
