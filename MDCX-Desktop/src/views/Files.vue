<template>
  <div class="files-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h2>文件管理 / 目录浏览</h2>
      <p class="subtitle">浏览服务器磁盘目录 · 选择媒体路径 · 支持 Windows 盘符与 Linux 挂载点</p>
    </div>

    <!-- 工具栏 -->
    <div class="action-bar">
      <el-button @click="goUp" :disabled="!parentPath" :loading="loading">
        <el-icon><Top /></el-icon> 上级目录
      </el-button>
      <el-button @click="goRoots" :loading="loading">
        <el-icon><HomeFilled /></el-icon> 此电脑
      </el-button>
      <el-switch
        v-model="showFiles"
        active-text="显示文件"
        inactive-text="仅目录"
        @change="loadCurrent"
        style="margin-left: 8px"
      />
      <el-button @click="copyCurrentPath" :disabled="!currentPath || currentPath === 'THIS_PC'">
        <el-icon><CopyDocument /></el-icon> 复制当前路径
      </el-button>
    </div>

    <!-- 面包屑 -->
    <div class="breadcrumb-bar">
      <el-breadcrumb separator="/">
        <el-breadcrumb-item v-for="(seg, i) in breadcrumb" :key="i">
          <a @click="navigateTo(seg.path)" class="crumb-link">{{ seg.name }}</a>
        </el-breadcrumb-item>
      </el-breadcrumb>
      <span v-if="currentPath && currentPath !== 'THIS_PC'" class="current-path">{{ currentPath }}</span>
    </div>

    <!-- 目录/文件列表 -->
    <el-card shadow="never" class="list-card">
      <div v-loading="loading" class="entries">
        <div
          v-for="entry in entries"
          :key="entry.path"
          class="entry"
          :class="{ 'is-file': entry.type === 'file' }"
          @click="entry.type === 'directory' ? enter(entry) : undefined"
        >
          <div class="entry-icon">
            <el-icon v-if="entry.type === 'directory'" size="22" color="#409eff"><FolderOpened /></el-icon>
            <el-icon v-else size="22" color="#909399"><Document /></el-icon>
          </div>
          <div class="entry-name" :title="entry.name">{{ entry.name }}</div>
          <div class="entry-meta" v-if="entry.type === 'file'">{{ formatSize(entry.size) }}</div>
          <div class="entry-meta" v-else-if="entry.drive_type">{{ entry.drive_type }}</div>
        </div>
        <el-empty v-if="!loading && !entries.length" description="空目录" :image-size="80" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Top, HomeFilled, CopyDocument, FolderOpened, Document } from '@element-plus/icons-vue'
import { getFileRoots, browseDirectory } from '@/api'

const loading = ref(false)
const showFiles = ref(false)
const entries = ref([])
const currentPath = ref('THIS_PC')
const currentName = ref('此电脑')
const parentPath = ref(null)

const breadcrumb = ref([{ name: '此电脑', path: 'THIS_PC' }])

async function loadRoots() {
  loading.value = true
  try {
    const res = await getFileRoots()
    entries.value = res.roots || []
    currentPath.value = 'THIS_PC'
    currentName.value = '此电脑'
    parentPath.value = null
    breadcrumb.value = [{ name: '此电脑', path: 'THIS_PC' }]
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

async function loadCurrent() {
  loading.value = true
  try {
    const res = await browseDirectory(currentPath.value, showFiles.value)
    entries.value = res.entries || []
    currentName.value = res.current_name
    parentPath.value = res.parent_path
    breadcrumb.value = splitPath(currentPath.value)
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function enter(entry) {
  currentPath.value = entry.path
  loadCurrent()
}

function goUp() {
  if (parentPath.value) {
    currentPath.value = parentPath.value
    loadCurrent()
  }
}

function goRoots() {
  loadRoots()
}

function navigateTo(path) {
  currentPath.value = path
  loadCurrent()
}

function copyCurrentPath() {
  if (!currentPath.value || currentPath.value === 'THIS_PC') return
  navigator.clipboard?.writeText(currentPath.value).then(
    () => ElMessage.success('路径已复制'),
    () => ElMessage.warning('复制失败，请手动选择')
  )
}

function splitPath(p) {
  if (p === 'THIS_PC') return [{ name: '此电脑', path: 'THIS_PC' }]
  // Windows 盘符路径: C:\a\b
  if (/^[A-Za-z]:[\\/]/.test(p)) {
    const drive = p.slice(0, 2) // C:
    const sep = p[2] // \ or /
    const rest = p.slice(3)
    const segs = rest.split(/[\\/]/).filter(Boolean)
    const crumbs = [{ name: drive, path: drive + sep }]
    let acc = drive + sep
    segs.forEach((s) => {
      acc += s + sep
      crumbs.push({ name: s, path: acc.replace(/[\\/]$/, '') })
    })
    return crumbs
  }
  // Linux 路径: /a/b
  const segs = p.split('/').filter(Boolean)
  const crumbs = [{ name: '/', path: '/' }]
  let acc = ''
  segs.forEach((s) => {
    acc += '/' + s
    crumbs.push({ name: s, path: acc })
  })
  return crumbs
}

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = bytes
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(1)} ${units[i]}`
}

onMounted(() => {
  loadRoots()
})
</script>

<style scoped>
.files-page {
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

.action-bar {
  margin-bottom: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.breadcrumb-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding: 10px 14px;
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 8px;
  flex-wrap: wrap;
}

.crumb-link {
  cursor: pointer;
  color: #409eff;
}

.crumb-link:hover {
  text-decoration: underline;
}

.current-path {
  font-size: 12px;
  color: #909399;
  font-family: monospace;
  word-break: break-all;
}

.entries {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
  min-height: 300px;
}

.entry {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
}

.entry:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.1);
}

.entry.is-file {
  cursor: default;
}

.entry.is-file:hover {
  transform: none;
  box-shadow: none;
}

.entry-icon {
  flex-shrink: 0;
}

.entry-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-meta {
  font-size: 11px;
  color: #909399;
  flex-shrink: 0;
}
</style>
