<template>
  <div class="refresh-folders-page">
    <el-card shadow="never" class="intro-card">
      <div class="intro">
        <el-icon size="28"><RefreshRight /></el-icon>
        <div>
          <h3>文件夹刷新</h3>
          <p>重新扫描指定盘符/目录，自动更新影片文件路径。适用于视频文件迁移、盘符整理等场景。</p>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="config-card">
      <template #header>
        <div class="card-title"><el-icon><FolderOpened /></el-icon> 扫描配置</div>
      </template>

      <el-form label-width="140px" class="config-form">
        <el-form-item label="扫描目录">
          <el-input
            v-model="directoriesText"
            type="textarea"
            :rows="4"
            placeholder="每行一个目录路径，例如：&#10;D:\Videos&#10;E:\Media&#10;F:\Movies"
          />
          <div class="form-tip">输入要扫描的根目录，每行一个。将递归扫描所有子目录中的视频文件。</div>
        </el-form-item>

        <el-form-item label="清理失效路径">
          <el-switch v-model="clearMissing" />
          <span class="switch-label">清理已不存在文件的影片记录</span>
          <div class="form-tip">开启后，文件已被删除或移动的影片将被清除 file_path</div>
        </el-form-item>

        <el-form-item label="预览模式">
          <el-switch v-model="dryRun" />
          <span class="switch-label">仅预览变更，不实际修改数据库</span>
          <div class="form-tip">开启后只展示扫描结果，不会修改任何数据</div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" size="large" @click="startScan" :loading="scanning">
            <el-icon><Search /></el-icon>
            {{ scanning ? '扫描中...' : '开始扫描' }}
          </el-button>
          <el-button size="large" @click="reset" :disabled="scanning">
            <el-icon><Refresh /></el-icon> 重置
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 扫描进度 -->
    <el-card v-if="scanning" shadow="never" class="progress-card">
      <div class="progress-block">
        <el-icon class="is-loading progress-icon"><Loading /></el-icon>
        <span class="progress-text">正在扫描目录，请稍候...</span>
      </div>
    </el-card>

    <!-- 扫描结果 -->
    <template v-if="result">
      <el-card shadow="never" class="summary-card">
        <template #header>
          <div class="card-title">
            <el-icon><DataAnalysis /></el-icon>
            扫描概览
            <el-tag v-if="result.dry_run" type="warning" size="small" style="margin-left:8px">预览模式</el-tag>
          </div>
        </template>

        <el-row :gutter="16">
          <el-col :span="6">
            <div class="stat-item">
              <div class="stat-value">{{ result.scanned_dirs }}</div>
              <div class="stat-label">扫描目录</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="stat-item">
              <div class="stat-value">{{ result.scanned_files }}</div>
              <div class="stat-label">扫描文件</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="stat-item">
              <div class="stat-value">{{ result.unique_codes }}</div>
              <div class="stat-label">识别番号</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="stat-item">
              <div class="stat-value">{{ result.total_movies_in_db }}</div>
              <div class="stat-label">数据库影片</div>
            </div>
          </el-col>
        </el-row>

        <el-row :gutter="16" style="margin-top: 16px">
          <el-col :span="6">
            <div class="stat-item highlight green">
              <div class="stat-value">{{ result.updated_count }}</div>
              <div class="stat-label">路径已更新</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="stat-item highlight blue">
              <div class="stat-value">{{ result.unchanged_count }}</div>
              <div class="stat-label">路径未变</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="stat-item highlight orange">
              <div class="stat-value">{{ result.cleared_count }}</div>
              <div class="stat-label">已清理</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="stat-item highlight red">
              <div class="stat-value">{{ result.not_found_count }}</div>
              <div class="stat-label">未匹配</div>
            </div>
          </el-col>
        </el-row>

        <div class="duration-info">
          <el-icon><Clock /></el-icon>
          耗时 {{ result.scan_duration_seconds }} 秒
        </div>
      </el-card>

      <el-card v-if="result.updated.length" shadow="never" class="detail-card">
        <template #header>
          <div class="card-title">
            <el-icon><SuccessFilled /></el-icon> 路径变更列表
            <span class="detail-count">{{ result.updated_count }} 条</span>
          </div>
        </template>
        <el-table :data="result.updated" stripe max-height="400" size="small">
          <el-table-column prop="code" label="番号" width="140" />
          <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
          <el-table-column prop="old_path" label="旧路径" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span :class="{ 'missing-path': !row.old_path }">{{ row.old_path || '（空）' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="new_path" label="新路径" min-width="200" show-overflow-tooltip />
        </el-table>
      </el-card>

      <el-card v-if="result.cleared.length" shadow="never" class="detail-card">
        <template #header>
          <div class="card-title">
            <el-icon><Delete /></el-icon> 已清理列表
            <span class="detail-count">{{ result.cleared_count }} 条</span>
          </div>
        </template>
        <el-table :data="result.cleared" stripe max-height="300" size="small">
          <el-table-column prop="code" label="番号" width="140" />
          <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
          <el-table-column prop="old_path" label="原路径（已失效）" min-width="300" show-overflow-tooltip />
        </el-table>
      </el-card>

      <el-card v-if="result.not_found.length" shadow="never" class="detail-card">
        <template #header>
          <div class="card-title">
            <el-icon><WarningFilled /></el-icon> 未匹配列表
            <span class="detail-count">{{ result.not_found_count }} 条</span>
          </div>
        </template>
        <el-table :data="result.not_found" stripe max-height="300" size="small">
          <el-table-column prop="code" label="番号" width="140" />
          <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip />
          <el-table-column prop="path" label="文件路径" min-width="300" show-overflow-tooltip />
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  RefreshRight, FolderOpened, Search, Refresh, DataAnalysis, Clock,
  SuccessFilled, Delete, WarningFilled, Loading
} from '@element-plus/icons-vue'
import { refreshFolders } from '@/api'

const directoriesText = ref('')
const clearMissing = ref(true)
const dryRun = ref(false)
const scanning = ref(false)
const result = ref(null)

const startScan = async () => {
  const dirs = directoriesText.value
    .split('\n')
    .map(s => s.trim())
    .filter(Boolean)

  if (!dirs.length) {
    ElMessage.warning('请输入至少一个扫描目录')
    return
  }

  scanning.value = true
  result.value = null

  try {
    const res = await refreshFolders(dirs, dryRun.value, clearMissing.value)
    result.value = res
    if (res.dry_run) {
      ElMessage.success(`预览完成：扫描 ${res.scanned_files} 个文件，将更新 ${res.updated_count} 条，清理 ${res.cleared_count} 条`)
    } else {
      ElMessage.success(`刷新完成：更新 ${res.updated_count} 条路径，清理 ${res.cleared_count} 条失效记录`)
    }
  } catch (e) {
    ElMessage.error(`扫描失败: ${e?.response?.data?.detail || e?.message || '未知错误'}`)
  } finally {
    scanning.value = false
  }
}

const reset = () => {
  directoriesText.value = ''
  result.value = null
}
</script>

<style scoped>
.refresh-folders-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1200px;
  margin: 0 auto;
}

