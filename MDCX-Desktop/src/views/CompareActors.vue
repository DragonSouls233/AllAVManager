<template>
  <div class="compare-actors-page">
    <el-card shadow="never" class="intro-card">
      <div class="intro">
        <el-icon size="28"><UserFilled /></el-icon>
        <div>
          <h3>{{ moduleLabel }} - 对比演员库</h3>
          <p>为每个演员配置对应的在线演员页URL和本地目录，后续对比时只需选演员即可执行，无需重复输入。
            <template v-if="isUncensored">当前为无码库，自动读取 JavBus / JavDB 的 uncensored 分区。</template>
            <template v-else>对比源：JavBus / JavDB / JavBooks / Avmoo；支持「探测」按钮自动搜索填写URL。</template>
          </p>
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

        <el-button type="warning" :loading="detectingAll" @click="handleDetectAll">
          <el-icon><Aim /></el-icon> 批量探测女优页
        </el-button>
        <el-checkbox v-model="overwriteDetectAll" class="overwrite-check">覆盖已配置</el-checkbox>

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

        <el-table-column label="数据源" width="110" align="center">
          <template #default="{ row }">
            <template v-if="row.compare_configs?.length">
              <el-tag
                v-for="cfg in row.compare_configs"
                :key="cfg.source"
                size="small"
                :type="SOURCE_COLORS[cfg.source] || 'info'"
                style="margin: 1px 2px"
              >{{ sourceLabel(cfg.source) }}</el-tag>
            </template>
            <span v-else class="no-config">-</span>
          </template>
        </el-table-column>

        <el-table-column label="在线URL" min-width="280">
          <template #default="{ row }">
            <div class="url-cell" v-if="editingId === row.id">
              <el-select v-model="editSource" size="small" style="width: 110px; margin-right: 4px">
                <el-option label="JavBus" value="javbus" />
                <el-option label="JavDB" value="javdb" />
                <el-option label="JavBooks" value="javbooks" />
                <el-option label="Avmoo" value="avmoo" />
              </el-select>
              <el-input
                v-model="editUrl"
                size="small"
                placeholder="https://www.javbus.com/star/xxx"
                style="flex: 1"
              />
            </div>
            <template v-else>
              <!-- 固定展示 4 个数据源槽位（JavBus / JavDB / JavBooks / Avmoo），未配置的源显示占位 -->
              <div v-for="src in ALL_SOURCES" :key="src" class="url-line">
                <span class="url-source">{{ sourceLabel(src) }}</span>
                <span v-if="cfgMap(row)[src]?.url" class="url-text" :title="cfgMap(row)[src].url">{{ cfgMap(row)[src].url }}</span>
                <span v-else class="no-config">未配置URL</span>
              </div>
            </template>
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

        <el-table-column label="操作" width="240" fixed="right">
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
                type="warning"
                link
                :loading="detectUrlId === row.id"
                @click="detectUrl(row)"
              >
                <el-icon><Aim /></el-icon> 探测
              </el-button>
              <el-button
                size="small"
                type="danger"
                link
                :loading="comparingAllId === row.id"
                @click="runCompareAll(row)"
              >
                <el-icon><Connection /></el-icon> 多源对比
              </el-button>
              <!-- 每个已配置URL的数据源各一个对比按钮，方便切换 JavBus / JavDB -->
              <template v-if="row.compare_configs && row.compare_configs.filter(c => c.url).length">
                <el-button
                  v-for="cfg in row.compare_configs.filter(c => c.url)"
                  :key="cfg.source"
                  size="small"
                  type="success"
                  link
                  :loading="comparingId === row.id && comparingSource === cfg.source"
                  @click="runCompare(row, cfg.source)"
                >
                  <el-icon><Connection /></el-icon> {{ sourceLabel(cfg.source) }}对比
                </el-button>
              </template>
              <el-button
                v-else
                size="small"
                type="success"
                link
                :loading="comparingId === row.id"
                @click="runCompare(row, '')"
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
    <el-dialog v-model="resultVisible" title="对比结果" width="94%" top="4vh">
      <template v-if="compareResult">
        <!-- ===== 单源模式头部统计 ===== -->
        <el-row v-if="!compareResult.sources" :gutter="16" class="stat-row">
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

        <!-- ===== 双源模式：每源一个统计卡片 ===== -->
        <el-row v-else :gutter="12" class="stat-row">
          <el-col :span="12" v-for="(srcRes, srcKey) in compareResult.sources" :key="srcKey">
            <div class="source-block" :class="'source-' + srcRes.status">
              <div class="source-block-title">
                <span class="source-block-name">{{ sourceLabel(srcKey) }}</span>
                <el-tag size="small" :type="srcRes.status === 'ok' ? 'success' : (srcRes.status === 'empty' ? 'info' : 'danger')">
                  {{ srcRes.status === 'ok' ? '正常' : (srcRes.status === 'empty' ? '无数据' : '失败') }}
                </el-tag>
                <span v-if="srcRes.status !== 'ok'" class="source-block-msg">{{ srcRes.message || srcRes.detail }}</span>
              </div>
              <div v-if="srcRes.status === 'ok'" class="source-stats">
                <div class="stat-item"><div class="stat-val">{{ srcRes.online_count }}</div><div class="stat-label">在线</div></div>
                <div class="stat-item"><div class="stat-val">{{ srcRes.local_count }}</div><div class="stat-label">本地</div></div>
                <div class="stat-item stat-warning"><div class="stat-val">{{ srcRes.matched_count }}</div><div class="stat-label">已匹配</div></div>
                <div class="stat-item stat-danger"><div class="stat-val">{{ srcRes.missing_count }}</div><div class="stat-label">未更新</div></div>
                <div class="stat-item stat-danger"><div class="stat-val">{{ srcRes.chinese_mismatch_count }}</div><div class="stat-label">中字差异</div></div>
                <div class="stat-item"><div class="stat-val">{{ srcRes.local_only_count }}</div><div class="stat-label">本地独有</div></div>
              </div>
            </div>
          </el-col>
        </el-row>

        <!-- 单源本地汇总 -->
        <div v-if="!compareResult.sources && compareResult.local_summary" class="result-summary">
          <el-tag type="success" size="small">中字 {{ compareResult.local_summary.chinese || 0 }}</el-tag>
          <el-tag type="info" size="small">非中字 {{ compareResult.local_summary.non_chinese || 0 }}</el-tag>
          <el-tag type="danger" size="small" v-if="compareResult.local_summary.uncensored">破解 {{ compareResult.local_summary.uncensored }}</el-tag>
          <el-tag size="small">文件 {{ compareResult.local_summary.from_file || 0 }}</el-tag>
          <el-tag size="small">数据库 {{ compareResult.local_summary.from_database || 0 }}</el-tag>
          <el-tag v-if="compareResult.chinese_mismatch_count" type="warning" size="small">中字差异 {{ compareResult.chinese_mismatch_count }}</el-tag>
        </div>

        <!-- ===== 双源模式：外层按源切换 ===== -->
        <el-tabs v-if="compareResult.sources" v-model="sourceTab" class="result-tabs">
          <el-tab-pane
            v-for="(srcRes, srcKey) in compareResult.sources"
            :key="srcKey"
            :name="srcKey"
            :label="`${sourceLabel(srcKey)} (缺 ${srcRes.missing_count || 0})`"
          >
            <el-empty v-if="srcRes.status !== 'ok'" :description="srcRes.message || srcRes.detail || '该数据源无数据'" />
          </el-tab-pane>
        </el-tabs>

        <!-- ===== 内层 tabs（单源=整个结果，双源=当前选中源） ===== -->
        <el-tabs v-if="activePane" v-model="resultTab" class="result-tabs">
          <el-tab-pane :label="`未更新 (${activePane.missing_count || 0})`" name="missing">
            <div class="tab-toolbar">
              <el-button size="small" type="primary" plain :disabled="!activePane.missing_videos?.length" @click="copyAllMagnets(activePane.missing_videos)">
                <el-icon><CopyDocument /></el-icon> 一键复制全部磁力
              </el-button>
              <span class="tab-hint">磁力带 C/UC 后缀或中文标记默认判定为中文版</span>
            </div>
            <el-empty v-if="!activePane.missing_videos?.length" description="没有未更新的影片" />
            <el-table v-else :data="activePane.missing_videos" stripe max-height="460" size="small">
              <el-table-column prop="code" label="番号" width="120" />
              <el-table-column prop="title" label="标题" show-overflow-tooltip />
              <el-table-column prop="date" label="日期" width="90" />
              <el-table-column label="中字" width="65">
                <template #default="{ row }"><el-tag v-if="row.has_chinese" type="success" size="small">中字</el-tag><span v-else>-</span></template>
              </el-table-column>
              <el-table-column label="磁力" width="210">
                <template #default="{ row }">
                  <div v-if="row.magnets?.length" class="magnet-cell">
                    <el-tag v-if="bestMagnet(row).chinese" type="success" size="small">中文</el-tag>
                    <span class="magnet-name" :title="bestMagnet(row).name">{{ bestMagnet(row).name || bestMagnet(row).size || '磁力' }}</span>
                    <div class="magnet-actions">
                      <el-button size="small" link type="primary" @click="copyMagnet(row)">复制</el-button>
                      <el-button size="small" link type="success" @click="openMagnet(row)">打开</el-button>
                    </div>
                  </div>
                  <span v-else class="no-config">-</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="120" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" link @click="onScrape(row.code)">刮削</el-button>
                  <el-button v-if="row.url" size="small" link @click="openUrl(row.url)">查看</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane :label="`中字差异 (${activePane.chinese_mismatch_count || 0})`" name="chinese">
            <el-alert title="在线为中字版本，但本地是非中字；下方磁力为在线中字版，可一键复制下载替换" type="warning" :closable="false" show-icon style="margin-bottom:12px" />
            <el-empty v-if="!activePane.chinese_mismatch?.length" description="没有中字差异" />
            <el-table v-else :data="activePane.chinese_mismatch" stripe max-height="460" size="small">
              <el-table-column prop="code" label="番号" width="120" />
              <el-table-column prop="online_title" label="在线标题" show-overflow-tooltip />
              <el-table-column label="在线" width="70"><template #default><el-tag type="success" size="small">中字</el-tag></template></el-table-column>
              <el-table-column label="本地" width="70"><template #default="{ row }"><el-tag :type="row.local_is_chinese ? 'success' : 'danger'" size="small">{{ row.local_is_chinese ? '中字' : '英文' }}</el-tag></template></el-table-column>
              <el-table-column label="中字磁力" width="180">
                <template #default="{ row }">
                  <div v-if="row.magnets?.length" class="magnet-cell">
                    <span class="magnet-name" :title="bestMagnet(row).name">{{ bestMagnet(row).name || bestMagnet(row).size || '磁力' }}</span>
                    <div class="magnet-actions">
                      <el-button size="small" link type="primary" @click="copyMagnet(row)">复制</el-button>
                      <el-button size="small" link type="success" @click="openMagnet(row)">打开</el-button>
                    </div>
                  </div>
                  <span v-else class="no-config">-</span>
                </template>
              </el-table-column>
              <el-table-column prop="local_file_path" label="本地路径" show-overflow-tooltip />
            </el-table>
          </el-tab-pane>
          <el-tab-pane :label="`本地独有 (${activePane.local_only_count || 0})`" name="local">
            <el-empty v-if="!activePane.local_only?.length" description="没有本地独有的影片" />
            <el-table v-else :data="activePane.local_only" stripe max-height="460" size="small">
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
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UserFilled, Search, Refresh, Edit, Connection, Aim, FolderOpened, Folder, CopyDocument } from '@element-plus/icons-vue'
import {
  getCompareActors, saveActorCompareUrl, scanAllCompareActors,
  detectActorLocalDir, compareOnlineByActor, scrapeByCode, browseDir,
  detectActorCompareUrl, detectAllCompareUrls, runAllCompareByActor
} from '@/api'

