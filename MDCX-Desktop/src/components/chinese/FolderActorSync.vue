<template>
  <div class="folder-actor-sync">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>文件夹演员同步</span>
          <el-button type="primary" size="small" :loading="syncing" @click="startSync">
            <el-icon><Refresh /></el-icon> 立即同步
          </el-button>
        </div>
      </template>

      <div class="sync-info" v-if="!notConfigured">
        <p>从国产媒体目录的文件夹名自动识别演员</p>
        <p class="hint">
          文件夹名规则：中文名（2-8字）、英文名（首字母大写）、
          支持 "+" / "." / "_" 分割多演员名
        </p>
      </div>

      <el-empty v-if="notConfigured" description="未配置国产媒体目录，请先在设置中配置" />

      <div v-if="result" class="sync-result">
        <el-alert :type="result.errors?.length ? 'warning' : 'success'" show-icon>
          <p>扫描完成：共发现 {{ result.total }} 部视频，识别 {{ result.scanned }} 部，</p>
          <p>发现 {{ result.actors?.length || 0 }} 名演员</p>
        </el-alert>
        <el-collapse v-if="result.errors?.length" style="margin-top: 8px">
          <el-collapse-item title="查看扫描错误">
            <p v-for="e in result.errors" :key="e" class="error-item">{{ e }}</p>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getChineseActors, syncChineseFolderActors } from '@/api/chinese'

const syncing = ref(false)
const notConfigured = ref(false)
const result = ref(null)

async function startSync() {
  syncing.value = true
  try {
    result.value = await syncChineseFolderActors()
  } finally {
    syncing.value = false
  }
}

onMounted(async () => {
  try {
    const actors = await getChineseActors()
    if (!actors) notConfigured.value = true
  } catch {
    notConfigured.value = true
  }
})
</script>

<style scoped>
.sync-info p { margin: 4px 0; }
.hint { font-size: 12px; color: #999; }
.sync-result { margin-top: 12px; }
.error-item { font-size: 12px; color: #e6a23c; margin: 2px 0; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
</style>
