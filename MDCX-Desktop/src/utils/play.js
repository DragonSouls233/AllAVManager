/**
 * 模块播放路由工具
 * 统一处理 6 大模块的播放信息获取和播放 URL 生成
 */
import { getJavPlayInfo, getJavPlayUrl } from '@/api/jav'
import { getFc2PlayInfo, getFc2PlayUrl } from '@/api/fc2'
import { getUncensoredPlayInfo, getUncensoredPlayUrl } from '@/api/uncensored'
import { getChinesePlayInfo, getChinesePlayUrl } from '@/api/chinese'
import { getPornhubPlayInfo, getPornhubPlayUrl } from '@/api/pornhub'
import { getWesternPlayInfo, getWesternPlayUrl } from '@/api/western'

const MODULE_API_MAP = {
  jav: { getPlayInfo: getJavPlayInfo, getPlayUrl: getJavPlayUrl },
  uncensored: { getPlayInfo: getUncensoredPlayInfo, getPlayUrl: getUncensoredPlayUrl },
  fc2: { getPlayInfo: getFc2PlayInfo, getPlayUrl: getFc2PlayUrl },
  chinese: { getPlayInfo: getChinesePlayInfo, getPlayUrl: getChinesePlayUrl },
  pornhub: { getPlayInfo: getPornhubPlayInfo, getPlayUrl: getPornhubPlayUrl },
  western: { getPlayInfo: getWesternPlayInfo, getPlayUrl: getWesternPlayUrl },
}

export function getModulePlayAPI(module) {
  return MODULE_API_MAP[module] || null
}

export async function getModulePlayInfo(module, movieId) {
  const api = getModulePlayAPI(module)
  if (!api) return null
  return await api.getPlayInfo(movieId)
}

export async function getModulePlayUrl(module, movieId, protocol = 'http') {
  const api = getModulePlayAPI(module)
  if (!api) return null
  return await api.getPlayUrl(movieId, protocol)
}
