<template>
  <div class="empty-state" :class="[`type-${type}`, { inline }]">
    <el-icon class="empty-icon" :size="iconSize">
      <component :is="iconComp" />
    </el-icon>
    <div class="empty-title">{{ titleText }}</div>
    <div class="empty-desc" v-if="description">{{ description }}</div>
    <div class="empty-actions" v-if="$slots.default">
      <slot />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  Files, Search, WarningFilled, Loading, Picture,
  Box, VideoCamera, FolderOpened, CircleClose
} from '@element-plus/icons-vue'

const props = defineProps({
  // 状态类型：no-data(无数据) / no-results(无搜索结果) / error(错误) / loading(加载中)
  type: {
    type: String,
    default: 'no-data',
    validator: (v) => ['no-data', 'no-results', 'error', 'loading'].includes(v),
  },
  // 自定义标题，不传则使用 type 默认文案
  title: { type: String, default: '' },
  // 描述文案
  description: { type: String, default: '' },
  // 图标大小
  iconSize: { type: Number, default: 64 },
  // 内联模式（高度更小，用于卡片内部/Tab 面板）
  inline: { type: Boolean, default: false },
})

// 类型 → 图标 + 默认文案
const TYPE_META = {
  'no-data': { icon: Box, label: '暂无数据' },
  'no-results': { icon: Search, label: '未找到匹配结果' },
  'error': { icon: WarningFilled, label: '加载失败' },
  'loading': { icon: Loading, label: '加载中...' },
}

const iconComp = computed(() => TYPE_META[props.type]?.icon || Box)
const titleText = computed(() => props.title || TYPE_META[props.type]?.label || '暂无数据')
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 40px 20px;
  text-align: center;
  color: var(--text-secondary, #909399);
}

.empty-state.inline {
  padding: 24px 12px;
  gap: 8px;
}

.empty-state.inline .empty-icon {
  --el-icon-size: 40px;
}

.empty-icon {
  color: var(--text-placeholder, #c0c4cc);
}

/* 加载中图标旋转 */
.type-loading .empty-icon {
  animation: rotating 1.5s linear infinite;
  color: var(--el-color-primary, #409eff);
}

/* 错误状态使用危险色 */
.type-error .empty-icon {
  color: var(--el-color-danger, #f56c6c);
}

.empty-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary, #303133);
}

.empty-state.inline .empty-title {
  font-size: 13px;
}

.empty-desc {
  font-size: 12px;
  color: var(--text-placeholder, #c0c4cc);
  line-height: 1.5;
  max-width: 320px;
}

.empty-actions {
  margin-top: 4px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}

@keyframes rotating {
  from { transform: rotate(0); }
  to { transform: rotate(360deg); }
}
</style>
