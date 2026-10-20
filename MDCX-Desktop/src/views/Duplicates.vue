<template>
  <div class="duplicates-page">
    <div class="page-header">
      <h2>重复番号扫描</h2>
      <p class="desc">扫描媒体目录中同一番号存在多份视频文件的重复项，帮助清理冗余副本、节约硬盘空间。中字版（-C/-UC）会被优先推荐保留。</p>
    </div>

    <div class="toolbar">
      <div class="toolbar-left">
        <el-checkbox-group v-model="selectedModules" :min="1">
          <el-checkbox-button label="jav">JAV</el-checkbox-button>
          <el-checkbox-button label="uncensored">无码</el-checkbox-button>
          <el-checkbox-button label="chinese">国产</el-checkbox-button>
          <el-checkbox-button label="western">欧美</el-checkbox-button>
          <el-checkbox-button label="fc2">FC2</el-checkbox-button>
        </el-checkbox-group>
        <el-tooltip content="对每个视频文件读取首尾各 64KB 计算内容指纹，额外找出「改名/错贴番号/分卷误判」导致文件名匹配不到的重复副本。大库会明显拉长扫描时间，按需开启。" placement="top">
          <el-checkbox v-model="contentCheck" style="margin-left:12px">内容指纹（找改名副本）</el-checkbox>
        </el-tooltip>
      </div>
      <div class="toolbar-right">
        <el-button type="primary" :loading="scanning" :icon="Search" @click="startScan">
          {{ scanning ? '扫描中...' : '开始扫描' }}
        </el-button>
      </div>
    </div>

    <div v-if="errorMsg" class="error-box">
      <el-alert type="error" :title="errorMsg" show-icon closable @close="errorMsg = ''" />
    </div>

    <div v-if="result && !scanning" class="summary">
      <el-row :gutter="16">
        <el-col :span="8">
          <el-statistic title="扫描视频文件" :value="result.total_files" />
        </el-col>
        <el-col :span="8">
          <el-statistic title="重复组数" :value="result.total_groups">
            <template #suffix>
              <el-tag v-if="result.total_groups > 0" type="warning" size="small" style="margin-left:8px">
                {{ result.duplicate_files }} 个多余文件
              </el-tag>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="8">
          <el-statistic title="可释放空间" :value="result.space_wasted_display" />
        </el-col>
      </el-row>
    </div>

    <div v-if="result && result.total_groups > 0" class="groups">
      <!-- 第一级：分类/演员 -->
      <el-collapse v-for="[cat, groups] in categoryGroups" :key="cat" class="cat-block">
        <el-collapse-item :name="cat">
          <template #title>
            <div class="cat-title">
              <el-tag type="primary" size="small">{{ cat }}</el-tag>
              <span class="cat-count">{{ groups.length }} 个番号重复</span>
              <span class="cat-waste">可释放 {{ formatBytes(groups.reduce((s, g) => s + g.wasted_bytes, 0)) }}</span>
            </div>
          </template>
          <!-- 第二级：番号 -->
          <el-collapse v-for="group in groups" :key="group.base_code" class="code-block">
            <el-collapse-item :name="cat + '/' + group.base_code">
          <template #title>
            <div class="code-title">
              <el-tag type="danger" size="small">{{ group.file_count }} 个重复</el-tag>
              <el-tooltip v-if="group.content_match" content="组内有文件内容指纹（oshash）完全相同，是字节级副本，删除冗余副本零风险" placement="top">
                <el-tag type="success" size="small">含字节相同副本</el-tag>
              </el-tooltip>
              <el-tooltip v-else content="组内文件内容指纹不同，属于版本差异（如中字版/无字幕版/不同片源），删哪个需要判断" placement="top">
                <el-tag type="info" size="small">版本差异</el-tag>
              </el-tooltip>
              <span class="code-name">{{ group.base_code }}</span>
              <span class="code-waste">→ {{ group.wasted_display }}</span>
            </div>
          </template>
          <!-- 第三级：文件表 -->
          <el-table :data="group.files" stripe size="small">
            <el-table-column label="推荐" width="70">
              <template #default="{ $index }">
                <el-tag v-if="$index === group.keep_index" type="success" size="small">保留</el-tag>
                <el-tag v-else type="info" size="small">可删</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="文件路径" prop="path" min-width="400" show-overflow-tooltip />
            <el-table-column label="后缀" prop="suffix" width="100" />
            <el-table-column label="中字" width="70" align="center">
              <template #default="{ row }">
                <el-icon v-if="row.is_chinese" color="#67c23a"><Check /></el-icon>
                <span v-else style="color:#c0c4cc">-</span>
              </template>
            </el-table-column>
            <el-table-column label="文件大小" prop="size_display" width="110" />
            <el-table-column label="内容指纹" width="120">
              <template #default="{ row }">
                <span v-if="row.oshash" style="font-family:monospace;font-size:11px" :title="row.oshash">{{ row.oshash.slice(0, 10) }}…</span>
                <span v-else style="color:#c0c4cc">-</span>
              </template>
            </el-table-column>
          </el-table>
            </el-collapse-item>
          </el-collapse>
        </el-collapse-item>
      </el-collapse>
    </div>

    <div v-if="contentGroups.length > 0" class="content-groups">
      <h3>跨名内容重复 <el-tag type="warning" size="small">{{ contentGroups.length }} 组</el-tag></h3>
      <p class="desc">以下文件的内容指纹（oshash）完全相同，但文件名/番号不同或提取不出番号——纯文件名匹配永远找不到它们。大文件推荐保留。</p>
      <el-collapse v-for="(cg, i) in contentGroups" :key="cg.oshash + i" class="cat-block">
        <el-collapse-item :name="'cg-' + i">
          <template #title>
            <div class="cat-title">
              <el-tag type="danger" size="small">{{ cg.file_count }} 个副本</el-tag>
              <span class="code-name">{{ cg.oshash }}</span>
              <span class="cat-waste">可释放 {{ cg.wasted_display }}</span>
            </div>
          </template>
          <el-table :data="cg.files" stripe size="small">
            <el-table-column label="推荐" width="70">
              <template #default="{ $index }">
                <el-tag v-if="$index === 0" type="success" size="small">保留</el-tag>
                <el-tag v-else type="info" size="small">可删</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="文件路径" prop="path" min-width="400" show-overflow-tooltip />
            <el-table-column label="识别番号" width="120">
              <template #default="{ row }">
                <span v-if="row.code" style="font-family:monospace">{{ row.code }}{{ row.part ? '-CD' + row.part : '' }}</span>
                <span v-else style="color:#c0c4cc">未识别</span>
              </template>
            </el-table-column>
            <el-table-column label="文件大小" prop="size_display" width="110" />
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </div>

    <div v-if="result && result.total_groups === 0 && contentGroups.length === 0 && !scanning" class="empty">
      <el-empty description="未发现重复番号，所有番号均为唯一" />
    </div>

    <div v-if="!result && !scanning" class="placeholder">
      <el-empty :description="`点击「开始扫描」扫描 jav 模块共 8000+ 文件中存在的重复番号\n(扫描时间约 1~3 分钟)`">
        <template #image>
          <el-icon :size="60" color="#909399"><FolderOpened /></el-icon>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Search, Check, FolderOpened } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const selectedModules = ref(['jav'])
