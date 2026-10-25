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

    <!-- 推广残留清理卡片 -->
    <el-card shadow="never" class="residue-card">
      <template #header>
        <div class="card-title">
          <el-icon><Delete /></el-icon> 推广残留清理
          <span class="form-tip">扫描媒体目录里的广告插页（扫码/域名/推广站目录命名），清理是移入回收站而非直接删除</span>
        </div>
      </template>
      <el-button type="primary" :loading="residueScanning" @click="runResidueScan">
        <el-icon><Search /></el-icon> 扫描推广残留
      </el-button>
      <el-button v-if="residueResult" @click="runResidueScan" :loading="residueScanning">重新扫描</el-button>

      <el-alert v-if="residueResult" type="info" :closable="false" style="margin-top: 12px">
        <template #title>
          扫描 {{ residueResult.summary.scanned_entries }} 项（{{ residueResult.summary.elapsed_sec }}s）：
          建议清理 {{ residueResult.summary.junk_count }} 个（{{ formatSize(residueResult.summary.junk_bytes) }}），
          待确认 {{ residueResult.summary.review_count }} 个（{{ formatSize(residueResult.summary.review_bytes) }}）
          <span v-if="residueResult.summary.scan_errors">
            （{{ residueResult.summary.scan_errors }} 个目录读取失败）
          </span>
          <span v-if="residueResult.summary.timed_out" style="color: #e6a23c">
            （目录太多已到 {{ residueResult.summary.elapsed_sec }}s 上限提前停止，结果不完整）
          </span>
        </template>
      </el-alert>

      <el-tabs v-if="residueResult && (residueResult.junk.length || residueResult.review.length)" v-model="residueTab" style="margin-top: 12px">
        <el-tab-pane :label="`建议清理（${residueResult.junk.length}）`" name="junk">
          <template #label>
            <span>建议清理（{{ residueResult.junk.length }}）</span>
          </template>
          <el-alert type="warning" :closable="false" style="margin-bottom: 8px">
            <template #title>命中硬判据（整个名字都是推广语/装饰符小图/品牌推广名）。仍建议扫一眼理由再清理。</template>
          </el-alert>
          <el-table :data="residueResult.junk" border size="small" max-height="400"
                    @selection-change="(rows) => residueSelectedJunk = rows">
            <el-table-column type="selection" width="42" />
            <el-table-column prop="filename" label="文件名" min-width="240" show-overflow-tooltip />
            <el-table-column prop="size" label="大小" width="90">
              <template #default="{ row }">{{ formatSize(row.size) }}</template>
            </el-table-column>
            <el-table-column prop="score" label="分数" width="60" />
            <el-table-column prop="reasons" label="判定理由" min-width="220">
              <template #default="{ row }">
                <el-tag v-for="r in row.reasons" :key="r" size="small" type="danger" effect="plain" style="margin: 2px">{{ r }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="danger" @click="trashOneResidue(row)">移入回收站</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane :label="`待确认（${residueResult.review.length}）`" name="review">
          <el-alert type="info" :closable="false" style="margin-bottom: 8px">
            <template #title>分数没到自动清理线（住在推广目录/域名打包目录等弱证据），看过再决定。</template>
          </el-alert>
          <el-table :data="residueResult.review" border size="small" max-height="400"
                    @selection-change="(rows) => residueSelectedReview = rows">
            <el-table-column type="selection" width="42" />
            <el-table-column prop="filename" label="文件名" min-width="240" show-overflow-tooltip />
            <el-table-column prop="size" label="大小" width="90">
              <template #default="{ row }">{{ formatSize(row.size) }}</template>
            </el-table-column>
            <el-table-column prop="score" label="分数" width="60" />
            <el-table-column prop="reasons" label="判定理由" min-width="220">
              <template #default="{ row }">
                <el-tag v-for="r in row.reasons" :key="r" size="small" type="warning" effect="plain" style="margin: 2px">{{ r }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="danger" @click="trashOneResidue(row)">移入回收站</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>

      <div v-if="residueResult && (residueResult.junk.length || residueResult.review.length)" style="margin-top: 12px">
        <el-button type="danger" :disabled="!residueSelected.length" @click="trashSelectedResidue">
          移入回收站（已选 {{ residueSelected.length }}）
        </el-button>
        <span class="form-tip" style="margin-left: 8px">移入回收站可随时恢复，不会直接删除</span>
      </div>
    </el-card>

    <!-- 回收站卡片 -->
    <el-card shadow="never" class="trash-card" v-if="trashBatches.length">
      <template #header>
        <div class="card-title">
          <el-icon><Delete /></el-icon> 回收站（{{ trashTotalCount }} 个，{{ formatSize(trashTotalSize) }}）
          <span class="form-tip">清理的推广残留先移到这里，可恢复；永久删除后不可恢复</span>
        </div>
      </template>
      <el-table :data="trashBatches" border size="small" max-height="400">
        <el-table-column prop="batch" label="批次" width="170" />
        <el-table-column prop="count" label="文件数" width="70" />
        <el-table-column prop="size" label="大小" width="90">
          <template #default="{ row }">{{ formatSize(row.size) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="restoreBatch(row)">整批恢复</el-button>
            <el-button size="small" type="danger" @click="purgeBatch(row)">整批永久删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

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
import { Search, WarningFilled, CircleCloseFilled, Delete } from '@element-plus/icons-vue'
import {
  scanUnrecognized, manualLinkFile, manualSetNumber,
  renameUnrecognizedFile, deleteUnrecognizedFile, getMovies,
  scanAdResidue, trashAdResidue, getAdTrash, restoreAdTrash, purgeAdTrash
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

// ================= 推广残留清理 =================
const formatSize = (bytes) => {
  const n = Number(bytes) || 0
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB'
  return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB'
}

const residueScanning = ref(false)
const residueResult = ref(null)
const residueTab = ref('junk')
// 🔴 两个 tab 各存一份选中：共用一个 ref 时，切 tab 会互相覆盖，
// 在「建议清理」勾了一堆再切到「待确认」，勾选项会静默丢失。
const residueSelectedJunk = ref([])
const residueSelectedReview = ref([])
const residueSelected = computed(
  () => residueTab.value === 'junk' ? residueSelectedJunk.value : residueSelectedReview.value
)
const clearResidueSelection = () => {
  residueSelectedJunk.value = []
  residueSelectedReview.value = []
}

const runResidueScan = async () => {
  residueScanning.value = true
  try {
    residueResult.value = await scanAdResidue({})
    clearResidueSelection()
    const s = residueResult.value.summary
    if (!s.junk_count && !s.review_count) {
      ElMessage.success('未发现推广残留')
    } else {
      ElMessage.success(`扫描完成：建议清理 ${s.junk_count} 个，待确认 ${s.review_count} 个`)
    }
  } catch (e) {
    ElMessage.error('扫描失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    residueScanning.value = false
  }
}

const trashOneResidue = async (row) => {
  try {
    await ElMessageBox.confirm(
      `将「${row.filename}」移入回收站？\n原路径会空出来，回收站里可随时恢复。`,
      '移入回收站', { type: 'warning', confirmButtonText: '移入回收站', cancelButtonText: '取消' })
  } catch {
    return  // 用户取消
  }
  await doTrashResidue([row.path])
}

const trashSelectedResidue = async () => {
  if (!residueSelected.value.length) return
  try {
    await ElMessageBox.confirm(
      `将选中的 ${residueSelected.value.length} 个文件移入回收站？`,
      '批量移入回收站', { type: 'warning', confirmButtonText: '移入回收站', cancelButtonText: '取消' })
  } catch {
    return
  }
  await doTrashResidue(residueSelected.value.map(r => r.path))
}

const doTrashResidue = async (paths) => {
  try {
    const res = await trashAdResidue(paths)
    const failed = (res.results || []).filter(r => !r.ok)
    if (res.moved) {
      ElMessage.success(`已移入回收站 ${res.moved} 个` + (failed.length ? `，${failed.length} 个失败` : ''))
      // 从当前列表里移除已清理的，刷新回收站
      const movedPaths = new Set((res.results || []).filter(r => r.ok).map(r => r.path))
      if (residueResult.value) {
        residueResult.value.junk = residueResult.value.junk.filter(i => !movedPaths.has(i.path))
        residueResult.value.review = residueResult.value.review.filter(i => !movedPaths.has(i.path))
      }
      clearResidueSelection()
      await loadTrash()
    } else {
      ElMessage.error(failed.length ? failed[0].error : '移入回收站失败')
    }
  } catch (e) {
    ElMessage.error('操作失败: ' + (e.response?.data?.detail || e.message))
  }
}

// ================= 回收站 =================
const trashBatches = ref([])
const trashTotalCount = computed(() => trashBatches.value.reduce((n, b) => n + b.count, 0))
const trashTotalSize = computed(() => trashBatches.value.reduce((n, b) => n + b.size, 0))

const loadTrash = async () => {
  try {
    const res = await getAdTrash()
    trashBatches.value = res.batches || []
  } catch {
    // 回收站加载失败不打扰主流程
  }
}

const restoreBatch = async (row) => {
  const paths = row.items.filter(i => i.exists).map(i => i.trashed)
  if (!paths.length) {
    ElMessage.warning('该批次里没有可恢复的文件')
    return
  }
  try {
    await ElMessageBox.confirm(
      `恢复「${row.batch}」批次的 ${paths.length} 个文件到原路径？\n原位置已有同名文件时会跳过。`,
      '恢复', { type: 'info', confirmButtonText: '恢复', cancelButtonText: '取消' })
  } catch {
    return
  }
  try {
    const res = await restoreAdTrash(paths)
    if (res.restored) {
      ElMessage.success(`已恢复 ${res.restored} 个`)
      await loadTrash()
      runResidueScan()  // 恢复的文件可能重新出现在扫描结果里，静默刷新
    } else {
      const failed = (res.results || []).find(r => !r.ok)
      ElMessage.warning(failed ? failed.error : '恢复失败')
    }
  } catch (e) {
    ElMessage.error('操作失败: ' + (e.response?.data?.detail || e.message))
  }
}

const purgeBatch = async (row) => {
  const paths = row.items.filter(i => i.exists).map(i => i.trashed)
  if (!paths.length) {
    ElMessage.warning('该批次里没有可删除的文件')
    return
  }
  try {
    await ElMessageBox.confirm(
      `永久删除「${row.batch}」批次的 ${paths.length} 个文件？\n此操作不可恢复！`,
      '永久删除', { type: 'error', confirmButtonText: '确认永久删除', cancelButtonText: '取消' })
  } catch {
    return
  }
  try {
    const res = await purgeAdTrash(paths)
    if (res.purged) {
      ElMessage.success(`已永久删除 ${res.purged} 个`)
      await loadTrash()
    } else {
      ElMessage.warning('删除失败')
    }
  } catch (e) {
    ElMessage.error('操作失败: ' + (e.response?.data?.detail || e.message))
  }
}

loadTrash()

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

.residue-card :deep(.el-tabs__item) {
  font-size: 13px;
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