const route = useRoute()

// 支持 prop 传入（无码包装器）或从路由路径自动检测：/uncensored/compare-actors → uncensored
const props = defineProps({ module: { type: String, default: null } })
const MODULE_NAMES = ['jav', 'fc2', 'uncensored', 'chinese', 'western', 'pornhub']
const currentModule = computed(() => {
  if (props.module) return props.module
  const seg = route.path.split('/')
  return MODULE_NAMES.includes(seg[1]) ? seg[1] : null
})
const MODULE_LABELS = {
  jav: 'JAV 有码', fc2: 'FC2', uncensored: 'JAV 无码',
  chinese: '国产', western: '欧美', pornhub: 'Pornhub'
}
const moduleLabel = computed(() => (currentModule.value ? MODULE_LABELS[currentModule.value] || currentModule.value : '中心数据库'))
const isUncensored = computed(() => currentModule.value === 'uncensored')

// 对比数据源显示名与颜色（与后端 _COMPARE_SOURCES 一致）
const SOURCE_LABELS = { javbus: 'JavBus', javdb: 'JavDB', javbooks: 'JavBooks', avmoo: 'Avmoo' }
const SOURCE_COLORS = { javbus: 'warning', javdb: 'primary', javbooks: 'success', avmoo: 'danger' }
const sourceLabel = (s) => SOURCE_LABELS[s] || s
const ALL_SOURCES = ['javbus', 'javdb', 'javbooks', 'avmoo']

