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
              v-model="mod.enabled"
              size="small"
              @change="(v) => toggleModule(mod.name, v)"
            />
          </div>
          <div class="module-stats">
            <p>媒体目录：<span class="path">{{ mod.media_dirs?.[0] || '未配置' }}</span></p>
            <p v-if="stats[mod.name]">
              影片：{{ stats[mod.name].movie_count }} 部 |
              演员：{{ stats[mod.name].actor_count }} 人
            </p>
          </div>
          <div style="margin-top: 12px">
            <el-button size="small" @click="triggerScan(mod.name)" :loading="scanning[mod.name]">
              扫描
            </el-button>
            <el-tag v-if="mod.actor_from_folder" size="small" type="success" style="margin-left: 8px">
              文件夹演员
            </el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getModules, getModuleStats, scanModule } from '@/api/modules'

const modules = ref([])
const stats = ref({})
const scanning = ref({})

const moduleIcons = { jav: '🇯🇵', uncensored: '🔞', fc2: '💿', chinese: '🇨🇳', pornhub: '🌍' }
const moduleLabels = { jav: 'JAV 有码', uncensored: 'JAV 无码', fc2: 'FC2', chinese: '国产', pornhub: 'PORNHub' }

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
    const s = await getModuleStats(name)
    stats.value[name] = s
  } finally {
    scanning.value[name] = false
  }
}

function toggleModule(name, enabled) {
  // TODO: 写配置
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
