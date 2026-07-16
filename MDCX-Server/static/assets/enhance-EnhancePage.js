import { G as defineComponent, a0 as h, aj as resolveComponent, k as ref, p as reactive, w as computed, l as onMounted, z as onBeforeUnmount } from "./vendor-vue-uR07gohA.js";
import { b as ElMessage } from "./vendor-element-0uyBntp7.js";
import { e as api } from "./index-CZVICNFO.js";

const SECTIONS = [
  { key: 'downloads', label: '下载任务管理', icon: '📥' },
  { key: 'modules', label: '模块管理', icon: '🧩' },
  { key: 'sites', label: '站点注册表', icon: '🌐' },
  { key: 'emby-push', label: 'Emby 元数据推送', icon: '📤' },
  { key: 'mnamer', label: '智能重命名', icon: '🏷' },
  { key: 'fanart', label: 'Fanart 背景图', icon: '🖼' },
  { key: 'nfo', label: 'NFO 批量管理', icon: '📄' },
  { key: 'translate', label: '翻译功能', icon: '🌍' },
  { key: 'mosaic', label: '马赛克识别', icon: '🔍' },
  { key: 'auto-download', label: '订阅自动下载', icon: '📡' },
  { key: 'cookies', label: 'Cookie 管理', icon: '🍪' },
];

function safeArray(data) {
  if (Array.isArray(data)) return data;
  if (data && typeof data === 'object') {
    for (const key of ['data', 'items', 'records', 'list', 'results', 'sites', 'modules', 'movies', 'actors']) {
      if (Array.isArray(data[key])) return data[key];
    }
  }
  return [];
}

function apiGet(url) {
  return api.get(url.replace('/api/v1', '') || url, { params: { _t: Date.now() } })
    .then(r => r.data || r)
    .catch(e => { console.error(url, e); return null; });
}

function apiPost(url, data) {
  return api.post(url.replace('/api/v1', '') || url, data || {})
    .then(r => r.data || r)
    .catch(e => { console.error(url, e); return null; });
}

function apiPut(url, data) {
  return api.put(url.replace('/api/v1', '') || url, data || {})
    .then(r => r.data || r)
    .catch(e => { console.error(url, e); return null; });
}

function statusClass(s) {
  const m = { completed: 'ok', downloading: 'warn', paused: 'warn', cancelled: 'err', failed: 'err' };
  return m[s] || 'warn';
}

