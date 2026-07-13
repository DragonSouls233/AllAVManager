<template>
  <div class="page movie-graph-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <el-icon><Connection /></el-icon>
          影片关联图谱
        </h2>
        <span class="page-subtitle">基于同演员/同系列/同标签/同厂商构建关联图谱</span>
      </div>
    </div>

    <!-- 搜索工具栏 -->
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-input
            v-model="movieIdInput"
            placeholder="输入影片 ID 或番号"
            clearable
            style="width: 240px"
            @keyup.enter="loadGraph"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-button type="primary" :loading="loading" @click="loadGraph">
            <el-icon><Search /></el-icon> 查询图谱
          </el-button>
          <el-divider direction="vertical" />
          <span class="depth-label">关联深度</span>
          <el-slider
            v-model="depth"
            :min="1"
            :max="3"
            :step="1"
            :show-tooltip="false"
            style="width: 140px"
            @change="onDepthChange"
          />
          <el-tag size="small" effect="plain">{{ depth }} 层</el-tag>
        </div>
      </div>
    </el-card>

    <!-- 空状态 -->
    <el-card v-if="!graph.nodes.length && !loading" shadow="never" class="empty-card">
      <EmptyState
        type="no-results"
        title="请输入影片 ID 查询图谱"
        description="输入一个影片 ID,即可查看基于演员/系列/标签/厂商构建的关联关系"
      />
    </el-card>

    <!-- 主体:图谱 + 推荐列表 -->
    <el-row :gutter="16" v-loading="loading" v-if="graph.nodes.length || loading">
      <!-- 图谱可视化区 -->
      <el-col :xs="24" :lg="16">
        <el-card shadow="never" class="graph-card">
          <template #header>
            <div class="card-header-bar">
              <div class="card-header-title">
                <el-icon><Share /></el-icon>
                关联图谱
                <span class="graph-meta">{{ graph.nodes.length }} 节点 · {{ graph.edges.length }} 边</span>
              </div>
              <div class="legend-bar">
                <span class="legend-item"><i class="dot dot-actor"></i>同演员</span>
                <span class="legend-item"><i class="dot dot-series"></i>同系列</span>
                <span class="legend-item"><i class="dot dot-tag"></i>同标签</span>
                <span class="legend-item"><i class="dot dot-studio"></i>同厂商</span>
              </div>
            </div>
          </template>

          <div class="svg-wrapper">
            <svg
              v-if="graph.nodes.length"
              :viewBox="`0 0 ${svgWidth} ${svgHeight}`"
              class="graph-svg"
              preserveAspectRatio="xMidYMid meet"
            >
              <!-- 边 -->
              <g class="edges">
                <line
                  v-for="(edge, idx) in layoutEdges"
                  :key="'e' + idx"
                  :x1="edge.x1"
                  :y1="edge.y1"
                  :x2="edge.x2"
                  :y2="edge.y2"
                  :stroke="edge.color"
                  :stroke-width="edge.width"
                  :stroke-opacity="0.6"
                />
              </g>
              <!-- 节点 -->
              <g class="nodes">
                <g
                  v-for="node in layoutNodes"
                  :key="node.id"
                  :transform="`translate(${node.x}, ${node.y})`"
                  class="graph-node-g"
                  @click="onNodeClick(node)"
                >
                  <circle
                    :r="node.r"
                    :fill="node.fill"
                    :stroke="node.stroke"
                    stroke-width="2"
                  />
                  <image
                    v-if="node.cover_url"
                    :href="node.cover_url"
                    :x="-node.r"
                    :y="-node.r"
                    :width="node.r * 2"
                    :height="node.r * 2"
                    :clip-path="`circle(${node.r}px at center)`"
                    preserveAspectRatio="xMidYMid slice"
                  />
                  <text
                    :y="node.r + 14"
                    text-anchor="middle"
                    class="node-label"
                  >{{ node.code || node.id }}</text>
                  <text
                    v-if="node.isCenter"
                    :y="node.r + 28"
                    text-anchor="middle"
                    class="node-center-tag"
                  >中心节点</text>
                </g>
              </g>
            </svg>
            <div v-else class="graph-placeholder">
              <el-icon :size="48"><Loading /></el-icon>
              <p>正在生成图谱…</p>
            </div>
          </div>

          <!-- 按关联类型分组的关联影片(简化版备用展示) -->
          <el-collapse v-if="groupedByType.size" class="group-collapse">
            <el-collapse-item
              v-for="[type, items] in groupedByType"
              :key="type"
              :name="type"
            >
              <template #title>
                <span class="group-title">
                  <i class="dot" :class="'dot-' + type"></i>
                  {{ typeLabel(type) }}({{ items.length }})
                </span>
              </template>
              <div class="group-grid">
                <div
                  v-for="item in items"
                  :key="item.id"
                  class="group-cell"
                  @click="onNodeClick(item)"
                >
                  <img v-if="item.cover_url" :src="item.cover_url" :alt="item.code" />
                  <div v-else class="group-cell-fallback">
                    <el-icon><Picture /></el-icon>
                  </div>
                  <div class="group-cell-code">{{ item.code }}</div>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-card>
      </el-col>

      <!-- 右侧推荐列表 -->
      <el-col :xs="24" :lg="8">
        <el-card shadow="never" class="recommend-card">
          <template #header>
            <div class="card-header-title">
              <el-icon><MagicStick /></el-icon>
              关联推荐
              <el-tag size="small" effect="plain" style="margin-left: 8px">
                {{ recommendations.length }}
              </el-tag>
            </div>
          </template>
          <div v-if="recommendations.length" class="rec-list">
            <div
              v-for="rec in recommendations"
              :key="rec.id"
              class="rec-item"
              @click="onNodeClick(rec)"
            >
              <div class="rec-cover">
                <img v-if="rec.cover_url" :src="rec.cover_url" :alt="rec.code" />
                <div v-else class="rec-cover-fallback">
                  <el-icon><Picture /></el-icon>
                </div>
                <RatingStars
                  v-if="rec.score != null"
                  :rating="rec.score"
                  size="small"
                  class="rec-rating"
                />
              </div>
              <div class="rec-info">
                <div class="rec-code">{{ rec.code }}</div>
                <div class="rec-title">{{ rec.title || '未命名' }}</div>
                <div class="rec-reason">
                  <el-tag
                    v-for="reason in parseReasons(rec)"
                    :key="reason"
                    size="small"
                    effect="plain"
                    :type="reasonTagType(reason)"
                  >{{ reason }}</el-tag>
                </div>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无推荐,先查询图谱" :image-size="80" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Connection, Search, Share, MagicStick, Picture, Loading
} from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import RatingStars from '@/components/RatingStars.vue'
import { getMovieGraph, getMovieRecommendations } from '@/api'

