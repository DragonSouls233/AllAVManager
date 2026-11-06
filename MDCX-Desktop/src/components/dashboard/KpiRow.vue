<template>
  <section class="kpi-wrap" aria-label="关键指标">
    <div class="section-head">
      <h2 class="section-title">数据概览</h2>
      <router-link class="section-link" to="/stats">查看统计 →</router-link>
    </div>

    <div class="kpi">
      <article
        v-for="card in cards"
        :key="card.key"
        class="kpi-card"
        :class="`tone-${card.tone}`"
      >
        <div class="kpi-top">
          <span class="kpi-icon" aria-hidden="true">
            <el-icon :size="18"><component :is="card.icon" /></el-icon>
          </span>
          <span class="kpi-label">{{ card.label }}</span>
        </div>
        <div class="kpi-value" :class="{ 'is-muted': card.value === null }">
          {{ card.value === null ? '—' : card.value }}
        </div>
        <div class="kpi-sub" :class="card.subTone ? `is-${card.subTone}` : ''">
          {{ card.sub }}
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
/**
 * KpiRow —— 首页区块 3 · 4 张 KPI 卡（Commercial v6）
 *
 * 数据契约不变（ARCH-phase1 §9.2，F3/F5 修正后）：
 * - 影片 / 演员 / 待刮削：全部来自 `shellStats.dashboard`（0 请求）
 * - 标签数：`getTags({page:1,page_size:1}).total`（1 次轻请求，dashboard 无此字段）
 * - 放弃「系列数」；第四卡副行显示失败数（>0 用 danger 色）
 *
 * v6 视觉：图标渐变胶囊 + 30px 大数字 + 区块标题「数据概览」，更像商业分析面板。
 */
import { computed, onMounted, ref } from 'vue'
import { VideoCamera, User, PriceTag, Refresh } from '@element-plus/icons-vue'
import { getTags } from '@/api'
import { useShellStatsStore } from '@/stores/shellStats'

const shell = useShellStatsStore()
const tagTotal = ref(null)
const tagFailed = ref(false)

function fmt(n) {
  const v = Number(n)
  if (!Number.isFinite(v)) return null
  if (v >= 10000) return `${(v / 10000).toFixed(1)}w`
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`
  return String(v)
}

const cards = computed(() => {
  const movies = shell.dashboard ? fmt(shell.moviesTotal) : null
  const actors = shell.dashboard ? fmt(shell.actorsTotal) : null
  const pending = shell.dashboard ? fmt(shell.pendingTotal) : null
  const failed = shell.failedTotal

  return [
    {
      key: 'movies',
      label: '影片',
      icon: VideoCamera,
      tone: 'indigo',
      value: movies,
      sub: shell.dashboard ? `已完成 ${fmt(shell.completedTotal) ?? 0}` : '加载失败',
      subTone: shell.dashboard ? '' : 'muted',
    },
    {
      key: 'actors',
      label: '演员',
      icon: User,
      tone: 'cyan',
      value: actors,
      sub: shell.dashboard ? '全库去重后人数' : '加载失败',
      subTone: '',
    },
    {
      key: 'tags',
      label: '标签',
      icon: PriceTag,
      tone: 'violet',
      value: tagFailed.value ? null : fmt(tagTotal.value),
      sub: tagFailed.value ? '加载失败' : '可用于筛选与推荐',
      subTone: tagFailed.value ? 'muted' : '',
    },
    {
      key: 'pending',
      label: '待刮削',
      icon: Refresh,
      tone: 'amber',
      value: pending,
      sub: failed > 0 ? `失败 ${failed}` : '暂无失败任务',
      subTone: failed > 0 ? 'danger' : 'muted',
    },
  ]
})

onMounted(async () => {
  try {
    const res = await getTags({ page: 1, page_size: 1 })
    tagTotal.value = typeof res?.total === 'number' ? res.total : 0
  } catch (e) {
    tagFailed.value = true
  }
})
</script>

<style scoped>
.kpi-wrap {
  display: flex;
  flex-direction: column;
}

.kpi {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.kpi-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 16px 18px 18px;
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: var(--radius-card, 10px);
  background: var(--bg-card);
  box-shadow: var(--shadow-kpi);
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    transform 0.15s ease;
}

.kpi-card:hover {
  border-color: var(--card-border-hover);
  box-shadow: var(--shadow-card);
  transform: translateY(-1px);
}

.kpi-top {
  display: flex;
  align-items: center;
  gap: 9px;
}

.kpi-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 9px;
  color: #fff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.tone-indigo .kpi-icon { background: linear-gradient(135deg, #6b7cf0, var(--accent)); }
.tone-cyan .kpi-icon   { background: linear-gradient(135deg, #38bdf8, #0ea5e9); }
.tone-violet .kpi-icon { background: linear-gradient(135deg, #a78bfa, #8b5cf6); }
.tone-amber .kpi-icon  { background: linear-gradient(135deg, #fbbf24, #f59e0b); }

.kpi-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.kpi-value {
  font-size: 30px;
  font-weight: 650;
  line-height: 1.1;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.kpi-value.is-muted {
  color: var(--text-placeholder);
}

.kpi-sub {
  font-size: 12px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kpi-sub.is-danger {
  color: var(--danger-color);
}

.kpi-sub.is-muted {
  color: var(--text-placeholder);
}

@media (max-width: 900px) {
  .kpi {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
