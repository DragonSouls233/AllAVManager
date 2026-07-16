<template>
  <div class="module-manager">
    <h2 style="margin-bottom: 16px">模块管理</h2>

    <el-row :gutter="16">
      <el-col :span="8" v-for="mod in modules" :key="mod.name">
        <el-card shadow="hover" class="module-card" :class="{ disabled: !mod.enabled }">
          <div class="module-header">
            <span class="module-icon">{{ moduleIcons[mod.name] }}</span>
            <span class="module-name">{{ moduleLabels[mod.name] }}</span>
            <el-switch
              :model-value="mod.enabled"
              size="small"
              :loading="toggling[mod.name]"
              @change="(v) => toggleModule(mod.name, v)"
            />
          </div>
          <div class="module-stats">
            <p>媒体目录：<span class="path">{{ mod.media_dirs?.[0] || '未配置' }}</span></p>
            <p v-if="stats[mod.name]">
              ���片：{{ stats[mod.name].movie_count }} 部 |
              演员：{{ stats[mod.name].actor_count }} 人
            </p>
          </div>
          <div style="margin-top: 12px">
            <el-button size="small" @click="triggerScan(mod.name)" :loading="scanning[mod.name]">
              扫描
            </el-button>
            <el-button size="small" @click="viewMovies(mod.name)" :disabled="!mod.enabled">
              <el-icon><VideoCamera /></el-icon>
            </el-button>
            <el-button size="small" @click="editDirs(mod)">
              <el-icon><Edit /></el-icon>
            </el-button>
            <el-tag v-if="mod.actor_from_folder" size="small" type="success" style="margin-left: 8px">
              文件夹演员
            </el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 编辑媒体目录对话框 -->
    <el-dialog v-model="dirsDialog" :title="'编辑媒体目录 - ' + editingModule" width="500px">
      <el-input
        v-model="editingDirs"
        type="textarea"
        :rows="4"
        placeholder="每行一个目录路径"
      />
      <template #footer>
        <el-button @click="dirsDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveDirs">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Edit, VideoCamera } from '@element-plus/icons-vue'
import { getModules, getModuleStats, scanModule, getModulesConfig, updateModulesConfig, toggleModuleEnabled } from '@/api/modules'

const router = useRouter()

const modules = ref([])
const stats = ref({})
const scanning = ref({})
const toggling = ref({})
const saving = ref(false)
const dirsDialog = ref(false)
const editingModule = ref('')
const editingDirs = ref('')

const moduleIcons = { jav: '🇯🇵', uncensored: '🔞', fc2: '💿', chinese: '🇨🇳', pornhub: '🌐', western: '🌍' }
const moduleLabels = { jav: 'JAV 有码', uncensored: 'JAV 无码', fc2: 'FC2', chinese: '国产', pornhub: 'PORNHub', western: '欧美' }

async function loadModules() {
  modules.value = await getModules()
  for (const mod of modules.value) {
    try {
      const s = await getModuleStats(mod.name)
      stats.value[mod.name] = s
    } catch { /* ok */ }
  }
}

async function triggerScan(name) {
  scanning.value[name] = true
  try {
    await scanModule(name)
    ElMessage.success(`${moduleLabels[name]} 扫描完成`)
    const s = await getModuleStats(name)
    stats.value[name] = s
  } catch (e) {
    ElMessage.error('扫描失败: ' + (e?.response?.data?.detail || e.message || '未知错��'))
  } finally {
    scanning.value[name] = false
  }
}

async function toggleModule(name, enabled) {
  toggling.value[name] = true
  try {
    await toggleModuleEnabled(name, enabled)
    ElMessage.success(`${moduleLabels[name]} ${enabled ? '已启用' : '已禁用'}`)
  } catch (e) {
    ElMessage.error('操作失败: ' + (e?.response?.data?.detail || e.message || '未知错误'))
    // 回滚 UI
    const mod = modules.value.find(m => m.name === name)
    if (mod) mod.enabled = !enabled
  } finally {
    toggling.value[name] = false
  }
}

function viewMovies(name) {
  const routes = { jav: '/movies', chinese: '/chinese', fc2: '/fc2', uncensored: '/uncensored', pornhub: '/pornhub', western: '/western' }
  router.push(routes[name] || '/movies')
}

function editDirs(mod) {
  editingModule.value = moduleLabels[mod.name]
  editingDirs.value = (mod.media_dirs || []).join('\n')
  dirsDialog.value = true
}

async function saveDirs() {
  saving.value = true
  try {
    const moduleName = modules.value.find(m => moduleLabels[m.name] === editingModule.value)?.name
    if (!moduleName) return
    const dirs = editingDirs.value.split('\n').map(s => s.trim()).filter(Boolean)
    await updateModulesConfig({ [moduleName]: { media_dirs: dirs } })
    ElMessage.success('媒体目录已保存')
    dirsDialog.value = false
    await loadModules()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e?.response?.data?.detail || e.message || '未知错误'))
  } finally {
    saving.value = false
  }
}

onMounted(loadModules)
</script>

<style scoped>
.module-manager { padding: 20px; }
.module-card { margin-bottom: 16px; }
.module-card.disabled { opacity: 0.6; }
.module-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.module-icon { font-size: 20px; }
.module-name { flex: 1; font-weight: bold; }
.module-stats { font-size: 13px; color: #666; }
.path { font-family: monospace; font-size: 12px; color: #999; }
</style>
