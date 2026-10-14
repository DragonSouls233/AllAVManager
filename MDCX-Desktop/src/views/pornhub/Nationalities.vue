<template>
  <div class="nationality-page">
    <el-card shadow="never" class="head-card">
      <template #header>
        <span class="card-title">
          <el-icon><MapLocation /></el-icon> PORNHub 国籍
        </span>
      </template>
      <div class="head-row">
        <el-input
          v-model="keyword"
          placeholder="在全部国籍中搜索演员..."
          clearable
          style="width: 260px"
          @keyup.enter="onSearch"
          @clear="onSearch"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button type="primary" @click="onSearch()">搜索</el-button>
        <div class="spacer" />
        <el-tag type="info" effect="plain">
          {{ nations.length }} 个国籍 · 共 {{ sumCount }} 位演员
        </el-tag>
        <el-button :loading="loading" @click="reload()">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
      <div class="hint">
        国籍来自扫描影片时的<strong>媒体根下顶级文件夹名</strong>（如 <code>N:\澳大利亚\...</code> → 澳大利亚）；
        顶级目录若是分类名（素人/已注销等）也会原样成为一组，均按你的规则保留、不做合并。
      </div>
    </el-card>

    <div class="body">
      <!-- 左：国籍列表 -->
      <el-card shadow="never" class="nat-list-card" v-loading="natLoading">
        <template #header>
          <span class="list-title">国籍分组</span>
        </template>
        <div class="nat-list">
          <button
            class="nat-item"
            :class="{ active: !current }"
            @click="selectNation('')"
          >
            <span class="nat-name">全部</span>
            <span class="nat-num">{{ sumCount }}</span>
          </button>
          <button
            v-for="n in nations"
            :key="n.nationality"
            class="nat-item"
            :class="{ active: current === n.nationality }"
            @click="selectNation(n.nationality)"
          >
            <span class="nat-name">{{ n.nationality }}</span>
            <span class="nat-num">{{ n.count }}</span>
          </button>
          <el-empty v-if="!natLoading && !nations.length" description="暂无国籍数据" :image-size="60" />
        </div>
      </el-card>

      <!-- 右：该国籍下的演员 -->
      <el-card shadow="never" class="actor-card" v-loading="loading">
        <template #header>
          <span class="list-title">
            <template v-if="current">
              {{ current }} · {{ total }} 位演员
            </template>
            <template v-else>全部演员 · {{ total }} 位</template>
          </span>
        </template>

        <div class="actor-grid">
          <div
            v-for="a in actors"
            :key="a.id"
            class="actor-item"
            @click="goActor(a.id)"
          >
            <div class="actor-avatar">
              <el-image :src="avatarSrc(a)" fit="cover" class="avatar-img" lazy>
                <template #error><div class="avatar-ph">无头像</div></template>
              </el-image>
            </div>
            <div class="actor-name" :title="a.name">{{ a.name }}</div>
            <div class="actor-meta">
              <span v-if="a.movie_count != null">{{ a.movie_count }} 部作品</span>
            </div>
            <el-tag v-if="a.nationality" size="mini" type="info" class="nat-tag">
              {{ a.nationality }}
            </el-tag>
          </div>
        </div>

        <el-empty
          v-if="!loading && !actors.length"
          :description="current ? `「${current}」下暂无演员` : '暂无演员'"
        />

        <div class="pager" v-if="total > pageSize">
          <el-pagination
            v-model:current-page="page"
            :page-size="pageSize"
            :total="total"
            layout="total, prev, pager, next"
            background
            @current-change="loadActors"
          />
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { MapLocation, Search, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getPornhubActorNationalities, getPornhubActorsPage } from '@/api/pornhub'
import { getAvatarSrc } from '@/utils/media'

const router = useRouter()

const nations = ref([])
const natLoading = ref(false)
const loading = ref(false)

const actors = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(48)

const current = ref('')
const keyword = ref('')

const sumCount = computed(() => nations.value.reduce((s, n) => s + (n.count || 0), 0))

async function loadNationalities() {
  natLoading.value = true
  try {
    const res = await getPornhubActorNationalities()
    nations.value = Array.isArray(res) ? res : []
  } catch (e) {
    nations.value = []
    ElMessage.error(e?.response?.data?.detail || '加载国籍列表失败')
  } finally {
    natLoading.value = false
  }
}

async function loadActors() {
  loading.value = true
  try {
    const res = await getPornhubActorsPage({
      skip: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
      search: keyword.value || undefined,
      nationality: current.value || undefined
    })
    actors.value = res?.actors || res?.items || []
    total.value = res?.total || 0
  } catch (e) {
    actors.value = []
    total.value = 0
    ElMessage.error(e?.response?.data?.detail || '加载演员失败')
  } finally {
    loading.value = false
  }
}

// 切国籍必须回第一页，否则会停在第 N 页看不到结果
function selectNation(nat) {
  current.value = nat
  page.value = 1
  loadActors()
}

function onSearch() {
  page.value = 1
  loadActors()
}

function reload() {
  loadNationalities()
  loadActors()
}

function avatarSrc(a) {
  return getAvatarSrc(a)
}

function goActor(id) {
  router.push(`/pornhub/actors/${id}`)
}

onMounted(() => {
  loadNationalities()
  loadActors()
})
</script>

<style scoped>
.nationality-page { max-width: 1400px; margin: 0 auto; }
.head-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.spacer { flex: 1; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 15px; }
.list-title { font-weight: 600; font-size: 14px; }
.hint { margin-top: 10px; font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.7; }
.hint code { background: var(--el-fill-color-light); padding: 1px 5px; border-radius: 3px; }

.body { display: flex; gap: 12px; margin-top: 12px; align-items: flex-start; }
.nat-list-card { width: 230px; flex-shrink: 0; }
.actor-card { flex: 1; min-width: 0; }

.nat-list { max-height: calc(100vh - 300px); overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
.nat-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 7px 10px; border: 1px solid var(--el-border-color-light);
  border-radius: 6px; background: var(--el-bg-color); cursor: pointer;
  font-size: 13px; text-align: left; color: var(--el-text-color-regular);
}
.nat-item:hover { border-color: var(--el-color-primary); color: var(--el-color-primary); }
.nat-item.active {
  background: var(--el-color-primary); border-color: var(--el-color-primary);
  color: #fff;
}
.nat-item.active .nat-num { background: rgba(255, 255, 255, 0.25); color: #fff; }
.nat-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nat-num {
  flex-shrink: 0; margin-left: 6px; font-size: 11px;
  background: var(--el-fill-color-light); color: var(--el-text-color-secondary);
  border-radius: 9px; padding: 1px 7px;
}

.actor-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 14px;
}
.actor-item {
  cursor: pointer; border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px; padding: 8px; text-align: center;
  transition: transform .15s, box-shadow .15s;
}
.actor-item:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0, 0, 0, .12); }
.actor-avatar { width: 100%; aspect-ratio: 3 / 4; border-radius: 6px; overflow: hidden; background: var(--el-fill-color-light); }
.avatar-img { width: 100%; height: 100%; display: block; }
.avatar-ph {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  font-size: 12px; color: var(--el-text-color-placeholder);
}
.actor-name {
  margin-top: 6px; font-size: 13px; font-weight: 500;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.actor-meta {
  margin-top: 2px; font-size: 11px; color: var(--el-text-color-secondary);
  display: flex; gap: 8px; justify-content: center;
}
.nat-tag { margin-top: 5px; }
.pager { margin-top: 14px; display: flex; justify-content: center; }
</style>
