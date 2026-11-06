<template>
  <nav class="page-breadcrumb" aria-label="面包屑导航">
    <template v-for="(crumb, idx) in trail" :key="`${crumb.label}-${idx}`">
      <span v-if="idx > 0" class="bc-sep" aria-hidden="true">/</span>
      <router-link v-if="crumb.to && idx < trail.length - 1" :to="crumb.to" class="bc-link">
        {{ crumb.label }}
      </router-link>
      <span v-else class="bc-current" :aria-current="idx === trail.length - 1 ? 'page' : undefined">
        {{ crumb.label }}
      </span>
    </template>
  </nav>
</template>

<script setup>
/**
 * PageBreadcrumb —— 面包屑
 *
 * 由 `nav.js` 的 `resolveBreadcrumb()` 派生，取代原 `AdminLayout.vue` 里
 * 120 行的 `pageTitle` switch 表（§7.3）。所有文案/层级只在 nav.js 维护一次。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { resolveBreadcrumb } from '@/config/nav'

const route = useRoute()

const trail = computed(() => resolveBreadcrumb(route.path, route.query))
</script>

<style scoped>
.page-breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
}

.bc-sep {
  color: var(--text-placeholder);
  flex-shrink: 0;
}

.bc-link {
  color: var(--text-secondary);
  text-decoration: none;
  flex-shrink: 0;
  border-radius: 4px;
  transition: color var(--dur-fast, 120ms);
}

.bc-link:hover {
  color: var(--accent);
}

.bc-link:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.bc-current {
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