// 把 compare_configs 转成 {source: cfg} 映射，供固定 4 源槽位渲染（未配置的源显示占位）
const cfgMap = (row) => {
  const m = {}
  for (const cfg of (row.compare_configs || [])) m[cfg.source] = cfg
  return m
}

const searchText = ref('')
const minMovies = ref(10)
const items = ref([])
const total = ref(0)
const loading = ref(false)
const scanning = ref(false)
const detectingAll = ref(false)
const overwriteDetectAll = ref(false)

// 编辑状态
const editingId = ref(null)
const editUrl = ref('')
const editSource = ref('javbus')
const editDir = ref('')
const savingId = ref(null)
const detectingId = ref(null)
const detectUrlId = ref(null)

// 对比状态
const comparingId = ref(null)
const comparingSource = ref('')
const comparingAllId = ref(null)
const comparing = ref(false)
const resultVisible = ref(false)
const resultTab = ref('missing')
const sourceTab = ref('javbus')
const compareResult = ref(null)

// 当前展示的面板：单源=整个结果；双源=当前选中源的结果
const activePane = computed(() => {
  if (!compareResult.value) return null
  if (!compareResult.value.sources) return compareResult.value
  return compareResult.value.sources[sourceTab.value] || null
})

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
    const res = await getCompareActors({ min_movies: minMovies.value, search: searchText.value || undefined, module: currentModule.value || undefined })
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
    const res = await scanAllCompareActors(minMovies.value, currentModule.value)
    const data = res.data || res
    ElMessage.success(data.message || '扫描完成')
    await loadActors()
  } catch (e) {
    ElMessage.error('扫描失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    scanning.value = false
  }
}

