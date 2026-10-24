/* 待处理数量的轮询。
 *
 * 为什么需要它：批量刮削/扫描这类接口是「立刻返回 started，任务在后台跑」的语义，
 * 服务端的 pending_count 会持续下降，但前端拿到的只是一个瞬间快照。
 * 此前 PORNHUB 影片库只在进入页面时取一次 `pending_count`，任务跑了一整天，
 * 角标仍然停在旧数字上——用户看到「刮了这么多怎么还剩 9000」，其实服务端早已不是那个数。
 *
 * 这里给页面一个显式的轮询开关：任务启动后打开，归零或手动关闭时停。
 * 不做成全局后台轮询，是因为不同页面的代价不一样（PORNHUB 列表带封面字段，比 JAV 重）。 */
import { onUnmounted, ref } from 'vue'

/**
 * @param {() => Promise<number|null>} tick   一次轮询要执行的取数；返回当前待处理数量，返回 null 表示「这次没拿到，继续轮」
 * @param {object}  [options]
 * @param {number}  [options.intervalMs=15000] 轮询间隔
 * @param {number}  [options.maxDurationMs]    最长轮询多久后自动放弃，不传则一直轮到归零或 stop()
 * @param {() => boolean} [options.stopWhen]  额外停止条件（例如用户切走了筛选）
 */
export function usePendingPoll(tick, options = {}) {
  const { intervalMs = 15000, maxDurationMs, stopWhen } = options

  const polling = ref(false)
  let timer = null
  let startedAt = 0

  function clear() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function stop() {
    clear()
    polling.value = false
  }

  async function runOnce() {
    try {
      const n = await tick()
      // 归零（含「已经拿到 0」）就收工，别让一个空任务把定时器挂一整天
      if (n === 0 || stopWhen?.()) stop()
      else if (maxDurationMs && Date.now() - startedAt > maxDurationMs) stop()
    } catch {
      // 单次失败不打断轮询：局域网抖动、后端正在重启都该由下一轮接上。
      // 错误提示由 axios 拦截器统一负责，这里不再重复弹。
      if (maxDurationMs && Date.now() - startedAt > maxDurationMs) stop()
    }
  }

  /** 开始轮询。重复调用是幂等的，不会叠出两个定时器。 */
  function start() {
    if (polling.value) return
    polling.value = true
    startedAt = Date.now()
    clear()
    timer = setInterval(runOnce, intervalMs)
    // 立刻先跑一轮，否则要等一个间隔才看到变化
    runOnce()
  }

  onUnmounted(stop)

  return { polling, start, stop }
}