const contentCheck = ref(false)
const scanning = ref(false)
const result = ref(null)
const errorMsg = ref('')

function formatBytes(b) {
  if (b >= 1073741824) return (b / 1073741824).toFixed(2) + ' GB'
  if (b >= 1048576) return (b / 1048576).toFixed(1) + ' MB'
  return (b / 1024).toFixed(0) + ' KB'
}

const categoryGroups = computed(() => {
  const raw = []
  if (result.value?.groups) raw.push(...result.value.groups)
  if (result.value?.modules) {
    result.value.modules.forEach(m => { if (m.groups) raw.push(...m.groups) })
  }
  const map = {}
  raw.forEach(g => {
    const cat = g.category || '其他'
    if (!map[cat]) map[cat] = []
    map[cat].push(g)
  })
  // 按分类名排序，每个分类内按番号排序
  const entries = Object.entries(map).sort((a, b) => a[0].localeCompare(b[0]))
  entries.forEach(([, groups]) => groups.sort((a, b) => a.base_code.localeCompare(b.base_code)))
  return entries
})

// 跨名内容重复组（content_check=True 时才有），合并多模块结果
const contentGroups = computed(() => {
  const raw = []
  if (result.value?.content_groups) raw.push(...result.value.content_groups)
  if (result.value?.modules) {
    result.value.modules.forEach(m => { if (m.content_groups) raw.push(...m.content_groups) })
  }
  return raw.sort((a, b) => (b.wasted_bytes || 0) - (a.wasted_bytes || 0))
})

async function startScan() {
  scanning.value = true
  result.value = null
  errorMsg.value = ''
  try {
    const moduleParams = selectedModules.value.map(m => `module=${m}`).join('&')
    const contentParam = contentCheck.value ? '&content=1' : ''
    const data = await api.get(`/duplicates/scan?${moduleParams}${contentParam}`, { timeout: 600000 })
    console.log('重复扫描结果:', data)
    result.value = data
    const extra = contentGroups.value.length > 0 ? `，另发现 ${contentGroups.value.length} 组跨名内容重复` : ''
    if (!data || (data.total_groups === 0 && contentGroups.value.length === 0)) {
      ElMessage.success('扫描完成，未发现重复番号')
    } else {
      ElMessage.success(`发现 ${data.total_groups} 组重复，共 ${data.duplicate_files} 个文件，可释放 ${data.space_wasted_display}${extra}`)
    }
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '扫描失败'
    errorMsg.value = msg
    console.error('重复扫描失败:', e)
    ElMessage.error(msg)
  } finally {
    scanning.value = false
  }
}
</script>

<style scoped>
.duplicates-page {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header h2 {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 6px;
}

.page-header .desc {
  color: #909399;
  font-size: 13px;
  margin-bottom: 20px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  background: #fff;
  padding: 16px;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}

.summary {
  background: #fff;
  padding: 20px;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
  margin-bottom: 20px;
}

.groups {
  margin-bottom: 20px;
}

.content-groups {
  margin-bottom: 20px;
}

.content-groups h3 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.content-groups .desc {
  color: #909399;
  font-size: 13px;
  margin-bottom: 16px;
}

.cat-block {
  margin-bottom: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
}

.cat-title {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.cat-count {
  color: #606266;
  font-size: 14px;
}

.cat-waste {
  color: #e6a23c;
  font-size: 13px;
  margin-left: auto;
  margin-right: 20px;
}

.code-block {
  margin: 4px 16px 4px 0;
  border-left: 3px solid #e6a23c;
}

.code-title {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.code-name {
  font-weight: 600;
  font-family: monospace;
  font-size: 14px;
  color: #303133;
}

.code-waste {
  color: #e6a23c;
  font-size: 13px;
  margin-left: auto;
  margin-right: 20px;
}

.empty {
  padding: 60px 0;
}

.placeholder {
  padding: 60px 0;
  text-align: center;
}

.error-box {
  margin-bottom: 16px;
}
</style>
