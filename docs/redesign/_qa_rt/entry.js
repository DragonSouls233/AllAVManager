import { createPinia, setActivePinia } from 'pinia'
import { __calls, __setHealth } from './api-stub.js'
import { useShellStatsStore } from '@/stores/shellStats'

const results = []
function check(name, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  results.push({ ok, name, actual, expected })
}

setActivePinia(createPinia())
const store = useShellStatsStore()

// 用例 A：初始态（未 refresh）→ 失败数应为 0，不闪警告
check('A 初始 recentFailedTasks', store.recentFailedTasks, 0)
check('A 初始 healthRaw', store.healthRaw, null)

// 用例 B：health 返回 recent_failed=3 → 3
__setHealth(async () => ({ tasks: { recent_failed: 3, error_rate: 0.1 }, database: { healthy: true } }))
await store.refresh()
check('B recentFailedTasks=3', store.recentFailedTasks, 3)
check('B health=ok', store.health, 'ok')
check('B healthRaw 已留存', store.healthRaw?.tasks?.recent_failed, 3)

// 用例 C：health 返回但缺 recent_failed → 0
__setHealth(async () => ({ tasks: { error_rate: 0.0 }, database: { healthy: true } }))
await store.refresh()
check('C 缺字段→0', store.recentFailedTasks, 0)

// 用例 D：health 返回 null → 0（不炸）
__setHealth(async () => null)
await store.refresh()
check('D 返回 null→0', store.recentFailedTasks, 0)

// 用例 E：health 请求失败 → 0 且不保留旧值（无脏读）
__setHealth(async () => ({ tasks: { recent_failed: 7 } }))
await store.refresh()
check('E 先置 7', store.recentFailedTasks, 7)
__setHealth(async () => { throw new Error('network down') })
await store.refresh()
check('E 失败后清零（无脏读）', store.recentFailedTasks, 0)
check('E health=unknown', store.health, 'unknown')

// 用例 F：两次 refresh 不重复请求（幂等）
const before = __calls.health
await Promise.all([store.refresh(), store.refresh(), store.refresh()])
check('F 并发 refresh 只打 1 次 health', __calls.health - before, 1)

// 用例 G：error_rate>0.2 → warn
__setHealth(async () => ({ tasks: { recent_failed: 1, error_rate: 0.5 }, database: { healthy: true } }))
await store.refresh()
check('G error_rate 高→warn', store.health, 'warn')

// 用例 H：database.healthy=false → error
__setHealth(async () => ({ tasks: { error_rate: 0.0 }, database: { healthy: false } }))
await store.refresh()
check('H db 不健康→error', store.health, 'error')

let fail = 0
for (const r of results) {
  if (!r.ok) fail++
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}  actual=${JSON.stringify(r.actual)} expected=${JSON.stringify(r.expected)}`)
}
console.log(`\n合计 ${results.length} 条，FAIL ${fail} 条`)
process.exit(fail ? 1 : 0)
