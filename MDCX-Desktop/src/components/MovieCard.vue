<template>
  <div
    class="movie-card"
    :class="[`mode-${viewMode}`, `img-${imageMode}`]"
    role="article"
    :aria-label="`影片：${movie.code}${movie.title ? ' - ' + movie.title : ''}`"
    tabindex="0"
    @click="$emit('click', movie.id)"
    @mouseenter="onEnter"
    @mouseleave="onLeave"
    @keydown.enter="$emit('click', movie.id)"
    @keydown.space.prevent="$emit('click', movie.id)"
  >
    <div class="movie-cover">
      <img
        :src="displayCover"
        :alt="`封面图：${movie.code}`"
        class="movie-cover-img"
        decoding="async"
        loading="lazy"
        @error="onCoverError"
      />

      <!-- 评分 -->
      <RatingStars v-if="movie.rating != null" :rating="movie.rating" />

      <!-- 播放次数 -->
      <div class="movie-play-count" v-if="movie.play_count > 0" aria-hidden="true">
        <el-icon><View /></el-icon> {{ movie.play_count }}
      </div>

      <!-- 收藏按钮 -->
      <div
        class="movie-fav-btn touch-target"
        role="button"
        tabindex="0"
        :aria-label="movie._fav ? '取消收藏' : '收藏影片'"
        :aria-pressed="!!movie._fav"
        @click.stop="$emit('fav', movie)"
        @keydown.enter.stop.prevent="$emit('fav', movie)"
        @keydown.space.stop.prevent="$emit('fav', movie)"
      >
        <el-icon :class="{ 'fav-active': movie._fav }"><Star /></el-icon>
      </div>

      <!-- 播放按钮 -->
      <div
        class="movie-play touch-target"
        role="button"
        tabindex="0"
        aria-label="播放影片"
        @click.stop="$emit('play', movie.id)"
        @keydown.enter.stop.prevent="$emit('play', movie.id)"
        @keydown.space.stop.prevent="$emit('play', movie.id)"
      >
        <el-icon size="26"><VideoPlay /></el-icon>
      </div>

      <!-- 放大预览按钮 -->
      <div
        class="movie-zoom-btn touch-target"
        role="button"
        tabindex="0"
        aria-label="放大预览封面"
        @click.stop="$emit('preview-cover', movie)"
        @keydown.enter.stop.prevent="$emit('preview-cover', movie)"
        @keydown.space.stop.prevent="$emit('preview-cover', movie)"
      >
        <el-icon><ZoomIn /></el-icon>
      </div>

      <!-- 截图轮换指示器 -->
      <div
        class="image-dots"
        v-if="movie.sample_images && movie.sample_images.length > 0"
        role="group"
        :aria-label="`共 ${movie.sample_images.length} 张预览图,当前第 ${imgIndex === 0 ? 1 : imgIndex} 张`"
      >
        <span
          v-for="(img, idx) in movie.sample_images.slice(0, 8)"
          :key="idx"
          :class="{ active: imgIndex === idx + 1 }"
        ></span>
      </div>
    </div>

    <div class="movie-info">
      <div class="movie-code" @dblclick.stop="copyCode" title="双击复制番号">{{ movie.code }}</div>
      <div class="movie-title" :title="movie.title || '未命名'">{{ movie.title || '未命名' }}</div>

      <!-- 标签：用户标签=emerald / 抓取标签=orange（紧凑模式隐藏） -->
      <div class="movie-tags" v-if="movie._tags && movie._tags.length && viewMode !== 'compact'">
        <template v-if="!movie._tagsExpanded">
          <el-tag
            v-for="t in movie._tags.slice(0, 4)"
            :key="t.id || t.name"
            size="small"
            effect="plain"
            :class="t.is_user ? 'tag-user' : 'tag-crawler'"
            @click.stop="$emit('tag-click', t)"
          >{{ t.name }}</el-tag>
          <el-tag
            v-if="movie._tags.length > 4"
            size="small"
            type="info"
            effect="plain"
            class="tag-more-btn"
            @click.stop="movie._tagsExpanded = true"
          >+{{ movie._tags.length - 4 }}</el-tag>
        </template>
        <template v-else>
          <el-tag
            v-for="t in movie._tags"
            :key="t.id || t.name"
            size="small"
            effect="plain"
            :class="t.is_user ? 'tag-user' : 'tag-crawler'"
            @click.stop="$emit('tag-click', t)"
          >{{ t.name }}</el-tag>
          <el-tag
            size="small"
            type="info"
            effect="plain"
            class="tag-more-btn"
            @click.stop="movie._tagsExpanded = false"
          >收起</el-tag>
        </template>
      </div>

      <!-- 演员（紧凑模式隐藏） -->
      <div class="movie-actors" v-if="movie.actors && movie.actors.length && viewMode !== 'compact'">
        <el-popover
          v-for="actor in movie.actors.slice(0, 3)"
          :key="actor.id"
          trigger="hover"
          placement="top"
          :width="180"
          :show-after="200"
        >
          <template #reference>
            <span class="actor-name" @click.stop="$emit('actor-click', actor.id)">{{ actor.name }}</span>
            <span class="actor-sep" v-if="movie.actors.indexOf(actor) < Math.min(movie.actors.length, 3) - 1">·</span>
          </template>
          <div class="actor-popover">
            <LazyImage
              :src="getActorAvatar(actor.id)"
              :alt="actor.name"
              :placeholder="fallbackAvatar(actor.name)"
              width="100px"
              height="100px"
              class="actor-popover-avatar"
              @error="handleAvatarError"
            />
            <div class="actor-popover-name">{{ actor.name }}</div>
            <el-button size="small" type="primary" plain @click="$emit('actor-click', actor.id)">
              查看该演员全部作品
            </el-button>
          </div>
        </el-popover>
        <span v-if="movie.actors.length > 3" class="actor-more">
          +{{ movie.actors.length - 3 }}
        </span>
      </div>

      <!-- 详细模式：显示简介 -->
      <div class="movie-plot" v-if="viewMode === 'detail' && movie.plot">
        {{ movie.plot }}
      </div>

      <div class="movie-meta" v-if="viewMode !== 'compact'">
        <span v-if="movie.release_date"><el-icon><Calendar /></el-icon> {{ movie.release_date }}</span>
        <span v-if="movie.duration"><el-icon><Clock /></el-icon> {{ formatDuration(movie.duration) }}</span>
        <span v-if="movie.studio"><el-icon><OfficeBuilding /></el-icon> {{ movie.studio }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay, View, Star, Calendar, Clock, OfficeBuilding, ZoomIn } from '@element-plus/icons-vue'