const router = useRouter()

const movieIdInput = ref('')
const depth = ref(1)
const loading = ref(false)
const graph = ref({ nodes: [], edges: [] })
const recommendations = ref([])

// SVG 画布尺寸
const svgWidth = 800
const svgHeight = 560

// 关联类型 → 颜色
const TYPE_COLOR = {
  actor: '#409EFF',    // 蓝
  series: '#67C23A',   // 绿
  tag: '#E6A23C',      // 橙
  studio: '#9B59B6'    // 紫
}
const TYPE_LABEL = {
  actor: '同演员',
  series: '同系列',
  tag: '同标签',
  studio: '同厂商'
}

const TYPE_KEYS = Object.keys(TYPE_COLOR)

function typeLabel(type) {
  return TYPE_LABEL[type] || type
}

// 节点最大/最小半径
const R_MIN = 16
const R_MAX = 36

// 节点权重计算:节点入度+出度
function nodeWeight(nodeId) {
  return graph.value.edges.reduce((sum, e) => {
    if (String(e.source) === String(nodeId) || String(e.target) === String(nodeId)) {
      return sum + (e.weight || 1)
    }
    return sum
  }, 0)
}

// 找出节点的关联类型(取该节点与中心节点边的类型)
function nodeRelationType(nodeId, centerId) {
  const edge = graph.value.edges.find(e =>
    (String(e.source) === String(nodeId) && String(e.target) === String(centerId)) ||
    (String(e.target) === String(nodeId) && String(e.source) === String(centerId))
  )
  if (edge && edge.relation_type) return edge.relation_type
  // 兜底:从该节点所有边中取出现次数最多的类型
  const counts = {}
  graph.value.edges.forEach(e => {
    if (String(e.source) === String(nodeId) || String(e.target) === String(nodeId)) {
      const t = e.relation_type || 'actor'
      counts[t] = (counts[t] || 0) + 1
    }
  })
  return Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0] || 'actor'
}

