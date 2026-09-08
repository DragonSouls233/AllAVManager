/**
 * 桌面端启动引导。
 *
 * 桌面端是「纯消费型前端」：打开就该直接看到影片库，而不是先卡在登录页。
 * 启动顺序：
 *   1) 确定后端地址（localStorage → Electron 自动探测）
 *   2) 若本机已在后端可信 IP 白名单内 → 静默拿 token，免登录直入
 *   3) 都不行 → 交给登录页
 *
 * 注意：这里一律用「绝对 URL + 原生 fetch」。
 * 桌面端页面跑在 file:// 下，相对路径 /api/v1/... 会被解析成 file:///api/v1/...，
 * axios 实例虽然配了 baseURL，但拦截器等边界分支仍可能漏出相对路径。
 */
import { setServerUrl } from '@/api'
import { isDesktop } from '@/config/flavor'

const SERVER_KEY = 'serverUrl'
const TOKEN_KEY = 'token'

/** 可信 IP 模式使用的固定凭证（后端 auth_middleware 特判放行） */
const TRUSTED_TOKEN = 'trusted-ip-mode'

async function resolveServerUrl() {
  let url = (localStorage.getItem(SERVER_KEY) || '').trim().replace(/\/+$/, '')
  if (url) return url

  const api = typeof window !== 'undefined' ? window.electronAPI : null
  if (api?.detectBackend) {
    try {
      const result = await api.detectBackend()
      if (result?.ok && result.url) url = result.url.trim().replace(/\/+$/, '')
    } catch (e) {
      console.warn('[bootstrap] backend detection failed:', e)
    }
  }
  return url
}

async function tryTrustedIpLogin(base) {
  // 先看后端是否开启可信 IP（该端点是 PUBLIC_PATHS，无需登录）
  let enabled = false
  try {
    const res = await fetch(`${base}/api/v1/auth/trusted-ip`, { cache: 'no-store' })
    if (res.ok) {
      const cfg = await res.json()
      enabled = !!cfg?.enable_trusted_ip
    }
  } catch {
    return false
  }
  if (!enabled) return false

  // 再验证当前客户端 IP 是否真的在白名单里。
  // 注意：不能拿 /auth/me 探测——它下游 Depends(get_current_user) 会解析 token，
  // 而可信 IP 放行与 token 无关，用占位凭证必然 401，会误判成「未生效」。
  // 正确做法是「不带任何凭证」请求一个受保护的轻量端点，200 即代表 IP 已被放行。
  try {
    const probe = await fetch(`${base}/api/v1/modules`, { cache: 'no-store' })
    if (!probe.ok) return false
    localStorage.setItem(TOKEN_KEY, TRUSTED_TOKEN)
    return true
  } catch {
    return false
  }
}

/**
 * 必须在 router 首次导航前完成（main.js 中 await）。
 * Web 端直接跳过。
 */
export async function bootstrapDesktop() {
  if (!isDesktop) return
  const api = typeof window !== 'undefined' ? window.electronAPI : null
  if (api && !api.isElectron) return

  const url = await resolveServerUrl()
  if (!url) return

  setServerUrl(url)
  localStorage.setItem(SERVER_KEY, url)

  if (localStorage.getItem(TOKEN_KEY)) return
  const ok = await tryTrustedIpLogin(url)
  console.log(`[bootstrap] server=${url} trustedIp=${ok}`)
}

export { TRUSTED_TOKEN }
