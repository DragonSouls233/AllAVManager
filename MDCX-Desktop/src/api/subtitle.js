import { api } from './index'

/**
 * 字幕下载（JAV 有码 / 无码）。
 *
 * 后端约定：失败也是 HTTP 200 + `ok:false` + `reason`，
 * 所以这里不需要 catch 业务错误，只要把结果交给调用方展示。
 */

/** 失败原因 → 中文文案（前端唯一映射源，禁止在页面里另写字表） */
export const SUBTITLE_REASON_TEXT = {
  already_exists: '该影片已有字幕，已跳过',
  no_number: '无法从片名识别番号，无法搜索',
  no_file_path: '该影片没有本地文件路径，无法写入字幕',
  site_empty: '两个站点都没有搜到该番号的字幕',
  blocked: '站点暂时拒绝访问（可能触发风控），请稍后重试',
  timeout: '搜索或下载超时，请稍后重试',
  download_failed: '字幕文件下载失败，已尝试全部候选',
  write_failed: '写入视频目录失败（网络盘只读/磁盘已满）',
  cancelled: '已取消'
}

/** 把后端结果翻成一句可直接展示的中文 */
export function subtitleReasonText (res) {
  if (!res) return '未知错误'
  return SUBTITLE_REASON_TEXT[res.reason] || res.message || '字幕下载失败'
}

export function getSubtitleStatus (module, movieId) {
  return api.get(`/subtitles/${module}/${movieId}/status`)
}

/** 单条：整链路 45s 预算 + 两站搜索，超时放宽到 90s */
export function downloadMovieSubtitle (module, movieId, data = {}) {
  return api.post(`/subtitles/${module}/${movieId}/download`, data, { timeout: 90000 })
}

export function startSubtitleBatch (module, data = {}) {
  return api.post(`/subtitles/${module}/batch`, data, { timeout: 30000 })
}

export function getSubtitleBatch (module, jobId) {
  return api.get(`/subtitles/${module}/batch/${jobId}`)
}

export function cancelSubtitleBatch (module, jobId) {
  return api.post(`/subtitles/${module}/batch/${jobId}/cancel`)
}

export function getLatestSubtitleBatch (module) {
  return api.get(`/subtitles/${module}/batch/latest`)
}
