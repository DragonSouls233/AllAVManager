<template>
  <div class="site-registry">
    <div class="toolbar">
      <h2>站点注册表 ({{ totalCount }} 站点)</h2>
      <el-select v-model="activeCategory" style="width: 180px">
        <el-option v-for="c in categories" :key="c.id" :label="`${c.name} (${c.count})`" :value="c.id" />
      </el-select>
      <el-input v-model="keyword" placeholder="搜索站点..." clearable style="width: 240px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button @click="loadSites" :loading="loading">
        <el-icon><Refresh /></el-icon> 刷新
      </el-button>
    </div>

    <el-card v-loading="loading" style="min-height: 300px">
      <el-table :data="filteredSites" stripe style="width: 100%">
        <el-table-column prop="id" label="ID" width="120" />
        <el-table-column label="名称" min-width="150">
          <template #default="scope">
            <strong>{{ scope.row.name || scope.row.id }}</strong>
          </template>
        </el-table-column>
        <el-table-column label="主域名" min-width="250">
          <template #default="scope">
            <a :href="scope.row.primary" target="_blank" class="site-link">{{ scope.row.primary }}</a>
          </template>
        </el-table-column>
        <el-table-column label="镜像" min-width="80">
          <template #default="scope">
            <el-tag v-if="scope.row.fallbacks && scope.row.fallbacks.length" size="small">{{ scope.row.fallbacks.length }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="scope">
            <el-tag :type="typeTag(scope.row.type)" size="small">{{ scope.row.type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="刮削" width="70" align="center">
          <template #default="scope">
            <el-tag v-if="scope.row.supports_scrape" type="success" size="small">是</el-tag>
            <el-tag v-else type="info" size="small">否</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="下载" width="70" align="center">
          <template #default="scope">
            <el-tag v-if="scope.row.supports_download" type="success" size="small">是</el-tag>
            <el-tag v-else type="info" size="small">否</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="网络" width="130">
          <template #default="scope">
            {{ scope.row.network || scope.row.note || '-' }}
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && filteredSites.length === 0" description="无匹配站点" />
    </el-card>

    <!-- 统计 -->
    <el-card style="margin-top: 16px">
      <template #header><span>分类统计</span></template>
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item v-for="c in categories" :key="c.id" :label="c.name">
          <strong>{{ c.count }}</strong>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/index'

const activeCategory = ref('')
const keyword = ref('')
const loading = ref(false)
const categories = ref([])
const allSites = ref({})

const totalCount = computed(() => {
  let total = 0
  for (const k in allSites.value) {
    total += (allSites.value[k] || []).length
  }
  return total
})

const filteredSites = computed(() => {
  let list = []
  if (activeCategory.value && allSites.value[activeCategory.value]) {
    list = allSites.value[activeCategory.value]
  } else {
    for (const k in allSites.value) {
      list = list.concat(allSites.value[k])
    }
  }
  if (keyword.value) {
    const kw = keyword.value.toLowerCase()
    list = list.filter(s =>
      (s.name && s.name.toLowerCase().includes(kw)) ||
      (s.primary && s.primary.toLowerCase().includes(kw)) ||
      (s.id && s.id.toLowerCase().includes(kw))
    )
  }
  return list
})

function typeTag(type) {
  const map = { official: '', tube: 'warning', database: '', community: 'success', magnet: 'danger', aggregator: 'info', collector: '', live: 'danger', api: '', torrent: '', tool: '' }
  return map[type] || ''
}

async function loadSites() {
  loading.value = true
  try {
    const data = await api.get('/sites')
    allSites.value = data || {}
    categories.value = []
    for (const cat in data) {
      categories.value.push({ id: cat, name: catLabel(cat), count: (data[cat] || []).length })
    }
  } finally {
    loading.value = false
  }
}

function catLabel(cat) {
  const map = { chinese: '国产', western: '欧美', jav: 'JAV', magnet: '磁力' }
  return map[cat] || cat
}

onMounted(loadSites)
</script>

<style scoped>
.site-registry { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }
.toolbar h2 { margin: 0; font-size: 18px; }
.site-link { color: #409eff; text-decoration: none; }
.site-link:hover { text-decoration: underline; }
</style>
