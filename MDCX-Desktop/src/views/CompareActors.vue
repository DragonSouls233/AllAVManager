<template>
  <div class="compare-actors-page">
    <el-card shadow="never" class="intro-card">
      <div class="intro">
        <el-icon size="28"><UserFilled /></el-icon>
        <div>
          <h3>对比演员库</h3>
          <p>为每个演员配置对应的在线演员页URL和本地目录，后续对比时只需选演员即可执行，无需重复输入。</p>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <el-input
          v-model="searchText"
          placeholder="搜索演员名..."
          clearable
          style="width: 260px"
          @keyup.enter="loadActors"
          @clear="loadActors"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>

        <el-input-number v-model="minMovies" :min="1" :max="100" style="width: 100px" />
        <span class="toolbar-label">部以上</span>

        <el-button type="primary" @click="loadActors">
          <el-icon><Search /></el-icon> 查询
        </el-button>

        <el-button type="success" :loading="scanning" @click="handleScan">
          <el-icon><Refresh /></el-icon> 自动扫描
        </el-button>

        <span class="toolbar-hint" v-if="total">共 {{ total }} 个演员</span>
      </div>
    </el-card>

    <el-card shadow="never" v-if="items.length" class="table-card">
      <el-table :data="items" stripe max-height="700" size="small">
        <el-table-column type="index" width="50" />

        <el-table-column prop="name" label="演员名" width="160" fixed>
          <template #default="{ row }">
            <span class="actor-name">{{ row.name }}</span>
            <span v-if="row.name_jp" class="name-jp">（{{ row.name_jp }}）</span>
          </template>
        </el-table-column>

        <el-table-column prop="movie_count" label="作品数" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small">{{ row.movie_count }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="数据源" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.compare_config" :type="row.compare_config.source === 'javbus' ? 'warning' : 'primary'" size="small">
              {{ row.compare_config.source === 'javbus' ? 'JavBus' : 'JavDB' }}
            </el-tag>
            <span v-else class="no-config">-</span>
          </template>
        </el-table-column>

        <el-table-column label="在线URL" min-width="280">
          <template #default="{ row }">
            <div class="url-cell" v-if="editingId === row.id">
              <el-select v-model="editSource" size="small" style="width: 90px; margin-right: 4px">
                <el-option label="JavBus" value="javbus" />
                <el-option label="JavDB" value="javdb" />
              </el-select>
              <el-input
                v-model="editUrl"
                size="small"
                placeholder="https://www.javbus.com/star/xxx"
                style="flex: 1"
              />
            </div>
            <span v-else-if="row.compare_config?.url" class="url-text" :title="row.compare_config.url">
              {{ row.compare_config.url }}
            </span>
            <span v-else class="no-config">未配置</span>
          </template>
        </el-table-column>

        <el-table-column label="本地目录" min-width="260">
          <template #default="{ row }">
            <div class="dir-cell" v-if="editingId === row.id">
              <el-input v-model="editDir" size="small" placeholder="留空自动探测" style="flex: 1" readonly @click="openDirBrowser" />
              <el-button size="small" type="primary" @click="openDirBrowser" title="浏览目录">
                <el-icon><FolderOpened /></el-icon>
              </el-button>
              <el-button size="small" @click="detectDir(row)" :loading="detectingId === row.id" title="自动探测">
                <el-icon><Search /></el-icon>
              </el-button>
            </div>
            <span v-else-if="row.compare_config?.local_directory" class="dir-text" :title="row.compare_config.local_directory">
              <el-icon v-if="row.compare_config.auto_detected_dir" title="自动探测"><Aim /></el-icon>
              {{ row.compare_config.local_directory }}
            </span>
            <span v-else class="no-config">未设置</span>
          </template>
        </el-table-column>

        <el-table-column label="上次对比" width="100" align="center">
          <template #default="{ row }">
            <span v-if="row.compare_config?.last_compare_at" class="time-text">
              {{ formatDate(row.compare_config.last_compare_at) }}
            </span>
            <span v-else class="no-config">-</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <template v-if="editingId === row.id">
              <el-button size="small" type="primary" @click="saveUrl(row)" :loading="savingId === row.id">保存</el-button>
              <el-button size="small" @click="cancelEdit">取消</el-button>
            </template>
            <template v-else>
              <el-button size="small" type="primary" link @click="startEdit(row)">
                <el-icon><Edit /></el-icon> 编辑
              </el-button>
              <el-button
                size="small"
                type="success"
                link
                :disabled="!row.compare_config?.url"
                :loading="comparingId === row.id"
                @click="runCompare(row)"
              >
                <el-icon><Connection /></el-icon> 对比
              </el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-empty v-else-if="!loading" description="暂无数据，请先查询或点击「自动扫描」" />

    <!-- 对比结果弹窗 -->
    <el-dialog v-model="resultVisible" title="对比结果" width="90%" top="5vh">
      <template v-if="compareResult">
        <el-row :gutter="16" class="stat-row">
          <el-col :span="6">
            <div class="stat-item"><div class="stat-val">{{ compareResult.online_count }}</div><div class="stat-label">在线影片</div></div>
          </el-col>
          <el-col :span="6">
            <div class="stat-item"><div class="stat-val">{{ compareResult.local_count }}</div><div class="stat-label">本地影片</div></div>
          </el-col>
          <el-col :span="6">
            <div class="stat-item stat-warning"><div class="stat-val">{{ compareResult.matched_count }}</div><div class="stat-label">已匹配</div></div>
          </el-col>
          <el-col :span="6">
            <div class="stat-item stat-danger"><div class="stat-val">{{ compareResult.missing_count }}</div><div class="stat-label">未更新</div></div>
          </el-col>
        </el-row>

        <div v-if="compareResult.local_summary" class="result-summary">
          <el-tag type="success" size="small">中字 {{ compareResult.local_summary.chinese || 0 }}</el-tag>
          <el-tag type="info" size="small">非中字 {{ compareResult.local_summary.non_chinese || 0 }}</el-tag>
          <el-tag type="danger" size="small" v-if="compareResult.local_summary.uncensored">破解 {{ compareResult.local_summary.uncensored }}</el-tag>
          <el-tag size="small">文件 {{ compareResult.local_summary.from_file || 0 }}</el-tag>
          <el-tag size="small">数据库 {{ compareResult.local_summary.from_database || 0 }}</el-tag>
          <el-tag v-if="compareResult.chinese_mismatch_count" type="warning" size="small">中字差异 {{ compareResult.chinese_mismatch_count }}</el-tag>
        </div>

        <el-tabs v-model="resultTab" class="result-tabs">
          <el-tab-pane :label="`未更新 (${compareResult.missing_count || 0})`" name="missing">
            <el-empty v-if="!compareResult.missing_videos?.length" description="没有未更新的影片" />
            <el-table v-else :data="compareResult.missing_videos" stripe max-height="500" size="small">
              <el-table-column prop="code" label="番号" width="130" />
              <el-table-column prop="title" label="标题" show-overflow-tooltip />
              <el-table-column prop="date" label="日期" width="100" />
              <el-table-column label="中字" width="70">
                <template #default="{ row }"><el-tag v-if="row.has_chinese" type="success" size="small">中字</el-tag><span v-else>-</span></template>
              </el-table-column>
              <el-table-column label="操作" width="120">
                <template #default="{ row }">
                  <el-button size="small" type="primary" link @click="onScrape(row.code)">刮削</el-button>
                  <el-button v-if="row.url" size="small" link @click="openUrl(row.url)">查看</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane :label="`中字差异 (${compareResult.chinese_mismatch_count || 0})`" name="chinese">
            <el-alert title="在线为中字版本，但本地是非中字" type="warning" :closable="false" show-icon style="margin-bottom:12px" />
            <el-empty v-if="!compareResult.chinese_mismatch?.length" description="没有中字差异" />
            <el-table v-else :data="compareResult.chinese_mismatch" stripe max-height="500" size="small">
              <el-table-column prop="code" label="番号" width="130" />
              <el-table-column prop="online_title" label="在线标题" show-overflow-tooltip />
              <el-table-column label="在线" width="80"><template #default><el-tag type="success" size="small">中字</el-tag></template></el-table-column>
              <el-table-column label="本地" width="80"><template #default="{ row }"><el-tag :type="row.local_is_chinese ? 'success' : 'danger'" size="small">{{ row.local_is_chinese ? '中字' : '英文' }}</el-tag></template></el-table-column>
              <el-table-column prop="local_file_path" label="本地路径" show-overflow-tooltip />
            </el-table>
          </el-tab-pane>
          <el-tab-pane :label="`本地独有 (${compareResult.local_only_count || 0})`" name="local">
            <el-empty v-if="!compareResult.local_only?.length" description="没有本地独有的影片" />
            <el-table v-else :data="compareResult.local_only" stripe max-height="500" size="small">
              <el-table-column prop="code" label="番号" width="130" />
              <el-table-column label="中字" width="70"><template #default="{ row }"><el-tag v-if="row.is_chinese" type="success" size="small">中字</el-tag><span v-else>-</span></template></el-table-column>
              <el-table-column prop="source" label="来源" width="80" />
              <el-table-column prop="file_path" label="路径" show-overflow-tooltip />
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </template>
      <el-skeleton v-else :rows="6" animated />
    </el-dialog>

    <!-- 目录浏览弹窗 -->
    <el-dialog v-model="browserVisible" title="浏览目录" width="600px" top="8vh">
      <div class="dir-browser">
        <div class="dir-browser-path">
          <el-breadcrumb>
            <el-breadcrumb-item>
              <el-link type="primary" @click="navigateBrowser('')">根目录</el-link>
            </el-breadcrumb-item>
            <el-breadcrumb-item v-for="(seg, i) in browserPathSegments" :key="i">
              <el-link v-if="i < browserPathSegments.length - 1" type="primary" @click="navigateToIndex(i)">
                {{ seg }}
              </el-link>
              <span v-else>{{ seg }}</span>
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="dir-browser-path">
          <span class="dir-path-label">{{ browserCurrentPath }}</span>
        </div>
        <div class="dir-browser-list" v-loading="browserLoading">
          <div
            v-for="dir in browserDirs"
            :key="dir"
            class="dir-browser-item"
            @click="navigateBrowser(dir)"
            @dblclick="selectBrowserDir(dir)"
          >
            <el-icon><Folder /></el-icon>
            <span class="dir-name">{{ dir.split(/[/\\]/).pop() }}</span>
          </div>
          <el-empty v-if="!browserLoading && !browserDirs.length" description="该目录下没有子目录" />
        </div>
        <div class="dir-browser-actions">
          <el-button @click="browserVisible = false">取消</el-button>
          <el-button type="primary" @click="selectCurrentBrowserDir">选择此目录</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UserFilled, Search, Refresh, Edit, Connection, Aim, FolderOpened, Folder } from '@element-plus/icons-vue'
