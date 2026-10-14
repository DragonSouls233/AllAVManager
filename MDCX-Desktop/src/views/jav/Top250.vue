<template>
  <div class="top250">
    <el-card shadow="never">
      <template #header>
        <span class="card-title">
          <el-icon><Trophy /></el-icon> 🏆 JavDB TOP 250（有码）
        </span>
      </template>

      <!-- 未登录：登录框 -->
      <el-alert
        v-if="!token"
        type="warning"
        show-icon
        :closable="false"
        style="margin-bottom: 14px"
        title="该功能需要 JavDB App 登录"
        description="TOP250 仅 JavDB App（登录态）提供，网站与匿名接口均无。输入你的 JavDB App 账号密码登录后即可抓取并对照本地库。"
      />
      <el-form v-if="!token" :inline="true" class="login-bar" @submit.prevent>
        <el-form-item label="用户名">
          <el-input v-model="username" placeholder="JavDB App 用户名/邮箱" clearable />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" placeholder="密码" show-password @keyup.enter="doLogin" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="logging" @click="doLogin()">
            <el-icon><Key /></el-icon> 登录并抓取
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 已登录：筛选条 -->
      <div v-else class="filter-bar">
        <el-radio-group v-model="zone" @change="reload">
          <el-radio-button value="censored">有码</el-radio-button>
          <el-radio-button value="uncensored">无码</el-radio-button>
          <el-radio-button value="western">西方</el-radio-button>
          <el-radio-button value="fc2">FC2</el-radio-button>
        </el-radio-group>

        <el-switch
          v-model="onlyMissing"
          active-text="只看未收录"
          inactive-text="全部"
          @change="reload"
        />

        <div class="spacer" />

        <el-tag type="info" effect="plain">共 {{ total }} 部 · 已有 {{ have }} · 未收录 {{ missing }}</el-tag>
        <el-button :loading="loading" @click="reload(true)">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
        <el-button text type="info" @click="logout()">退出登录</el-button>
      </div>

      <el-alert
        v-if="token"
        title="数据抓取自 JavDB App TOP250，并对照本地 jav 库标记「已有 / 未收录」。绿色为本地已收录，橙色为待补。"
        type="info"
        show-icon
        :closable="false"
        style="margin: 12px 0"
      />

      <!-- 榜单卡片网格 -->
      <div v-loading="loading" class="grid">
        <div v-for="m in items" :key="m.ranking + m.code" class="card">
          <div class="rank" :class="{ top: m.ranking <= 3 }">{{ m.ranking }}</div>
          <el-image :src="m.cover_url" fit="cover" class="cover" lazy>
            <template #error><div class="cover-ph">无封面</div></template>
          </el-image>
          <div class="info">
            <div class="code-row">
              <span class="code">{{ m.code || '未识别番号' }}</span>
              <el-tag size="small" :type="m.in_library ? 'success' : 'warning'">
                {{ m.in_library ? '已有' : '未收录' }}
              </el-tag>
            </div>
            <div class="title" :title="m.title">{{ m.title || '（无标题）' }}</div>
            <div class="meta">
              <span v-if="m.score != null" class="score">★ {{ m.score }}</span>
              <span v-if="m.release_date" class="date">{{ m.release_date }}</span>
            </div>
          </div>
        </div>
      </div>

      <el-empty v-if="!loading && items.length === 0" description="暂无数据，先登录抓取 TOP250" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Trophy, Key, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { loginJavdbTop250, getJavTop250 } from '@/api/jav'

const TOKEN_KEY = 'javdb_top250_token'

const token = ref(localStorage.getItem(TOKEN_KEY) || '')
const username = ref('')
const password = ref('')
const logging = ref(false)

const zone = ref('censored')
const onlyMissing = ref(false)
const loading = ref(false)
const items = ref([])
const total = ref(0)
const have = ref(0)
const missing = ref(0)

async function doLogin() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  logging.value = true
  try {
    const res = await loginJavdbTop250(username.value, password.value)
    token.value = res.token
    localStorage.setItem(TOKEN_KEY, res.token)
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '登录失败')
  } finally {
    logging.value = false
  }
}

function logout() {
  token.value = ''
  localStorage.removeItem(TOKEN_KEY)
  items.value = []
}

async function load() {
  if (!token.value) return
  loading.value = true
  try {
    const res = await getJavTop250({
      zone: zone.value,
      only_missing: onlyMissing.value,
      token: token.value,
    })
    items.value = res.items || []
    total.value = res.total || 0
    have.value = res.have || 0
    missing.value = res.missing || 0
  } catch (e) {
    const detail = e?.response?.data?.detail || ''
    ElMessage.error(detail || '抓取 TOP250 失败')
    if (detail.includes('Token')) logout()
  } finally {
    loading.value = false
  }
}

function reload(force = false) {
  load()
}

onMounted(() => {
  if (token.value) load()
})
</script>

<style scoped>
.top250 { max-width: 1200px; margin: 0 auto; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 15px; }
.login-bar { display: flex; align-items: flex-end; gap: 8px; flex-wrap: wrap; }
.filter-bar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.spacer { flex: 1; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 14px;
  margin-top: 4px;
}
.card {
  position: relative;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
  background: var(--el-bg-color);
}
.rank {
  position: absolute;
  top: 6px; left: 6px;
  z-index: 2;
  min-width: 24px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(0,0,0,0.6);
  color: #fff;
  font-weight: 700;
  font-size: 13px;
  text-align: center;
}
.rank.top { background: #f0a020; color: #4a2c00; }
.cover { width: 100%; height: 200px; display: block; background: var(--el-fill-color-light); }
.cover-ph { width: 100%; height: 200px; display: flex; align-items: center; justify-content: center; color: var(--el-text-color-secondary); font-size: 13px; }
.info { padding: 8px; }
.code-row { display: flex; align-items: center; justify-content: space-between; gap: 4px; }
.code { font-family: monospace; font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.title {
  font-size: 13px; line-height: 1.4; height: 36px; margin: 4px 0;
  overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.meta { display: flex; gap: 10px; font-size: 12px; color: var(--el-text-color-secondary); }
.score { color: #e05b5b; font-weight: 600; }
</style>
