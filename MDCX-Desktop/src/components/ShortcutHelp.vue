<template>
  <transition name="sh-fade">
    <div
      v-if="modelValue"
      class="sh-mask"
      @click.self="close"
      @keydown.esc="close"
      tabindex="-1"
      ref="maskRef"
    >
      <div class="sh-panel" role="dialog" aria-label="键盘快捷键帮助">
        <div class="sh-head">
          <span class="sh-title">⌨ 键盘快捷键</span>
          <button class="sh-close" @click="close" aria-label="关闭">✕</button>
        </div>

        <div class="sh-body">
          <section v-for="g in groups" :key="g.title" class="sh-group">
            <h4 class="sh-group-title">{{ g.title }}</h4>
            <ul class="sh-list">
              <li v-for="(it, i) in g.items" :key="i" class="sh-row">
                <span class="sh-keys">
                  <kbd v-for="(k, ki) in it.keys" :key="ki" class="sh-kbd">{{ k }}</kbd>
                </span>
                <span class="sh-desc">{{ it.desc }}</span>
              </li>
            </ul>
          </section>
        </div>

        <div class="sh-foot">
          ※ 空格 / 方向键需在播放器聚焦时生效（点击播放器后）· 按 <kbd class="sh-kbd">?</kbd> 随时开关本面板
        </div>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

// 快捷键清单：已逐一核对 Artplayer 5.4.0 真实默认绑定 + 本项目自定义键。
// 默认键基于 e.code（播放器聚焦生效）；F / M / ? 为全局生效（本项目接入）。
const groups = [
  {
    title: '播放控制',
    items: [
      { keys: ['Space'], desc: '播放 / 暂停' },
      { keys: ['←'], desc: '后退 5 秒' },
      { keys: ['→'], desc: '前进 5 秒' },
      { keys: ['↑'], desc: '音量 +' },
      { keys: ['↓'], desc: '音量 −' },
      { keys: ['F'], desc: '切换全屏' },
      { keys: ['M'], desc: '静音 / 取消静音' },
      { keys: ['Esc'], desc: '退出全屏' },
    ],
  },
  {
    title: '界面',
    items: [
      { keys: ['?'], desc: '打开 / 关闭本帮助' },
    ],
  },
]

const close = () => emit('update:modelValue', false)
const toggle = () => emit('update:modelValue', !props.modelValue)

// 全局 ? 键：切换面板。与 Artplayer 约定一致——输入框/带修饰键时不触发。
const onKeydown = (e) => {
  if (e.key !== '?') return
  const tag = e.target?.tagName?.toUpperCase?.()
  const editable = e.target?.getAttribute?.('contenteditable')
  if (tag === 'INPUT' || tag === 'TEXTAREA' || editable === 'true' || editable === '') return
  if (e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return
  e.preventDefault()
  toggle()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.sh-mask {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
  outline: none;
}
.sh-panel {
  width: min(440px, 92vw);
  max-height: 84vh;
  overflow: auto;
  background: #1b1e26;
  border: 1px solid #2c303c;
  border-radius: 14px;
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.6);
  color: #e8eaf0;
  font-family: 'Inter', -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
.sh-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #2c303c;
}
.sh-title {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.sh-close {
  background: transparent;
  border: none;
  color: #9aa0ad;
  font-size: 16px;
  cursor: pointer;
  line-height: 1;
  padding: 4px 6px;
  border-radius: 6px;
}
.sh-close:hover {
  color: #fff;
  background: #2c303c;
}
.sh-body {
  padding: 8px 20px 4px;
}
.sh-group {
  margin: 12px 0;
}
.sh-group-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #6f7686;
  margin: 0 0 8px;
}
.sh-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.sh-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 7px 0;
}
.sh-keys {
  display: flex;
  gap: 4px;
  min-width: 96px;
}
.sh-kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 26px;
  padding: 0 7px;
  background: #2c303c;
  border: 1px solid #3a3f4d;
  border-bottom-width: 2px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #e8eaf0;
}
.sh-desc {
  font-size: 14px;
  color: #c4c9d4;
}
.sh-foot {
  padding: 12px 20px 16px;
  border-top: 1px solid #2c303c;
  font-size: 11.5px;
  line-height: 1.6;
  color: #767c8a;
}
.sh-foot .sh-kbd {
  min-width: 20px;
  height: 20px;
  font-size: 11px;
  vertical-align: middle;
}

.sh-fade-enter-active,
.sh-fade-leave-active {
  transition: opacity 0.18s ease;
}
.sh-fade-enter-from,
.sh-fade-leave-to {
  opacity: 0;
}
</style>
