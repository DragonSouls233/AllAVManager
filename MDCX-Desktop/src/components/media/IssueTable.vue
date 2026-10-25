<template>
  <div class="issue-table">
    <div v-if="!rows.length" class="empty">
      <el-empty description="这一类没有异常" :image-size="60" />
    </div>
    <template v-else>
      <div v-if="rows.length >= 200" class="cap-tip">
        <el-alert type="info" show-icon :closable="false" :title="`明细每类最多显示 200 条（已截断），汇总计数是全量的`" />
      </div>
      <el-table :data="rows" size="small" stripe max-height="520">
        <el-table-column prop="module" label="模块" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ moduleLabel(row.module) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="番号" width="140">
          <template #default="{ row }">
            <span class="code">{{ row.code || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
        <el-table-column label="文件路径" min-width="260">
          <template #default="{ row }">
            <span class="path" :title="row.file_path">{{ row.file_path }}</span>
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="200">
          <template #default="{ row }">
            <span class="detail">{{ row.detail }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" fixed="right">
          <template #default>
            <el-tag size="small" :type="tagType" effect="dark">{{ statusLabel }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="kind === 'probe'" label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="warning" plain @click="emit('repair', row)">修复</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  kind: { type: String, default: 'drive' }, // drive / file / probe
})
const emit = defineEmits(['repair'])

const moduleLabels = {
  jav: 'JAV', uncensored: '无码', chinese: '国产',
  western: '欧美', fc2: 'FC2', pornhub: 'PH',
}
function moduleLabel(m) { return moduleLabels[m] || m }

const statusLabel = computed(() => {
  if (props.kind === 'drive') return '盘符失效'
  if (props.kind === 'file') return '文件丢失'
  return '探测失败'
})
const tagType = computed(() => (props.kind === 'drive' ? 'warning' : 'danger'))
</script>

<style scoped>
.issue-table { margin-top: 4px; }
.cap-tip { margin-bottom: 10px; }
.empty { padding: 20px 0; }
.code { font-family: var(--font-mono, monospace); font-size: 12px; }
.path { font-size: 12px; color: #606266; word-break: break-all; }
.detail { font-size: 12px; color: #909399; }
</style>
