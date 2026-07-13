<template>
  <div class="unrecognized-page">
    <el-card shadow="never" class="scan-card">
      <template #header>
        <div class="card-title">
          <el-icon><Search /></el-icon> 未识别文件扫描
        </div>
      </template>
      <el-form :inline="true" :model="scanForm">
        <el-form-item label="扫描模式">
          <el-radio-group v-model="scanForm.scan_mode">
            <el-radio value="all">全部</el-radio>
            <el-radio value="no_number">仅无法提取番号</el-radio>
            <el-radio value="no_match">仅番号无匹配</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="runScan" :loading="scanning">
            <el-icon><Search /></el-icon> 开始扫描
          </el-button>
        </el-form-item>
      </el-form>

      <el-alert v-if="scanResult" type="info" :closable="false">
        <template #title>
          扫描完成: 共 {{ scanResult.total_files }} 个视频文件，
          {{ scanResult.no_number.length }} 个无法提取番号，
          {{ scanResult.no_match.length }} 个番号无匹配
          <span v-if="scanResult.scanned_at">（{{ formatTime(scanResult.scanned_at) }}）</span>
        </template>
      </el-alert>
    </el-card>

    <el-card shadow="never" v-if="scanResult && scanResult.no_match.length">
      <template #header>
        <div class="card-title">
          <el-icon><WarningFilled /></el-icon> 番号无匹配 ({{ scanResult.no_match.length }})
          <span class="form-tip">已提取番号但数据库中无对应记录</span>
        </div>
      </template>
      <el-table :data="scanResult.no_match" border size="small" style="width: 100%" max-height="400">
        <el-table-column prop="filename" label="文件名" min-width="250" show-overflow-tooltip />
        <el-table-column prop="extracted_number" label="提取番号" width="120">
          <template #default="{ row }">
            <el-tag type="warning" size="small">{{ row.extracted_number }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="size_mb" label="大小 (MB)" width="100" />
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openSetNumberDialog(row)">
              指定番号
            </el-button>
            <el-button size="small" @click="openLinkDialog(row)">
              关联影片
            </el-button>
            <el-button size="small" @click="openRenameDialog(row)">
              重命名
            </el-button>
            <el-button size="small" type="danger" @click="confirmDelete(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" v-if="scanResult && scanResult.no_number.length">
      <template #header>
        <div class="card-title">
          <el-icon><CircleCloseFilled /></el-icon> 无法提取番号 ({{ scanResult.no_number.length }})
          <span class="form-tip">文件名不符合番号规范</span>
        </div>
      </template>
      <el-table :data="scanResult.no_number" border size="small" style="width: 100%" max-height="400">
        <el-table-column prop="filename" label="文件名" min-width="250" show-overflow-tooltip />
        <el-table-column prop="size_mb" label="大小 (MB)" width="100" />
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openSetNumberDialog(row)">
              指定番号
            </el-button>
            <el-button size="small" @click="openLinkDialog(row)">
              关联影片
            </el-button>
            <el-button size="small" @click="openRenameDialog(row)">
              重命名
            </el-button>
            <el-button size="small" type="danger" @click="confirmDelete(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-empty v-if="scanResult && !scanResult.no_number.length && !scanResult.no_match.length" description="所有文件都已识别" />

    <!-- 指定番号对话框 -->
    <el-dialog v-model="setNumberDialog.visible" title="手动指定番号" width="500px">
      <el-form label-width="120px">
        <el-form-item label="文件">
          <span class="dialog-filename">{{ setNumberDialog.filename }}</span>
        </el-form-item>
        <el-form-item label="番号">
          <el-input v-model="setNumberDialog.number" placeholder="如 ABC-123" />
        </el-form-item>
        <el-form-item label="自动创建">
          <el-switch v-model="setNumberDialog.create_if_missing" />
          <span class="form-tip">如果数据库中无此番号记录，是否自动创建</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="setNumberDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitSetNumber" :loading="setNumberDialog.loading">确定</el-button>
      </template>
    </el-dialog>

    <!-- 关联影片对话框 -->
    <el-dialog v-model="linkDialog.visible" title="关联到现有影片" width="500px">
      <el-form label-width="120px">
        <el-form-item label="文件">
          <span class="dialog-filename">{{ linkDialog.filename }}</span>
        </el-form-item>
        <el-form-item label="搜索影片">
          <el-input v-model="linkDialog.searchKeyword" placeholder="输入番号或标题搜索" @input="searchMovies">
            <template #append>
              <el-button @click="searchMovies">搜索</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="选择影片">
          <el-select v-model="linkDialog.movieId" filterable placeholder="选择影片" style="width: 100%">
            <el-option
              v-for="m in linkDialog.searchResults"
              :key="m.id"
              :label="`${m.code} - ${m.title || '未命名'}`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="linkDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitLink" :loading="linkDialog.loading" :disabled="!linkDialog.movieId">
          确定关联
        </el-button>
      </template>
    </el-dialog>

    <!-- 重命名对话框 -->
    <el-dialog v-model="renameDialog.visible" title="重命名文件" width="500px">
      <el-form label-width="120px">
        <el-form-item label="原文件名">
          <span class="dialog-filename">{{ renameDialog.filename }}</span>
        </el-form-item>
        <el-form-item label="新文件名">
          <el-input v-model="renameDialog.newFilename" placeholder="如 ABC-123.mp4">
            <template #append>
              <span>{{ fileExt }}</span>
            </template>
          </el-input>
          <span class="form-tip">重命名后可重新识别番号</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renameDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitRename" :loading="renameDialog.loading">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, WarningFilled, CircleCloseFilled } from '@element-plus/icons-vue'
import {
  scanUnrecognized, manualLinkFile, manualSetNumber,
  renameUnrecognizedFile, deleteUnrecognizedFile, getMovies
} from '@/api'

const scanning = ref(false)
const scanResult = ref(null)

const scanForm = reactive({
  scan_mode: 'all',
})

const runScan = async () => {
  scanning.value = true
  try {
    scanResult.value = await scanUnrecognized({ scan_mode: scanForm.scan_mode })
    ElMessage.success('扫描完成')
  } catch (e) {
    ElMessage.error('扫描失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    scanning.value = false
  }
}

// 指定番号对话框
const setNumberDialog = reactive({
  visible: false,
  filePath: '',
  filename: '',
  number: '',
  create_if_missing: true,
  loading: false,
})

const openSetNumberDialog = (row) => {
  setNumberDialog.filePath = row.path
  setNumberDialog.filename = row.filename
  setNumberDialog.number = row.extracted_number || ''
  setNumberDialog.create_if_missing = true
  setNumberDialog.visible = true
}

const submitSetNumber = async () => {
  if (!setNumberDialog.number) {
    ElMessage.warning('请输入番号')
    return
  }
  setNumberDialog.loading = true
  try {
    const res = await manualSetNumber({
      file_path: setNumberDialog.filePath,
      number: setNumberDialog.number,
      create_if_missing: setNumberDialog.create_if_missing,
    })
    if (res.ok) {
      ElMessage.success(res.msg)
      setNumberDialog.visible = false
      runScan()
    } else {
      ElMessage.warning(res.msg)
    }
  } catch (e) {
    ElMessage.error('操作失败')
  } finally {
    setNumberDialog.loading = false
  }
}

// 关联影片对话框
const linkDialog = reactive({
  visible: false,
  filePath: '',
  filename: '',
  searchKeyword: '',
  searchResults: [],
  movieId: null,
  loading: false,
})

const openLinkDialog = (row) => {
  linkDialog.filePath = row.path
  linkDialog.filename = row.filename
  linkDialog.searchKeyword = row.extracted_number || ''
  linkDialog.searchResults = []
  linkDialog.movieId = null
  linkDialog.visible = true
  if (linkDialog.searchKeyword) {
    searchMovies()
  }
}

let searchTimer = null
const searchMovies = () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(async () => {
    if (!linkDialog.searchKeyword) {
      linkDialog.searchResults = []
      return
    }
    try {
      const res = await getMovies({ search: linkDialog.searchKeyword, page: 1, page_size: 20 })
      linkDialog.searchResults = res.items || []
    } catch (e) {
      linkDialog.searchResults = []
    }
  }, 300)
}

const submitLink = async () => {
  if (!linkDialog.movieId) {
    ElMessage.warning('请选择影片')
    return
  }
  linkDialog.loading = true
  try {
    const res = await manualLinkFile({
      file_path: linkDialog.filePath,
      movie_id: linkDialog.movieId,
    })
    if (res.ok) {
      ElMessage.success(res.msg)
      linkDialog.visible = false
      runScan()
    } else {
      ElMessage.warning(res.msg)
    }
  } catch (e) {
    ElMessage.error('操作失败')
  } finally {
    linkDialog.loading = false
  }
}

// 重命名对话框
const renameDialog = reactive({
  visible: false,
  filePath: '',
  filename: '',
  newFilename: '',
  loading: false,
})

const fileExt = computed(() => {
  const idx = renameDialog.filename.lastIndexOf('.')
  return idx >= 0 ? renameDialog.filename.substring(idx) : ''
})

const openRenameDialog = (row) => {
  renameDialog.filePath = row.path
  renameDialog.filename = row.filename
  renameDialog.newFilename = row.filename
  renameDialog.visible = true
}

const submitRename = async () => {
  if (!renameDialog.newFilename) {
    ElMessage.warning('请输入新文件名')
    return
  }
  renameDialog.loading = true
  try {
    // 自动补扩展名
    let newName = renameDialog.newFilename
    if (fileExt.value && !newName.endsWith(fileExt.value)) {
      newName = newName + fileExt.value
    }
    const res = await renameUnrecognizedFile({
      old_path: renameDialog.filePath,
      new_filename: newName,
    })
    if (res.ok) {
      ElMessage.success(res.msg)
      renameDialog.visible = false
      runScan()
    } else {
      ElMessage.warning(res.msg)
    }
  } catch (e) {
    ElMessage.error('操作失败')
  } finally {
    renameDialog.loading = false
  }
}

// 删除确认
const confirmDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除文件 ${row.filename} 吗？此操作不可恢复！`,
      '危险操作',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    const res = await deleteUnrecognizedFile({ file_path: row.path })
    if (res.ok) {
      ElMessage.success(res.msg)
      runScan()
    } else {
      ElMessage.warning(res.msg)
    }
  } catch (e) {
    // 取消
  }
}

const formatTime = (iso) => {
  try {
    return new Date(iso).toLocaleString('zh-CN')
  } catch {
    return iso
  }
}
</script>

<style scoped>
.unrecognized-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.form-tip {
  font-size: 12px;
  color: var(--text-secondary);
  margin-left: 8px;
  font-weight: normal;
}

.dialog-filename {
  font-family: monospace;
  font-size: 12px;
  word-break: break-all;
  color: var(--text-secondary);
}
</style>