const handleDetectAll = async () => {
  const overwrite = overwriteDetectAll.value
  try {
    await ElMessageBox.confirm(
      `将对「作品数≥${minMovies.value}」的演员，逐个去 ${ALL_SOURCES.map(sourceLabel).join(' / ')} 自动探测女优页（约每 1 秒一个，可能耗时较久）。` +
      (overwrite
        ? '已勾选「覆盖已配置」：会重新探测并覆盖所有已保存的 URL。'
        : '已配置对应源的演员会自动跳过。') +
      '确定开始？',
      '批量探测女优页',
      { confirmButtonText: '开始探测', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  detectingAll.value = true
  try {
    const res = await detectAllCompareUrls({ min_movies: minMovies.value, only_missing: !overwrite, delay: 1.0, sources: ALL_SOURCES }, currentModule.value)
    const data = res.data || res
    const srcStats = data.sources || {}
    const parts = Object.entries(srcStats).map(([s, st]) =>
      `${sourceLabel(s)}: 成功 ${st.detected || 0}，未找到 ${st.not_found || 0}，失败 ${st.failed || 0}，跳过 ${st.skipped || 0}`
    )
    ElMessage.success(`批量探测完成` + (parts.length ? '：' + parts.join('；') : ''))
    await loadActors()
  } catch (e) {
    ElMessage.error('批量探测失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    detectingAll.value = false
  }
}

const detectUrl = async (row) => {
  detectUrlId.value = row.id
  try {
    const res = await detectActorCompareUrl(row.id, 'all', currentModule.value)
    const data = res.data || res
    if (data.results) {
      const parts = Object.entries(data.results).map(([s, r]) =>
        `${sourceLabel(s)}:${r.status === 'ok' ? '已保存' : (r.status === 'not_found' ? '未找到' : '失败')}`
      )
      if (data.status === 'ok') {
        ElMessage.success('探测完成：' + parts.join('，'))
      } else {
        ElMessage.warning(data.message || '探测完成：' + parts.join('，'))
      }
    } else if (data.status === 'ok') {
      ElMessage.success(`已探测并保存：${data.url}`)
    } else {
      ElMessage.warning(data.message || '未找到匹配的女优页')
    }
    await loadActors()
  } catch (e) {
    ElMessage.error('探测失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    detectUrlId.value = null
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
    }, currentModule.value)
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
    const res = await detectActorLocalDir(row.id, currentModule.value)
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
    const res = await browseDir('/', currentModule.value)
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
    const res = await browseDir(browserCurrentPath.value, currentModule.value)
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

const runCompare = async (row, source = '') => {
  comparingId.value = row.id
  comparingSource.value = source
  comparing.value = true
  resultVisible.value = true
  compareResult.value = null
  try {
    const res = await compareOnlineByActor(row.id, { source }, currentModule.value)
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
    comparingSource.value = ''
    comparing.value = false
  }
}

// ===== 双源对比 =====
const runCompareAll = async (row) => {
  comparingAllId.value = row.id
  resultVisible.value = true
  compareResult.value = null
  resultTab.value = 'missing'
  sourceTab.value = 'javbus'
  try {
    const res = await runAllCompareByActor(row.id, {
      sources: ALL_SOURCES,
      fetch_magnets: true,
      magnet_limit: 30,
    }, currentModule.value)
    const data = res.data || res
    compareResult.value = data
    if (data.sources) {
      const okParts = []
      const failParts = []
      for (const [s, r] of Object.entries(data.sources)) {
        const name = sourceLabel(s)
        if (r.status === 'ok') okParts.push(`${name}: 缺 ${r.missing_count || 0}，中字差异 ${r.chinese_mismatch_count || 0}`)
        else if (r.status === 'empty') failParts.push(`${name}: 无数据`)
        else failParts.push(`${name}: 失败`)
      }
      if (okParts.length) ElMessage.success(`多源对比完成：${okParts.join('，')}`)
      if (failParts.length) ElMessage.warning(failParts.join('，'))
    } else {
      ElMessage.success(`对比完成：未更新 ${data.missing_count || 0}`)
    }
    await loadActors()
  } catch (e) {
    ElMessage.error('多源对比失败: ' + (e.response?.data?.detail || e.message))
    resultVisible.value = false
  } finally {
    comparingAllId.value = null
  }
}

// ===== 磁力工具 =====
const bestMagnet = (row) => {
  const magnets = row?.magnets || []
  if (!magnets.length) return null
  return magnets.find(m => m.chinese) || magnets[0]
}

const copyMagnet = async (row) => {
  const m = bestMagnet(row)
  if (!m?.link) return
  try {
    await navigator.clipboard.writeText(m.link)
    ElMessage.success('磁力链接已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

const openMagnet = (row) => {
  const m = bestMagnet(row)
  if (m?.link) window.open(m.link, '_blank')
}

const copyAllMagnets = async (videos) => {
  const links = (videos || [])
    .map(bestMagnet)
    .filter(m => m?.link)
    .map(m => m.link)
  if (!links.length) {
    ElMessage.warning('没有可复制的磁力链接')
    return
  }
  try {
    await navigator.clipboard.writeText(links.join('\n'))
    ElMessage.success(`已复制 ${links.length} 条磁力链接`)
  } catch {
    ElMessage.error('复制失败')
  }
}

const onScrape = async (code) => {
  try {
    const res = await scrapeByCode(code)
    const data = res.data || res
    ElMessage.success(`刮削成功: ${code}`)
    if (activePane.value?.missing_videos) {
      activePane.value.missing_videos = activePane.value.missing_videos.filter(v => v.code !== code)
      activePane.value.missing_count = activePane.value.missing_videos.length
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

.overwrite-check {
  margin-left: 12px;
  font-size: 13px;
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

.url-line {
  display: flex;
  align-items: center;
  gap: 6px;
  line-height: 1.8;
}

.url-source {
  flex: none;
  font-size: 12px;
  color: #909399;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 0 6px;
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

/* 双源对比 */
.source-block {
  border-radius: 8px;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.source-block.source-ok { border-color: #b3e19d; background: #f0f9eb; }
.source-block.source-error { border-color: #fbc4c4; background: #fef0f0; }
.source-block.source-empty { border-color: var(--el-border-color-lighter); background: var(--el-fill-color-light); }
.source-block-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.source-block-name { font-size: 15px; font-weight: 700; color: #303133; }
.source-block-msg { font-size: 12px; color: #f56c6c; }
.source-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}
.source-stats .stat-item { padding: 6px 4px; }
.source-stats .stat-val { font-size: 18px; }

/* 结果 tab 工具栏与磁力 */
.tab-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.tab-hint {
  font-size: 12px;
  color: #909399;
}
.magnet-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.magnet-name {
  font-size: 12px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.magnet-actions {
  flex: none;
  display: flex;
  align-items: center;
}

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
