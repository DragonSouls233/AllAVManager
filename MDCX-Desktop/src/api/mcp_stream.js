/**
 * MCP 协议 + 流媒体聚合搜索 API
 */

import request from '@/utils/request'

/**
 * 搜索番号的在线播放源
 * GET /api/mcp/stream/search?code={code}
 */
export function searchOnlineSource(code) {
  return request({
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
  return request({
    url: '/mcp/capabilities',
    method: 'GET',
  })
}

/**
 * 调用 MCP 工具
 * POST /api/mcp/tools/{toolName}
 */
export function callMCPTool(toolName, arguments_) {
  return request({
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
  return request({
    url: `/mcp/resources/${uri}`,
    method: 'GET',
  })
}
