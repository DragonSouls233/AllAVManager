<template>
  <el-form label-width="100px">
    <el-form-item label="标签模式">
      <el-radio-group :model-value="tagMode" @update:model-value="$emit('update:tagMode', $event)">
        <el-radio value="OR">任一匹配 (OR)</el-radio>
        <el-radio value="AND">全部匹配 (AND)</el-radio>
      </el-radio-group>
      <div class="form-tip">
        OR: 包含任一所选标签的影片; AND: 必须同时包含所有所选标签
      </div>
    </el-form-item>
    <el-form-item label="选择标签">
      <div class="tag-select-panel">
        <el-input
          :model-value="tagSearch"
          @update:model-value="$emit('update:tagSearch', $event)"
          placeholder="搜索标签..."
          clearable
          size="small"
          style="margin-bottom: 8px"
        />
        <div class="tag-list" v-loading="loading">
          <el-tag
            v-for="t in filteredTags"
            :key="t.id"
            :type="isSelected(t.id) ? 'primary' : 'info'"
            :effect="isSelected(t.id) ? 'dark' : 'plain'"
            class="tag-option"
            @click="$emit('toggle-tag', t)"
          >
            {{ t.name }}
            <span class="tag-cnt" v-if="t.movie_count">({{ t.movie_count }})</span>
          </el-tag>
          <el-empty v-if="!filteredTags.length" :image-size="60" description="无标签" />
        </div>
      </div>
    </el-form-item>
    <el-form-item label="评分区间">
      <div class="rating-range">
        <el-input-number
          :model-value="minRating"
          @update:model-value="$emit('update:minRating', $event)"
          :min="0"
          :max="10"
          :step="0.1"
          :precision="1"
          size="small"
          controls-position="right"
        />
        <span style="margin: 0 8px">-</span>
        <el-input-number
          :model-value="maxRating"
          @update:model-value="$emit('update:maxRating', $event)"
          :min="0"
          :max="10"
          :step="0.1"
          :precision="1"
          size="small"
          controls-position="right"
        />
      </div>
    </el-form-item>
    <el-form-item label="收藏">
      <el-switch
        :model-value="onlyFavorite"
        @update:model-value="$emit('update:onlyFavorite', $event)"
        active-text="仅显示已收藏"
      />
    </el-form-item>
    <el-form-item>
      <el-button @click="$emit('clear')">清除所有筛选</el-button>
      <el-button type="primary" @click="$emit('apply')">应用筛选</el-button>
    </el-form-item>
  </el-form>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  tags: { type: Array, default: () => [] },
  selectedTags: { type: Array, default: () => [] },
  tagMode: { type: String, default: 'OR' },
  tagSearch: { type: String, default: '' },
  minRating: { type: [Number, null], default: null },
  maxRating: { type: [Number, null], default: null },
  onlyFavorite: { type: Boolean, default: false },
  loading: { type: Boolean, default: false }
})

defineEmits([
  'update:tagMode', 'update:tagSearch', 'update:minRating', 'update:maxRating',
  'update:onlyFavorite', 'toggle-tag', 'clear', 'apply'
])

const filteredTags = computed(() => {
  if (!props.tagSearch) return props.tags
  const kw = props.tagSearch.toLowerCase()
  return props.tags.filter(t => t.name.toLowerCase().includes(kw))
})

const isSelected = (id) => props.selectedTags.some(t => t.id === id)
</script>

<style scoped>
.tag-select-panel {
  width: 100%;
}

.tag-list {
  max-height: 320px;
  overflow-y: auto;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 4px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.tag-option {
  cursor: pointer;
  transition: all 0.15s;
}

.tag-option:hover {
  transform: scale(1.05);
}

.tag-cnt {
  opacity: 0.7;
  font-size: 11px;
  margin-left: 2px;
}

.rating-range {
  display: flex;
  align-items: center;
}

.form-tip {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
  line-height: 1.5;
}
</style>