// 计算节点的布局位置(径向布局:中心节点居中,其他节点按角度均匀分布)
const layoutNodes = computed(() => {
  const nodes = graph.value.nodes
  if (!nodes.length) return []
  const centerId = movieIdInput.value.trim()
  const cx = svgWidth / 2
  const cy = svgHeight / 2

  const weights = nodes.map(n => nodeWeight(n.id))
  const maxW = Math.max(1, ...weights)

  // 找中心节点(若未匹配到则使用第一个节点)
  const centerIdx = (() => {
    const idx = nodes.findIndex(n => String(n.id) === String(centerId))
    return idx >= 0 ? idx : 0
  })()
  const centerNode = nodes[centerIdx]

  // 其他节点
  const others = nodes.filter((_, i) => i !== centerIdx)

  const result = []
  // 中心节点
  result.push({
    ...centerNode,
    x: cx,
    y: cy,
    r: R_MAX,
    fill: TYPE_COLOR.actor,
    stroke: 'var(--primary-color, #409eff)',
    isCenter: true
  })

  // 按关联类型分组,每组占用一个扇区
  const grouped = {}
  others.forEach(n => {
    const t = nodeRelationType(n.id, centerNode.id)
    if (!grouped[t]) grouped[t] = []
    grouped[t].push(n)
  })

  const radius = Math.min(svgWidth, svgHeight) * 0.35
  let angleOffset = 0
  TYPE_KEYS.forEach(type => {
    const group = grouped[type] || []
    if (!group.length) return
    const angleSpan = (group.length / others.length) * Math.PI * 2
    group.forEach((n, idx) => {
      const angle = angleOffset + (idx + 1) * (angleSpan / (group.length + 1))
      const w = nodeWeight(n.id)
      const r = R_MIN + (w / maxW) * (R_MAX - R_MIN)
      result.push({
        ...n,
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
        r,
        fill: TYPE_COLOR[type],
        stroke: TYPE_COLOR[type],
        relationType: type
      })
    })
    angleOffset += angleSpan
  })

  return result
})

// 边的布局
const layoutEdges = computed(() => {
  const nodeMap = new Map(layoutNodes.value.map(n => [String(n.id), n]))
  return graph.value.edges.map(edge => {
    const s = nodeMap.get(String(edge.source))
    const t = nodeMap.get(String(edge.target))
    if (!s || !t) return null
    const w = edge.weight || 1
    const type = edge.relation_type || 'actor'
    return {
      x1: s.x, y1: s.y, x2: t.x, y2: t.y,
      width: Math.max(1, Math.min(6, w)),
      color: TYPE_COLOR[type] || '#909399'
    }
  }).filter(Boolean)
})

// 按关联类型分组(用于折叠面板展示)
const groupedByType = computed(() => {
  const map = new Map()
  const centerId = movieIdInput.value.trim()
  graph.value.nodes.forEach(n => {
    if (String(n.id) === String(centerId)) return
    const t = nodeRelationType(n.id, centerId)
    if (!map.has(t)) map.set(t, [])
    map.get(t).push(n)
  })
  // 排序:按 TYPE_KEYS 顺序
  const sorted = new Map()
  TYPE_KEYS.forEach(k => {
    if (map.has(k)) sorted.set(k, map.get(k))
  })
  return sorted
})

function parseReasons(rec) {
  if (Array.isArray(rec.reasons)) return rec.reasons.slice(0, 3)
  if (rec.reason) return [rec.reason]
  // 推断:从关联类型
  const types = []
  if (rec.same_actors) types.push('同演员')
  if (rec.same_series) types.push('同系列')
  if (rec.same_tags) types.push('同标签')
  if (rec.same_studio) types.push('同厂商')
  return types.length ? types : ['关联推荐']
}

function reasonTagType(reason) {
  if (reason.includes('演员')) return 'primary'
  if (reason.includes('系列')) return 'success'
  if (reason.includes('标签')) return 'warning'
  if (reason.includes('厂商')) return 'info'
  return ''
}

function onNodeClick(node) {
  if (!node || !node.id) return
  router.push(`/movie/${node.id}`)
}

