/**
 * 女优收藏系统 API
 */
import { api } from './index'

/**
 * 获取女优收藏列表
 * GET /actresses?keyword=&favorite_only=&tier=&sort_by=
 */
export function getActresses(params) {
  return api({
    url: '/actresses',
    method: 'GET',
    params,
  })
}

/**
 * 女优数据库统计
 * GET /actresses/stats
 */
export function getActressStats() {
  return api({
    url: '/actresses/stats',
    method: 'GET',
  })
}

/**
 * 从各模块数据库同步女优
 * POST /actresses/sync
 */
export function syncActresses() {
  return api({
    url: '/actresses/sync',
    method: 'POST',
  })
}

/**
 * 设置/取消女优收藏
 * POST /actresses/{name}/favorite?favorite=true
 */
export function setActressFavorite(name, favorite) {
  return api({
    url: `/actresses/${encodeURIComponent(name)}/favorite`,
    method: 'POST',
    params: { favorite },
  })
}

/**
 * 设置女优Tier分级
 * POST /actresses/{name}/tier?tier=3
 */
export function setActressTier(name, tier) {
  return api({
    url: `/actresses/${encodeURIComponent(name)}/tier`,
    method: 'POST',
    params: { tier },
  })
}