import RatingStars from './RatingStars.vue'
import { defaultCover, getMovieCoverUrl, getMoviePosterUrl, getMovieThumbUrl, getServerBaseUrl, defaultAvatar, getFileProxyUrl, getActorAvatarUrlById } from '@/utils/media'

const props = defineProps({
  movie: { type: Object, required: true },
  // 视图模式：compact(紧凑) / standard(标准) / detail(详细)
  viewMode: { type: String, default: 'standard' },
  // 图片模式：poster(封面图) / thumbnail(缩略图)
  imageMode: { type: String, default: 'poster' },
  // 海报模式：full(完整) / mosaic(马赛克) / number_only(仅番号)
  posterMode: { type: String, default: 'full' },
})

defineEmits(['click', 'play', 'fav', 'actor-click', 'tag-click', 'preview-cover'])

// 悬停轮换截图
const imgIndex = ref(0)
let hoverTimer = null

// 主图：根据 imageMode 选择封面或缩略图
const baseImage = computed(() => {
  if (props.imageMode === 'thumbnail') {
    return getMovieThumbUrl(props.movie)
  }
  return getMovieCoverUrl(props.movie)
})

const currentImage = computed(() => {
  const m = props.movie
  const idx = imgIndex.value
  if (idx === 0 || !m.sample_images || m.sample_images.length === 0) {
    return baseImage.value
  }
  const url = m.sample_images[idx - 1]
  if (!url) return baseImage.value
  if (/^https?:\/\//i.test(url)) return url
  return getFileProxyUrl(url)
})

// 封面四级回退:cover_url(直接/代理) → 主图API → poster → thumb → 占位图
// Stage 0 先试 cover_url 字段——若是本地路径则通过文件代理加载,
// 为空/失败则进入 Stage 1 由后端 /cover/file 智能兜底。
const coverStage = ref(0) // 0=cover_url 直接/代理 1=主图API 2=poster 3=thumb 4=占位

const displayCover = computed(() => {
  const stage = coverStage.value
  if (stage >= 4) return defaultCover(props.movie?.code || 'MDCX')
  if (stage === 2) return getMoviePosterUrl(props.movie)
  if (stage === 3) return getMovieThumbUrl(props.movie)
  if (stage === 1) return currentImage.value
  // Stage 0: 优先尝试 cover_url,本地路径则文件代理
  const m = props.movie
  if (m?.cover_url) {
    if (/^https?:\/\//i.test(m.cover_url)) return m.cover_url
    return getFileProxyUrl(m.cover_url)
  }
  return currentImage.value // 无 cover_url,直接走 API
})

// 主图切换(含 hover 轮换)时重置回退阶段
watch(currentImage, () => {
  coverStage.value = 0
})

const onCoverError = () => {
  // hover 展示 sample 截图失败时,直接回到主封面,避免闪跳
  if (imgIndex.value !== 0) {
    imgIndex.value = 0
    return
  }
  if (coverStage.value < 4) {
    coverStage.value += 1
  }
}

const onEnter = () => {
  const m = props.movie
  if (!m.sample_images || m.sample_images.length === 0) return
  imgIndex.value = 0
  let i = 0
  hoverTimer = setInterval(() => {
    i = (i + 1) % (m.sample_images.length + 1)
    imgIndex.value = i
  }, 1200)
}

const onLeave = () => {
  if (hoverTimer) {
    clearInterval(hoverTimer)
    hoverTimer = null
  }
  imgIndex.value = 0
}

onBeforeUnmount(() => {
  if (hoverTimer) clearInterval(hoverTimer)
})

// 工具方法
const getActorAvatar = (actorId) => {
  return getActorAvatarUrlById(actorId)
}

// 演员头像默认占位:基于演员名生成
const fallbackAvatar = (name) => defaultAvatar(name || '?')

const handleAvatarError = () => {
  // 占位:LazyImage 会自动切换到 placeholder(fallbackAvatar)
}

const formatDuration = (minutes) => {
  if (!minutes) return ''
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h > 0 ? `${h}h${m}m` : `${m}m`
}

// v4.1 C6: 双击复制番号
const copyCode = async () => {
  const code = props.movie?.code
  if (!code) return
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(code)
    } else {
      const ta = document.createElement('textarea')
      ta.value = code
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    ElMessage.success(`已复制番号:${code}`)
  } catch (e) {
    ElMessage.error('复制失败，请手动选择文本')
  }
}
</script>

<style scoped>
.movie-card {
  cursor: pointer;
  border-radius: 10px;
  overflow: hidden;
  background: var(--bg-card);
  box-shadow: var(--shadow-sm);
  transition: transform 0.2s, box-shadow 0.2s;
  border: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
}

.movie-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-lg);
}

