<template>
  <el-dialog v-model="visible" :title="titleText" width="92%" top="3vh" @close="onClose">
    <div v-if="current" class="player-wrap">
      <div class="player-main">
        <video :key="current.id" :src="current.play_url" controls autoplay
               style="width:100%;max-height:62vh;background:#000"
               @error="$emit('video-error', current)" @ended="onEnded" />
        <div class="player-bar">
          <el-button :disabled="playIndex === 0" @click="prev">⏮ 上一集</el-button>
          <span class="pos">{{ playIndex + 1 }} / {{ playlist.length }}</span>
          <el-button :disabled="playIndex >= playlist.length - 1" @click="next">下一集 ⏭</el-button>
          <span class="now" v-if="current.episode">第 {{ current.episode }} 集</span>
          <span class="now" v-else-if="current.title">{{ current.title }}</span>
        </div>
        <div class="player-meta">
          <span v-if="current.maker" class="tag maker">{{ current.maker }}</span>
          <span v-if="current.series" class="tag series">{{ current.series }}</span>
          <span v-if="current.episode" class="tag">第{{ current.episode }}集</span>
          <span v-if="current.release_date" class="tag">{{ current.release_date }}</span>
        </div>
      </div>
      <div class="player-list">
        <div class="pl-head">播放列表 ({{ playlist.length }})</div>
        <div v-for="(m, i) in playlist" :key="m.id"
             :class="['pl-item', { active: i === playIndex, watched: m._played }]"
             @click="jumpTo(i)">
          <span class="pl-idx">{{ i + 1 }}</span>
          <img v-if="m.cover" :src="m.cover" class="pl-cover" @error="onCoverError" />
          <span class="pl-title">{{ m.title || m.code }}</span>
          <span class="pl-ep" v-if="m.episode">第{{ m.episode }}集</span>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'
import { ElMessage } from 'element-plus'

// 里番系列「连播」弹窗：系列页与喜好页共用。
// 播放列表由调用方提供，当前下标通过 v-model:playIndex 双向同步。
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  playlist: { type: Array, default: () => [] },
  playIndex: { type: Number, default: 0 },
  seriesName: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'update:playIndex', 'finished', 'video-error'])

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})
const current = computed(() => props.playlist[props.playIndex] || null)
const titleText = computed(() => (props.seriesName || current.value?.series || '') + ' · 连播')

function setIndex(i) {
  if (i >= 0 && i < props.playlist.length) emit('update:playIndex', i)
}
function markPlayed(i) {
  const m = props.playlist[i]
  if (m) m._played = true
}
function next() {
  if (props.playIndex < props.playlist.length - 1) {
    markPlayed(props.playIndex)
    setIndex(props.playIndex + 1)
  }
}
function prev() {
  if (props.playIndex > 0) setIndex(props.playIndex - 1)
}
function jumpTo(i) { setIndex(i) }
function onEnded() {
  markPlayed(props.playIndex)
  if (props.playIndex < props.playlist.length - 1) {
    setIndex(props.playIndex + 1)   // 自动连播下一集
  } else {
    ElMessage?.success?.('本系列播放完毕')
    emit('finished')
  }
}
function onCoverError(e) { e.target.style.visibility = 'hidden' }
function onClose() { visible.value = false }
</script>

<style scoped>
.player-wrap { display:flex; gap:16px; align-items:flex-start; }
.player-main { flex: 1 1 auto; min-width:0; }
.player-bar { display:flex; align-items:center; gap:12px; margin-top:10px; flex-wrap:wrap; }
.player-bar .pos { font-size:14px; color: var(--el-text-color-secondary); min-width:48px; text-align:center; }
.player-bar .now { font-size:13px; color: var(--el-text-color-secondary); margin-left:auto; }
.player-meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
.player-list { flex: 0 0 280px; max-height:62vh; overflow-y:auto; border-left:1px solid var(--el-border-color,#ebeef5); padding-left:14px; }
.pl-head { font-size:13px; font-weight:600; margin-bottom:8px; color: var(--el-text-color-secondary); }
.pl-item { display:flex; align-items:center; gap:8px; padding:6px 6px; border-radius:8px; cursor:pointer; }
.pl-item:hover { background: rgba(0,0,0,.05); }
.pl-item.active { background: rgba(179,127,235,.18); }
.pl-idx { font-size:12px; color: var(--el-text-color-secondary); width:20px; text-align:right; flex:0 0 auto; }
.pl-cover { width:34px; height:46px; object-fit:cover; border-radius:4px; background:#2a2a35; flex:0 0 auto; }
.pl-title { font-size:13px; line-height:1.3; overflow:hidden; text-overflow:ellipsis; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
.pl-ep { font-size:11px; color:#b37feb; flex:0 0 auto; }
.pl-item.watched .pl-title { color: var(--el-text-color-secondary); text-decoration: line-through; }
.tag { font-size:11px; padding:1px 7px; border-radius:8px; background: rgba(0,0,0,.06); }
.tag.maker { background: rgba(240,110,201,.15); color:#d24bb0; }
.tag.series { background: rgba(179,127,235,.15); color:#8a4fd0; }
@media (max-width: 860px) {
  .player-wrap { flex-direction: column; }
  .player-list { flex: 1 1 auto; max-height:40vh; border-left:none; border-top:1px solid var(--el-border-color,#ebeef5); padding-left:0; padding-top:12px; width:100%; }
}
</style>
