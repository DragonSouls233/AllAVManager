<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    title="选择媒体目录"
    width="650px"
    :close-on-click-modal="false"
    top="5vh"
  >
    <!-- 当前路径 -->
    <div class="browser-header">
      <el-breadcrumb>
        <el-breadcrumb-item>
          <el-link type="primary" @click="goRoot">此电脑</el-link>
        </el-breadcrumb-item>
        <el-breadcrumb-item v-for="seg in pathSegments" :key="seg.path">
          <el-link type="primary" @click="navigateTo(seg.path)">{{ seg.name }}</el-link>
        </el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <!-- 操作栏 -->
    <div class="browser-actions">
      <el-button size="small" @click="goUp" :disabled="!parentPath">
        <el-icon><Back /></el-icon> 上级目录
      </el-button>
      <el-button size="small" @click="enterCurrent" :disabled="!canEnterCurrent" type="primary" plain>
        <el-icon><FolderOpened /></el-icon> 进入此目录
      </el-button>
      <el-button size="small" @click="refresh" :loading="loading" style="margin-left:auto;">
        <el-icon><Refresh /></el-icon> 刷新
      </el-button>
    </div>

    <!-- 目录列表 -->
    <div class="browser-body" v-loading="loading">
      <div
        v-for="entry in entries"
        :key="entry.path"
        class="browser-item"
        :class="{ selected: selectedPath === entry.path }"
        @click="onItemClick(entry)"
      >
        <el-icon v-if="entry.is_drive" :size="20" style="margin-right:8px;color:#409eff;"><Connection /></el-icon>
        <el-icon v-else :size="20" style="margin-right:8px;color:#e6a23c;"><Folder /></el-icon>
        <span class="item-name">{{ entry.is_drive ? entry.path : entry.name }}</span>
        <el-tag v-if="entry.drive_type" size="small" type="info">{{ entry.drive_type }}</el-tag>
        <el-button size="small" link type="primary" class="item-enter-btn" @click.stop="enterDirectory(entry.path)">
          进入
        </el-button>
      </div>
      <el-empty v-if="!loading && entries.length === 0" description="该目录下没有子文件夹" />
    </div>

    <!-- 选中路径 -->
    <div class="browser-footer">
      <el-input
        :model-value="selectedPath"
        readonly
        size="small"
        placeholder="点击目录项选中，点击「进入」按钮进入子目录"
      >
        <template #prepend>已选</template>
      </el-input>
    </div>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="confirmSelect" :disabled="!selectedPath">确定选择</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Back, Refresh, Connection, Folder, FolderOpened } from '@element-plus/icons-vue'
import { browseDirectory } from '@/api'

const props = defineProps({
  visible: Boolean,
  initialPath: { type: String, default: '' }
})

const emit = defineEmits(['update:visible', 'select'])

const loading = ref(false)
const currentPath = ref('THIS_PC')
const currentName = ref('此电脑')
const parentPath = ref(null)
const entries = ref([])
const selectedPath = ref('')
const pathSegments = ref([])

const canEnterCurrent = computed(() => {
  return currentPath.value && currentPath.value !== 'THIS_PC'
})

// 监听对话框打开
watch(() => props.visible, async (val) => {
  if (val) {
    selectedPath.value = ''
    if (props.initialPath) {
      await loadDirectory(props.initialPath)
    } else {
      await loadDirectory('THIS_PC')
    }
  }
})

function updatePathSegments() {
  if (currentPath.value === 'THIS_PC') {
    pathSegments.value = []
    return
  }
  const segs = []
  // Windows 路径处理:  C:\Users\xxx  ->  [{name:"C:\", path:"C:\"}, {name:"Users", path:"C:\Users"}, {name:"xxx", path:"C:\Users\xxx"}]
  const normalized = currentPath.value.replace(/\//g, '\\')
  const parts = normalized.split('\\').filter(Boolean)

  if (parts.length > 0 && parts[0].match(/^[A-Za-z]:$/)) {
    // 盘符
    const drive = parts[0] + '\\'
    segs.push({ name: drive, path: drive })
    let accumulated = drive
    for (let i = 1; i < parts.length; i++) {
      accumulated = accumulated.replace(/\\$/, '') + '\\' + parts[i]
      segs.push({ name: parts[i], path: accumulated })
    }
  } else {
    let accumulated = ''
    for (let i = 0; i < parts.length; i++) {
      accumulated = (i === 0 ? '' : accumulated + '\\') + parts[i]
      segs.push({ name: parts[i], path: accumulated })
    }
  }
  pathSegments.value = segs
}

async function loadDirectory(path) {
  loading.value = true
  try {
    const res = await browseDirectory(path, false)
    currentPath.value = res.current_path
    currentName.value = res.current_name
    parentPath.value = res.parent_path
    entries.value = (res.entries || []).filter(e => e.type === 'directory' || e.is_drive)
    updatePathSegments()
    // 自动选中当前目录（盘符根目录不自动选中）
    if (currentPath.value !== 'THIS_PC') {
      selectedPath.value = currentPath.value
    } else {
      selectedPath.value = ''
    }
  } catch (e) {
    entries.value = []
    selectedPath.value = ''
    const detail = e?.response?.data?.detail || e.message || '未知错误'
    ElMessage.error('浏览目录失败: ' + detail)
  } finally {
    loading.value = false
  }
}

function goRoot() {
  loadDirectory('THIS_PC')
}

function goUp() {
  if (!parentPath.value) return
  if (parentPath.value === 'THIS_PC') {
    loadDirectory('THIS_PC')
  } else {
    loadDirectory(parentPath.value)
  }
}

function navigateTo(path) {
  loadDirectory(path)
}

function enterDirectory(path) {
  loadDirectory(path)
}

function enterCurrent() {
  if (canEnterCurrent.value) {
    enterDirectory(currentPath.value)
  }
}

/**
 * 单击条目：选中即可，再点一次「进入」按钮进入
 */
function onItemClick(entry) {
  selectedPath.value = entry.path
}

async function refresh() {
  await loadDirectory(currentPath.value)
}

function confirmSelect() {
  if (selectedPath.value) {
    emit('select', selectedPath.value)
    emit('update:visible', false)
  }
}
</script>

<style scoped>
.browser-header {
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-light);
}
.browser-actions {
  margin-bottom: 12px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.browser-body {
  min-height: 280px;
  max-height: 420px;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  padding: 4px;
}
.browser-item {
  display: flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
}
.browser-item:hover {
  background: var(--el-color-primary-light-9);
}
.browser-item.selected {
  background: var(--el-color-primary-light-8);
  color: var(--el-color-primary);
}
.item-name {
  flex: 1;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.item-enter-btn {
  opacity: 0;
  transition: opacity 0.15s;
  margin-left: 8px;
  flex-shrink: 0;
}
.browser-item:hover .item-enter-btn {
  opacity: 1;
}
.browser-item.selected .item-enter-btn {
  opacity: 1;
}
.browser-footer {
  margin-top: 12px;
}
</style>