/* ===== 视图模式：紧凑 ===== */
.movie-card.mode-compact {
  border-radius: 6px;
}
.movie-card.mode-compact .movie-cover {
  aspect-ratio: 2 / 3;
}
.movie-card.mode-compact .movie-info {
  padding: 6px 8px 8px;
  gap: 3px;
}
.movie-card.mode-compact .movie-code {
  font-size: 12px;
}
.movie-card.mode-compact .movie-title {
  font-size: 11px;
  -webkit-line-clamp: 1;
  min-height: 1.2em;
}
.movie-card.mode-compact .movie-play-count {
  font-size: 10px;
  padding: 1px 6px;
}
.movie-card.mode-compact .movie-fav-btn {
  width: 24px;
  height: 24px;
}
.movie-card.mode-compact .movie-zoom-btn {
  width: 22px;
  height: 22px;
}

/* ===== 视图模式：标准（默认） ===== */
.movie-card.mode-standard .movie-cover {
  aspect-ratio: 2 / 3;
}

/* ===== 视图模式：详细（横向布局） ===== */
.movie-card.mode-detail {
  flex-direction: row;
}
.movie-card.mode-detail .movie-cover {
  flex: 0 0 200px;
  aspect-ratio: 2 / 3;
  max-width: 200px;
}
.movie-card.mode-detail .movie-info {
  flex: 1;
  padding: 16px 20px;
  gap: 10px;
}
.movie-card.mode-detail .movie-title {
  font-size: 15px;
  -webkit-line-clamp: 3;
}
.movie-card.mode-detail .movie-plot {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  margin-top: 4px;
}

/* ===== 图片模式：缩略图（16:9 比例） ===== */
.movie-card.img-thumbnail .movie-cover {
  aspect-ratio: 16 / 9;
}
.movie-card.mode-detail.img-thumbnail .movie-cover {
  flex: 0 0 280px;
  max-width: 280px;
  aspect-ratio: 16 / 9;
}

.movie-cover {
  position: relative;
  aspect-ratio: 2 / 3;
  background: #1a1a2e;
  overflow: hidden;
}

.movie-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: opacity 0.15s;
}

/* 评分定位到封面左上 */
.movie-cover :deep(.rating-stars) {
  position: absolute;
  top: 6px;
  left: 6px;
}

.movie-play-count {
  position: absolute;
  top: 6px;
  right: 6px;
  background: rgba(0, 0, 0, 0.65);
  color: #fff;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 3px;
}

.movie-fav-btn {
  position: absolute;
  bottom: 6px;
  right: 6px;
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  border-radius: 50%;
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  backdrop-filter: blur(4px);
}

.movie-fav-btn:hover {
  background: rgba(0, 0, 0, 0.85);
  transform: scale(1.1);
}

.movie-fav-btn .fav-active {
  color: #f7ba2a;
}

.movie-play {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  opacity: 0;
  transition: opacity 0.2s, transform 0.2s, background 0.2s;
  backdrop-filter: blur(4px);
  cursor: pointer;
}

