/* 取数与缓存的统一出口（@/query）。
 *
 * 页面和 store 都从这里 import，不直接碰 client.js / keys.js，保证全站只有一个 QueryClient 实例。
 * 目前落地范围：PORNHUB 影片库 / 演员库、JAV 影片库。其余模块仍走原有 Pinia + axios 直连，
 * 二者可以共存——query 只是把「同样的请求不重复发、任务完成后能失效」这件事接管了。 */

export { queryClient, invalidateByPrefix, clearByPrefix } from './client'
export { queryKeys } from './keys'
export { usePendingPoll } from './pending-poll'
