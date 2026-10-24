<template>
  <div
    class="skeleton-grid"
    :style="gridStyle"
    role="status"
    aria-busy="true"
    aria-label="加载中"
  >
    <div v-for="i in count" :key="i" class="sk-card">
      <!-- 封面格与真实卡片同一个 3:4，骨架消失时高度不跳 -->
      <div class="sk-cover">
        <Skeleton width="100%" height="100%" :rounded="0" />
      </div>
      <div class="sk-meta">
        <Skeleton :width="titleWidth(i)" height="13" :rounded="4" />
        <Skeleton width="55%" height="11" :rounded="4" />
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * SkeletonGrid —— 卡片网格的骨架屏
 *
 * 为什么单独做一个：MDCX 126 个页面里只有 1 个用了骨架屏，其余加载时直接白屏或者只转一个圈。
 * 转圈的问题是「不知道要等出什么、等出来多大一块」，页面内容一到位还会整块跳一下。
 *
 * 这里刻意和 MediaGrid 用同一套网格参数（同一个 `--tile`、同一个 3:4 封面比例、同样的间隙），
 * 所以骨架和真实卡片占的位置完全一样 —— 数据回来时是「内容出现了」，不是「页面跳了一下」。
 *
 * 复用项目已有的 Skeleton.vue（shimmer / 暗色 / prefers-reduced-motion 都处理过了），不重写。
 */
import { computed } from 'vue'
import Skeleton from '@/components/Skeleton.vue'

const props = defineProps({
  /** 占位卡片数量。给一屏的量即可，给太多会在滚动条底下白画 */
  count: { type: Number, default: 18 },
  /** 列宽。默认读全局密度变量，和真实网格保持一致 */
  tile: { type: String, default: 'var(--tile, 200px)' },
  /** 卡片间隙 */
  gap: { type: String, default: '12px' },
  /** 封面比例 */
  coverRatio: { type: String, default: '3 / 4' },
})

const gridStyle = computed(() => ({
  '--sk-tile': props.tile,
  '--sk-gap': props.gap,
  '--sk-ratio': props.coverRatio,
}))

/** 标题行宽度做点变化，一条齐的可能被误认为「就一个块」 */
const WIDTHS = ['92%', '78%', '86%', '70%']
const titleWidth = (i) => WIDTHS[(i - 1) % WIDTHS.length]
</script>

<style scoped>
.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--sk-tile, 200px), 1fr));
  gap: var(--sk-gap, 12px);
}

.sk-card {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--bg-card);
}

.sk-cover {
  position: relative;
  aspect-ratio: var(--sk-ratio, 3 / 4);
  background: var(--border-light);
}

/* Skeleton 组件默认是 inline-block，这里撑满封面格 */
.sk-cover :deep(.skeleton) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.sk-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
}
</style>
