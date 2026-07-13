<template>
  <div class="compare">
    <el-card class="control-card">
      <template #header>
        <div class="card-header">
          <span>本地与在线对比</span>
          <el-tag size="small" type="info">参考 javdb ChineseComparator</el-tag>
        </div>
      </template>

      <el-radio-group v-model="mode" style="margin-bottom: 16px">
        <el-radio-button label="actress">演员页 URL</el-radio-button>
        <el-radio-button label="keyword">关键词搜索</el-radio-button>
      </el-radio-group>

      <el-radio-group v-model="source" style="margin-bottom: 16px; margin-left: 16px">
        <el-radio-button label="javdb">JavDB</el-radio-button>
        <el-radio-button label="javbus">JavBus</el-radio-button>
      </el-radio-group>

      <el-form label-width="110px" label-position="right">
        <el-form-item :label="mode === 'actress' ? '演员页 URL' : '关键词'">
          <el-input
            v-model="inputValue"
            :placeholder="mode === 'actress' ? (source === 'javbus' ? 'https://www.javbus.com/star/xxx' : 'https://javdb.com/actors/xxx') : '演员名 / 系列'"
            clearable
          />
        </el-form-item>

        <el-form-item label="本地目录">
          <el-select
            v-model="directories"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="留空则使用配置的媒体目录"
            style="width: 100%"
          >
            <el-option v-for="d in mediaDirOptions" :key="d" :label="d" :value="d" />
          </el-select>
          <div class="dir-search">
            <span class="hint">或按演员名直接定位目录：</span>
            <el-input
              v-model="actorDirName"
              placeholder="演员名（自动匹配本地文件夹）"
              style="width: 220px; margin-right: 8px"
              @keyup.enter="searchDirsByActor"
            />
            <el-button :loading="searchingDirs" @click="searchDirsByActor">
              <el-icon><Search /></el-icon> 搜索目录
            </el-button>
            <span v-if="dirSearchCount !== null" class="hint">匹配到 {{ dirSearchCount }} 个目录</span>
          </div>
        </el-form-item>

        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="最大爬取页数">
              <el-input-number v-model="maxPages" :min="1" :max="50" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="16">
            <el-form-item label="计入数据库">
              <el-switch v-model="includeDatabase" />
              <span class="hint">把数据库已刮削影片也计入本地集合</span>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item>
          <el-button type="primary" :loading="loading" @click="runCompare">
            <el-icon><Connection /></el-icon>
            开始在线对比
          </el-button>
          <el-button :loading="loadingLocal" @click="scanLocalOnly">
            <el-icon><FolderOpened /></el-icon>
            仅扫描本地
          </el-button>
          <el-button :loading="loadingDb" @click="loadDbSummary">数据库汇总</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-row :gutter="16" class="stat-row" v-if="result">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ result.online_count }}</div>
          <div class="stat-label">在线影片</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ result.local_count }}</div>
          <div class="stat-label">本地影片</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card stat-warning">
          <div class="stat-value">{{ result.matched_count }}</div>
          <div class="stat-label">已匹配</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card stat-danger">
          <div class="stat-value">{{ result.missing_count }}</div>
          <div class="stat-label">未更新（在线有本地无）</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="local-summary-card" v-if="result && result.local_summary" shadow="never">
      <div class="local-summary">
        <span>本地汇总：</span>
        <el-tag type="success">中字 {{ result.local_summary.chinese || 0 }}</el-tag>
        <el-tag type="info">非中字 {{ result.local_summary.non_chinese || 0 }}</el-tag>
        <el-tag type="danger" v-if="result.local_summary.uncensored">破解 {{ result.local_summary.uncensored }}</el-tag>
        <el-tag>文件 {{ result.local_summary.from_file || 0 }}</el-tag>
        <el-tag>数据库 {{ result.local_summary.from_database || 0 }}</el-tag>
        <el-tag type="warning" v-if="result.chinese_mismatch_count">
          中字差异 {{ result.chinese_mismatch_count }}
        </el-tag>
        <span class="source" v-if="result.online_source">来源：{{ result.online_source }}</span>
      </div>
    </el-card>

    <el-card v-loading="loading" class="result-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane :label="`未更新 (${result?.missing_count || 0})`" name="missing">
          <el-empty v-if="!result || !result.missing_videos?.length" description="没有未更新的影片" />
          <el-table v-else :data="result.missing_videos" stripe max-height="560">
            <el-table-column prop="code" label="番号" width="140" />
            <el-table-column prop="title" label="标题" show-overflow-tooltip />
            <el-table-column prop="date" label="日期" width="120" />
            <el-table-column label="中字" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.has_chinese" type="success" size="small">中字</el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="破解" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.is_uncensored" type="danger" size="small">破解</el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="160">
              <template #default="{ row }">
                <el-button v-if="row.url" size="small" link @click="openUrl(row.url)">查看</el-button>
                <el-button
                  size="small"
                  type="primary"
                  link
                  :loading="scrapingCodes.includes(row.code)"
                  @click="scrapeOne(row.code)"
                >刮削</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`中字差异 (${result?.chinese_mismatch_count || 0})`" name="chinese">
          <template #label>
            <span>中字差异 <el-badge v-if="result?.chinese_mismatch_count" :value="result.chinese_mismatch_count" type="warning" /></span>
          </template>
          <el-alert
            title="在线为中字版本，但本地是非中字（英文版）"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 12px"
          />
          <el-empty v-if="!result || !result.chinese_mismatch?.length" description="没有中字差异" />
          <el-table v-else :data="result.chinese_mismatch" stripe max-height="560">
            <el-table-column prop="code" label="番号" width="140" />
            <el-table-column prop="online_title" label="在线标题" show-overflow-tooltip />
            <el-table-column label="在线中字" width="100">
              <template #default>
                <el-tag type="success" size="small">是</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="本地中字" width="100">
              <template #default="{ row }">
                <el-tag :type="row.local_is_chinese ? 'success' : 'danger'" size="small">
                  {{ row.local_is_chinese ? '是' : '否（英文）' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="local_source" label="本地来源" width="100" />
            <el-table-column prop="local_file_path" label="本地路径" show-overflow-tooltip />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button v-if="row.online_url" size="small" link @click="openUrl(row.online_url)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`本地独有 (${result?.local_only_count || 0})`" name="local">
          <el-empty v-if="!result || !result.local_only?.length" description="本地没有在线缺失的影片" />
          <el-table v-else :data="result.local_only" stripe max-height="560">
            <el-table-column prop="code" label="番号" width="140" />
            <el-table-column label="中字" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.is_chinese" type="success" size="small">中字</el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="破解" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.is_uncensored" type="danger" size="small">破解</el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="source" label="来源" width="100" />
            <el-table-column prop="title" label="标题" show-overflow-tooltip />
            <el-table-column prop="file_path" label="路径" show-overflow-tooltip />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, FolderOpened, Search } from '@element-plus/icons-vue'
import { compareOnline, scanLocal, localDatabaseSummary, getConfig, compareSearchDirectories, scrapeByCode } from '@/api'

const mode = ref('actress')
const source = ref('javbus')
const inputValue = ref('')
const directories = ref([])
const mediaDirOptions = ref([])
const maxPages = ref(10)
const includeDatabase = ref(true)

const loading = ref(false)
const loadingLocal = ref(false)
const loadingDb = ref(false)
const result = ref(null)
const activeTab = ref('missing')

// 按演员名搜索本地目录
const actorDirName = ref('')
const searchingDirs = ref(false)
const dirSearchCount = ref(null)

// 正在刮削的番号集合
const scrapingCodes = ref([])

const loadConfig = async () => {
  try {
    const cfg = await getConfig()
    const scraper = cfg.scraper || cfg.data?.scraper || {}
    mediaDirOptions.value = scraper.media_dirs || []
  } catch (e) {
    console.error('加载配置失败', e)
  }
}

const runCompare = async () => {
  if (!inputValue.value) {
    ElMessage.warning(mode.value === 'actress' ? '请输入演员页 URL' : '请输入关键词')
    return
  }
  loading.value = true
  result.value = null
  activeTab.value = 'missing'
  try {
    const payload = {
      directories: directories.value,
      include_database: includeDatabase.value,
      max_pages: maxPages.value,
      source: source.value,
    }
    if (mode.value === 'actress') {
      payload.actress_url = inputValue.value
    } else {
      payload.keyword = inputValue.value
    }
    const res = await compareOnline(payload)
    result.value = res.items ? res : res.data || res
    if (result.value.status === 'empty') {
      ElMessage.warning(result.value.message || '未获取到在线列表')
    } else {
      ElMessage.success(`对比完成：未更新 ${result.value.missing_count}，中字差异 ${result.value.chinese_mismatch_count}`)
    }
  } catch (e) {
    ElMessage.error('对比失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

const scanLocalOnly = async () => {
  loadingLocal.value = true
  try {
    const res = await scanLocal(directories.value)
    const data = res.items ? res : res.data || res
    result.value = {
      online_count: 0,
      local_count: data.local_summary?.total || 0,
      matched_count: 0,
      missing_count: 0,
      chinese_mismatch_count: 0,
      local_only_count: 0,
      missing_videos: [],
      chinese_mismatch: [],
      local_only: [],
      local_summary: data.local_summary,
      online_source: 'local-scan',
    }
    ElMessage.success(`本地扫描完成：共 ${data.local_summary?.total || 0} 个`)
  } catch (e) {
    ElMessage.error('扫描失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loadingLocal.value = false
  }
}

const loadDbSummary = async () => {
  loadingDb.value = true
  try {
    const res = await localDatabaseSummary()
    const data = res.items ? res : res.data || res
    result.value = {
      online_count: 0,
      local_count: data.local_summary?.total || 0,
      matched_count: 0,
      missing_count: 0,
      chinese_mismatch_count: 0,
      local_only_count: 0,
      missing_videos: [],
      chinese_mismatch: [],
      local_only: [],
      local_summary: data.local_summary,
      online_source: 'database',
    }
    ElMessage.success(`数据库汇总完成：共 ${data.local_summary?.total || 0} 个`)
  } catch (e) {
    ElMessage.error('加载失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loadingDb.value = false
  }
}

const searchDirsByActor = async () => {
  if (!actorDirName.value.trim()) {
    ElMessage.warning('请输入演员名')
    return
  }
  searchingDirs.value = true
  dirSearchCount.value = null
  try {
    const res = await compareSearchDirectories(actorDirName.value.trim())
    const data = res.data || res
    const dirs = data.directories || []
    dirSearchCount.value = data.matched_count ?? dirs.length
    if (dirs.length) {
      // 合并进已选目录（去重）
      const merged = Array.from(new Set([...directories.value, ...dirs]))
      directories.value = merged
      ElMessage.success(`匹配到 ${dirs.length} 个目录，已加入扫描范围`)
    } else {
      ElMessage.warning('未找到匹配的本地目录，可手动添加')
    }
  } catch (e) {
    ElMessage.error('搜索目录失败：' + (e.response?.data?.detail || e.message))
  } finally {
    searchingDirs.value = false
  }
}

const scrapeOne = async (code) => {
  if (scrapingCodes.value.includes(code)) return
  scrapingCodes.value.push(code)
  try {
    const res = await scrapeByCode(code)
    const data = res.data || res
    if (data.status === 'ok') {
      ElMessage.success(`刮削成功：${code}（来源 ${data.source || '未知'}）`)
      // 从「未更新」列表移除已刮削项
      if (result.value?.missing_videos) {
        result.value.missing_videos = result.value.missing_videos.filter(v => v.code !== code)
        result.value.missing_count = result.value.missing_videos.length
      }
    } else {
      ElMessage.warning(`刮削未命中：${code}（${data.message || '无匹配数据'}）`)
    }
  } catch (e) {
    ElMessage.error(`刮削失败：${code} - ${e.response?.data?.detail || e.message}`)
  } finally {
    scrapingCodes.value = scrapingCodes.value.filter(c => c !== code)
  }
}

const openUrl = (url) => {
  if (url) window.open(url, '_blank')
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.compare {
  max-width: 1200px;
  margin: 0 auto;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.control-card {
  margin-bottom: 16px;
}
.hint {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
.dir-search {
  margin-top: 10px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.stat-row {
  margin-bottom: 16px;
}
.stat-card {
  text-align: center;
  padding: 8px 0;
}
.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: #409eff;
}
.stat-warning .stat-value {
  color: #e6a23c;
}
.stat-danger .stat-value {
  color: #f56c6c;
}
.stat-label {
  color: #909399;
  font-size: 13px;
  margin-top: 4px;
}
.local-summary-card {
  margin-bottom: 16px;
}
.local-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.local-summary .source {
  margin-left: auto;
  color: #909399;
  font-size: 12px;
}
.result-card {
  min-height: 300px;
}
</style>