.movie-play:hover {
  background: var(--el-color-primary, #409eff);
  transform: translate(-50%, -50%) scale(1.08);
}

.movie-card:hover .movie-play {
  opacity: 1;
}

/* 放大预览按钮（右下角，hover 时显示） */
.movie-zoom-btn {
  position: absolute;
  bottom: 6px;
  left: 6px;
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  border-radius: 50%;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  opacity: 0;
  transition: all 0.2s;
  backdrop-filter: blur(4px);
}

.movie-zoom-btn:hover {
  background: rgba(0, 0, 0, 0.85);
  transform: scale(1.1);
}

.movie-card:hover .movie-zoom-btn {
  opacity: 1;
}

.image-dots {
  position: absolute;
  bottom: 8px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.2s;
}

.movie-card:hover .image-dots {
  opacity: 1;
}

.image-dots span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.4);
  transition: all 0.2s;
}

.image-dots span.active {
  background: #fff;
  transform: scale(1.3);
}

/* 卡片信息 */
.movie-info {
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.movie-code {
  font-weight: 700;
  color: var(--primary-color);
  font-size: 14px;
  letter-spacing: 0.3px;
}

.movie-title {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.4;
  min-height: 1.4em;
}

.movie-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 2px;
}

.movie-tags .el-tag {
  cursor: pointer;
  transition: transform 0.15s;
}

.movie-tags .el-tag:hover {
  transform: scale(1.05);
}

.movie-actors {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  font-size: 12px;
  color: var(--text-secondary);
}

.actor-name {
  color: var(--primary-color);
  cursor: pointer;
  transition: color 0.15s;
}

.actor-name:hover {
  color: var(--primary-light);
  text-decoration: underline;
}

.actor-sep {
  margin: 0 4px;
  color: var(--text-placeholder);
}

.actor-more {
  color: var(--text-secondary);
}

.movie-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.movie-meta span {
  display: flex;
  align-items: center;
  gap: 3px;
}

/* 演员悬浮卡 */
.actor-popover {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 4px;
}

.actor-popover-avatar {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--bg-page);
}

.actor-popover-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 14px;
}

/* 标签颜色区分：用户标签=emerald / 抓取标签=orange */
.movie-tags :deep(.tag-user) {
  --el-tag-bg-color: rgba(16, 185, 129, 0.12);
  --el-tag-border-color: rgba(16, 185, 129, 0.4);
  --el-tag-text-color: #10b981;
  --el-tag-hover-color: #10b981;
}

.movie-tags :deep(.tag-user:hover) {
  --el-tag-bg-color: rgba(16, 185, 129, 0.22);
}

.movie-tags :deep(.tag-crawler) {
  --el-tag-bg-color: rgba(249, 115, 22, 0.12);
  --el-tag-border-color: rgba(249, 115, 22, 0.4);
  --el-tag-text-color: #f97316;
  --el-tag-hover-color: #f97316;
}

.movie-tags :deep(.tag-crawler:hover) {
  --el-tag-bg-color: rgba(249, 115, 22, 0.22);
}

.tag-more-btn {
  cursor: pointer !important;
}

/* ===== 海报模式：B2 马赛克纯净模式 ===== */
/* 马赛克模式：blur + 像素化 */
.movie-card.poster-mosaic .movie-cover img.cover-mosaic {
  filter: blur(20px) saturate(1.2);
  transform: scale(1.1);
  image-rendering: pixelated;
}

/* 马赛克模式下隐藏预览/播放等悬浮按钮，避免在模糊图上误操作 */
.movie-card.poster-mosaic .movie-play,
.movie-card.poster-mosaic .movie-zoom-btn,
.movie-card.poster-mosaic .image-dots {
  display: none;
}

/* 纯净模式：仅显示番号，无封面图 */
.movie-card.poster-number_only .movie-cover.poster-only {
  aspect-ratio: 2 / 3;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  text-align: center;
}

.movie-card.mode-detail.poster-number_only .movie-cover.poster-only {
  flex: 0 0 200px;
  max-width: 200px;
}

.movie-card.img-thumbnail.poster-number_only .movie-cover.poster-only {
  aspect-ratio: 16 / 9;
}

.poster-only-code {
  font-size: 18px;
  font-weight: 800;
  color: #fff;
  letter-spacing: 1px;
  word-break: break-all;
  line-height: 1.3;
}

.movie-card.mode-compact .poster-only-code {
  font-size: 14px;
}

.poster-only-hint {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.4);
  letter-spacing: 0.5px;
}

/* 纯净模式下隐藏评分/收藏/播放等封面悬浮元素 */
.movie-card.poster-number_only .movie-play-count,
.movie-card.poster-number_only .movie-fav-btn,
.movie-card.poster-number_only .movie-play,
.movie-card.poster-number_only .movie-zoom-btn,
.movie-card.poster-number_only .image-dots {
  display: none;
}
</style>
