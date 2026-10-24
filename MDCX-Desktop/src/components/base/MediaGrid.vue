<template>
  <div class="media-grid-root">
    <!--
      首次加载（一条数据都还没有）才铺骨架。
      已有内容时刷新不铺 —— 否则翻页/轮询每 15 秒闪一次骨架，比不铺更难受。
      这也是 peach 那条 refetchOnMount:false 的同一个判断：手上有一份就先看着。
    -->
    <SkeletonGrid
      v-if="showSkeleton"
      :count="skeletonCount"
      :tile="tile"
      :gap="gap"
      :cover-ratio="coverRatio"
    />

    <div v-else-if="items.length" class="media-grid" :style="gridStyle">
      <template v-for="(item, index) in items" :key="keyOf(item, index)">
        <slot :item="item" :index="index" />
      </template>
    </div>

    <!-- 空态：默认用项目已有的 EmptyState，页面想自己写就填 empty 槽 -->
    <slot v-else name="empty">
      <EmptyState :type="emptyType" :title="emptyTitle" :description="emptyDescription">
        <slot name="empty-actions" />
      </EmptyState>
    </slot>
  </div>
</template>

<script setup>
/**
 * MediaGrid —— 卡片网格
 *
 * 统一的是三件此前每个页面各写一遍的事：
 *   1. 网格列宽（57 个页面自己写 grid-template-columns，断点各家不同）
 *   2. 加载态（首次加载铺骨架，有数据时刷新不铺）
 *   3. 空态（接项目已有 EmptyState，不再各写一句「暂无数据」）
 *
 * 不统一的：卡片长什么样。卡片通过默认插槽由页面自己决定 —— 影片卡、演员卡、图集卡
 * 差别太大，硬塞进一个组件只会变成一堆 if。这里只管它们怎么排队。
 *
 * 列宽读全局 `--tile`（见 utils/density.js），所以密度切换对这里所有使用者一次生效。
 */
import { computed } from 'vue'
import EmptyState from '@/components/EmptyState.vue'
import SkeletonGrid from './SkeletonGrid.vue'

const props = defineProps({
  /** 数据数组 */
  items: { type: Array, default: () => [] },
  /** 是否在加载 */
  loading: { type: Boolean, default: false },
  /** 列宽。默认跟随全局密度 */
  tile: { type: String, default: 'var(--tile, 200px)' },
  /** 项目间隙 */
  gap: { type: String, default: '12px' },
  /** 封面比例（骨架与网格共用，保证不跳动） */
  coverRatio: { type: String, default: '3 / 4' },
  /** 骨架卡片数量 */
  skeletonCount: { type: Number, default: 18 },
  /** 数据项的唯一键字段，不传则用 index */
  keyField: { type: String, default: 'id' },

  // 空态
  emptyType: {
    type: String,
    default: 'no-data',
    validator: (v) => ['no-data', 'no-results', 'error', 'loading'].includes(v),
  },
  emptyTitle: { type: String, default: '' },
  emptyDescription: { type: String, default: '' },
})

const showSkeleton = computed(() => props.loading && !props.items.length)

const gridStyle = computed(() => ({
  '--mg-tile': props.tile,
  '--mg-gap': props.gap,
}))

function keyOf(item, index) {
  const k = item?.[props.keyField]
  return k === undefined || k === null ? index : k
}
</script>

<style scoped>
.media-grid-root {
  min-width: 0;
}

.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--mg-tile, 200px), 1fr));
  gap: var(--mg-gap, 12px);
  min-width: 0;
}
</style>
