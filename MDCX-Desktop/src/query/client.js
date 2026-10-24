/* 全站唯一的 TanStack Query 客户端。
 *
 * 借鉴自 peach（ref240-peach）frontend/src/query/client.ts 的取值决策，但按 MDCX 的
 * 部署形态重新论证过——MDCX 是 Electron 加载 file:// 连局域网服务器，与它的
 * 「本机回环 + 浏览器托管页面」不是一回事，所以每一条都重新检查过理由。
 *
 * 页面不直接 import 本文件，走 `@/query` 统一出口，保证用到的永远是同一个实例。 */
import { QueryClient } from '@tanstack/vue-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      /* 🔴 断网时也要发请求。浏览器/Electron 的 navigator.onLine 判断的是「能不能上外网」，
         而 MDCX 的数据全在局域网服务器（192.168.10.120:8420）。一旦外网断开或网卡状态
         抖动，onLine 会翻 false，Query 默认把请求挂成 paused —— 页面就停在旧数据上什么都不说，
         用户以为「后端不动了」。桌面端常驻、网络环境还带代理，这个坑比浏览器更容易踩。 */
      networkMode: 'always',

      /* 失败不重试。请求失败的典型原因是服务没起、库只读、脚本还在跑，同一秒再问三遍
         得到的是同一句话，只是把错误晚几秒显示出来。而且 axios 响应拦截器已经统一弹过
         ElMessage 了，重试只会把同一条红字弹三遍。真要重试的页面自己定轮询节律。 */
      retry: 0,

      /* 切回窗口不自动重取。桌面端 alt-tab 极频繁，自动重取会把「同一份数据两个节律」——
         页面自己的轮询和焦点触发打架。需要即时的页面显式轮询（见 usePendingPoll）。 */
      refetchOnWindowFocus: false,

      /* 挂载不重取：MDCX 的页面是「进页面 → store 主动 fetchQuery」，不是 peach 那种
         路由 prefetch 后 useQuery 自动接管的模型。这两个开关留给将来页面改用 useQuery 时
         的行为对齐，现在开着反而会让一次进入发两遍同样的请求。 */
      refetchOnMount: false,
      retryOnMount: false,

      /* 一律视为过期。MDCX 的语义是「进页面就要服务端最新的一份」，库里随时被扫描器、
         批量刮削、补封面任务改写，缓存秒级就用不上。这里要的是**在途请求合并**和
         **手动失效后统一刷新**，不是拿旧数据顶时间。 */
      staleTime: 0,
    },
  },
})

/** 手动让某个前缀下的查询全部过期（下一次 fetchQuery 会重新取）。
 *
 * 只失效不重取：调用点通常在「后台任务刚启动」之后，此刻立刻重取拿到的还是旧值，
 * 交给页面自己的轮询或用户下一次操作去取。 */
export function invalidateByPrefix(prefix) {
  return queryClient.invalidateQueries({ queryKey: prefix })
}

/** 丢弃某前缀下的缓存。切换服务器地址时必须调用——否则换了服务器还在读上一台的数据。 */
export function clearByPrefix(prefix) {
  return queryClient.removeQueries({ queryKey: prefix })
}
