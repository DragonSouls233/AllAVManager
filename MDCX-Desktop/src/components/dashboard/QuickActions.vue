<template>
  <section class="qa" aria-label="快捷操作">
    <router-link v-for="act in ACTIONS" :key="act.key" :to="act.to" class="qa-item">
      <span class="qa-icon" aria-hidden="true">
        <el-icon :size="16"><component :is="act.icon" /></el-icon>
      </span>
      <span class="qa-text">
        <span class="qa-label">{{ act.label }}</span>
        <span class="qa-desc">{{ act.desc }}</span>
      </span>
    </router-link>
  </section>
</template>

<script setup>
/**
 * QuickActions —— 首页区块 5 · 6 个快捷操作
 *
 * 纯静态（无请求）。取代旧首页每张模块卡上的 5 个 `el-button text`（30+ 按钮）。
 * 全部指向工具中心的具体工具，URL 即状态（`?tool=`），可直接分享/书签。
 */
const ACTIONS = [
  { key: 'import',   label: '批量导入',   desc: '扫描目录并入库',   icon: 'Upload',       to: '/import' },
  { key: 'scrape',   label: '刮削管理',   desc: '按模块批量刮削',   icon: 'Connection',   to: '/tools/scrape?tool=crawlers&module=jav' },
  { key: 'patch',    label: '补丁刮削',   desc: '只补缺失字段',     icon: 'MagicStick',   to: '/tools/fix?tool=patch&module=jav' },
  { key: 'dupes',    label: '重复番号',   desc: '找出重复入库',     icon: 'CopyDocument', to: '/tools/health?tool=duplicates' },
  { key: 'unrecog',  label: '未识别文件', desc: '处理命名失败项',   icon: 'FolderOpened', to: '/tools/organize?tool=unrecognized-files' },
  { key: 'ltxgap',   label: 'LTX 补全',   desc: '对比线上库找缺失', icon: 'Star',         to: '/jav/ltx-gap' },
  { key: 'tasks',    label: '任务管理',   desc: '查看运行中任务',   icon: 'List',         to: '/tools/system?tool=tasks' },
]
</script>

<style scoped>
.qa {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
}

.qa-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: var(--radius-card, 10px);
  background: var(--bg-card);
  box-shadow: var(--shadow-kpi);
  text-decoration: none;
  min-width: 0;
  transition:
    border-color var(--dur-fast, 120ms),
    box-shadow var(--dur-fast, 120ms),
    transform var(--dur-fast, 120ms);
}

.qa-item:hover {
  border-color: var(--card-border-hover);
  box-shadow: var(--shadow-card);
  transform: translateY(-1px);
}

.qa-item:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.qa-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: var(--radius-ctl, 8px);
  background: var(--hover-layer);
  color: var(--text-regular);
}

.qa-item:hover .qa-icon {
  color: var(--accent);
}

.qa-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.qa-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qa-desc {
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1280px) {
  .qa {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .qa {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