.intro-card {
  border-radius: 10px;
  background: linear-gradient(135deg, #f0f9ff 0%, #ecf5ff 100%);
  border-color: #b3d8ff;
}

.intro {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.intro h3 {
  margin: 0 0 4px;
  font-size: 17px;
  color: #303133;
}

.intro p {
  margin: 0;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}

.config-card {
  border-radius: 10px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 15px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.switch-label {
  margin-left: 8px;
  font-size: 13px;
  color: #606266;
}

.config-form {
  padding-right: 40px;
}

/* 进度 */
.progress-card {
  border-radius: 10px;
}

.progress-block {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 20px 0;
}

.progress-icon {
  font-size: 24px;
  color: #409eff;
  animation: rotating 1.5s linear infinite;
}

.progress-text {
  font-size: 15px;
  color: #409eff;
  font-weight: 500;
}

@keyframes rotating {
  from { transform: rotate(0); }
  to { transform: rotate(360deg); }
}

/* 统计概览 */
.summary-card {
  border-radius: 10px;
}

.stat-item {
  text-align: center;
  padding: 12px 8px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
}

.stat-item.highlight {
  background: var(--el-color-primary-light-9);
}

.stat-item.highlight.green {
  background: #f0f9eb;
}

.stat-item.highlight.blue {
  background: #ecf5ff;
}

.stat-item.highlight.orange {
  background: #fdf6ec;
}

.stat-item.highlight.red {
  background: #fef0f0;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--el-text-color-primary);
}

.highlight.green .stat-value { color: #67c23a; }
.highlight.blue .stat-value { color: #409eff; }
.highlight.orange .stat-value { color: #e6a23c; }
.highlight.red .stat-value { color: #f56c6c; }

.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.duration-info {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 16px;
  font-size: 13px;
  color: #909399;
}

/* 详情 */
.detail-card {
  border-radius: 10px;
}

.detail-count {
  font-weight: 400;
  font-size: 13px;
  color: #909399;
}

.missing-path {
  color: #c0c4cc;
  font-style: italic;
}
</style>