import {
  getCompareActors, saveActorCompareUrl, scanAllCompareActors,
  detectActorLocalDir, compareOnlineByActor, scrapeByCode, browseDir
} from '@/api'

const searchText = ref('')
const minMovies = ref(10)
const items = ref([])
const total = ref(0)
const loading = ref(false)
const scanning = ref(false)

// 编辑状态
const editingId = ref(null)
const editUrl = ref('')
const editSource = ref('javdb')
const editDir = ref('')
const savingId = ref(null)
const detectingId = ref(null)

// 对比状态
const comparingId = ref(null)
const comparing = ref(false)
const resultVisible = ref(false)
const resultTab = ref('missing')
const compareResult = ref(null)

// 目录浏览器状态
const browserVisible = ref(false)
const browserCurrentPath = ref('')
const browserDirs = ref([])
const browserLoading = ref(false)
const browserPathSegments = computed(() => {
  if (!browserCurrentPath.value) return []
  const sep = browserCurrentPath.value.includes('\\') ? '\\' : '/'
  return browserCurrentPath.value.split(sep).filter(Boolean)
})

function formatDate(d) {
  if (!d) return '-'
  const date = new Date(d)
  return `${date.getMonth() + 1}/${date.getDate()}`
}

const loadActors = async () => {
  loading.value = true
  try {
    const res = await getCompareActors({ min_movies: minMovies.value, search: searchText.value || undefined })
    const data = res.items || res.data?.items || []
    items.value = data
    total.value = res.total || res.data?.total || data.length
  } catch (e) {
    ElMessage.error('加载演员列表失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

const handleScan = async () => {
  scanning.value = true
  try {
    const res = await scanAllCompareActors(minMovies.value)
    const data = res.data || res
    ElMessage.success(data.message || '扫描完成')
    await loadActors()
  } catch (e) {
    ElMessage.error('扫描失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    scanning.value = false
  }
}

const startEdit = (row) => {
  editingId.value = row.id
  editUrl.value = row.compare_config?.url || ''
  editSource.value = row.compare_config?.source || 'javdb'
  editDir.value = row.compare_config?.local_directory || ''
}

const cancelEdit = () => {
  editingId.value = null
  editUrl.value = ''
  editDir.value = ''
}

const saveUrl = async (row) => {
  if (!editUrl.value.trim()) {
    ElMessage.warning('请输入演员页URL')
    return
  }
  savingId.value = row.id
  try {
    await saveActorCompareUrl(row.id, {
      source: editSource.value,
      url: editUrl.value.trim(),
      local_directory: editDir.value.trim() || null,
    })
    ElMessage.success('已保存')
    editingId.value = null
    await loadActors()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingId.value = null
  }
}

const detectDir = async (row) => {
  detectingId.value = row.id
  try {
    const res = await detectActorLocalDir(row.id)
    const data = res.data || res
    if (data.found) {
      editDir.value = data.matched || data.directories[0] || ''
      ElMessage.success(`探测到目录: ${editDir.value}`)
    } else {
      ElMessage.warning(data.message || '未找到本地目录')
    }
  } catch (e) {
    ElMessage.error('探测失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    detectingId.value = null
  }
}

const openDirBrowser = async () => {
  browserCurrentPath.value = editDir.value || (await getDefaultBrowsePath())
  browserVisible.value = true
  await loadBrowserDirs()
}

const getDefaultBrowsePath = async () => {
  try {
    const res = await browseDir('/')
    const data = res.data || res
    if (data.subdirectories?.length) {
      return data.subdirectories[0]
    }
  } catch {}
  return 'C:\\'
}

const loadBrowserDirs = async () => {
  browserLoading.value = true
  try {
    const res = await browseDir(browserCurrentPath.value)
    const data = res.data || res
    browserDirs.value = data.subdirectories || []
    browserCurrentPath.value = data.current_path || browserCurrentPath.value
  } catch (e) {
    ElMessage.error('浏览目录失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    browserLoading.value = false
  }
}

const navigateBrowser = async (dir) => {
  if (dir === '') {
    browserCurrentPath.value = ''
    return
  }
  browserCurrentPath.value = dir
  await loadBrowserDirs()
}

const navigateToIndex = async (index) => {
  const sep = browserCurrentPath.value.includes('\\') ? '\\' : '/'
  const parts = browserCurrentPath.value.split(sep).filter(Boolean)
  const newPath = parts.slice(0, index + 1).join(sep)
  if (browserCurrentPath.value.startsWith('/')) {
    browserCurrentPath.value = '/' + newPath
  } else {
    browserCurrentPath.value = newPath + sep
  }
  await loadBrowserDirs()
}

const selectBrowserDir = async (dir) => {
  editDir.value = dir
  browserVisible.value = false
  ElMessage.success(`已选择目录: ${dir}`)
}

const selectCurrentBrowserDir = () => {
  selectBrowserDir(browserCurrentPath.value)
}

const runCompare = async (row) => {
  comparingId.value = row.id
  comparing.value = true
  resultVisible.value = true
  compareResult.value = null
  try {
    const res = await compareOnlineByActor(row.id)
    const data = res.items ? res : res.data || res
    compareResult.value = data
    if (data.status === 'empty') {
      ElMessage.warning(data.message || '未获取到在线列表，请检查Cookie是否有效')
    } else {
      ElMessage.success(`对比完成：未更新 ${data.missing_count || 0}，中字差异 ${data.chinese_mismatch_count || 0}`)
    }
    await loadActors()
  } catch (e) {
    ElMessage.error('对比失败: ' + (e.response?.data?.detail || e.message))
    resultVisible.value = false
  } finally {
    comparingId.value = null
    comparing.value = false
  }
}

const onScrape = async (code) => {
  try {
    const res = await scrapeByCode(code)
    const data = res.data || res
    ElMessage.success(`刮削成功: ${code}`)
    if (compareResult.value?.missing_videos) {
      compareResult.value.missing_videos = compareResult.value.missing_videos.filter(v => v.code !== code)
      compareResult.value.missing_count = compareResult.value.missing_videos.length
    }
  } catch (e) {
    ElMessage.error(`刮削失败: ${code}`)
  }
}

const openUrl = (url) => {
  if (url) window.open(url, '_blank')
}

onMounted(() => {
  loadActors()
})
</script>

<style scoped>
.compare-actors-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1400px;
  margin: 0 auto;
}

.intro-card {
  border-radius: 10px;
  background: linear-gradient(135deg, #f0f9ff 0%, #ecf5ff 100%);
  border-color: #b3d8ff;
}

.intro {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.intro h3 { margin: 0 0 4px; font-size: 17px; color: #303133; }
.intro p { margin: 0; font-size: 13px; color: #606266; line-height: 1.6; }

.toolbar-card { border-radius: 10px; }

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar-label {
  font-size: 13px;
  color: #606266;
}

.toolbar-hint {
  margin-left: auto;
  font-size: 13px;
  color: #909399;
}

.table-card { border-radius: 10px; }

.actor-name {
  font-weight: 600;
  color: #303133;
}

.name-jp {
  color: #909399;
  font-size: 12px;
}

.no-config {
  color: #c0c4cc;
  font-style: italic;
  font-size: 12px;
}

.url-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}

.url-text {
  font-size: 12px;
  color: #409eff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
  max-width: 260px;
}

.dir-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}

.dir-text {
  font-size: 12px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 4px;
  max-width: 200px;
}

.time-text {
  font-size: 12px;
  color: #909399;
}

.stat-row { margin-bottom: 12px; }
.stat-item { text-align: center; padding: 8px; border-radius: 6px; background: var(--el-fill-color-light); }
.stat-item.stat-warning { background: #fdf6ec; }
.stat-item.stat-danger { background: #fef0f0; }
.stat-val { font-size: 24px; font-weight: 700; color: #409eff; }
.stat-warning .stat-val { color: #e6a23c; }
.stat-danger .stat-val { color: #f56c6c; }
.stat-label { font-size: 12px; color: #909399; margin-top: 2px; }
.result-summary { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.result-tabs { margin-top: 8px; }

.dir-browser { min-height: 300px; display: flex; flex-direction: column; gap: 8px; }
.dir-browser-path {
  background: var(--el-fill-color-light);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  word-break: break-all;
}
.dir-path-label { color: #909399; font-size: 12px; }
.dir-browser-list {
  flex: 1;
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 4px 0;
}
.dir-browser-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s;
  color: #409eff;
}
.dir-browser-item:hover { background: var(--el-color-primary-light-9); }
.dir-browser-item .dir-name { font-size: 13px; }
.dir-browser-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 8px;
}
</style>
