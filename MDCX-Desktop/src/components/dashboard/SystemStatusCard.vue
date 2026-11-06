<template>
  <section class="sys" aria-label="系统状态">
    <h2 class="sys-title">系统</h2>

    <dl class="sys-list">
      <!-- 服务状态（健康等级由 shellStats 派生，`/stats/health` 本身无 status 字段） -->
      <div class="sys-row">
        <dt>服务状态</dt>
        <dd>
          <span class="sys-dot" :class="`is-${shell.health}`" aria-hidden="true" />
          <span :class="`sys-tone-${shell.health}`">{{ shell.healthText }}</span>
        </dd>
      </div>

      <!-- 元数据完整度（/stats/storage 是完整度，不是磁盘容量） -->
      <div class="sys-row">
        <dt>元数据完整度</dt>
        <dd>
          <template v-if="coverage === null">
            <span class="sys-muted">—</span>
            <router-link class="sys-link" to="/tools/scrape">去补全</router-link>
          </template>
          <template v-else>
            <span class="sys-num">{{ coverage }}%</span>
            <span class="sys-muted">封面/剧情</span>
          </template>
        </dd>
      </div>

      <!-- 版本 -->
      <div class="sys-row">
        <dt>版本</dt>
        <dd>
          <span class="sys-num">v{{ shell.version || '—' }}</span>
          <button type="button" class="sys-link" @click="$emit('open-changelog')">更新日志</button>
        </dd>
      </div>
    </dl>

    <div v-if="failedTasks > 0" class="sys-warn">
      近 7 日失败任务 {{ failedTasks }} 个
      <router-link class="sys-link" to="/tools/system?tool=tasks">查看</router-link>
    </div>
  </section>
</template>

<script setup>
/**
 * SystemStatusCard —— 首页区块 7 · 服务 / 完整度 / 版本
 *
 * 修正 F4（ARCH-phase1 §0 / 坑 16）：
 * - `GET /stats/storage` 返回的是**元数据完整度**（images.with_cover / with_poster、
 *   metadata.with_plot / with_actors），不是磁盘容量；
 * - `GET /stats/health` **没有 status 字段** —— 旧 Home.vue:191 读 `s.status` 恒为
 *   undefined，这正是"服务器正常"徽章永远显示"未连接"的根因。健康等级改由 shellStats 派生。
 *
 * 请求纪律（QA P2 修正）：
 * - 本组件**只发 1 次请求** —— `getStorageStats()`（完整度，dashboard/health 都无此字段）；
 * - 服务状态、失败任务数、版本全部读 shellStats（`/stats/health` 已由外壳 30s 轮询，
 *   原始 payload 存在 `healthRaw`，`recentFailedTasks` 即由其派生）。
 */
import { computed, onMounted, ref } from 'vue'
import { getStorageStats } from '@/api'
import { useShellStatsStore } from '@/stores/shellStats'

defineEmits(['open-changelog'])

const shell = useShellStatsStore()
const coverage = ref(null)

/** 失败任务数：读 store 派生值，不再自己打 /stats/health */
const failedTasks = computed(() => shell.recentFailedTasks)

const percent = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

onMounted(async () => {
  try {
    const s = await getStorageStats()
    // 优先用「有封面比例」，没有就退化成「有剧情比例」，两者都没有 → null
    const withCover = percent(s?.images?.with_cover)
    const withPlot = percent(s?.metadata?.with_plot)
    const pick = withCover ?? withPlot
    if (pick !== null) {
      // 后端可能返回 0..1 也可能返回 0..100
      const asPct = pick <= 1 ? pick * 100 : pick
      coverage.value = Math.round(asPct)
    }
  } catch (e) {
    coverage.value = null
  }
})
</script>

<style scoped>
.sys {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 16px;
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: var(--radius-card, 10px);
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
  min-width: 0;
}

.sys-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.sys-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
}

.sys-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 28px;
  font-size: 13px;
}

.sys-row dt {
  color: var(--text-secondary);
  flex-shrink: 0;
}

.sys-row dd {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 0;
  min-width: 0;
  color: var(--text-regular);
}

.sys-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-placeholder);
}

.sys-dot.is-ok { background: var(--success-color); }
.sys-dot.is-warn { background: var(--warning-color); }
.sys-dot.is-error { background: var(--danger-color); }
.sys-dot.is-unknown { background: var(--text-placeholder); }

.sys-tone-ok { color: var(--success-color); }
.sys-tone-warn { color: var(--warning-color); }
.sys-tone-error { color: var(--danger-color); }
.sys-tone-unknown { color: var(--text-placeholder); }

.sys-num {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--text-primary);
}

.sys-muted {
  font-size: 12px;
  color: var(--text-placeholder);
}

.sys-link {
  border: 0;
  padding: 0;
  background: transparent;
  font-family: inherit;
  font-size: 12px;
  color: var(--accent);
  text-decoration: none;
  cursor: pointer;
  white-space: nowrap;
}

.sys-link:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-radius: 4px;
}

.sys-warn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--border-light);
  font-size: 12px;
  color: var(--danger-color);
}
</style>
