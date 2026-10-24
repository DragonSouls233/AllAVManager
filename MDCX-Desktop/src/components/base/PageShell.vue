<template>
  <div class="page-shell" :data-padding="padding" :style="shellStyle">
    <!-- 页头：标题是真标题元素（不是加粗的 div），读屏和快捷键跳转才认得出来 -->
    <header v-if="hasHeader" class="ps-header">
      <div class="ps-heading">
        <h1 v-if="title || $slots.title" class="ps-title">
          <slot name="title">{{ title }}</slot>
        </h1>
        <p v-if="description || $slots.description" class="ps-desc">
          <slot name="description">{{ description }}</slot>
        </p>
        <div v-if="$slots.meta" class="ps-meta"><slot name="meta" /></div>
      </div>
      <div v-if="$slots.actions" class="ps-actions"><slot name="actions" /></div>
    </header>

    <!-- 工具条：搜索框、筛选、批量操作。29 个页面此前各写一份 .toolbar，这里收成一处 -->
    <div v-if="$slots.toolbar" class="ps-toolbar"><slot name="toolbar" /></div>

    <!-- 正文 -->
    <div class="ps-body"><slot /></div>

    <!-- 页脚：分页 -->
    <div v-if="$slots.footer" class="ps-footer"><slot name="footer" /></div>
  </div>
</template>

<script setup>
/**
 * PageShell —— 页面骨架
 *
 * 借鉴 peach 的 `react/components/page.tsx`：它整个组件只有 5 行（居中 + 最大宽 + 间距）。
 * 骨架越薄，越容易被采用；每加一个约束，就多一个页面不想用它的理由。
 *
 * 这里也只做四件事：页头、工具条、正文、页脚四个槽 + 统一的边距。
 * 不接管配色、不接管布局方式、不接管滚动 —— 那些交给页面自己，各模块差别太大。
 *
 * 为什么要有它：MDCX 126 个页面里 29 个自己写 `.toolbar`、57 个自己写 `grid-template-columns`，
 * 边距和断点各不相同，同一个操作在不同页面里位置不一样。这个组件本身不解决美感问题，
 * 它解决的是「同一个东西每次都长得不太一样」。
 */
import { computed, useSlots } from 'vue'

const props = defineProps({
  /** 页面标题 */
  title: { type: String, default: '' },
  /** 标题下的一句说明 */
  description: { type: String, default: '' },
  /** 正文最大宽度。默认不限制（表格/网格页要铺满）；表单页可给 1200px 之类的值 */
  maxWidth: { type: String, default: '' },
  /** 内边距档位：normal 常规页面 / compact 内容密集的库页面 / none 自带内边距的页面 */
  padding: {
    type: String,
    default: 'normal',
    validator: (v) => ['normal', 'compact', 'none'].includes(v),
  },
  /** 各区块之间的纵向间距 */
  gap: { type: String, default: '16px' },
})

const slots = useSlots()

const hasHeader = computed(
  () => Boolean(props.title || props.description || slots.title || slots.description || slots.meta || slots.actions),
)

const shellStyle = computed(() => ({
  '--ps-max': props.maxWidth || 'none',
  '--ps-gap': props.gap,
}))
</script>

<style scoped>
.page-shell {
  display: flex;
  flex-direction: column;
  gap: var(--ps-gap, 16px);
  box-sizing: border-box;
  width: 100%;
  /* 不限制宽度时 max-width:none；给了值就居中 */
  max-width: var(--ps-max, none);
  margin-inline: auto;
}

.page-shell {
  padding: 20px;
}

/* compact：媒体库这类以网格为主的页面，减少留白让一屏多放几行 */
.page-shell[data-padding='compact'] {
  padding: 12px 16px 16px;
}

.page-shell[data-padding='none'] {
  padding: 0;
}

.ps-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.ps-heading {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.ps-title {
  margin: 0;
  font-size: 18px;
  font-weight: 500;
  line-height: 1.4;
  color: var(--text-primary);
}

.ps-desc {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.ps-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-secondary);
}

.ps-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ps-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.ps-body {
  min-width: 0;
  /* 正文自己管滚动；骨架不管，避免嵌套滚动条 */
}

.ps-footer {
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
