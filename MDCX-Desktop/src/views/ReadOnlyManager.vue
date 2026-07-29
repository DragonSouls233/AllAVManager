<template>
  <div class="read-only-page">
    <div class="page-header">
      <h2>唯读来源管理</h2>
      <p class="desc">扫描现有视频文件，在不修改原文件的前提下生成 .strm 串流 + .nfo 元数据</p>
    </div>

    <!-- 扫描配置 -->
    <el-card class="config-card">
      <template #header>
        <span>目录扫描</span>
      </template>
      <el-form :model="form" label-width="120px">
        <el-form-item label="视频根目录">
          <el-input v-model="form.root_path" placeholder="如 F:\Movies\Chinese">
            <template #append>
              <el-button @click="browseFolder">浏览</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="选项">
          <el-checkbox v-model="form.recursive">递归子目录</el-checkbox>
          <el-checkbox v-model="form.generate_strm">生成 .strm</el-checkbox>
          <el-checkbox v-model="form.generate_nfo">生成 .nfo</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="scanning" @click="startScan">
            {{ scanning ? '扫描中...' : '开始扫描' }}
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 结果 -->
    <el-card v-if="scanResult" class="result-card">
      <template #header>
        <span>扫描结果</span>
      </template>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="根目录">{{ scanResult.root }}</el-descriptions-item>
        <el-descriptions-item label="视频文件">{{ scanResult.videos_found }}</el-descriptions-item>
        <el-descriptions-item label=".strm 生成">{{ scanResult.strm_generated }}</el-descriptions-item>
        <el-descriptions-item label=".nfo 生成">{{ scanResult.nfo_generated }}</el-descriptions-item>
        <el-descriptions-item label="数据目录">{{ scanResult.data_dir }}</el-descriptions-item>
        <el-descriptions-item label="JSON 索引">{{ scanResult.json_index }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 已有索引 -->
    <el-card v-if="indexData" class="index-card">
      <template #header>
        <span>已有索引 ({{ indexData.count }} 个视频)</span>
      </template>
      <el-table :data="indexData.movies" stripe style="width: 100%" max-height="400">
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column prop="module" label="模块" width="100" />
        <el-table-column prop="studio" label="工作室" width="120" />
        <el-table-column prop="file_size" label="大小" width="100">
          <template #default="{ row }">
            {{ formatBytes(row.file_size) }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.strm_path" size="small" type="success">已生成</el-tag>
            <el-tag v-else size="small">待生成</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="copyPath(row.file_path)">复制路径</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 空状态 -->
    <el-empty v-if="!scanResult && !indexData && !scanning" description="点击「开始扫描」创建唯读来源索引" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { scanReadOnlyDirectory, getReadOnlyIndex } from '@/api/read_only'

const form = ref({
  root_path: '',
  recursive: true,
  generate_strm: true,
  generate_nfo: true,
})
const scanning = ref(false)
const scanResult = ref(null)
const indexData = ref(null)

function browseFolder() {
  if (window.electronAPI) {
    window.electronAPI.selectFolder().then((folder) => {
      if (folder) form.value.root_path = folder
    })
  } else {
    ElMessage.info('请在桌面端使用，或手动输入路径')
  }
}

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(1)} ${units[i]}`
}

function copyPath(path) {
  navigator.clipboard.writeText(path).then(() => {
    ElMessage.success('已复制路径')
  })
}

async function startScan() {
  if (!form.value.root_path) {
    ElMessage.warning('请输入视频根目录')
    return
  }
  scanning.value = true
  scanResult.value = null
  try {
    const res = await scanReadOnlyDirectory({
      root_path: form.value.root_path,
      recursive: form.value.recursive,
      generate_strm: form.value.generate_strm,
      generate_nfo: form.value.generate_nfo,
    })
    scanResult.value = res
    ElMessage.success(`扫描完成: ${res.videos_found} 个视频`)
    await loadIndex()
  } catch (e) {
    ElMessage.error('扫描失败: ' + (e.detail || e.message || e))
  } finally {
    scanning.value = false
  }
}

async function loadIndex() {
  try {
    const res = await getReadOnlyIndex()
    indexData.value = res
  } catch (e) {
    // 无索引不报错
  }
}

onMounted(async () => {
  await loadIndex()
})
</script>

<style scoped>
.read-only-page { padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.page-header h2 { margin: 0; font-size: 18px; }
.desc { color: var(--el-text-color-secondary); font-size: 13px; margin-top: 4px; }
.config-card { max-width: 600px; }
.result-card {}
.index-card {}
</style>
