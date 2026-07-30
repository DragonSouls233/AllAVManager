<template>
  <div class="site-list-inner">
    <div v-for="(item, idx) in items" :key="item.name"
      class="site-row" :class="{ 'row-disabled': !item.enabled }">
      <div class="row-priority">
        <el-tag :type="idx === 0 ? 'danger' : idx < 3 ? 'warning' : 'info'" effect="dark" size="small">
          #{{ idx + 1 }}
        </el-tag>
      </div>
      <div class="row-info">
        <div class="row-name">
          <span class="name-text">{{ item.display_name }}</span>
          <el-tag size="small" type="info">{{ item.name }}</el-tag>
          <el-tag v-if="!item.enabled" size="small" type="danger">已禁用</el-tag>
        </div>
        <div class="row-url">
          <el-link :href="item.base_url" target="_blank" type="primary" :underline="false">
            {{ item.base_url || '-' }}
          </el-link>
        </div>
        <div class="row-meta">
          <span class="meta-item">刮削 {{ item.scraped_count }} ({{ item.scraped_percent }}%)</span>
          <span class="meta-item">覆盖能力 {{ item.field_coverage_score }}/100</span>
          <span class="meta-item" v-if="item.supported_types?.length">{{ item.supported_types.join(' · ') }}</span>
        </div>
      </div>
      <div class="row-ping">
        <template v-if="pingResults[item.name]">
          <div class="ping-row">
            <span class="ping-label">直连</span>
            <el-tag :type="pingTagType(pingResults[item.name].direct)" size="small">
              {{ pingText(pingResults[item.name].direct) }}
            </el-tag>
          </div>
          <div class="ping-row" v-if="pingResults[item.name].proxy">
            <span class="ping-label">代理</span>
            <el-tag :type="pingTagType(pingResults[item.name].proxy)" size="small">
              {{ pingText(pingResults[item.name].proxy) }}
            </el-tag>
          </div>
        </template>
        <span v-else class="ping-empty">未测速</span>
      </div>
      <div class="row-actions">
        <el-switch :model-value="item.enabled"
          @change="(v) => $emit('toggle', item.name, v)" size="small" />
        <el-button size="small" link type="primary"
          @click="$emit('pingSingle', item.name)"
          :loading="singlePinging === item.name">
          <el-icon><Connection /></el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ items: Array, pingResults: Object, singlePinging: String })
defineEmits(['toggle', 'pingSingle'])

function pingTagType(r) {
  if (!r) return 'info'
  if (r.success === false) return 'danger'
  if (r.time_ms && r.time_ms > 3000) return 'warning'
  return 'success'
}
function pingText(r) {
  if (!r) return '-'
  if (r.success === false) return `失败 ${r.time_ms || 0}ms`
  return `${r.status_code || 'OK'} · ${r.time_ms}ms`
}
</script>

<style scoped>
.site-list-inner { margin:-8px; }
.site-row { display:grid; grid-template-columns:80px 1fr 200px 100px; gap:12px; align-items:center; padding:10px 12px; border-bottom:1px solid #f0f2f5; background:#fff; transition:background .15s; }
.site-row:last-child { border-bottom:none; }
.site-row:hover { background:#f5f7fa; }
.site-row.row-disabled { opacity:.55; background:#fafafa; }
.row-priority { text-align:center; }
.row-info { min-width:0; }
.row-name { display:flex; align-items:center; gap:6px; margin-bottom:4px; }
.name-text { font-weight:600; font-size:14px; color:#303133; }
.row-url { font-size:12px; margin-bottom:4px; }
.row-meta { display:flex; flex-wrap:wrap; gap:12px; font-size:11px; color:#909399; }
.row-ping { font-size:12px; }
.ping-row { display:flex; justify-content:space-between; align-items:center; gap:6px; margin-bottom:4px; }
.ping-label { color:#909399; font-size:11px; }
.ping-empty { color:#c0c4cc; font-size:11px; }
.row-actions { display:flex; align-items:center; gap:8px; justify-content:flex-end; }
</style>