export default defineComponent({
  name: "EnhancePage",
  setup() {
    const activeTab = ref('downloads');
    const loading = reactive({ downloads: false, modules: false, sites: false, cookies: false });

    // ========== Downloads ==========
    const downloads = ref([]);
    const downloadStats = ref(null);
    const newDownloadUrl = ref('');

    async function fetchDownloads() {
      loading.downloads = true;
      const r = await apiGet('/api/v1/download/list');
      downloads.value = safeArray(r);
      const s = await apiGet('/api/v1/download/stats');
      downloadStats.value = s;
      loading.downloads = false;
    }
    async function cancelDownload(id) { await apiPost('/api/v1/download/cancel/' + id, {}); fetchDownloads(); }
    async function startDownload() {
      if (!newDownloadUrl.value) return ElMessage.warning('请输入 URL');
      await apiPost('/api/v1/download/start', { url: newDownloadUrl.value });
      ElMessage.success('下载已添加');
      newDownloadUrl.value = '';
      fetchDownloads();
    }

    // ========== Modules ==========
    const modules = ref([]);
    async function fetchModules() {
      loading.modules = true;
      const r = await apiGet('/api/v1/modules');
      modules.value = safeArray(r).map(m => ({ ...m, stats: {} }));
      for (const m of modules.value) {
        const s = await apiGet('/api/v1/modules/' + m.name + '/stats');
        if (s) m.stats = s;
      }
      loading.modules = false;
    }
    async function toggleModule(name) {
      await apiPost('/api/v1/modules/' + name + '/toggle', {});
      fetchModules();
    }
    async function scanModule(name) { await apiPost('/api/v1/modules/' + name + '/scan', {}); ElMessage.success('扫描任务已触发'); }

    // ========== Sites ==========
    const sites = ref([]);
    const siteSearch = ref('');
    const siteCategory = ref('');
    const siteCategories = ref([]);
    const filteredSites = computed(() => {
      let list = sites.value;
      if (siteSearch.value) { const q = siteSearch.value.toLowerCase(); list = list.filter(s => s.name?.toLowerCase().includes(q) || s.url?.toLowerCase().includes(q)); }
      if (siteCategory.value) list = list.filter(s => s.category === siteCategory.value);
      return list;
    });
    async function fetchSites() {
      loading.sites = true;
      const r = await apiGet('/api/v1/sites');
      sites.value = safeArray(r);
      const cats = [...new Set(sites.value.map(s => s.category).filter(Boolean))];
      siteCategories.value = cats;
      loading.sites = false;
    }

    // ========== Emby Push ==========
    const embyPushStatus = ref(null);
    const embyPushMovieId = ref('');
    const embySearchQuery = ref('');
    const embySearchResults = ref([]);
    async function fetchEmbyPushStatus() { embyPushStatus.value = await apiGet('/api/v1/emby-push/status'); }
    async function pushEmbyMovie() {
      if (!embyPushMovieId.value) return ElMessage.warning('请输入影片ID');
      await apiPost('/api/v1/emby-push/movie/' + embyPushMovieId.value, {});
      ElMessage.success('推送完成');
    }
    async function batchPushEmby() { await apiPost('/api/v1/emby-push/batch', {}); ElMessage.success('批量推送完成'); }
    async function refreshEmbyLibrary() { await apiPost('/api/v1/emby-push/refresh-library', {}); ElMessage.success('刷新任务已触发'); }
    async function searchEmby() {
      if (!embySearchQuery.value) return;
      const r = await apiGet('/api/v1/emby-push/search?q=' + encodeURIComponent(embySearchQuery.value));
      embySearchResults.value = safeArray(r);
    }

    // ========== mnamer ==========
    const mnamerHealth = ref(null);
    const mnamerFilepath = ref('');
    const mnamerCandidates = ref([]);
    async function fetchMnamerHealth() { mnamerHealth.value = await apiGet('/api/v1/mnamer/health'); }
    async function mnamerPreview() {
      if (!mnamerFilepath.value) return;
      const r = await apiPost('/api/v1/mnamer/candidates', { filepath: mnamerFilepath.value });
      mnamerCandidates.value = safeArray(r);
    }
    async function mnamerRename(name) {
      await apiPost('/api/v1/mnamer/rename', { filepath: mnamerFilepath.value, name });
      ElMessage.success('重命名完成');
    }

    // ========== Fanart ==========
    const fanartTmdbId = ref('');
    const fanartMovieId = ref('');
    const fanartResults = ref([]);
    async function searchFanart() {
      if (!fanartTmdbId.value) return;
      const r = await apiGet('/api/v1/fanart/search/' + fanartTmdbId.value);
      fanartResults.value = safeArray(r);
    }
    async function downloadFanart() {
      if (!fanartMovieId.value) return;
      await apiPost('/api/v1/fanart/download/' + fanartMovieId.value, {});
      ElMessage.success('下载完成');
    }

    // ========== NFO ==========
    const nfoMovieId = ref('');
    async function exportNfo() {
      if (!nfoMovieId.value) return;
      const r = await apiGet('/api/v1/nfo/movie/' + nfoMovieId.value);
      ElMessage.success('NFO 导出完成');
    }
    async function exportNfoFile() {
      if (!nfoMovieId.value) return;
      window.open('/api/v1/nfo/movie/' + nfoMovieId.value + '/file', '_blank');
    }
    async function batchExportNfo() {
      await apiPost('/api/v1/nfo/batch-export', {});
      ElMessage.success('批量导出任务已触发');
    }

    // ========== Translate ==========
    const translateText = ref('');
    const translateTarget = ref('zh');
    const translateResult = ref('');
    const translateMovieId = ref('');
    async function doTranslate() {
      if (!translateText.value) return;
      const r = await apiPost('/api/v1/translate', { text: translateText.value, target_lang: translateTarget.value });
      translateResult.value = r?.translated_text || r?.text || '';
    }
    async function translateMovie() {
      if (!translateMovieId.value) return;
      await apiPost('/api/v1/translate/movie', { movie_id: translateMovieId.value });
      ElMessage.success('翻译完成');
    }

    // ========== Mosaic ==========
    const mosaicMovieId = ref('');
    const mosaicResult = ref('');
    const mosaicPatterns = ref([]);
    async function identifyMosaic() {
      if (!mosaicMovieId.value) return;
      const r = await apiPost('/api/v1/mosaic/identify', { movie_id: mosaicMovieId.value });
      mosaicResult.value = typeof r === 'string' ? r : (r?.result || '已提交识别任务');
    }
    async function fetchMosaicPatterns() { mosaicPatterns.value = safeArray(await apiGet('/api/v1/mosaic/uncensored-patterns')); }

    // ========== Auto Download ==========
    const autoDownloadStatus = ref(null);
    async function fetchAutoDownloadStatus() { autoDownloadStatus.value = await apiGet('/api/v1/subscription-downloader/status'); }
    async function manualCheckDownload() { await apiPost('/api/v1/subscription-downloader/check', {}); ElMessage.success('检查完成'); }
    async function manualDownload() { await apiPost('/api/v1/subscription-downloader/download', {}); ElMessage.success('下载任务已触发'); }

    // ========== Cookies ==========
    const cookieSites = ref([]);
    const cookieDialog = reactive({ visible: false, site: '', cookie: '' });
    async function fetchCookieStatus() {
      loading.cookies = true;
      const r = await apiGet('/api/v1/config/cookie/status');
      cookieSites.value = Object.entries(r || {}).map(([site, d]) => ({ site, ...d })) || [];
      loading.cookies = false;
    }
    function showCookieDialog(site) { cookieDialog.site = site; cookieDialog.cookie = ''; cookieDialog.visible = true; }
    async function validateCookie(site) {
      const r = await apiPost('/api/v1/config/cookie/' + site + '/validate', {});
      ElMessage.info(r?.valid ? 'Cookie 有效' : 'Cookie 无效');
      fetchCookieStatus();
    }
    async function saveCookie() {
      await apiPut('/api/v1/config/cookie/' + cookieDialog.site, { cookie: cookieDialog.cookie });
      ElMessage.success('Cookie 已保存');
      cookieDialog.visible = false;
      fetchCookieStatus();
    }

    // Init
    onMounted(() => {
      fetchDownloads();
      fetchModules();
      fetchSites();
      fetchEmbyPushStatus();
      fetchMnamerHealth();
      fetchCookieStatus();
    });

    return {
      activeTab, loading,
      // Downloads
      downloads, downloadStats, newDownloadUrl, fetchDownloads, cancelDownload, startDownload,
      // Modules
      modules, fetchModules, toggleModule, scanModule,
      // Sites
      sites, siteSearch, siteCategory, siteCategories, filteredSites, fetchSites,
      // Emby
      embyPushStatus, embyPushMovieId, embySearchQuery, embySearchResults,
      fetchEmbyPushStatus, pushEmbyMovie, batchPushEmby, refreshEmbyLibrary, searchEmby,
      // mnamer
      mnamerHealth, mnamerFilepath, mnamerCandidates, fetchMnamerHealth, mnamerPreview, mnamerRename,
      // Fanart
      fanartTmdbId, fanartMovieId, fanartResults, searchFanart, downloadFanart,
      // NFO
      nfoMovieId, exportNfo, exportNfoFile, batchExportNfo,
      // Translate
      translateText, translateTarget, translateResult, translateMovieId, doTranslate, translateMovie,
      // Mosaic
      mosaicMovieId, mosaicResult, mosaicPatterns, identifyMosaic, fetchMosaicPatterns,
      // Auto Download
      autoDownloadStatus, fetchAutoDownloadStatus, manualCheckDownload, manualDownload,
      // Cookies
      cookieSites, cookieDialog, fetchCookieStatus, showCookieDialog, validateCookie, saveCookie,
      // Utils
      safeArray, statusClass, SECTIONS,
    };
  },
  render(ctx) {
    const $ = resolveComponent;
    const elTabs = $("el-tabs");
    const elTabPane = $("el-tab-pane");
    const elCard = $("el-card");
    const elButton = $("el-button");
    const elTable = $("el-table");
    const elTableColumn = $("el-table-column");
    const elTag = $("el-tag");
    const elInput = $("el-input");
    const elForm = $("el-form");
    const elFormItem = $("el-form-item");
    const elSelect = $("el-select");
    const elOption = $("el-option");
    const elSwitch = $("el-switch");
    const elProgress = $("el-progress");
    const elDialog = $("el-dialog");
    const elDescriptions = $("el-descriptions");
    const elDescriptionsItem = $("el-descriptions-item");
    const elDivider = $("el-divider");
    const elAlert = $("el-alert");

    const self = ctx;

    // Tab content builders
    function renderDownloads() {
      return [
        h(elCard, null, {
          default: () => [
            h('div', { style: 'display:flex;align-items:center;gap:12px;margin-bottom:12px' }, [
              h(elButton, { type: 'primary', size: 'small', onClick: self.fetchDownloads }, { default: () => '刷新列表' }),
              self.downloadStats ? h(elTag, { type: 'info' }, { default: () => '总计 ' + (self.downloadStats.total || self.downloadStats.data?.length || self.downloads.length) + ' 任务' }) : null,
            ]),
            h(elTable, { data: self.downloads, stripe: true, style: 'width:100%', vLoading: self.loading.downloads, emptyText: '暂无下载任务' }, {
              default: () => [
                h(elTableColumn, { prop: 'task_id', label: '任务ID', width: '180' }),
                h(elTableColumn, { label: '状态', width: '100' }, {
                  default: (s) => h('span', { class: 'tag-' + self.statusClass(s.row.status) }, s.row.status)
                }),
                h(elTableColumn, { prop: 'url', label: 'URL', minWidth: '200', showOverflowTooltip: true }),
                h(elTableColumn, { label: '进度', width: '120' }, {
                  default: (s) => h(elProgress, { percentage: s.row.progress || 0, status: s.row.status === 'completed' ? 'success' : undefined, 'stroke-width': 14 })
                }),
                h(elTableColumn, { label: '操作', width: '120', fixed: 'right' }, {
                  default: (s) => h(elButton, { size: 'small', type: 'danger', plain: true, onClick: () => self.cancelDownload(s.row.task_id), disabled: s.row.status === 'completed' || s.row.status === 'cancelled' }, { default: () => '取消' })
                }),
              ]
            }),
          ]
        }),
        h(elCard, null, {
          header: () => '添加下载任务',
          default: () => h(elForm, { model: {}, inline: true }, {
            default: () => [
              h(elFormItem, { label: 'URL' }, { default: () => h(elInput, { modelValue: self.newDownloadUrl, 'onUpdate:modelValue': (v) => self.newDownloadUrl = v, placeholder: '输入下载链接', style: 'width:400px' }) }),
              h(elFormItem, null, { default: () => h(elButton, { type: 'primary', onClick: self.startDownload }, { default: () => '开始下载' }) }),
            ]
          })
        }),
      ];
    }

    function renderModules() {
      return h(elCard, null, {
        default: () => [
          h(elButton, { size: 'small', onClick: self.fetchModules }, { default: () => '刷新' }),
          h(elTable, { data: self.modules, stripe: true, style: 'width:100%;margin-top:12px', vLoading: self.loading.modules }, {
            default: () => [
              h(elTableColumn, { prop: 'name', label: '模块名', width: '120' }),
              h(elTableColumn, { prop: 'title', label: '显示名称', width: '150' }),
              h(elTableColumn, { label: '状态', width: '100' }, {
                default: (s) => h(elSwitch, { modelValue: s.row.enabled, 'onUpdate:modelValue': () => self.toggleModule(s.row.name) })
              }),
              h(elTableColumn, { label: '影片数', width: '100' }, {
                default: (s) => s.row.stats?.movie_count || 0
              }),
              h(elTableColumn, { label: '演员数', width: '100' }, {
                default: (s) => s.row.stats?.actor_count || 0
              }),
              h(elTableColumn, { label: '操作', width: '160' }, {
                default: (s) => h(elButton, { size: 'small', type: 'primary', plain: true, onClick: () => self.scanModule(s.row.name) }, { default: () => '扫描' })
              }),
            ]
          }),
        ]
      });
    }

    function renderSites() {
      return h(elCard, null, {
        default: () => [
          h('div', { style: 'display:flex;align-items:center;gap:12px;margin-bottom:12px' }, [
            h(elInput, { modelValue: self.siteSearch, 'onUpdate:modelValue': (v) => self.siteSearch = v, placeholder: '搜索站点...', style: 'width:300px', clearable: true }),
            h(elSelect, { modelValue: self.siteCategory, 'onUpdate:modelValue': (v) => self.siteCategory = v, placeholder: '分类', clearable: true, style: 'width:150px' }, {
              default: () => self.siteCategories.map(c => h(elOption, { key: c, label: c, value: c }))
            }),
            h(elButton, { size: 'small', onClick: self.fetchSites }, { default: () => '查询' }),
          ]),
          h(elTable, { data: self.filteredSites, stripe: true, style: 'width:100%', vLoading: self.loading.sites }, {
            default: () => [
              h(elTableColumn, { prop: 'id', label: 'ID', width: '60' }),
              h(elTableColumn, { prop: 'name', label: '站点名称', width: '160' }),
              h(elTableColumn, { prop: 'url', label: 'URL', minWidth: '250', showOverflowTooltip: true }),
              h(elTableColumn, { prop: 'category', label: '分类', width: '100' }),
              h(elTableColumn, { label: '可刮削', width: '80' }, {
                default: (s) => h(elTag, { type: s.row.scrapable ? 'success' : 'info', size: 'small' }, { default: () => s.row.scrapable ? '是' : '否' })
              }),
            ]
          }),
        ]
      });
    }

    function renderEmbyPush() {
      return [
        h(elCard, null, {
          default: () => [
            h('div', { style: 'display:flex;align-items:center;gap:12px;margin-bottom:12px' }, [
              self.embyPushStatus ? h(elTag, { type: self.embyPushStatus.connected ? 'success' : 'danger' }, { default: () => '状态: ' + (self.embyPushStatus.connected ? '已连接' : '未连接') }) : null,
              self.embyPushStatus ? h(elTag, null, { default: () => '推送: ' + (self.embyPushStatus.push_count || 0) + ' 部' }) : null,
            ]),
            h(elForm, { model: {}, inline: true }, {
              default: () => [
                h(elFormItem, { label: '影片ID' }, { default: () => h(elInput, { modelValue: self.embyPushMovieId, 'onUpdate:modelValue': (v) => self.embyPushMovieId = v, placeholder: '输入影片ID', style: 'width:200px' }) }),
                h(elFormItem, null, { default: () => h(elButton, { type: 'primary', onClick: self.pushEmbyMovie }, { default: () => '推送元数据' }) }),
                h(elFormItem, null, { default: () => h(elButton, { type: 'warning', plain: true, onClick: self.batchPushEmby }, { default: () => '批量推送' }) }),
                h(elFormItem, null, { default: () => h(elButton, { plain: true, onClick: self.refreshEmbyLibrary }, { default: () => '刷新媒体库' }) }),
              ]
            }),
          ]
        }),
        h(elCard, null, {
          header: () => '搜索 Emby 中的影片',
          default: () => [
            h(elForm, { inline: true }, {
              default: () => [
                h(elFormItem, { label: '关键词' }, { default: () => h(elInput, { modelValue: self.embySearchQuery, 'onUpdate:modelValue': (v) => self.embySearchQuery = v, placeholder: '输入搜索关键词', style: 'width:300px' }) }),
                h(elFormItem, null, { default: () => h(elButton, { onClick: self.searchEmby }, { default: () => '搜索' }) }),
              ]
            }),
            self.embySearchResults.length ? h(elTable, { data: self.embySearchResults, stripe: true, style: 'width:100%' }, {
              default: () => [
                h(elTableColumn, { prop: 'Id', label: 'ID' }),
                h(elTableColumn, { prop: 'Name', label: '名称' }),
                h(elTableColumn, { prop: 'Path', label: '路径', showOverflowTooltip: true }),
              ]
            }) : null,
          ]
        }),
      ];
    }

    function renderMnamer() {
      return h(elCard, null, {
        default: () => [
          self.mnamerHealth ? h(elTag, { type: self.mnamerHealth.status === 'ok' ? 'success' : 'danger', style: 'margin-bottom:12px' }, { default: () => 'mnamer 服务: ' + (self.mnamerHealth.status === 'ok' ? '正常' : '异常') }) : null,
          h(elForm, { model: {}, labelWidth: '100' }, {
            default: () => [
              h(elFormItem, { label: '文件路径' }, { default: () => h(elInput, { modelValue: self.mnamerFilepath, 'onUpdate:modelValue': (v) => self.mnamerFilepath = v, placeholder: '输入文件路径进行预览', style: 'width:500px' }) }),
              h(elFormItem, null, { default: () => h(elButton, { type: 'primary', onClick: self.mnamerPreview }, { default: () => '预览候选命名' }) }),
            ]
          }),
          self.mnamerCandidates.length ? h(elTable, { data: self.mnamerCandidates, stripe: true, style: 'width:100%;margin-top:12px' }, {
            default: () => [
              h(elTableColumn, { prop: 'name', label: '候选名称' }),
              h(elTableColumn, { label: '操作', width: '120' }, {
                default: (s) => h(elButton, { size: 'small', type: 'primary', onClick: () => self.mnamerRename(s.row.name) }, { default: () => '执行重命名' })
              }),
            ]
          }) : null,
        ]
      });
    }

    function renderFanart() {
      return h(elCard, null, {
        default: () => [
          h(elForm, { inline: true }, {
            default: () => [
              h(elFormItem, { label: 'TMDB ID' }, { default: () => h(elInput, { modelValue: self.fanartTmdbId, 'onUpdate:modelValue': (v) => self.fanartTmdbId = v, placeholder: '输入 TMDB ID', style: 'width:200px' }) }),
              h(elFormItem, null, { default: () => h(elButton, { type: 'primary', onClick: self.searchFanart }, { default: () => '搜索 Fanart' }) }),
              h(elFormItem, { label: '影片ID' }, { default: () => h(elInput, { modelValue: self.fanartMovieId, 'onUpdate:modelValue': (v) => self.fanartMovieId = v, placeholder: '输入影片ID', style: 'width:200px' }) }),
              h(elFormItem, null, { default: () => h(elButton, { type: 'warning', plain: true, onClick: self.downloadFanart }, { default: () => '下载 Fanart' }) }),
            ]
          }),
          self.fanartResults.length ? h('div', { style: 'display:flex;flex-wrap:wrap;gap:12px;margin-top:12px' },
            self.fanartResults.map(f => h('div', { style: 'width:200px;text-align:center' }, [
              h('img', { src: f.url || f.image, style: 'width:100%;height:120px;object-fit:cover;border-radius:4px', alt: f.title || 'Fanart' }),
              h('p', { style: 'font-size:12px;margin-top:4px' }, f.title || ''),
            ]))
          ) : null,
        ]
      });
    }

    function renderNfo() {
      return h(elCard, null, {
        default: () => [
          h(elForm, { inline: true }, {
            default: () => [
              h(elFormItem, { label: '影片ID' }, { default: () => h(elInput, { modelValue: self.nfoMovieId, 'onUpdate:modelValue': (v) => self.nfoMovieId = v, placeholder: '输入影片ID', style: 'width:200px' }) }),
              h(elFormItem, null, { default: () => h(elButton, { onClick: self.exportNfo, type: 'primary' }, { default: () => '导出 NFO' }) }),
              h(elFormItem, null, { default: () => h(elButton, { onClick: self.exportNfoFile, type: 'success' }, { default: () => '下载 NFO 文件' }) }),
            ]
          }),
          h(elDivider),
          h('div', null, [
            h(elButton, { onClick: self.batchExportNfo, type: 'primary', plain: true }, { default: () => '批量导出 NFO' }),
          ]),
        ]
      });
    }

    function renderTranslate() {
      return h(elCard, null, {
        default: () => [
          h(elForm, { model: {}, labelWidth: '80' }, {
            default: () => [
              h(elFormItem, { label: '原文' }, { default: () => h(elInput, { modelValue: self.translateText, 'onUpdate:modelValue': (v) => self.translateText = v, type: 'textarea', rows: 3, placeholder: '输入要翻译的文本', style: 'width:500px' }) }),
              h(elFormItem, { label: '目标语言' }, {
                default: () => h(elSelect, { modelValue: self.translateTarget, 'onUpdate:modelValue': (v) => self.translateTarget = v, style: 'width:200px' }, {
                  default: () => [
                    h(elOption, { label: '中文', value: 'zh' }),
                    h(elOption, { label: '英文', value: 'en' }),
                    h(elOption, { label: '日语', value: 'ja' }),
                    h(elOption, { label: '韩语', value: 'ko' }),
                  ]
                })
              }),
              h(elFormItem, null, { default: () => h(elButton, { type: 'primary', onClick: self.doTranslate }, { default: () => '翻译' }) }),
            ]
          }),
          self.translateResult ? h(elInput, { modelValue: self.translateResult, 'onUpdate:modelValue': () => {}, type: 'textarea', rows: 3, readonly: true, placeholder: '翻译结果', style: 'margin-top:12px' }) : null,
          h(elDivider),
          h(elForm, { inline: true }, {
            default: () => [
              h(elFormItem, { label: '影片ID' }, { default: () => h(elInput, { modelValue: self.translateMovieId, 'onUpdate:modelValue': (v) => self.translateMovieId = v, style: 'width:200px', placeholder: '翻译影片元数据' }) }),
              h(elFormItem, null, { default: () => h(elButton, { onClick: self.translateMovie }, { default: () => '翻译影片' }) }),
            ]
          }),
        ]
      });
    }

    function renderMosaic() {
      return h(elCard, null, {
        default: () => [
          h(elForm, { model: {}, labelWidth: '100' }, {
            default: () => [
              h(elFormItem, { label: '影片ID' }, { default: () => h(elInput, { modelValue: self.mosaicMovieId, 'onUpdate:modelValue': (v) => self.mosaicMovieId = v, placeholder: '输入影片ID', style: 'width:300px' }) }),
              h(elFormItem, null, { default: () => h(elButton, { type: 'primary', onClick: self.identifyMosaic }, { default: () => '识别马赛克' }) }),
            ]
          }),
          self.mosaicResult ? h(elAlert, { title: self.mosaicResult, type: 'info', 'show-icon': true, closable: false, style: 'margin-bottom:12px' }) : null,
          h(elButton, { onClick: self.fetchMosaicPatterns, size: 'small' }, { default: () => '查看无码模式列表' }),
          self.mosaicPatterns.length ? h(elTable, { data: self.mosaicPatterns, stripe: true, style: 'width:100%;margin-top:12px', maxHeight: '300' }, {
            default: () => [
              h(elTableColumn, { prop: 'pattern', label: '模式', minWidth: '200' }),
              h(elTableColumn, { prop: 'description', label: '描述', minWidth: '300' }),
            ]
          }) : null,
        ]
      });
    }

    function renderAutoDownload() {
      return h(elCard, null, {
        default: () => [
          h(elButton, { onClick: self.fetchAutoDownloadStatus, size: 'small' }, { default: () => '刷新状态' }),
          self.autoDownloadStatus ? h('div', { style: 'margin-top:12px' }, [
            h(elDescriptions, { column: 2, border: true }, {
              default: () => [
                h(elDescriptionsItem, { label: '服务状态' }, { default: () => self.autoDownloadStatus.enabled ? '已启用' : '未启用' }),
                h(elDescriptionsItem, { label: '最近检查' }, { default: () => self.autoDownloadStatus.last_check || '从未' }),
                h(elDescriptionsItem, { label: '待下载项' }, { default: () => self.autoDownloadStatus.pending || 0 }),
                h(elDescriptionsItem, { label: '已下载' }, { default: () => self.autoDownloadStatus.downloaded || 0 }),
              ]
            }),
            h('div', { style: 'display:flex;gap:12px;margin-top:16px' }, [
              h(elButton, { type: 'primary', onClick: self.manualCheckDownload }, { default: () => '手动检查' }),
              h(elButton, { type: 'warning', plain: true, onClick: self.manualDownload }, { default: () => '手动下载' }),
            ]),
          ]) : null,
        ]
      });
    }

    function renderCookies() {
      return [
        h(elCard, null, {
          default: () => [
            h(elButton, { onClick: self.fetchCookieStatus, size: 'small' }, { default: () => '刷新 Cookie 状态' }),
            h(elTable, { data: self.cookieSites, stripe: true, style: 'width:100%;margin-top:12px', vLoading: self.loading.cookies }, {
              default: () => [
                h(elTableColumn, { prop: 'site', label: '站点', width: '150' }),
                h(elTableColumn, { label: '登录状态', width: '120' }, {
                  default: (s) => h(elTag, { type: s.row.logged_in ? 'success' : 'danger', size: 'small' }, { default: () => s.row.logged_in ? '已登录' : '未登录' })
                }),
                h(elTableColumn, { label: '操作', width: '350' }, {
                  default: (s) => [
                    h(elButton, { size: 'small', type: 'primary', plain: true, onClick: () => self.validateCookie(s.row.site) }, { default: () => '验证' }),
                    h(elButton, { size: 'small', onClick: () => self.showCookieDialog(s.row.site) }, { default: () => '设置 Cookie' }),
                  ]
                }),
              ]
            }),
          ]
        }),
        h(elDialog, { modelValue: self.cookieDialog.visible, 'onUpdate:modelValue': (v) => self.cookieDialog.visible = v, title: '设置 Cookie', width: '500' }, {
          default: () => [
            h(elForm, { model: self.cookieDialog }, {
              default: () => [
                h(elFormItem, { label: '站点' }, { default: () => self.cookieDialog.site }),
                h(elFormItem, { label: 'Cookie' }, { default: () => h(elInput, { modelValue: self.cookieDialog.cookie, 'onUpdate:modelValue': (v) => self.cookieDialog.cookie = v, type: 'textarea', rows: 4, placeholder: '粘贴 Cookie 字符串' }) }),
              ]
            }),
          ],
          footer: () => [
            h(elButton, { onClick: () => self.cookieDialog.visible = false }, { default: () => '取消' }),
            h(elButton, { type: 'primary', onClick: self.saveCookie }, { default: () => '保存' }),
          ]
        }),
      ];
    }

    const TAB_CONTENT = {
      'downloads': renderDownloads,
      'modules': renderModules,
      'sites': renderSites,
      'emby-push': renderEmbyPush,
      'mnamer': renderMnamer,
      'fanart': renderFanart,
      'nfo': renderNfo,
      'translate': renderTranslate,
      'mosaic': renderMosaic,
      'auto-download': renderAutoDownload,
      'cookies': renderCookies,
    };

    // Page-level styles
    const pageStyle = { padding: '0' };
    const headerStyle = { marginBottom: '20px' };
    const headerTitleStyle = { fontSize: '20px', fontWeight: '600', margin: '0 0 4px 0' };
    const headerDescStyle = { fontSize: '13px', color: '#909399', margin: '0' };

    return h('div', { style: pageStyle, class: 'enhance-page' }, [
      h('div', { style: headerStyle }, [
        h('h2', { style: headerTitleStyle }, '功能增强面板'),
        h('p', { style: headerDescStyle }, '集成管理功能，按标签页切换使用'),
      ]),
      h(elTabs, {
        modelValue: self.activeTab,
        'onUpdate:modelValue': (v) => self.activeTab = v,
        type: 'border-card',
        style: 'min-height:calc(100vh - 180px)',
      }, {
        default: () => self.SECTIONS.map(section =>
          h(elTabPane, {
            key: section.key,
            label: section.icon + ' ' + section.label,
            name: section.key,
            lazy: true,
          }, {
            default: () => {
              const renderFn = TAB_CONTENT[section.key];
              return renderFn ? renderFn() : h('div', '内容加载中...');
            }
          })
        )
      }),
    ]);
  }
});