async function loadGraph() {
  const raw = movieIdInput.value.trim()
  if (!raw) { ElMessage.warning('请输入影片 ID 或番号'); return }
  const movieId = parseInt(raw)
  if (!movieId) { ElMessage.warning('请输入有效的影片 ID'); return }
  loading.value = true
  graph.value = { nodes: [], edges: [] }
  recommendations.value = []
  try {
    const [graphRes, recRes] = await Promise.all([
      getMovieGraph(movieId, depth.value),
      getMovieRecommendations(movieId, 12)
    ])
    graph.value = {
      nodes: graphRes.nodes || [],
      edges: graphRes.edges || []
    }
    recommendations.value = recRes.items || recRes || []
    if (!graph.value.nodes.length) {
      ElMessage.info('未找到关联数据')
    }
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function onDepthChange() {
  if (movieIdInput.value.trim() && graph.value.nodes.length) {
    loadGraph()
  }
}
</script>

<style scoped>
.movie-graph-page {
  gap: var(--gap-md);
}

.toolbar-card {
  border-radius: var(--radius-md) !important;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex-wrap: wrap;
}

.depth-label {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  margin-left: var(--gap-sm);
}

.empty-card {
  border-radius: var(--radius-md) !important;
}

.graph-card,
.recommend-card {
  border-radius: var(--radius-md) !important;
  height: 100%;
}

.card-header-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.card-header-title {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-weight: 600;
  font-size: var(--font-size-md);
  color: var(--text-primary);
}

.graph-meta {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  font-weight: 400;
}

.legend-bar {
  display: flex;
  align-items: center;
  gap: var(--gap-md);
  flex-wrap: wrap;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--text-placeholder);
}

.dot-actor { background: #409EFF; }
.dot-series { background: #67C23A; }
.dot-tag { background: #E6A23C; }
.dot-studio { background: #9B59B6; }

.svg-wrapper {
  width: 100%;
  background: var(--bg-page);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.graph-svg {
  width: 100%;
  height: 560px;
  display: block;
  background: radial-gradient(circle at center, rgba(64, 158, 255, 0.04) 0%, transparent 70%);
}

.graph-node-g {
  cursor: pointer;
  transition: transform 0.2s;
}

.graph-node-g:hover {
  transform: scale(1.1);
}

.node-label {
  font-size: 11px;
  fill: var(--text-regular);
  font-weight: 500;
  pointer-events: none;
  user-select: none;
}

.node-center-tag {
  font-size: 10px;
  fill: var(--primary-color);
  font-weight: 600;
  pointer-events: none;
}

.graph-placeholder {
  height: 560px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--gap-sm);
  color: var(--text-secondary);
}

.group-collapse {
  margin-top: var(--gap-md);
  border-top: 1px solid var(--border-light);
  padding-top: var(--gap-sm);
}

.group-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
  color: var(--text-primary);
}

.group-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: var(--gap-sm);
  padding: var(--gap-sm) 0;
}

.group-cell {
  cursor: pointer;
  text-align: center;
  transition: transform var(--transition-fast);
}

.group-cell:hover {
  transform: translateY(-3px);
}

.group-cell img {
  width: 100%;
  aspect-ratio: 2 / 3;
  object-fit: cover;
  border-radius: var(--radius-sm);
}

.group-cell-fallback {
  width: 100%;
  aspect-ratio: 2 / 3;
  background: var(--bg-page);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-placeholder);
}

.group-cell-code {
  font-size: var(--font-size-xs);
  color: var(--text-regular);
  margin-top: 4px;
}

.rec-list {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  max-height: 720px;
  overflow-y: auto;
}

.rec-item {
  display: flex;
  gap: var(--gap-sm);
  padding: var(--gap-sm);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  border: 1px solid var(--border-light);
}

.rec-item:hover {
  border-color: var(--primary-light);
  transform: translateX(-2px);
  box-shadow: var(--shadow-sm);
}

.rec-cover {
  position: relative;
  width: 70px;
  height: 100px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  flex-shrink: 0;
  background: var(--bg-page);
}

.rec-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.rec-cover-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-placeholder);
}

.rec-rating {
  position: absolute;
  bottom: 4px;
  left: 4px;
}

.rec-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.rec-code {
  font-weight: 600;
  font-size: var(--font-size-sm);
  color: var(--primary-color);
}

.rec-title {
  font-size: var(--font-size-xs);
  color: var(--text-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.rec-reason {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: auto;
}

@media (max-width: 768px) {
  .graph-svg,
  .graph-placeholder {
    height: 420px;
  }
}
</style>
