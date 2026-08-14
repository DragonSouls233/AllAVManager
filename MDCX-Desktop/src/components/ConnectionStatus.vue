<template>
  <div
    class="conn-status"
    :class="status"
    :title="tooltip"
    @click="manualCheck"
  >
    <span class="conn-dot" :class="{ pulse: status === 'reconnect' }"></span>
    <span class="conn-text">{{ label }}</span>
    <span v-if="status !== 'reconnect' && latency > 0" class="conn-latency">{{ latency }}ms</span>
    <span v-if="status === 'reconnect' && retryCount > 0" class="conn-retry">({{ retryCount }}/{{ maxRetry }})</span>
  </div>
</template>

<script setup>
/**
 * ConnectionStatus —— 后端连接状态胶囊（Cinema v1 设计 §3.2）
 *
 * 三态：
 *   online   绿  后端已连接，延迟正常
 *   weak     黄  弱网（延迟超阈值），提示用户可能降码率
 *   reconnect 红(脉冲) 连接中断，自动退避重连中
 *
 * 数据来源：复用现有 checkServerConnection()（GET /api/v1/health）。
 * 弱网判定：探活往返耗时 > weakThresholdMs。
 * 重连：探活失败时转 reconnect，指数退避重试（最多 maxRetry 次后改为每 10s 轮询）。
 * 外部事件：Play.vue 在播放加载失败时 dispatch window 事件 'mdcx:network-error'，
 *          本组件监听后立刻进入 reconnect 并触发一次探活。
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { checkServerConnection } from '@/api'

const props = defineProps({
  // 当前播放模式文案，例如 "直连" / "HLS·自适应" / "网盘"
  mode: { type: String, default: '' },
  // 探活间隔(ms)
  interval: { type: Number, default: 15000 },
  // 弱网延迟阈值(ms)
  weakThresholdMs: { type: Number, default: 300 },
})

const status = ref('online') // online | weak | reconnect
const latency = ref(0)
const version = ref('')
const retryCount = ref(0)
const maxRetry = 5
let timer = null
let retryTimer = null
let checking = false

const label = computed(() => {
  if (status.value === 'online') return `后端已连接${props.mode ? ' · ' + props.mode : ''}`
  if (status.value === 'weak') return '弱网 · 已自动降码率'
  return '连接中断 · 自动重连中'
})

const tooltip = computed(() => {
  if (status.value === 'online') {
    return `后端已连接${version.value ? ' (v' + version.value + ')' : ''} · 延迟 ${latency.value}ms · 点击手动探活`
  }
  if (status.value === 'weak') {
    return `网络延迟 ${latency.value}ms 超过阈值 ${props.weakThresholdMs}ms，建议切换到低码率 · 点击手动探活`
  }
  return `与后端连接失败${retryCount.value ? '，已重试 ' + retryCount.value + ' 次' : ''} · 点击立即重连`
})

const backoff = (n) => Math.min(1000 * 2 ** n, 10000)

const doCheck = async () => {
  if (checking) return
  checking = true
  const t0 = performance.now()
  try {
    const res = await checkServerConnection()
    const cost = Math.round(performance.now() - t0)
    if (res && res.ok) {
      latency.value = cost
      version.value = res.version || ''
      retryCount.value = 0
      status.value = cost > props.weakThresholdMs ? 'weak' : 'online'
    } else {
      enterReconnect()
    }
  } catch (e) {
    enterReconnect()
  } finally {
    checking = false
  }
}

const enterReconnect = () => {
  if (status.value !== 'reconnect') status.value = 'reconnect'
  retryCount.value += 1
  if (retryTimer) clearTimeout(retryTimer)
  const delay = retryCount.value <= maxRetry ? backoff(retryCount.value) : 10000
  retryTimer = setTimeout(doCheck, delay)
}

const manualCheck = () => {
  if (retryTimer) clearTimeout(retryTimer)
  retryCount.value = 0
  status.value = 'online'
  doCheck()
}

const onNetworkError = () => {
  enterReconnect()
}

onMounted(() => {
  doCheck()
  timer = setInterval(doCheck, props.interval)
  window.addEventListener('mdcx:network-error', onNetworkError)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (retryTimer) clearTimeout(retryTimer)
  window.removeEventListener('mdcx:network-error', onNetworkError)
})
</script>

<style scoped>
.conn-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  user-select: none;
  border: 1px solid transparent;
  transition: background 0.2s, color 0.2s, border-color 0.2s;
  white-space: nowrap;
}
.conn-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: 0 0 auto;
}
.conn-latency {
  opacity: 0.8;
  font-variant-numeric: tabular-nums;
}
.conn-retry {
  opacity: 0.85;
}

.conn-status.online {
  background: rgba(46, 204, 113, 0.12);
  color: #2ecc71;
  border-color: rgba(46, 204, 113, 0.35);
}
.conn-status.online .conn-dot {
  background: #2ecc71;
  box-shadow: 0 0 0 3px rgba(46, 204, 113, 0.18);
}

.conn-status.weak {
  background: rgba(245, 166, 35, 0.12);
  color: #f5a623;
  border-color: rgba(245, 166, 35, 0.35);
}
.conn-status.weak .conn-dot {
  background: #f5a623;
  box-shadow: 0 0 0 3px rgba(245, 166, 35, 0.18);
}

.conn-status.reconnect {
  background: rgba(239, 77, 86, 0.12);
  color: #ef4d56;
  border-color: rgba(239, 77, 86, 0.35);
}
.conn-status.reconnect .conn-dot {
  background: #ef4d56;
}
.conn-status.reconnect .conn-dot.pulse {
  animation: conn-pulse 1.1s ease-out infinite;
}

@keyframes conn-pulse {
  0% { box-shadow: 0 0 0 0 rgba(239, 77, 86, 0.5); }
  70% { box-shadow: 0 0 0 6px rgba(239, 77, 86, 0); }
  100% { box-shadow: 0 0 0 0 rgba(239, 77, 86, 0); }
}
</style>
