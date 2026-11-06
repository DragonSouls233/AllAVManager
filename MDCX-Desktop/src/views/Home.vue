<template>
  <div class="dash">
    <!-- 1 · 欢迎 + 状态 + 3 按钮 -->
    <HeroBanner class="col-12" />

    <!-- 2 · 继续观看（空则整块消失，不占位） -->
    <ContinueWatching class="col-12" />

    <!-- 3 · 4 张 KPI -->
    <KpiRow class="col-12" />

    <!-- 4 · 7 个模块 pill -->
    <ModulePills class="col-12" />

    <!-- 5 · 6 个快捷操作 -->
    <QuickActions class="col-12" />

    <!-- 6 / 7 / 8 · 同排 5 : 4 : 3 -->
    <RecentActivity class="col-5" />
    <RecommendStrip class="col-4" />
    <SystemStatusCard class="col-3" @open-changelog="onOpenChangelog" />
  </div>
</template>

<script setup>
/**
 * Home —— 首页工作台（Phase 1 重写）
 *
 * 从「模块广告牌」变成「工作台」，编排 8 个区块（ARCH-phase1 §9.1）：
 *   Hero / 继续观看 / KPI / 模块 pill / 快捷操作 / 最近活动 / 推荐 / 系统
 *
 * 已删除（§9.4）：
 * - `.module-grid` 3×3 大卡 + 每卡 5 个 `el-button text`（共 30+ 按钮）
 * - `hero-card` 深蓝渐变条
 * - `v-loading` 白遮罩（改骨架屏）
 * - `hover: translateY(-3px)` + 阴影浮起
 *
 * 本文件**不发任何全库聚合请求**：KPI / pill / 状态全部读 shellStats（0 请求）。
 */
import HeroBanner from '@/components/dashboard/HeroBanner.vue'
import ContinueWatching from '@/components/dashboard/ContinueWatching.vue'
import KpiRow from '@/components/dashboard/KpiRow.vue'
import ModulePills from '@/components/dashboard/ModulePills.vue'
import QuickActions from '@/components/dashboard/QuickActions.vue'
import RecentActivity from '@/components/dashboard/RecentActivity.vue'
import RecommendStrip from '@/components/dashboard/RecommendStrip.vue'
import SystemStatusCard from '@/components/dashboard/SystemStatusCard.vue'

/**
 * 「更新日志」对话框挂在 AdminLayout（它是全局副作用宿主）。
 * 首页只负责把意图通过 window 事件传上去，避免为了一个按钮做 provide/inject。
 */
function onOpenChangelog() {
  window.dispatchEvent(new CustomEvent('mdcx-open-changelog'))
}
</script>

<style scoped>
.dash {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 16px;
  width: 100%;
  max-width: var(--content-max, 1440px);
  margin-inline: auto;
}

.col-12 { grid-column: span 12; min-width: 0; }
.col-5 { grid-column: span 5; min-width: 0; }
.col-4 { grid-column: span 4; min-width: 0; }
.col-3 { grid-column: span 3; min-width: 0; }

/* A7：三个宽度无横向滚动 */
@media (max-width: 1180px) {
  .col-5 { grid-column: span 12; }
  .col-4 { grid-column: span 6; }
  .col-3 { grid-column: span 6; }
}

@media (max-width: 760px) {
  .col-4,
  .col-3 {
    grid-column: span 12;
  }
}
</style>
