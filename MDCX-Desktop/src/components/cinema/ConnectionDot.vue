<template>
  <el-tooltip :content="text" placement="right">
    <div class="conn-dot" :class="`conn-${level}`" :aria-label="text" role="status">
      <span class="conn-pulse" />
    </div>
  </el-tooltip>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { getSystemHealth } from '@/api'

const level = ref('unknown') // ok / error / unknown
const text = computed(() => ({
  ok: '已连接到服务器',
  error: '服务器异常',
  unknown: '未连接服务器'
}[level.value]))

let timer = null

async function probe() {
  try {
    await getSystemHealth()
    level.value = 'ok'
  } catch (e) {
    level.value = e?.response ? 'error' : 'unknown'
  }
}

onMounted(() => {
  probe()
  timer = setInterval(probe, 30000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.conn-dot {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto;
}

.conn-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-3);
}

.conn-ok .conn-pulse {
  background: #35C759;
  box-shadow: 0 0 8px rgba(53, 199, 89, 0.7);
}

.conn-error .conn-pulse {
  background: #FF5A5F;
  box-shadow: 0 0 8px rgba(255, 90, 95, 0.7);
}
</style>
