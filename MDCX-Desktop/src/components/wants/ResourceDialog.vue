<template>
  <el-dialog
    :model-value="modelValue"
    title="磁力资源"
    :width="760"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
    @open="onOpen"
  >
    <div v-loading="searching" class="res-dialog">
      <div class="res-head">
        <div class="res-code">
          <span class="label">番号</span>
          <span class="code">{{ code }}</span>
        </div>
        <div class="res-actions">
          <span v-if="result.cached" class="cache-tip">缓存结果</span>
          <el-button size="small" :icon="Refresh" :loading="searching" @click="onSearch(true)">
            刷新
          </el-button>
        </div>
      </div>

      <el-alert
        v-if="result.state === 'empty' || result.state === 'error' || result.state === 'cooldown'"
        :type="result.state === 'cooldown' ? 'warning' : 'info'"
        show-icon :closable="false"
        :title="result.message || '没有搜到资源'"
        class="res-alert"
      />

      <template v-if="result.state === 'ready' && result.items.length">
        <div class="res-summary">
          共 {{ result.items.length }} 条资源，其中中字版 {{ result.chinese_count }} 条
          <span v-if="result.total_time_ms" class="muted">（{{ result.total_time_ms }}ms）</span>
        </div>
        <el-table :data="result.items" size="small" stripe max-height="380">
          <el-table-column label="中字" width="56">
            <template #default="{ row }">
              <el-tag v-if="row.is_chinese" type="warning" size="small" effect="dark">中字</el-tag>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="名称" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="rname">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="90">
            <template #default="{ row }">
              <span class="mono">{{ row.size_text || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="做种" width="60">
            <template #default="{ row }">
              <span :class="row.seeders > 0 ? 'seeders on' : 'seeders'">{{ row.seeders }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button
                text type="primary" size="small"
                :loading="sendingMagnet === row.magnet"
                @click="onSend(row)"
              >发送下载</el-button>
              <el-button text size="small" @click="onCopy(row)">复制</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="res-foot">
          发送下载会交给当前激活的下载器（aria2/qb/tr），下载进度在「下载管理」查看。
          中字版优先排在前面——「可替换旧版」的场景直接发第一条即可。
        </div>
      </template>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { searchWantResources, sendWantResource, updateWant } from '@/api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  code: { type: String, default: '' },
  wantId: { type: [Number, String], default: null },
})

const emit = defineEmits(['update:modelValue', 'sent'])

const searching = ref(false)
const sendingMagnet = ref('')
const result = reactive({ state: '', items: [], message: '', cached: false, chinese_count: 0 })

async function onSearch(force = false) {
  if (!props.code) return
  searching.value = true
  try {
    const data = await searchWantResources(props.code, force)
    Object.assign(result, data)
  } catch (e) {
    Object.assign(result, {
      state: 'error', items: [],
      message: e?.response?.data?.detail || '搜索失败，请稍后重试',
    })
  } finally {
    searching.value = false
  }
}

function onOpen() {
  Object.assign(result, { state: '', items: [], message: '', cached: false, chinese_count: 0 })
  onSearch(false)
}

async function onSend(row) {
  sendingMagnet.value = row.magnet
  try {
    await sendWantResource({ magnet: row.magnet, name: row.name })
    // 顺手把磁链存回 want 条目，下次不用再搜
    if (props.wantId) {
      try { await updateWant(props.wantId, { magnet: row.magnet }) } catch { /* 存不回不阻塞下载 */ }
    }
    ElMessage.success(`已发送到下载器：${row.name.slice(0, 40)}`)
    emit('sent', row)
    emit('update:modelValue', false)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '发送下载失败')
  } finally {
    sendingMagnet.value = ''
  }
}

async function onCopy(row) {
  try {
    await navigator.clipboard.writeText(row.magnet)
    ElMessage.success('磁力链接已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}
</script>

<style scoped>
.res-head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 12px;
}
.res-code .label { color: #909399; font-size: 12px; margin-right: 8px; }
.res-code .code { font-family: var(--font-mono, monospace); font-weight: 600; font-size: 14px; }
.res-actions { display: flex; align-items: center; gap: 10px; }
.cache-tip { color: #909399; font-size: 12px; }
.res-alert { margin-bottom: 12px; }
.res-summary { font-size: 13px; margin-bottom: 8px; color: var(--el-text-color-regular); }
.muted { color: #909399; font-size: 12px; }
.rname { font-size: 12px; }
.mono { font-family: var(--font-mono, monospace); font-size: 12px; }
.seeders { font-family: var(--font-mono, monospace); font-size: 12px; color: #909399; }
.seeders.on { color: #67c23a; font-weight: 600; }
.res-foot {
  margin-top: 10px; font-size: 12px; color: #909399; line-height: 1.6;
}
</style>
