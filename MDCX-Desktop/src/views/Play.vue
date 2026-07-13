<template>
  <div class="play" v-loading="loading">
    <!-- 播放器主区域 -->
    <div class="player-container">
      <div ref="artplayerRef" class="artplayer-box"></div>
      <div v-if="!movie?.file_path" class="no-file">
        <el-empty description="该影片没有关联文件" />
      </div>
    </div>

    <!-- 信息与控制栏 -->
    <div class="player-info" v-if="movie">
      <div class="info-header">
        <div class="movie-code" @dblclick="copyCode" title="双击复制番号">{{ movie.code }}</div>
        <div class="info-actions">
          <el-button type="primary" size="small" @click="openExternal('http')">
            <el-icon><VideoPlay /></el-icon> 外部播放
          </el-button>
          <el-button type="success" size="small" @click="playWithMpv">
            <el-icon><Monitor /></el-icon> mpv 播放
          </el-button>
          <el-button
            size="small"
            :type="adaptiveMode ? 'warning' : 'default'"
            :disabled="!hlsQualities.length"
            @click="toggleAdaptive"
            :title="hlsQualities.length ? '切换 HLS 自适应码率（多画质自动切换）' : '当前影片不支持自适应码率'"
          >
            <el-icon><MagicStick /></el-icon>
            {{ adaptiveMode ? '自适应已开' : '自适应码率' }}
          </el-button>
          <el-button size="small" @click="markChapter">
            <el-icon><Flag /></el-icon> 标记此刻
          </el-button>
          <el-button size="small" @click="generateGifHere">
            <el-icon><Picture /></el-icon> 生成 GIF
          </el-button>
        </div>
      </div>
      <div class="movie-title" @dblclick="copyTitle" title="双击复制标题">{{ movie.title || '未命名' }}</div>
      <!-- 影片详情（NFO 元数据） -->
      <div class="movie-detail" v-if="movie">
        <p class="detail-plot" v-if="movie.plot">{{ movie.plot }}</p>
        <div class="detail-grid">
          <div class="detail-item" v-if="movie.release_date">
            <span class="detail-label">发行日期</span>
            <span class="detail-value">{{ movie.release_date }}</span>
          </div>
          <div class="detail-item" v-if="movie.director">
            <span class="detail-label">导演</span>
            <span class="detail-value">{{ movie.director }}</span>
          </div>
          <div class="detail-item" v-if="movie.maker">
            <span class="detail-label">发行商</span>
            <span class="detail-value">{{ movie.maker }}</span>
          </div>
          <div class="detail-item" v-if="movie.studio">
            <span class="detail-label">制作商</span>
            <span class="detail-value">{{ movie.studio }}</span>
          </div>
          <div class="detail-item" v-if="movie.series">
            <span class="detail-label">系列</span>
            <span class="detail-value">{{ movie.series }}</span>
          </div>
          <div class="detail-item detail-item--full" v-if="genreList.length">
            <span class="detail-label">标签</span>
            <span class="detail-value chip-group">
              <el-tag v-for="g in genreList" :key="g" size="small" type="info" effect="plain">{{ g }}</el-tag>
            </span>
          </div>
          <div class="detail-item detail-item--full" v-if="actorList.length">
            <span class="detail-label">演员</span>
            <span class="detail-value chip-group">
              <el-tag
                v-for="a in actorList"
                :key="a.id"
                size="small"
                class="actor-chip"
                @click="goActorDetail(a.id)"
              >{{ a.name }}</el-tag>
            </span>
          </div>
        </div>
      </div>

      <!-- 评分组件 -->
      <div class="rating-block">
        <div class="rating-label">
          <el-icon><Star /></el-icon>
          <span>我的评分</span>
        </div>
        <div class="rating-stars" @mouseleave="hoverRating = 0">
          <span
            v-for="i in 10"
            :key="i"
            class="star"
            :class="{
              filled: i <= (hoverRating || tempRating || movie.rating || 0),
              half: (hoverRating === 0 && !tempRating && movie.rating && i - 0.5 <= movie.rating && i > movie.rating)
            }"
            @mouseenter="hoverRating = i"
            @click="setRating(i)"
          >
            <el-icon><Star /></el-icon>
          </span>
        </div>
        <div class="rating-value">
          <el-input-number
            v-model="ratingInput"
            :min="0"
            :max="10"
            :step="0.1"
            :precision="1"
            size="small"
            controls-position="right"
            style="width: 110px"
            @change="onRatingInput"
          />
          <span class="rating-max">/ 10</span>
          <el-button
            v-if="tempRating !== null"
            type="primary"
            size="small"
            @click="saveRating"
            :loading="savingRating"
            style="margin-left: 12px"
          >保存</el-button>
          <el-button v-if="tempRating !== null" size="small" @click="cancelRating">取消</el-button>
          <el-button
            v-if="movie.rating != null && tempRating === null"
            size="small"
            text
            @click="clearRating"
          >清除评分</el-button>
        </div>
      </div>
    </div>

    <!-- Tab 面板：章节 / GIF / 字幕 / 缩略图 -->
    <el-tabs v-model="activeTab" class="player-tabs" v-if="movie">
      <!-- 章节 -->
      <el-tab-pane :label="`章节 (${chapters.length})`" name="chapters">
        <div class="tab-toolbar">
          <el-button size="small" @click="loadChapters">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
          <el-button size="small" type="primary" @click="markChapter">
            <el-icon><Flag /></el-icon> 标记此刻
          </el-button>
          <el-button size="small" @click="detectChapters" :loading="autoDetecting">
            <el-icon><MagicStick /></el-icon> 自动检测
          </el-button>
          <el-button size="small" @click="genChapterThumbs" :loading="generatingThumbs">
            <el-icon><Picture /></el-icon> 生成缩略图
          </el-button>
          <el-button
            size="small"
            @click="generateSprite"
            :loading="generatingSprite"
          >
            <el-icon><Grid /></el-icon> 生成进度条预览
          </el-button>
        </div>

        <el-table v-if="chapters.length" :data="chapters" border size="small">
          <el-table-column label="时间" width="120">
            <template #default="{ row }">
              <el-button text size="small" @click="seekTo(row.start)">
                {{ formatTime(row.start) }}
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="缩略图" width="100">
            <template #default="{ row }">
              <img v-if="row.thumbnail" :src="row.thumbnail" class="chapter-thumb" />
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="标题" prop="title" />
          <el-table-column label="来源" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.source === 'auto' ? 'info' : 'success'">
                {{ row.source === 'auto' ? '自动' : '手动' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button text size="small" @click="editChapter(row)">编辑</el-button>
              <el-button text size="small" type="danger" @click="removeChapter(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无章节，点击'标记此刻'或'自动检测'添加" :image-size="60" />
      </el-tab-pane>

      <!-- GIF -->
      <el-tab-pane :label="`GIF (${gifs.length})`" name="gifs">
        <div class="tab-toolbar">
          <el-button size="small" @click="loadGifs">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
          <el-form inline size="small" style="margin-left: auto">
            <el-form-item label="时长(秒)">
              <el-input-number v-model="gifForm.duration" :min="0.5" :max="30" :step="0.5" :precision="1" size="small" style="width: 90px" />
            </el-form-item>
            <el-form-item label="宽度">
              <el-input-number v-model="gifForm.width" :min="120" :max="800" :step="40" size="small" style="width: 90px" />
            </el-form-item>
            <el-form-item label="帧率">
              <el-input-number v-model="gifForm.fps" :min="2" :max="30" size="small" style="width: 70px" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" size="small" @click="generateGifHere" :loading="generatingGif">
                生成当前时刻 GIF
              </el-button>
            </el-form-item>
          </el-form>
        </div>

        <div v-if="gifs.length" class="gif-grid">
          <div v-for="g in gifs" :key="g.gif_url" class="gif-card">
            <img :src="g.gif_url" :alt="g.file_name" loading="lazy" />
            <div class="gif-meta">
              <span>{{ g.width }}x{{ g.height }}</span>
              <span>{{ formatSize(g.file_size) }}</span>
              <el-button text size="small" type="danger" @click="removeGif(g.file_name)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无 GIF，设置参数后点击'生成当前时刻 GIF'" :image-size="60" />
      </el-tab-pane>

      <!-- 字幕 -->
      <el-tab-pane label="字幕" name="subtitles">
        <div class="tab-toolbar">
          <el-button size="small" @click="loadSubtitles">
            <el-icon><Refresh /></el-icon> 重新扫描
          </el-button>
        </div>

        <div v-if="subtitles.embedded?.length || subtitles.external?.length">
          <div v-if="subtitles.embedded?.length" class="subtitle-group">
            <div class="group-title">内嵌字幕轨道</div>
            <el-table :data="subtitles.embedded" border size="small">
              <el-table-column label="轨道" width="60" prop="index" />
              <el-table-column label="语言" width="80" prop="language" />
              <el-table-column label="标题" prop="title" />
              <el-table-column label="编码" width="100" prop="codec" />
              <el-table-column label="默认" width="60">
                <template #default="{ row }">
                  <el-tag v-if="row.default" size="small" type="success">是</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div v-if="subtitles.external?.length" class="subtitle-group" style="margin-top: 16px">
            <div class="group-title">外挂字幕文件</div>
            <el-table :data="subtitles.external" border size="small">
              <el-table-column label="文件名" prop="filename" />
              <el-table-column label="语言" width="80">
                <template #default="{ row }">
                  <el-tag size="small">{{ row.language }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="格式" width="80" prop="ext" />
              <el-table-column label="来源" width="100">
                <template #default="{ row }">
                  <el-tag size="small" type="info">{{ sourceLabel(row.source) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="80">
                <template #default="{ row }">{{ formatSize(row.size) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="120">
                <template #default="{ row }">
                  <el-button text size="small" @click="loadExternalSubtitle(row)">加载</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
        <el-empty v-else description="未找到字幕文件。可将 .srt/.ass/.vtt 字幕放到视频同目录" :image-size="60" />
      </el-tab-pane>

      <!-- 缩略图进度条 -->
      <el-tab-pane label="进度条预览" name="sprite">
        <div class="tab-toolbar">
          <el-button size="small" @click="loadSprite">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
          <el-button size="small" type="primary" @click="generateSprite" :loading="generatingSprite">
            <el-icon><Grid /></el-icon> 生成精灵图
          </el-button>
          <el-form inline size="small" style="margin-left: auto">
            <el-form-item label="间隔(秒)">
              <el-input-number v-model="spriteForm.interval" :min="5" :max="300" size="small" style="width: 90px" />
            </el-form-item>
            <el-form-item label="列数">
              <el-input-number v-model="spriteForm.cols" :min="2" :max="20" size="small" style="width: 70px" />
            </el-form-item>
          </el-form>
        </div>

        <el-alert
          v-if="spriteMeta"
          type="success"
          :closable="false"
          :title="`已生成 ${spriteMeta.count} 张缩略图 · 间隔 ${spriteMeta.interval}s · 尺寸 ${spriteMeta.thumb_width}x${spriteMeta.thumb_height}`"
          style="margin-bottom: 12px"
        />
        <div v-if="spriteMeta?.sprite_url" class="sprite-preview">
          <img :src="spriteMeta.sprite_url" alt="精灵图预览" />
        </div>
        <el-empty v-else description="未生成精灵图，点击上方按钮生成" :image-size="60" />
      </el-tab-pane>

      <!-- 截图时间轴（Phase 2.2 §1） -->
      <el-tab-pane label="截图时间轴" name="timeline">
        <div class="tab-toolbar">
          <el-button size="small" @click="loadTimelineThumbs" :loading="loadingTimeline">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
          <span class="muted timeline-hint" v-if="timelineThumbs.length">
            共 {{ timelineThumbs.length }} 张截图 · 点击缩略图跳转播放位置
          </span>
        </div>
        <div v-if="timelineThumbs.length" class="timeline-strip">
          <div
            v-for="(t, idx) in timelineThumbs"
            :key="idx"
            class="timeline-thumb"
            :class="{ active: timelineCurrent === idx }"
            :title="formatTime(t.time)"
            @click="seekTo(t.time)"
          >
            <img :src="t.url" :alt="`截图 ${idx + 1}`" loading="lazy" />
            <span class="timeline-time">{{ formatTime(t.time) }}</span>
          </div>
        </div>
        <EmptyState
          v-else
          type="no-data"
          description="暂无视频截图，可点击「刷新」加载或先生成精灵图"
          inline
        />
      </el-tab-pane>

      <!-- 字段来源精选（v3.1 §7.5） -->
      <el-tab-pane label="字段来源" name="source-merge">
        <div class="tab-toolbar">
          <el-button size="small" @click="loadFieldSources" :loading="loadingFields">
            <el-icon><Refresh /></el-icon> 刷新字段
          </el-button>
          <el-select
            v-model="previewSource"
            placeholder="选择来源预览"
            size="small"
            style="width: 160px; margin-left: 12px"
            :disabled="!availableSources.length"
          >
            <el-option v-for="s in availableSources" :key="s" :label="s" :value="s" />
          </el-select>
          <el-button
            size="small"
            type="primary"
            @click="previewScrape"
            :loading="previewing"
            :disabled="!previewSource"
            style="margin-left: 8px"
          >
            <el-icon><MagicStick /></el-icon> 预览刮削
          </el-button>
          <el-button
            size="small"
            type="success"
            @click="applyFieldMerge"
            :loading="applying"
            :disabled="!fieldRows.length"
            style="margin-left: auto"
          >
            <el-icon><Check /></el-icon> 应用选中字段
          </el-button>
        </div>

        <el-alert
          v-if="fieldRows.length"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
          title="勾选要应用的字段，点击「应用选中字段」将所选值写入数据库。预览刮削不会写入，可对比后再应用。"
        />

        <el-table
          v-if="fieldRows.length"
          :data="fieldRows"
          border
          size="small"
          @selection-change="onSelectionChange"
        >
          <el-table-column type="selection" width="40" />
          <el-table-column label="字段" prop="label" width="140" />
          <el-table-column label="当前值">
            <template #default="{ row }">
              <span class="field-current">{{ formatFieldValue(row.value) }}</span>
              <el-tag v-if="row.source" size="small" type="info" style="margin-left: 6px">{{ row.source }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="预览值">
            <template #default="{ row }">
              <span v-if="row.preview !== null && row.preview !== undefined" class="field-preview">
                {{ formatFieldValue(row.preview) }}
              </span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button
                v-if="row.preview !== null && row.preview !== undefined && row.preview !== row.value"
                text
                size="small"
                type="primary"
                @click="applySingleField(row)"
              >
                应用
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="点击「刷新字段」加载当前影片字段及来源" :image-size="60" />
      </el-tab-pane>

      <!-- 元数据来源可视化对比（Phase 2.2 §2） -->
      <el-tab-pane label="来源对比" name="source-compare">
        <div class="tab-toolbar">
          <el-button size="small" @click="loadSourceCompare" :loading="loadingCompare">
            <el-icon><Refresh /></el-icon> 刷新对比
          </el-button>
          <el-select
            v-model="compareFields"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择对比字段"
            size="small"
            style="width: 280px; margin-left: 12px"
          >
            <el-option
              v-for="f in COMPARE_FIELDS"
              :key="f.key"
              :label="f.label"
              :value="f.key"
            />
          </el-select>
        </div>

        <el-alert
          v-if="sourceCompareData.length"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
          title="各爬虫来源（JavDB / JavBus 等）字段差异对比，相同值以同色背景标识，空值以「-」表示。"
        />

        <el-table
          v-if="sourceCompareData.length"
          :data="sourceCompareRows"
          border
          size="small"
          :row-class-name="compareRowClass"
        >
          <el-table-column label="字段" prop="label" width="140" fixed />
          <el-table-column
            v-for="src in sourceCompareData"
            :key="src.source"
            :label="src.source"
            min-width="180"
          >
            <template #default="{ row }">
              <span v-if="row.values[src.source] != null && row.values[src.source] !== ''">
                {{ formatFieldValue(row.values[src.source]) }}
              </span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState
          v-else
          type="no-data"
          description="暂无来源对比数据，点击「刷新对比」加载各爬虫来源字段"
          inline
        />
      </el-tab-pane>

      <!-- Fanart 背景图（v4.1 C1） -->
      <el-tab-pane label="Fanart 背景" name="fanart">
        <div class="tab-toolbar">
          <el-button size="small" @click="loadFanarts" :loading="fanartLoading">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
          <el-button size="small" type="primary" @click="searchFanartsOnline" :loading="fanartSearching">
            <el-icon><Search /></el-icon> 在线搜索
          </el-button>
          <el-button
            size="small"
            type="success"
            @click="downloadFanartBackground"
            :loading="fanartDownloading"
            :disabled="!movie.tmdb_id && !fanartSearchResult"
          >
            <el-icon><Download /></el-icon> 下载并应用为背景
          </el-button>
          <div class="fanart-tmdb-input">
            <span class="muted">TMDB ID:</span>
            <el-input-number
              v-model="tmdbIdInput"
              :min="1"
              :controls="false"
              size="small"
              style="width: 120px"
              placeholder="未设置"
            />
            <el-button size="small" @click="saveTmdbId" :loading="savingTmdbId">保存</el-button>
          </div>
        </div>

        <el-alert
          v-if="!movie.tmdb_id"
          type="info"
          :closable="false"
          title="尚未设置 TMDB ID"
          description="fanart.tv 基于 TMDB ID 查询影片背景图。请先在上方输入 TMDB ID 并保存，然后点击「在线搜索」。"
          style="margin-bottom: 12px"
        />

        <!-- 已下载的背景图 -->
        <div v-if="fanartImages && fanartImages.length" class="fanart-grid">
          <div v-for="(img, idx) in fanartImages" :key="idx" class="fanart-item">
            <img :src="img.url" :alt="`Fanart ${idx + 1}`" loading="lazy" @error="onFanartImgError" />
            <div class="fanart-meta">
              <span>{{ img.type || 'background' }}</span>
              <span v-if="img.likes" class="muted">♥ {{ img.likes }}</span>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无已下载的背景图" :image-size="60" />

        <!-- 在线搜索结果 -->
        <div v-if="fanartSearchResult" class="fanart-search-result">
          <h4>在线搜索结果</h4>
          <div v-if="fanartSearchResult.moviebackground && fanartSearchResult.moviebackground.length" class="fanart-grid">
            <div v-for="(img, idx) in fanartSearchResult.moviebackground" :key="`bg-${idx}`" class="fanart-item">
              <img :src="img.url" :alt="`背景 ${idx + 1}`" loading="lazy" @error="onFanartImgError" />
              <div class="fanart-meta">
                <span>background</span>
                <span v-if="img.likes" class="muted">♥ {{ img.likes }}</span>
              </div>
            </div>
          </div>
          <div v-if="fanartSearchResult.movieposter && fanartSearchResult.movieposter.length" class="fanart-poster-row">
            <h5>海报（{{ fanartSearchResult.movieposter.length }}）</h5>
            <div class="poster-strip">
              <img
                v-for="(img, idx) in fanartSearchResult.movieposter"
                :key="`p-${idx}`"
                :src="img.url"
                :alt="`海报 ${idx + 1}`"
                class="poster-thumb"
                loading="lazy"
                @error="onFanartImgError"
              />
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-empty v-if="!movie && !loading" description="加载失败" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  VideoPlay, Monitor, Star, Flag, Picture, Refresh, MagicStick, Grid, Delete, Check, Search, Download
} from '@element-plus/icons-vue'
import Artplayer from 'artplayer'
import Hls from 'hls.js'
import {
  getMovie, getMoviePlayUrl, playWithMpv as mpvPlay, updateMovie,
  getPlayerConfig, listChapters, addChapter, updateChapter, deleteChapter,
  autoDetectChapters, generateChapterThumbnails,
  listGifs, generateGif, deleteGif,
  listSubtitles,
  getThumbnailSprite, generateThumbnailSprite,
  getSourceMergeFields, previewSourceScrape, applySourceMerge,
  getHlsQualities,
  // fanart.tv 集成 (v4.1 C1)
  getMovieFanarts, searchFanarts as searchFanartsApi, downloadMovieFanart, updateMovieTmdbId
} from '@/api'
import EmptyState from '@/components/EmptyState.vue'
import { getServerBaseUrl, getSubtitleFileUrl } from '@/utils/media'

const route = useRoute()
const router = useRouter()
const artplayerRef = ref(null)
let art = null
let hls = null

const movie = ref(null)
const loading = ref(false)
const currentProtocol = ref('http')
const activeTab = ref('chapters')

// 评分
const hoverRating = ref(0)
const tempRating = ref(null)
const ratingInput = ref(0)
const savingRating = ref(false)

// ===== 详情元数据（NFO 字段展示）=====
// genre 后端返回的是 JSON 字符串（如 '["剧情","爱情"]'）或逗号分隔文本，统一解析为数组
const genreList = computed(() => {
  const g = movie.value?.genre
  if (!g) return []
  try {
    const parsed = JSON.parse(g)
    if (Array.isArray(parsed)) return parsed.map(String)
  } catch (e) { /* 非 JSON，走下方文本拆分 */ }
  return String(g).split(/[,，]/).map(s => s.trim()).filter(Boolean)
})
const actorList = computed(() => movie.value?.actors || [])
const goActorDetail = (id) => {
  if (id) router.push(`/actors/${id}`)
}

// 章节
const chapters = ref([])
const autoDetecting = ref(false)
const generatingThumbs = ref(false)

// GIF
const gifs = ref([])
const generatingGif = ref(false)
const gifForm = reactive({ duration: 3.0, width: 480, fps: 12 })

// 字幕
const subtitles = ref({ embedded: [], external: [] })

// 缩略图进度条
const spriteMeta = ref(null)
const generatingSprite = ref(false)
const spriteForm = reactive({ interval: 30, cols: 10 })

// v3.5: 音轨切换 + HLS 自适应画质
const audioTracks = ref([])
const hlsQualities = ref([])
const adaptiveMode = ref(false)

// ===== 字段来源精选（§7.5）=====
const loadingFields = ref(false)
const fieldRows = ref([])
const availableSources = ref([])
const previewSource = ref('')
const previewing = ref(false)
const applying = ref(false)
const selectedFields = ref([])

// 字段中文名映射
const FIELD_LABELS = {
  title: '标题',
  plot: '简介',
  plot_short: '简短简介',
  release_date: '发行日期',
  runtime: '时长',
  director: '导演',
  studio: '制作商',
  series: '系列',
  code: '番号',
  genre: '标签',
  actors: '演员',
  cover_url: '封面',
  poster_url: '海报',
  trailer_url: '预告片',
  is_uncensored: '是否无码',
}

// ===== 截图时间轴（Phase 2.2 §1）=====
const timelineThumbs = ref([])
const loadingTimeline = ref(false)
const timelineCurrent = ref(-1)

// 从已生成的精灵图或 sample_images 构建时间轴
const loadTimelineThumbs = async () => {
  loadingTimeline.value = true
  try {
    // 优先从精灵图元数据生成（含时间戳）
    if (spriteMeta.value?.thumbs?.length) {
      timelineThumbs.value = spriteMeta.value.thumbs.map((t, i) => ({
        url: t.url || t,
        time: t.time ?? (spriteMeta.value.interval || 30) * (i + 1),
      }))
      return
    }
    // 兜底：使用影片的 sample_images（无精确时间戳，按平均分布推算）
    const samples = movie.value?.sample_images || []
    const duration = movie.value?.duration || 0
    if (samples.length && duration) {
      const step = duration * 60 / samples.length
      timelineThumbs.value = samples.map((url, i) => ({
        url,
        time: Math.round(step * (i + 0.5)),
      }))
      return
    }
    // 都没有则空
    timelineThumbs.value = []
  } catch (e) {
    timelineThumbs.value = []
  } finally {
    loadingTimeline.value = false
  }
}

// ===== Fanart 背景图集成（v4.1 C1）=====
const fanartLoading = ref(false)
const fanartSearching = ref(false)
const fanartDownloading = ref(false)
const fanartImages = ref([])        // 已下载的背景图列表
const fanartSearchResult = ref(null) // 在线搜索结果
const tmdbIdInput = ref(null)
const savingTmdbId = ref(false)

const loadFanarts = async () => {
  if (!movie.value?.id) return
  fanartLoading.value = true
  try {
    const data = await getMovieFanarts(movie.value.id)
    fanartImages.value = data?.images || []
    if (data?.tmdb_id) tmdbIdInput.value = data.tmdb_id
  } catch (e) {
    fanartImages.value = []
    const msg = e?.response?.data?.detail || e?.message || '加载失败'
    ElMessage.warning(`加载 Fanart 失败: ${msg}`)
  } finally {
    fanartLoading.value = false
  }
}

const searchFanartsOnline = async () => {
  const tmdbId = movie.value?.tmdb_id || tmdbIdInput.value
  if (!tmdbId) {
    ElMessage.warning('请先设置 TMDB ID 并保存')
    return
  }
  fanartSearching.value = true
  try {
    const data = await searchFanartsApi(tmdbId)
    fanartSearchResult.value = data
    ElMessage.success(`搜索完成: ${data?.name || 'TMDB-' + tmdbId}`)
  } catch (e) {
    fanartSearchResult.value = null
    const msg = e?.response?.data?.detail || e?.message || '搜索失败'
    ElMessage.error(`Fanart 搜索失败: ${msg}`)
  } finally {
    fanartSearching.value = false
  }
}

const downloadFanartBackground = async () => {
  if (!movie.value?.id) return
  fanartDownloading.value = true
  try {
    const data = await downloadMovieFanart(movie.value.id)
    ElMessage.success(`已应用背景图: ${data?.image_url || '完成'}`)
    // 重新加载已下载列表
    await loadFanarts()
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '下载失败'
    ElMessage.error(`下载 Fanart 失败: ${msg}`)
  } finally {
    fanartDownloading.value = false
  }
}

const saveTmdbId = async () => {
  if (!movie.value?.id) return
  if (!tmdbIdInput.value) {
    ElMessage.warning('请输入 TMDB ID')
    return
  }
  savingTmdbId.value = true
  try {
    await updateMovieTmdbId(movie.value.id, tmdbIdInput.value)
    movie.value.tmdb_id = tmdbIdInput.value
    ElMessage.success('TMDB ID 已保存')
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '保存失败'
    ElMessage.error(`保存失败: ${msg}`)
  } finally {
    savingTmdbId.value = false
  }
}

const onFanartImgError = (e) => {
  if (e?.target) e.target.style.display = 'none'
}

// ===== 双击复制（v4.1 C6）=====
const copyToClipboard = async (text, label) => {
  if (!text) return
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      // 兜底方案：使用临时 textarea
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    ElMessage.success(`已复制${label}: ${text}`)
  } catch (e) {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

const copyCode = () => copyToClipboard(movie.value?.code, '番号')
const copyTitle = () => copyToClipboard(movie.value?.title, '标题')

// ===== 元数据来源可视化对比（Phase 2.2 §2）=====
const loadingCompare = ref(false)
const sourceCompareData = ref([]) // [{ source: 'JavDB', fields: { title, plot, ... } }, ...]
const compareFields = ref([])

// 可对比字段定义（复用 FIELD_LABELS）
const COMPARE_FIELDS = [
  { key: 'title', label: '标题' },
  { key: 'plot', label: '简介' },
  { key: 'release_date', label: '发行日期' },
  { key: 'runtime', label: '时长' },
  { key: 'director', label: '导演' },
  { key: 'studio', label: '制作商' },
  { key: 'series', label: '系列' },
  { key: 'code', label: '番号' },
  { key: 'actors', label: '演员' },
  { key: 'cover_url', label: '封面' },
  { key: 'is_uncensored', label: '是否无码' },
]

// 默认对比字段（首次加载为空时使用）
const DEFAULT_COMPARE_FIELDS = ['title', 'release_date', 'director', 'studio', 'actors', 'cover_url']

const loadSourceCompare = async () => {
  loadingCompare.value = true
  try {
    // 复用字段来源接口（getSourceMergeFields）提取各来源原始数据
    const data = await getSourceMergeFields(route.params.id)
    // data.sources 期望结构：[{ source, fields: { ... } }]
    const sources = data?.sources || data?.items || []
    sourceCompareData.value = sources.map(s => ({
      source: s.source || s.name || '未知来源',
      fields: s.fields || s.values || {},
    }))
    // 首次加载默认选中字段
    if (!compareFields.value.length) {
      compareFields.value = [...DEFAULT_COMPARE_FIELDS]
    }
  } catch (e) {
    // 接口未提供多来源明细时，使用当前影片作为单一来源展示
    if (movie.value) {
      sourceCompareData.value = [{
        source: movie.value.source || '本地',
        fields: { ...movie.value },
      }]
      if (!compareFields.value.length) {
        compareFields.value = [...DEFAULT_COMPARE_FIELDS]
      }
    } else {
      sourceCompareData.value = []
    }
  } finally {
    loadingCompare.value = false
  }
}

// 对比表格行数据：根据选中字段生成
const sourceCompareRows = computed(() => {
  const fields = compareFields.value.length ? compareFields.value : DEFAULT_COMPARE_FIELDS
  return fields.map(key => {
    const label = FIELD_LABELS[key] || key
    const values = {}
    for (const src of sourceCompareData.value) {
      values[src.source] = src.fields?.[key] ?? ''
    }
    return { key, label, values }
  })
})

// 行高亮：所有来源值一致（无差异）时标记为相同
const compareRowClass = ({ row }) => {
  const vals = Object.values(row.values).filter(v => v !== '' && v != null)
  if (vals.length <= 1) return ''
  const allSame = vals.every(v => String(v) === String(vals[0]))
  return allSame ? 'compare-row-same' : ''
}

// ===== Artplayer 初始化 =====

// v3.5: 构建播放器设置菜单（章节/音轨/画质）
const buildArtSettings = () => {
  const items = []
  // 章节
  if (chapters.value.length) {
    items.push({
      html: '章节',
      tooltip: '显示章节列表',
      selector: chapters.value.map(c => ({
        html: `${formatTime(c.start)} - ${c.title}`,
        time: c.start,
      })),
      onSelect(item) {
        art.currentTime = item.time
        return item.html
      }
    })
  }
  // 音轨切换
  if (audioTracks.value.length > 1) {
    items.push({
      html: '音轨',
      tooltip: '切换音轨',
      selector: audioTracks.value.map(t => ({
        html: t.label || `音轨 ${t.index + 1}`,
        value: t.index,
        default: !!t.default,
      })),
      onSelect(item) {
        switchAudioTrack(item.value)
        return item.html
      }
    })
  }
  // 画质切换（HLS 自适应码率）
  if (hlsQualities.value.length) {
    items.push({
      html: '画质',
      tooltip: '自适应码率',
      selector: [
        { html: '自动', value: -1, default: true },
        ...hlsQualities.value.map((q, i) => ({
          html: q.label || `${q.height}p`,
          value: i,
        })),
      ],
      onSelect(item) {
        switchQuality(item.value)
        return item.html
      }
    })
  }
  return items
}

// v3.5: 切换音轨
const switchAudioTrack = (trackIndex) => {
  if (!art) return
  const video = art.video
  if (hls) {
    try { hls.audioTrack = trackIndex } catch (e) { console.warn('音轨切换失败:', e) }
  } else if (video && video.audioTracks && video.audioTracks.length) {
    for (let i = 0; i < video.audioTracks.length; i++) {
      video.audioTracks[i].enabled = i === trackIndex
    }
  } else {
    ElMessage.warning('当前浏览器或播放模式不支持音轨切换，建议使用 HLS 模式')
  }
}

// v3.5: 切换画质（HLS 自适应码率）
const switchQuality = (levelIndex) => {
  if (!hls) {
    ElMessage.warning('画质切换仅支持 HLS 自适应码率模式')
    return
  }
  hls.currentLevel = levelIndex
}

// v3.5: 切换自适应码率模式
const toggleAdaptive = async () => {
  if (!hlsQualities.value.length) {
    ElMessage.warning('当前影片不支持自适应码率')
    return
  }
  adaptiveMode.value = !adaptiveMode.value
  if (adaptiveMode.value) {
    ElMessage.success('已开启自适应码率，正在加载多画质 HLS...')
  } else {
    ElMessage.info('已关闭自适应码率')
  }
  await loadVideo()
}

const initArtplayer = (videoUrl) => {
  if (art) {
    art.destroy(false)
    art = null
  }
  if (hls) {
    hls.destroy()
    hls = null
  }

  const isHls = videoUrl.includes('/hls/') || videoUrl.endsWith('.m3u8')

  art = new Artplayer({
    container: artplayerRef.value,
    url: videoUrl,
    type: isHls ? 'm3u8' : 'video',
    customType: {
      m3u8: (video, url) => {
        if (Hls.isSupported()) {
          if (hls) hls.destroy()
          hls = new Hls()
          hls.loadSource(url)
          hls.attachMedia(video)
        } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
          video.src = url
        }
      }
    },
    volume: 0.7,
    autoplay: false,
    autoSize: false,
    autoMini: false,
    screenshot: true,
    setting: true,
    loop: false,
    flip: true,
    playbackRate: true,
    aspectRatio: true,
    fullscreen: true,
    fullscreenWeb: true,
    subtitleOffset: true,
    miniProgressBar: true,
    mutex: true,
    backdrop: true,
    playsInline: true,
    autoPlayback: true,
    airplay: true,
    theme: '#2396ef',
    lang: 'zh-cn',
    moreVideoAttr: {
      crossOrigin: 'anonymous',
      preload: 'auto',
    },
    settings: buildArtSettings(),

    contextmenu: [
      {
        html: '标记此刻为章节',
        click() {
          markChapter()
        }
      },
      {
        html: '生成 GIF（3 秒）',
        click() {
          generateGifHere()
        }
      }
    ],
    controls: [
      {
        name: 'mark-chapter',
        position: 'right',
        html: '<i class="art-icon">📍</i>',
        tooltip: '标记此刻',
        click() {
          markChapter()
        }
      }
    ]
  })

  // 加载缩略图进度条 VTT
  if (spriteMeta.value?.vtt_url) {
    loadThumbnailSpriteVtt(spriteMeta.value.vtt_url)
  }

  art.on('ready', () => {
    console.log('Artplayer ready')
  })
}

const loadThumbnailSpriteVtt = (vttUrl) => {
  if (!art) return
  // Artplayer 5 支持 thumbnail 配置（需 artplayer-plugin-thumbnail 或直接用 VTT）
  // 这里通过自定义控件实现简易预览
  fetch(vttUrl).then(r => r.text()).then(vtt => {
    const cues = parseVtt(vtt)
    art.template.ingestedThumbnailCues = cues
  }).catch(() => {})
}

const parseVtt = (vtt) => {
  const cues = []
  const lines = vtt.split('\n')
  let current = null
  for (const line of lines) {
    const m = line.match(/(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})/)
    if (m) {
      current = { start: parseTimestamp(m[1]), end: parseTimestamp(m[2]) }
    } else if (current && line.includes('#xywh=')) {
      const xywh = line.match(/#xywh=(\d+),(\d+),(\d+),(\d+)/)
      if (xywh) {
        current.x = parseInt(xywh[1])
        current.y = parseInt(xywh[2])
        current.w = parseInt(xywh[3])
        current.h = parseInt(xywh[4])
        cues.push(current)
      }
    }
  }
  return cues
}

const parseTimestamp = (ts) => {
  const [h, m, s] = ts.split(':')
  return parseFloat(h) * 3600 + parseFloat(m) * 60 + parseFloat(s)
}

// ===== 数据加载 =====
const loadMovie = async () => {
  loading.value = true
  try {
    const id = route.params.id
    movie.value = await getMovie(id)
    ratingInput.value = Number(movie.value.rating) || 0

    // 一次性获取播放器配置
    try {
      const cfg = await getPlayerConfig(id)
      chapters.value = cfg.chapters || []
      gifs.value = cfg.gifs || []
      subtitles.value = cfg.subtitles || { embedded: [], external: [] }
      spriteMeta.value = cfg.thumbnail_sprite || null
      // v3.5: 音轨列表
      audioTracks.value = cfg.audio_tracks || []
    } catch (e) {
      console.warn('getPlayerConfig failed', e)
    }

    // v3.5: 加载 HLS 自适应画质列表
    try {
      const qRes = await getHlsQualities(id)
      hlsQualities.value = qRes.items || []
    } catch (e) {
      console.warn('getHlsQualities failed', e)
    }

    // v4.1 C1: 初始化 TMDB ID 输入框，并尝试加载已下载的 Fanart
    if (movie.value.tmdb_id) {
      tmdbIdInput.value = movie.value.tmdb_id
    }

    if (movie.value.file_path) {
      await loadVideo()
    }
  } catch (e) {
    console.error(e)
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

const loadVideo = async () => {
  if (!movie.value?.file_path) {
    ElMessage.warning('该影片没有关联文件')
    return
  }

  try {
    // v3.5: 自适应码率模式使用 master.m3u8
    let videoUrl
    if (adaptiveMode.value) {
      const base = getServerBaseUrl()
      videoUrl = `${base}/api/v1/movies/${route.params.id}/hls/master.m3u8`
    } else {
      const res = await getMoviePlayUrl(route.params.id, currentProtocol.value)
      videoUrl = res.play_url
    }
    await nextTick()
    initArtplayer(videoUrl)
  } catch (e) {
    console.error(e)
  }
}

const changeProtocol = async (protocol) => {
  currentProtocol.value = protocol
  await loadVideo()
}

const openExternal = async (protocol) => {
  try {
    const res = await getMoviePlayUrl(route.params.id, protocol)
    window.open(res.play_url, '_blank')
  } catch (e) {
    ElMessage.error('获取播放地址失败')
  }
}

const playWithMpv = async () => {
  try {
    const res = await mpvPlay(route.params.id)
    const data = res.items ? res : (res.data || res)
    if (data.status === 'ok') {
      ElMessage.success(`mpv 已启动 (PID: ${data.pid})`)
    } else {
      ElMessage.error(data.message || '启动 mpv 失败')
    }
  } catch (e) {
    const msg = e.response?.data?.detail || '启动 mpv 失败'
    ElMessage.error(msg)
  }
}

// ===== 评分 =====
const setRating = (i) => { tempRating.value = i; ratingInput.value = i }
const onRatingInput = (val) => {
  if (val == null) tempRating.value = 0
  else tempRating.value = Math.max(0, Math.min(10, Number(val)))
}
const saveRating = async () => {
  if (!movie.value || tempRating.value === null) return
  savingRating.value = true
  try {
    await updateMovie(movie.value.id, { rating: tempRating.value })
    movie.value.rating = tempRating.value
    tempRating.value = null
    ElMessage.success('评分已保存')
  } catch (e) {
    ElMessage.error('评分保存失败')
  } finally {
    savingRating.value = false
  }
}
const cancelRating = () => {
  tempRating.value = null
  ratingInput.value = Number(movie.value.rating) || 0
}
const clearRating = async () => {
  if (!movie.value) return
  savingRating.value = true
  try {
    await updateMovie(movie.value.id, { rating: null })
    movie.value.rating = null
    tempRating.value = null
    ratingInput.value = 0
    ElMessage.success('已清除评分')
  } catch (e) {
    ElMessage.error('清除失败')
  } finally {
    savingRating.value = false
  }
}

// ===== 章节 =====
const loadChapters = async () => {
  try {
    const res = await listChapters(route.params.id)
    chapters.value = res.items || []
  } catch (e) {}
}

const markChapter = async () => {
  if (!art) return
  const t = art.currentTime
  try {
    const res = await addChapter(route.params.id, { start: t })
    chapters.value.push(res)
    chapters.value.sort((a, b) => a.start - b.start)
    ElMessage.success(`已标记章节 @ ${formatTime(t)}`)
  } catch (e) {
    ElMessage.error('标记失败')
  }
}

const removeChapter = async (id) => {
  try {
    await deleteChapter(route.params.id, id)
    chapters.value = chapters.value.filter(c => c.id !== id)
    ElMessage.success('已删除')
  } catch (e) {}
}

const editChapter = async (row) => {
  try {
    const { value } = await ElMessageBox.prompt('章节标题', '编辑章节', {
      inputValue: row.title, inputPattern: /.+/, inputErrorMessage: '标题不能为空'
    })
    await updateChapter(route.params.id, row.id, { title: value })
    row.title = value
    ElMessage.success('已更新')
  } catch (e) {}
}

const detectChapters = async () => {
  autoDetecting.value = true
  try {
    const res = await autoDetectChapters(route.params.id, { threshold: 0.4, min_duration: 10 })
    chapters.value = res.chapters || []
    ElMessage.success(`检测完成：新增 ${res.added} 个章节`)
  } catch (e) {
    ElMessage.error('检测失败')
  } finally {
    autoDetecting.value = false
  }
}

const genChapterThumbs = async () => {
  generatingThumbs.value = true
  try {
    const res = await generateChapterThumbnails(route.params.id)
    chapters.value = res.chapters || chapters.value
    ElMessage.success(`生成 ${res.updated} 张缩略图`)
  } catch (e) {
    ElMessage.error('生成失败')
  } finally {
    generatingThumbs.value = false
  }
}

const seekTo = (t) => {
  if (art) art.currentTime = t
}

// ===== GIF =====
const loadGifs = async () => {
  try {
    const res = await listGifs(route.params.id)
    gifs.value = res.items || []
  } catch (e) {}
}

const generateGifHere = async () => {
  if (!art) return
  const t = art.currentTime
  generatingGif.value = true
  try {
    const res = await generateGif(route.params.id, {
      start: t,
      duration: gifForm.duration,
      width: gifForm.width,
      fps: gifForm.fps
    })
    gifs.value.unshift(res)
    ElMessage.success(`GIF 已生成 (${formatSize(res.file_size)})`)
  } catch (e) {
    ElMessage.error('GIF 生成失败')
  } finally {
    generatingGif.value = false
  }
}

const removeGif = async (filename) => {
  try {
    await ElMessageBox.confirm('确认删除该 GIF？', '提示', { type: 'warning' })
  } catch { return }
  try {
    await deleteGif(route.params.id, filename)
    gifs.value = gifs.value.filter(g => g.file_name !== filename)
    ElMessage.success('已删除')
  } catch (e) {}
}

// ===== 字幕 =====
const loadSubtitles = async () => {
  try {
    const res = await listSubtitles(route.params.id)
    subtitles.value = res
  } catch (e) {}
}

const loadExternalSubtitle = (sub) => {
  if (!art) return
  // 通过 URL 加载外挂字幕(使用工具函数统一 base URL)
  const subtitleUrl = getSubtitleFileUrl(route.params.id, sub.path)
  // Artplayer 5 用 art.subtitle.init 加载
  art.subtitle = {
    url: subtitleUrl,
    type: sub.ext === '.vtt' ? 'vtt' : 'srt',
    encoding: 'utf-8',
    style: { color: '#fff' },
  }
  ElMessage.success(`已加载字幕：${sub.filename}`)
}

// ===== 缩略图进度条 =====
const loadSprite = async () => {
  try {
    spriteMeta.value = await getThumbnailSprite(route.params.id)
  } catch (e) {
    spriteMeta.value = null
  }
}

const generateSprite = async () => {
  generatingSprite.value = true
  try {
    spriteMeta.value = await generateThumbnailSprite(route.params.id, {
      interval: spriteForm.interval,
      cols: spriteForm.cols
    })
    ElMessage.success('精灵图生成完成')
  } catch (e) {
    ElMessage.error('生成失败')
  } finally {
    generatingSprite.value = false
  }
}

// ===== 字段来源精选方法（§7.5）=====
const loadFieldSources = async () => {
  if (!movie.value?.id) {
    ElMessage.warning('请先加载影片')
    return
  }
  loadingFields.value = true
  try {
    const res = await getSourceMergeFields(movie.value.id)
    // 期望返回 { fields: [{key, value, source}], sources: [...] }
    const fields = res.fields || res.items || []
    const sources = res.sources || res.available_sources || []
    availableSources.value = sources
    fieldRows.value = fields.map(f => ({
      key: f.key,
      label: FIELD_LABELS[f.key] || f.key,
      value: f.value,
      source: f.source || '',
      preview: null,
    }))
    if (fieldRows.value.length === 0) {
      ElMessage.info('暂无字段来源数据，可先执行预览刮削')
    }
  } catch (e) {
    const msg = e.response?.data?.detail || '加载字段来源失败'
    ElMessage.error(msg)
  } finally {
    loadingFields.value = false
  }
}

const previewScrape = async () => {
  if (!movie.value?.id || !previewSource.value) {
    ElMessage.warning('请先选择来源')
    return
  }
  previewing.value = true
  try {
    const res = await previewSourceScrape(movie.value.id, previewSource.value)
    // 期望返回 { fields: [{key, preview}] }
    const items = res.fields || res.items || []
    const previewMap = {}
    items.forEach(f => { previewMap[f.key] = f.preview ?? f.value })
    fieldRows.value = fieldRows.value.map(row => ({
      ...row,
      preview: previewMap.hasOwnProperty(row.key) ? previewMap[row.key] : row.value,
    }))
    ElMessage.success(`已预览 ${items.length} 个字段（来源：${previewSource.value}）`)
  } catch (e) {
    const msg = e.response?.data?.detail || '预览刮削失败'
    ElMessage.error(msg)
  } finally {
    previewing.value = false
  }
}

const applyFieldMerge = async () => {
  if (!movie.value?.id || !selectedFields.value.length) {
    ElMessage.warning('请勾选要应用的字段')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将应用 ${selectedFields.value.length} 个字段到当前影片，是否继续？`,
      '应用字段确认',
      { type: 'warning' }
    )
  } catch { return }

  applying.value = true
  try {
    // 仅应用预览值与当前值不同的字段
    const fields = selectedFields.value
      .filter(r => r.preview !== null && r.preview !== undefined && r.preview !== r.value)
      .map(r => ({ key: r.key, value: r.preview }))
    if (!fields.length) {
      ElMessage.info('所选字段无变更')
      return
    }
    const res = await applySourceMerge(movie.value.id, fields)
    // 更新本地状态
    fields.forEach(f => {
      const row = fieldRows.value.find(r => r.key === f.key)
      if (row) {
        row.value = f.value
        row.source = previewSource.value
      }
      // 同步到 movie.value
      if (movie.value && movie.value.hasOwnProperty(f.key)) {
        movie.value[f.key] = f.value
      }
    })
    ElMessage.success(res.message || `已应用 ${fields.length} 个字段`)
  } catch (e) {
    const msg = e.response?.data?.detail || '应用字段失败'
    ElMessage.error(msg)
  } finally {
    applying.value = false
  }
}

const applySingleField = async (row) => {
  if (!movie.value?.id || row.preview == null) return
  applying.value = true
  try {
    await applySourceMerge(movie.value.id, [{ key: row.key, value: row.preview }])
    row.value = row.preview
    row.source = previewSource.value
    if (movie.value && movie.value.hasOwnProperty(row.key)) {
      movie.value[row.key] = row.preview
    }
    ElMessage.success(`已应用字段：${row.label}`)
  } catch (e) {
    const msg = e.response?.data?.detail || '应用字段失败'
    ElMessage.error(msg)
  } finally {
    applying.value = false
  }
}

const onSelectionChange = (selection) => {
  selectedFields.value = selection
}

const formatFieldValue = (val) => {
  if (val === null || val === undefined || val === '') return '—'
  if (Array.isArray(val)) return val.join(', ')
  if (typeof val === 'object') {
    try { return JSON.stringify(val) } catch { return String(val) }
  }
  if (typeof val === 'boolean') return val ? '是' : '否'
  return String(val)
}

// ===== 工具函数 =====
const formatTime = (sec) => {
  if (sec == null) return '-'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const formatSize = (bytes) => {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

const sourceLabel = (s) => ({
  same_dir: '同目录',
  sibling: '同目录(番号)',
  subdir: '子目录',
  library: '字幕库'
})[s] || s

onMounted(() => {
  loadMovie()

  // 监听全局快捷键事件（mpv 播放/暂停/截图）
  window.addEventListener('mdcx-mpv-toggle', onMpvToggle)
  window.addEventListener('mdcx-mpv-screenshot', onMpvScreenshot)
})

const onMpvToggle = () => {
  if (art) art.toggle()
}
const onMpvScreenshot = () => {
  if (art) art.screenshot()
}

onUnmounted(() => {
  if (art) art.destroy(false)
  if (hls) hls.destroy()
  window.removeEventListener('mdcx-mpv-toggle', onMpvToggle)
  window.removeEventListener('mdcx-mpv-screenshot', onMpvScreenshot)
})
</script>

<style scoped>
.play {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.player-container {
  background: #000;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
}

.artplayer-box {
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: 70vh;
}

.no-file {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.player-info {
  background: var(--bg-card, #fff);
  padding: 20px;
  border-radius: 8px;
  border: 1px solid var(--border-light, #ebeef5);
}

.info-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.movie-code {
  font-size: 24px;
  font-weight: bold;
  color: var(--primary-color, #409eff);
}

.info-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.movie-title {
  font-size: 18px;
  margin-top: 10px;
  color: var(--text-primary, #303133);
}

.movie-detail {
  margin-top: 12px;
}

.detail-plot {
  margin: 0 0 14px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-regular, #606266);
  white-space: pre-wrap;
  background: var(--bg-page, #f5f7fa);
  border-radius: 6px;
  padding: 12px 14px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px 24px;
}

.detail-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
  min-width: 0;
}

.detail-item--full {
  grid-column: 1 / -1;
}

.detail-label {
  flex: 0 0 auto;
  color: var(--text-secondary, #909399);
  font-weight: 600;
}

.detail-value {
  color: var(--text-primary, #303133);
  word-break: break-word;
}

.chip-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.actor-chip {
  cursor: pointer;
  transition: all 0.15s;
}

.actor-chip:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

.rating-block {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-light, #ebeef5);
}

.rating-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-regular, #606266);
  margin-bottom: 8px;
}

.rating-stars {
  display: flex;
  gap: 4px;
  font-size: 24px;
  margin-bottom: 8px;
  cursor: pointer;
}

.star {
  color: #dcdfe6;
  transition: color 0.15s;
}

.star.filled {
  color: #f7ba2a;
}

.star.half {
  position: relative;
  color: #dcdfe6;
}

.star.half::before {
  content: '';
  position: absolute;
  inset: 0 50% 0 0;
  background: #f7ba2a;
  -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1024 1024'><path d='M908.1 353.1l-253.9-36.9L540.7 86.1c-3.1-6.3-8.2-11.4-14.5-14.5-15.8-7.8-35-1.3-42.9 14.5L369.8 316.2l-253.9 36.9c-7 1-13.4 4.3-18.3 9.3-12.3 12.7-12.1 32.9 0.6 45.3l183.7 179.1-43.4 252.9c-1.2 6.9-0.1 14.1 3.2 20.3 8.2 15.6 27.6 21.7 43.2 13.4L512 754l227.1 119.4c6.2 3.3 13.4 4.4 20.3 3.2 17.4-3 29.1-19.5 26.1-36.9l-43.4-252.9 183.7-179.1c5-4.9 8.3-11.3 9.3-18.3 2.7-17.5-9.5-33.7-27-36.3z'/></svg>") no-repeat center / contain;
  mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1024 1024'><path d='M908.1 353.1l-253.9-36.9L540.7 86.1c-3.1-6.3-8.2-11.4-14.5-14.5-15.8-7.8-35-1.3-42.9 14.5L369.8 316.2l-253.9 36.9c-7 1-13.4 4.3-18.3 9.3-12.3 12.7-12.1 32.9 0.6 45.3l183.7 179.1-43.4 252.9c-1.2 6.9-0.1 14.1 3.2 20.3 8.2 15.6 27.6 21.7 43.2 13.4L512 754l227.1 119.4c6.2 3.3 13.4 4.4 20.3 3.2 17.4-3 29.1-19.5 26.1-36.9l-43.4-252.9 183.7-179.1c5-4.9 8.3-11.3 9.3-18.3 2.7-17.5-9.5-33.7-27-36.3z'/></svg>") no-repeat center / contain;
}

.rating-value {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
}

.rating-max {
  color: var(--text-secondary, #909399);
}

.player-tabs {
  background: var(--bg-card, #fff);
  border-radius: 8px;
  border: 1px solid var(--border-light, #ebeef5);
  padding: 0 16px;
}

.tab-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.chapter-thumb {
  width: 80px;
  height: 45px;
  object-fit: cover;
  border-radius: 4px;
}

.muted {
  color: var(--text-secondary, #909399);
}

.gif-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.gif-card {
  background: var(--bg-page, #f5f7fa);
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--border-light, #ebeef5);
}

.gif-card img {
  width: 100%;
  display: block;
  background: #000;
}

.gif-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 8px;
  font-size: 12px;
  color: var(--text-secondary, #909399);
}

.subtitle-group {
  margin-bottom: 16px;
}

.group-title {
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-primary, #303133);
  font-size: 14px;
}

.sprite-preview {
  text-align: center;
}

.sprite-preview img {
  max-width: 100%;
  border: 1px solid var(--border-light, #ebeef5);
  border-radius: 4px;
}

/* ===== 截图时间轴 ===== */
.timeline-hint {
  margin-left: 12px;
}

.timeline-strip {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 8px 4px;
  border: 1px solid var(--border-light, #ebeef5);
  border-radius: 6px;
  background: var(--bg-page, #f5f7fa);
}

.timeline-thumb {
  flex: 0 0 auto;
  width: 120px;
  border: 2px solid transparent;
  border-radius: 4px;
  overflow: hidden;
  cursor: pointer;
  position: relative;
  background: #000;
  transition: border-color 0.15s, transform 0.15s;
}

.timeline-thumb:hover {
  border-color: var(--el-color-primary, #409eff);
  transform: translateY(-2px);
}

.timeline-thumb.active {
  border-color: var(--el-color-primary, #409eff);
}

.timeline-thumb img {
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  display: block;
}

.timeline-time {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  font-size: 10px;
  text-align: center;
  color: #fff;
  background: rgba(0, 0, 0, 0.6);
  padding: 2px 0;
}

/* ===== 来源对比 ===== */
.player-tabs :deep(.compare-row-same) {
  background: var(--el-color-success-light-9, #f0f9eb);
}

.player-tabs :deep(.compare-row-same td) {
  color: var(--text-secondary, #606266);
}

/* ===== Fanart 背景（v4.1 C1） ===== */
.fanart-tmdb-input {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.fanart-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.fanart-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--border-light, #ebeef5);
  border-radius: 6px;
  overflow: hidden;
  background: var(--bg-page, #f5f7fa);
}

.fanart-item img {
  width: 100%;
  height: 180px;
  object-fit: cover;
  display: block;
}

.fanart-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px;
  font-size: 12px;
  color: var(--text-secondary, #606266);
  background: var(--bg-card, #fff);
}

.fanart-search-result {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px dashed var(--border-light, #ebeef5);
}

.fanart-search-result h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--text-primary, #303133);
}

.fanart-search-result h5 {
  margin: 16px 0 8px;
  font-size: 13px;
  color: var(--text-secondary, #606266);
}

.fanart-poster-row .poster-strip {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 6px;
}

.poster-thumb {
  height: 200px;
  border-radius: 4px;
  border: 1px solid var(--border-light, #ebeef5);
  object-fit: cover;
}
</style>
