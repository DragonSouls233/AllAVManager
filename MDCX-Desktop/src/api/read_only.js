/**
 * 唯读来源 + STRM 生成 API
 */
import { api } from './index'

/**
 * 扫描目录，生成唯读引用
 * POST /read-only/scan?root_path=...&generate_strm=true&generate_nfo=true
 */
export function scanReadOnlyDirectory(params) {
  return api({
    url: '/read-only/scan',
    method: 'POST',
    params,
  })
}

/**
 * 获取唯读来源索引 JSON
 * GET /read-only/index
 */
export function getReadOnlyIndex() {
  return api({
    url: '/read-only/index',
    method: 'GET',
  })
}
