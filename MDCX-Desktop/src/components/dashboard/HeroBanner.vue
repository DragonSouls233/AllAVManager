<template>
  <section class="hero" aria-label="欢迎与概览">
    <div class="hero-glow" aria-hidden="true" />

    <div class="hero-text">
      <div class="hero-eyebrow">
        <span class="status-dot" :class="`is-${shell.health}`" aria-hidden="true" />
        <span>{{ shell.healthText }}</span>
      </div>
      <h1 class="hero-title">
        欢迎回来，<span class="hero-name">{{ username }}</span>
      </h1>
      <p class="hero-sub">
        全库 <b>{{ moviesLabel }}</b> 部影片 · <b>{{ actorsLabel }}</b> 位演员
        <span class="hero-sep">—</span> 一切尽在掌握
      </p>
    </div>

    <div class="hero-actions">
      <el-button type="primary" @click="go('/jav/movies')">浏览影片库</el-button>
      <el-button @click="go('/import')">批量导入</el-button>
      <el-button text @click="go('/tools')">工具中心 →</el-button>
    </div>
  </section>
</template>

<script setup>
/**
 * HeroBanner —— 首页区块 1（Commercial v6）
 *
 * v6 变化：从"纯文字条"升级为有品牌锚点的商业头 ——
 * 柔和 accent 渐变底 + 右上光晕 + 26px 大标题 + 状态胶囊 eyebrow。
 * 数据仍全部读 shellStats（0 请求）。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useShellStatsStore } from '@/stores/shellStats'

const router = useRouter()
const authStore = useAuthStore()
const shell = useShellStatsStore()

const username = computed(() => authStore.username)

function fmt(n) {
  const v = Number(n) || 0
  if (v >= 10000) return `${(v / 10000).toFixed(1)}w`
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`
  return String(v)
}

const moviesLabel = computed(() => fmt(shell.moviesTotal))
const actorsLabel = computed(() => fmt(shell.actorsTotal))

function go(path) {
  router.push(path).catch(() => {})
}
</script>

<style scoped>
.hero {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
  padding: 22px 26px;
  border: 1px solid var(--hairline, var(--border-color));
  border-radius: var(--radius-lg, 16px);
  background: linear-gradient(
    120deg,
    color-mix(in srgb, var(--accent) 7%, var(--bg-card)) 0%,
    var(--bg-card) 44%
  );
  box-shadow: var(--shadow-card);
}

.hero-glow {
  position: absolute;
  right: -90px;
  top: -130px;
  width: 340px;
  height: 340px;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    color-mix(in srgb, var(--accent) 24%, transparent),
    transparent 70%
  );
  filter: blur(8px);
  opacity: 0.9;
  pointer-events: none;
}

.hero-text {
  position: relative;
  z-index: 1;
  min-width: 0;
}

.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 10px;
  margin-bottom: 12px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  font-size: 12px;
  font-weight: 500;
  color: var(--accent);
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: currentColor;
}

.status-dot.is-ok { color: var(--success-color); }
.status-dot.is-warn { color: var(--warning-color); }
.status-dot.is-error { color: var(--danger-color); }
.status-dot.is-unknown { color: var(--text-placeholder); }

.hero-title {
  margin: 0 0 6px;
  font-size: var(--text-h1, 26px);
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.2;
  color: var(--text-primary);
}

.hero-name {
  color: var(--accent);
}

.hero-sub {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.hero-sub b {
  color: var(--text-primary);
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.hero-sep {
  margin: 0 4px;
  color: var(--text-placeholder);
}

.hero-actions {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
</style>
