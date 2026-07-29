/**
 * MCP 协议 + 流媒体聚合搜索 API
 */

import { api } from './index'

/**
 * 搜索番号的在线播放源
 * GET /api/mcp/stream/search?code={code}
 */
export function searchOnlineSource(code) {
  return api({
    url: '/mcp/stream/search',
    method: 'GET',
    params: { code },
  })
}

/**
 * 获取 MCP 能力声明
 * GET /api/mcp/capabilities
 */
export function getMCPCapabilities() {
  return api({
    url: '/mcp/capabilities',
    method: 'GET',
  })
}

/**
 * 调用 MCP 工具
 * POST /api/mcp/tools/{toolName}
 */
export function callMCPTool(toolName, arguments_) {
  return api({
    url: `/mcp/tools/${toolName}`,
    method: 'POST',
    data: arguments_,
  })
}

/**
 * 获取 MCP 资源
 * GET /api/mcp/resources/{uri}
 */
export function getMCPResource(uri) {
  return api({
    url: `/mcp/resources/${uri}`,
    method: 'GET',
  })
}

/**
 * 获取欧美品牌列表
 * GET /api/western-enhanced/brands
 */
export function getWesternBrands() {
  return api({
    url: '/western-enhanced/brands',
    method: 'GET',
  })
}

/**
 * 欧美聚合搜索
 * POST /api/western-enhanced/aggregate-search
 */
export function westernAggregateSearch(data) {
  return api({
    url: '/western-enhanced/aggregate-search',
    method: 'POST',
    data,
  })
}

/**
 * Stash: 通过 URL 刮削场景
 * GET /api/stash/scene/url?url={url}
 */
export function stashSceneByUrl(url) {
  return api({
    url: '/stash/scene/url',
    method: 'GET',
    params: { url },
  })
}

/**
 * Stash: 通过名称搜索场景
 * GET /api/stash/scene/search?name={name}&brand={brand}
 */
export function stashSceneSearch(name, brand = '') {
  return api({
    url: '/stash/scene/search',
    method: 'GET',
    params: { name, brand },
  })
}

/**
 * Stash: 搜索演员
 * GET /api/stash/performer/search?name={name}
 */
export function stashPerformerSearch(name) {
  return api({
    url: '/stash/performer/search',
    method: 'GET',
    params: { name },
  })
}
