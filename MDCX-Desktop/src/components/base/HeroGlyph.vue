<template>
  <!--
    HeroGlyph —— 资料页用的 16px 线性图标

    项目里已有 @element-plus/icons-vue，但它一套图标混了实心/线性两种画法，
    排进同一行元数据会一粗一细；资料页这种「一行一个图标」的地方要的是同一副
    16px、2px 描边的线性字形（对标的资料卡就是这么画的），所以这里自己画。
    只画资料页用得到的几种，缺的再加 —— 不做通用图标库。
  -->
  <svg
    class="hero-glyph"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="(d, i) in paths" :key="i" :d="d" />
    <circle v-for="(c, i) in circles" :key="`c${i}`" :cx="c[0]" :cy="c[1]" :r="c[2]" />
    <rect
      v-for="(r, i) in rects"
      :key="`r${i}`"
      :x="r[0]"
      :y="r[1]"
      :width="r[2]"
      :height="r[3]"
      :rx="r[4] || 2"
    />
  </svg>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** 图标名；未知名字渲染成空（不报错、不占位符污染版面） */
  name: { type: String, default: '' },
})

// 全部按 24×24 网格画，组件把它缩到 16px。
const SHAPES = {
  film: { paths: ['M3 4h18v16H3z', 'M7 4v16', 'M17 4v16', 'M3 9h4', 'M3 15h4', 'M17 9h4', 'M17 15h4'], rects: [] },
  user: { paths: ['M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2'], circles: [[12, 7, 4]] },
  'id-card': { paths: ['M3 5h18v14H3z', 'M7 10h4', 'M7 14h7'], circles: [[16.5, 10, 1.6]], rects: [] },
  briefcase: { paths: ['M3 8h18v11H3z', 'M9 8V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2', 'M3 13h18'], rects: [] },
  calendar: { paths: ['M4 6h16v14H4z', 'M8 3v4', 'M16 3v4', 'M4 11h16'], rects: [] },
  ruler: { paths: ['M3.5 15.5 15.5 3.5l5 5L8.5 20.5z', 'M7 12l2 2', 'M10 9l2 2', 'M13 6l2 2'], rects: [] },
  tags: { paths: ['M3 4h8l10 10-8 8L3 12z', 'M7.5 8.5h.01'], circles: [[8, 8.5, 1.2]], rects: [] },
  location: { paths: ['M12 21s7-6 7-11a7 7 0 1 0-14 0c0 5 7 11 7 11z'], circles: [[12, 10, 2.6]] },
  globe: { paths: ['M3 12h18', 'M12 3a15 15 0 0 1 0 18', 'M12 3a15 15 0 0 0 0 18'], circles: [[12, 12, 9]] },
  link: { paths: ['M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1', 'M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1'], rects: [] },
  star: { paths: ['M12 4l2.4 5.2 5.6.7-4.1 3.9 1 5.6-4.9-2.8-4.9 2.8 1-5.6L4 9.9l5.6-.7z'], rects: [] },
  layers: { paths: ['M12 3l9 5-9 5-9-5z', 'M3 13l9 5 9-5'], rects: [] },
  clock: { paths: ['M12 7v5l3 2'], circles: [[12, 12, 9]] },
  heart: { paths: ['M12 20s-7-4.4-7-9a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 4.6-7 9-7 9z'], rects: [] },
  'arrow-up-right': { paths: ['M7 17 17 7', 'M8 7h9v9'], rects: [] },
}

const shape = computed(() => SHAPES[props.name] || { paths: [], circles: [], rects: [] })
const paths = computed(() => shape.value.paths || [])
const circles = computed(() => shape.value.circles || [])
const rects = computed(() => shape.value.rects || [])
</script>

<style scoped>
.hero-glyph {
  flex: none;
  width: 16px;
  height: 16px;
}
</style>
