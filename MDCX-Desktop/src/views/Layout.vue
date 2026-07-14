<template>
  <div class="layout-root">
    <!-- 自定义标题栏（仅 Electron 环境） -->
    <TitleBar />
    <el-container class="layout-container">
    <!-- 跳到主内容（无障碍快捷导航） -->
    <a href="#main-content" class="skip-link">跳到主内容</a>
    <el-aside :width="collapsed ? '64px' : '220px'" class="sidebar" id="main-sidebar" role="navigation" aria-label="主导航">
      <div class="logo-area">
        <div class="logo-icon">
          <el-icon size="22"><VideoCamera /></el-icon>
        </div>
        <transition name="fade">
          <div v-show="!collapsed" class="logo-text">
            <h2>龙魂</h2>
            <span>视频管理系统</span>
          </div>
        </transition>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="collapsed"
        router
        class="menu"
        background-color="transparent"
        text-color="rgba(255,255,255,0.75)"
        active-text-color="#fff"
        :unique-opened="true"
      >
        <el-menu-item index="/">
          <el-icon><HomeFilled /></el-icon>
          <template #title>首页</template>
        </el-menu-item>

        <el-sub-menu index="modules">
          <template #title>
            <el-icon><Grid /></el-icon>
            <span>多模块</span>
          </template>
          <el-menu-item index="/movies">
            <el-icon><VideoCamera /></el-icon>
            <template #title>JAV 有码</template>
          </el-menu-item>
          <el-menu-item index="/uncensored" v-if="moduleEnabled.uncensored !== false">
            <el-icon><View /></el-icon>
            <template #title>JAV 无码</template>
          </el-menu-item>
          <el-menu-item index="/fc2" v-if="moduleEnabled.fc2 !== false">
            <el-icon><Film /></el-icon>
            <template #title>FC2</template>
          </el-menu-item>
          <el-menu-item index="/chinese">
            <el-icon><DataAnalysis /></el-icon>
            <template #title>国产</template>
          </el-menu-item>
          <el-menu-item index="/pornhub" v-if="moduleEnabled.pornhub !== false">
            <el-icon><Promotion /></el-icon>
            <template #title>PORNHub</template>
          </el-menu-item>
          <el-menu-item index="/western" v-if="moduleEnabled.western !== false">
            <el-icon><VideoCamera /></el-icon>
            <template #title>欧美</template>
          </el-menu-item>
          <el-menu-item index="/download" v-if="moduleEnabled.western !== false">
            <el-icon><Download /></el-icon>
            <template #title>下载管理</template>
          </el-menu-item>
          <el-menu-item index="/sites">
            <el-icon><Connection /></el-icon>
            <template #title>站点注册表</template>
          </el-menu-item>
          <el-menu-item index="/modules">
            <el-icon><Setting /></el-icon>
            <template #title>模块管理</template>
          </el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="content">
          <template #title>
            <el-icon><Files /></el-icon>
            <span>内容管理</span>
          </template>
          <el-menu-item index="/movies">
            <el-icon><VideoCamera /></el-icon>
            <template #title>番号库</template>
          </el-menu-item>
          <el-menu-item index="/actors">
            <el-icon><User /></el-icon>
            <template #title>演员</template>
          </el-menu-item>
          <el-menu-item index="/favorites">
            <el-icon><Star /></el-icon>
            <template #title>收藏夹</template>
          </el-menu-item>
          <el-menu-item index="/tags">
            <el-icon><PriceTag /></el-icon>
            <template #title>标签管理</template>
          </el-menu-item>
          <el-menu-item index="/studios">
            <el-icon><OfficeBuilding /></el-icon>
            <template #title>制片厂管理</template>
          </el-menu-item>
          <el-menu-item index="/tiers">
            <el-icon><Trophy /></el-icon>
            <template #title>分级治理</template>
          </el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="tools">
          <template #title>
            <el-icon><Tools /></el-icon>
            <span>系統工具</span>
          </template>
          <!-- 刮削核心 -->
          <el-menu-item index="/crawlers">
            <el-icon><Connection /></el-icon>
            <template #title>爬虫管理</template>
          </el-menu-item>
          <el-menu-item index="/site-priority">
            <el-icon><Sort /></el-icon>
            <template #title>站点优先级</template>
          </el-menu-item>
          <el-menu-item index="/naming-template">
            <el-icon><EditPen /></el-icon>
            <template #title>命名模板</template>
          </el-menu-item>
          <el-menu-item index="/compare">
            <el-icon><DataAnalysis /></el-icon>
            <template #title>本地对比</template>
          </el-menu-item>
          <el-menu-item index="/compare-actors">
            <el-icon><UserFilled /></el-icon>
            <template #title>对比演员库</template>
          </el-menu-item>
          <el-menu-item index="/patch">
            <el-icon><MagicStick /></el-icon>
            <template #title>补丁刮削</template>
          </el-menu-item>
          <el-menu-item index="/nfo-scrape">
            <el-icon><Document /></el-icon>
            <template #title>NFO 免改名刮削</template>
          </el-menu-item>
          <el-menu-item index="/source-merge">
            <el-icon><Management /></el-icon>
            <template #title>多来源数据精选</template>
          </el-menu-item>
          <!-- 导入与文件 -->
          <el-menu-item index="/import">
            <el-icon><Upload /></el-icon>
            <template #title>批量导入</template>
          </el-menu-item>
          <el-menu-item index="/webdav-import">
            <el-icon><Download /></el-icon>
            <template #title>WebDAV 导入</template>
          </el-menu-item>
          <el-menu-item index="/cloud-drive2">
            <el-icon><Cloudy /></el-icon>
            <template #title>CloudDrive2 网盘</template>
          </el-menu-item>
          <el-menu-item index="/pan-115">
            <el-icon><Cloudy /></el-icon>
            <template #title>115 网盘</template>
          </el-menu-item>
          <el-menu-item index="/unrecognized-files">
            <el-icon><WarningFilled /></el-icon>
            <template #title>未识别文件处理</template>
          </el-menu-item>
          <el-menu-item index="/face-crop">
            <el-icon><Avatar /></el-icon>
            <template #title>人脸裁剪</template>
          </el-menu-item>
          <el-menu-item index="/poster-enhance">
            <el-icon><PictureFilled /></el-icon>
            <template #title>海报增强</template>
          </el-menu-item>
          <el-menu-item index="/fingerprint">
            <el-icon><CopyDocument /></el-icon>
            <template #title>指纹去重</template>
          </el-menu-item>
          <el-menu-item index="/file-organize">
            <el-icon><FolderOpened /></el-icon>
            <template #title>文件整理</template>
          </el-menu-item>
          <el-menu-item index="/auto-organize">
            <el-icon><SetUp /></el-icon>
            <template #title>自动整理</template>
          </el-menu-item>
          <el-menu-item index="/refresh-folders">
            <el-icon><RefreshRight /></el-icon>
            <template #title>文件夹刷新</template>
          </el-menu-item>
          <el-menu-item index="/view-status">
            <el-icon><CircleCheck /></el-icon>
            <template #title>三态标记</template>
          </el-menu-item>
          <!-- 监测与通知 -->
          <el-menu-item index="/tasks">
            <el-icon><List /></el-icon>
            <template #title>任务管理</template>
          </el-menu-item>
          <el-menu-item index="/viewing-report">
            <el-icon><DataAnalysis /></el-icon>
            <template #title>观影报告</template>
          </el-menu-item>
          <el-menu-item index="/webhooks">
            <el-icon><Bell /></el-icon>
            <template #title>Webhook 通知</template>
          </el-menu-item>
          <!-- Cookie 与账号 -->
          <el-menu-item index="/cookiecloud">
            <el-icon><Connection /></el-icon>
            <template #title>CookieCloud 同步</template>
          </el-menu-item>
          <el-menu-item index="/cookie-manager">
            <el-icon><Key /></el-icon>
            <template #title>Cookie 管理器</template>
          </el-menu-item>
          <!-- 演员与订阅 -->
          <el-menu-item index="/metatube-plugin">
            <el-icon><Connection /></el-icon>
            <template #title>Metatube 插件</template>
          </el-menu-item>
          <el-menu-item index="/gfriends">
            <el-icon><Avatar /></el-icon>
            <template #title>Gfriends 头像库</template>
          </el-menu-item>
          <el-menu-item index="/subscriptions">
            <el-icon><StarFilled /></el-icon>
            <template #title>演员订阅</template>
          </el-menu-item>
          <el-menu-item index="/series-subscriptions">
            <el-icon><Collection /></el-icon>
            <template #title>系列订阅</template>
          </el-menu-item>
          <!-- 扩展功能 -->
          <el-menu-item index="/recommendations">
            <el-icon><Promotion /></el-icon>
            <template #title>智能推荐</template>
          </el-menu-item>
          <el-menu-item index="/movie-graph">
            <el-icon><Share /></el-icon>
            <template #title>影片图谱</template>
          </el-menu-item>
          <el-menu-item index="/plugins">
            <el-icon><Box /></el-icon>
            <template #title>插件系统</template>
          </el-menu-item>
          <el-menu-item index="/telegram-bot">
            <el-icon><ChatLineRound /></el-icon>
            <template #title>Telegram Bot</template>
          </el-menu-item>
          <el-menu-item index="/users">
            <el-icon><UserFilled /></el-icon>
            <template #title>用户管理</template>
          </el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="system">
          <template #title>
            <el-icon><Setting /></el-icon>
            <span>系統設置</span>
          </template>
          <el-menu-item index="/settings">
            <el-icon><Setting /></el-icon>
            <template #title>系统设置</template>
          </el-menu-item>
          <el-menu-item index="/network-diag">
            <el-icon><Connection /></el-icon>
            <template #title>网络诊断</template>
          </el-menu-item>
          <el-menu-item index="/proxy-xray">
            <el-icon><Lightning /></el-icon>
            <template #title>内置代理</template>
          </el-menu-item>
          <el-menu-item index="/themes">
            <el-icon><MagicStick /></el-icon>
            <template #title>皮肤主题</template>
          </el-menu-item>
          <el-menu-item index="/tvbox">
            <el-icon><VideoCamera /></el-icon>
            <template #title>TVBox/MacCMS</template>
          </el-menu-item>
          <el-menu-item index="/emby-config">
            <el-icon><Connection /></el-icon>
            <template #title>Emby 兼容</template>
          </el-menu-item>
          <el-menu-item index="/strm">
            <el-icon><Link /></el-icon>
            <template #title>STRM 生成</template>
          </el-menu-item>
          <el-menu-item index="/downloaders">
            <el-icon><Download /></el-icon>
            <template #title>下载器</template>
          </el-menu-item>
          <el-menu-item index="/workflows">
            <el-icon><Operation /></el-icon>
            <template #title>工作流</template>
          </el-menu-item>
          <el-menu-item index="/logs">
            <el-icon><Tickets /></el-icon>
            <template #title>系统日志</template>
          </el-menu-item>
          <el-menu-item index="/log-stream">
            <el-icon><Monitor /></el-icon>
            <template #title>实时日志流</template>
          </el-menu-item>
          <el-menu-item index="/files">
            <el-icon><FolderOpened /></el-icon>
            <template #title>文件管理</template>
          </el-menu-item>
          <el-menu-item index="/system-status">
            <el-icon><DataLine /></el-icon>
            <template #title>系统状态</template>
          </el-menu-item>
          <el-menu-item index="/mpv-settings">
            <el-icon><Monitor /></el-icon>
            <template #title>mpv 设置</template>
          </el-menu-item>
          <el-menu-item index="/desktop-settings">
            <el-icon><Platform /></el-icon>
            <template #title>桌面设置</template>
          </el-menu-item>
          <el-menu-item index="/schema-settings">
            <el-icon><Grid /></el-icon>
            <template #title>Schema 设置</template>
          </el-menu-item>
          <el-menu-item index="/deploy">
            <el-icon><Upload /></el-icon>
            <template #title>部署档位</template>
          </el-menu-item>
          <el-menu-item index="/backup">
            <el-icon><Box /></el-icon>
            <template #title>自动备份</template>
          </el-menu-item>
          <el-menu-item index="changelog" @click.prevent="openChangelog">
            <el-icon><Document /></el-icon>
            <template #title>更新日志</template>
          </el-menu-item>
          <el-menu-item index="check-update" @click.prevent="openUpdateDialog" v-if="isElectron">
            <el-icon><Download /></el-icon>
            <template #title>检查更新</template>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>

      <div class="sidebar-footer" v-show="!collapsed" @click="openChangelog" style="cursor: pointer;" title="点击查看更新日志">
        <span class="ver">v{{ versionInfo.version || '0.01' }}</span>
      </div>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-button text class="collapse-btn touch-target" @click="collapsed = !collapsed"
            :aria-label="collapsed ? '展开侧边栏' : '折叠侧边栏'"
            :aria-expanded="!collapsed"
            aria-controls="main-sidebar"
          >
            <el-icon size="18"><Fold v-if="!collapsed" /><Expand v-else /></el-icon>
          </el-button>
          <el-breadcrumb separator="/" class="breadcrumb" aria-label="面包屑导航">
            <el-breadcrumb-item :to="{ path: '/' }">
              <el-icon><HomeFilled /></el-icon>
            </el-breadcrumb-item>
            <el-breadcrumb-item>{{ pageTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <el-tooltip content="全局搜索" placement="bottom">
            <el-button text circle class="touch-target" @click="globalSearchVisible = true" aria-label="全局搜索">
              <el-icon size="18"><Search /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip :content="isDark ? '切换到亮色模式' : '切换到暗黑模式'" placement="bottom">
            <el-button text circle class="touch-target" @click="toggleDark"
              :aria-label="isDark ? '切换到亮色模式' : '切换到暗黑模式'"
              :aria-pressed="isDark"
            >
              <el-icon size="18">
                <Sunny v-if="isDark" />
                <Moon v-else />
              </el-icon>
            </el-button>
          </el-tooltip>
          <el-popover
            placement="bottom-end"
            :width="280"
            trigger="click"
            v-model:visible="nsfwPopoverVisible"
          >
            <template #reference>
              <el-tooltip :content="nsfwEnabled ? 'NSFW 模式：已开启' : 'NSFW 模式：已关闭'" placement="bottom">
                <el-button
                  text
                  circle
                  class="touch-target"
                  :class="['nsfw-btn', { 'nsfw-active': nsfwEnabled }]"
                  @click="nsfwPopoverVisible = !nsfwPopoverVisible"
                  :aria-label="nsfwEnabled ? 'NSFW 模式已开启,点击关闭' : 'NSFW 模式已关闭,点击开启'"
                  :aria-expanded="nsfwPopoverVisible"
                  aria-haspopup="dialog"
                >
                  <el-icon size="18">
                    <View v-if="nsfwEnabled" />
                    <Hide v-else />
                  </el-icon>
                </el-button>
              </el-tooltip>
            </template>
            <div class="nsfw-panel">
              <div class="nsfw-panel-title">NSFW 模式</div>
              <div class="nsfw-panel-desc">关闭后将隐藏封面、标题、演员头像等敏感内容</div>
              <div class="nsfw-panel-row">
                <span>启用 NSFW 模式</span>
                <el-switch v-model="nsfwEnabled" @change="onNsfwToggle" :loading="nsfwLoading" />
              </div>
              <el-divider />
              <div class="nsfw-panel-row">
                <span>隐藏封面</span>
                <el-switch v-model="nsfwConfig.hide_cover" @change="onNsfwConfigChange" />
              </div>
              <div class="nsfw-panel-row">
                <span>隐藏标题</span>
                <el-switch v-model="nsfwConfig.hide_title" @change="onNsfwConfigChange" />
              </div>
              <div class="nsfw-panel-row">
                <span>隐藏演员头像</span>
                <el-switch v-model="nsfwConfig.hide_actor_avatar" @change="onNsfwConfigChange" />
              </div>
              <div class="nsfw-panel-row">
                <span>模糊缩略图</span>
                <el-switch v-model="nsfwConfig.blur_thumbnails" @change="onNsfwConfigChange" />
              </div>
              <div class="nsfw-panel-row">
                <span>模糊强度</span>
                <el-slider
                  v-model="nsfwConfig.blur_intensity"
                  :min="1"
                  :max="50"
                  :disabled="!nsfwConfig.blur_thumbnails"
                  style="width: 120px"
                  @change="onNsfwConfigChange"
                />
              </div>
            </div>
          </el-popover>
          <!-- 自动更新通知（仅 Electron 环境） -->
          <el-tooltip v-if="isElectron && updateAvailable" :content="`新版本 ${updateVersion} 可用`" placement="bottom">
            <el-badge :value="'!'" type="primary" class="update-badge">
              <el-button text circle class="touch-target" @click="updateDialogVisible = true"
                :aria-label="`新版本 ${updateVersion} 可用,点击查看`"
              >
                <el-icon size="18"><Download /></el-icon>
              </el-button>
            </el-badge>
          </el-tooltip>
          <el-tooltip v-if="isElectron && updateDownloaded" content="更新已就绪，点击安装" placement="bottom">
            <el-button text circle type="success" class="touch-target" @click="installUpdate"
              aria-label="更新已就绪,点击安装并重启"
            >
              <el-icon size="18"><CircleCheck /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip content="刷新页面" placement="bottom">
            <el-button text circle class="touch-target" @click="refresh" aria-label="刷新页面">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip content="退出登录" placement="bottom">
            <el-button text circle class="touch-target" @click="logout" aria-label="退出登录">
              <el-icon><SwitchButton /></el-icon>
            </el-button>
          </el-tooltip>
          <el-divider direction="vertical" />
          <div class="user-info" aria-label="当前登录用户">
            <el-avatar :size="28" class="user-avatar" aria-hidden="true">
              <el-icon><User /></el-icon>
            </el-avatar>
            <span class="user-name">{{ currentUser }}</span>
          </div>
        </div>
      </el-header>

      <el-main class="main-content" id="main-content" role="main">
        <router-view v-slot="{ Component }">
          <transition name="fade-slide" mode="out-in">
            <keep-alive :max="20" :exclude="excludeCache">
              <component :is="Component" :key="$route.name" />
            </keep-alive>
          </transition>
        </router-view>
      </el-main>

      <!-- 底部状态栏：服务器状态 / 任务进度 / 统计信息 -->
      <el-footer class="status-bar" :height="'24px'">
        <div class="status-left">
          <span class="status-item" :class="`health-${healthLevel}`">
            <el-icon class="status-dot"><component :is="healthIcon" /></el-icon>
            {{ healthText }}
          </span>
          <el-divider direction="vertical" />
          <span class="status-item">
            <el-icon><Film /></el-icon> 影片 {{ stats.movies }}
          </span>
          <span class="status-item">
            <el-icon><User /></el-icon> 演员 {{ stats.actors }}
          </span>
          <span class="status-item">
            <el-icon><Files /></el-icon> 标签 {{ stats.tags }}
          </span>
        </div>
        <div class="status-right">
          <span v-if="taskProgress.active > 0" class="status-item task-progress">
            <el-icon class="is-loading"><Loading /></el-icon>
            任务 {{ taskProgress.done }}/{{ taskProgress.total }}
            <el-progress
              v-if="taskProgress.total > 0"
              :percentage="taskPercent"
              :stroke-width="6"
              :show-text="false"
              class="status-progress"
            />
          </span>
          <el-divider direction="vertical" v-if="taskProgress.active > 0" />
          <span class="status-item muted">v1.0.0</span>
          <el-tooltip content="撤销/重做历史" placement="top">
            <span class="status-item undo-state" :class="{ disabled: !undoStore.canUndo && !undoStore.canRedo }">
              <el-icon><RefreshLeft /></el-icon>
              <span v-if="undoStore.canUndo">可撤销 {{ undoStore.undoCount }}</span>
              <span v-else-if="undoStore.canRedo">可重做 {{ undoStore.redoCount }}</span>
              <span v-else>无历史</span>
            </span>
          </el-tooltip>
        </div>
      </el-footer>
    </el-container>

    <!-- 全局状态通告区（屏幕阅读器礼貌播报） -->
    <div aria-live="polite" aria-atomic="true" class="sr-only">
      {{ liveStatus }}
    </div>

    <!-- 自动更新对话框（仅 Electron 环境） -->
    <el-dialog v-model="updateDialogVisible" title="应用更新" width="440px" v-if="isElectron">
      <div class="update-dialog-content">
        <!-- 检查中 -->
        <div v-if="updateStatus === 'checking'" class="update-state">
          <el-icon class="is-loading" :size="32"><Refresh /></el-icon>
          <p>正在检查更新...</p>
        </div>

        <!-- 有新版本 -->
        <div v-else-if="updateStatus === 'available'" class="update-state">
          <el-icon :size="40" color="#409EFF"><Download /></el-icon>
          <h3>发现新版本 v{{ updateVersion }}</h3>
          <div v-if="updateReleaseNotes" class="update-notes" v-html="updateReleaseNotes"></div>
          <p class="update-hint">点击下方按钮下载更新</p>
          <el-button type="primary" :loading="updateDownloading" @click="downloadUpdate">
            {{ updateDownloading ? '下载中...' : '下载更新' }}
          </el-button>
        </div>

        <!-- 下载进度 -->
        <div v-else-if="updateStatus === 'downloading'" class="update-state">
          <el-icon :size="32" color="#409EFF"><Download /></el-icon>
          <p>正在下载更新...</p>
          <el-progress :percentage="updateProgress" :stroke-width="8" />
          <p class="update-progress-text">
            {{ formatBytes(updateTransferred) }} / {{ formatBytes(updateTotal) }}
          </p>
        </div>

        <!-- 下载完成 -->
        <div v-else-if="updateStatus === 'downloaded'" class="update-state">
          <el-icon :size="40" color="#67C23A"><CircleCheck /></el-icon>
          <h3>更新已就绪</h3>
          <p>新版本 v{{ updateVersion }} 已下载完成，重启应用以完成安装。</p>
          <el-button type="success" @click="installUpdate">安装并重启</el-button>
        </div>

        <!-- 无更新 -->
        <div v-else-if="updateStatus === 'not-available'" class="update-state">
          <el-icon :size="40" color="#67C23A"><CircleCheck /></el-icon>
          <h3>已是最新版本</h3>
          <p>当前版本 v1.0.0 是最新的。</p>
        </div>

        <!-- 错误 -->
        <div v-else-if="updateStatus === 'error'" class="update-state">
          <el-icon :size="40" color="#F56C6C"><WarningFilled /></el-icon>
          <h3>更新失败</h3>
          <p class="update-error">{{ updateError }}</p>
          <el-button @click="checkForUpdates">重试</el-button>
        </div>

        <!-- 初始状态 -->
        <div v-else class="update-state">
          <el-icon :size="32" color="#909399"><Download /></el-icon>
          <p>检查是否有新版本</p>
          <el-button type="primary" @click="checkForUpdates">检查更新</el-button>
        </div>
      </div>
    </el-dialog>

    <!-- 更新日志对话框 -->
    <el-dialog v-model="changelogVisible" title="更新日志" width="560px">
      <div class="changelog-content">
        <div class="changelog-header">
          <span class="changelog-version">v{{ versionInfo.version || '0.01' }}</span>
          <el-tag size="small" type="success">{{ versionInfo.patch_level || 'baseline' }}</el-tag>
          <span class="changelog-date">{{ versionInfo.build_date || '' }}</span>
        </div>
        <el-divider />
        <div class="changelog-list">
          <div v-for="(patch, i) in (versionInfo.patches || []).slice().reverse()" :key="i" class="changelog-item">
            <el-icon class="changelog-icon"><Document /></el-icon>
            <span class="changelog-text">{{ patch }}</span>
          </div>
          <div v-if="!(versionInfo.patches || []).length" class="changelog-empty">
            暂无更新记录
          </div>
        </div>
        <el-divider />
        <div class="changelog-footer">
          <span>爬虫数: {{ versionInfo.scrapers || 55 }}</span>
          <span>内置代理: {{ versionInfo.xray ? '✅' : '❌' }}</span>
          <span>NFO缓存: {{ versionInfo.nfo_cache ? '✅' : '❌' }}</span>
        </div>
      </div>
    </el-dialog>
    <transition name="fade-slide">
      <div v-if="avatarStore.active" class="avatar-scrape-float" role="status" aria-live="polite">
        <div class="asf-header">
          <el-icon class="is-loading asf-spin"><Loading /></el-icon>
          <span class="asf-title">头像刮削进行中</span>
          <el-button text size="small" class="asf-cancel" @click="avatarStore.cancel()">
            取消
          </el-button>
        </div>
        <div class="asf-body">
          <el-progress :percentage="avatarStore.progressPercent" :stroke-width="8" :show-text="false" />
          <div class="asf-text">{{ avatarStore.statusText }}</div>
          <div v-if="avatarStore.status.current_actor" class="asf-current">
            正在处理：{{ avatarStore.status.current_actor }}
          </div>
        </div>
      </div>
    </transition>

    <!-- 全局搜索弹窗 -->
    <el-dialog v-model="globalSearchVisible" title="全局搜索" width="600px" :close-on-click-modal="true" destroy-on-close>
      <div class="global-search-wrap">
        <el-input
          v-model="globalSearchKeyword"
          placeholder="输入番号、演员、标签、标题..."
          size="large"
          clearable
          @keyup.enter="doGlobalSearch"
          ref="globalSearchInput"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <div class="search-hints" v-if="globalSearchKeyword.trim().length < 2">
          <span class="hint-label">快速搜索提示：</span>
          <span class="hint-tag" @click="doQuickSearch('番号')">按番号</span>
          <span class="hint-tag" @click="doQuickSearch('演员')">按演员</span>
          <span class="hint-tag" @click="doQuickSearch('标签')">按标签</span>
          <span class="hint-tag" @click="doQuickSearch('标题')">按标题</span>
        </div>
        <div class="search-results" v-if="globalSearchKeyword.trim().length >= 2 && globalSearchResults.length">
          <el-divider />
          <div v-for="r in globalSearchResults" :key="r.module_name + '_' + r.id"
               class="search-result-item" @click="goToModuleItem(r)">
            <span class="search-result-module" :class="'mod-' + r.module_name">
              {{ moduleLabels[r.module_name] || r.module_name }}
            </span>
            <span class="search-result-title">{{ r.title || r.code }}</span>
            <span class="search-result-code">{{ r.code }}</span>
          </div>
        </div>
        <div v-if="globalSearchKeyword.trim().length >= 2 && globalSearchDone && !globalSearchResults.length"
             style="text-align:center;color:#999;padding:20px;">
          未找到匹配的结果
        </div>
      </div>
    </el-dialog>
  </el-container>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElNotification } from 'element-plus'
import {
  HomeFilled, VideoCamera, User, Connection, Setting, Refresh,
  SwitchButton, DataAnalysis, Star, CopyDocument, Monitor,
  Files, Tools, PriceTag, MagicStick, Upload, List, Tickets,
  Fold, Expand, Sunny, Moon, Trophy, Avatar, Sort, EditPen,
  View, Hide, Link, Platform, Box, Bell, StarFilled, Document,
  ChatLineRound, UserFilled, FolderOpened, CircleCheck, WarningFilled, Cloudy, Download, Grid,
  Film, Loading, RefreshLeft, RefreshRight, CircleCheckFilled, CloseBold,
  PictureFilled, Collection, Share, Promotion, SetUp,
  Operation, OfficeBuilding, DataLine, Management, Key, Search
} from '@element-plus/icons-vue'
import { getNsfwConfig, updateNsfwConfig, toggleNsfwMode } from '@/api'
import { getSystemHealth, getDashboardStats, getTaskStats, getVersion, getTags } from '@/api'
import { getModulesConfig, unifiedSearch } from '@/api/modules'
import { useThemeStore } from '@/stores/theme'
import { useAuthStore } from '@/stores/auth'
import { useUndoStore } from '@/stores/undo'
import { useAvatarScrapeStore } from '@/stores/avatarScrape'
import TitleBar from '@/components/TitleBar.vue'

const route = useRoute()
const router = useRouter()

const excludeCache = computed(() => {
  const p = route.path
  if (p.startsWith('/movie/') || p.startsWith('/play/') || p.startsWith('/actors/')) {
    return ['MovieDetail', 'Play', 'ActorDetail']
  }
  return []
})

const globalSearchVisible = ref(false)
const globalSearchKeyword = ref('')
const globalSearchInput = ref(null)
const globalSearchResults = ref([])
const globalSearchDone = ref(false)

const moduleLabels = { chinese: '国产', uncensored: '无码', fc2: 'FC2', pornhub: 'PORNHub', jav: 'JAV', western: '欧美' }

const doGlobalSearch = async () => {
  const kw = globalSearchKeyword.value.trim()
  if (kw.length < 2) return
  globalSearchDone.value = false
  try {
    const res = await unifiedSearch(kw)
    globalSearchResults.value = res.items || []
  } catch {
    globalSearchResults.value = []
  } finally {
    globalSearchDone.value = true
  }
}

const doQuickSearch = (type) => {
  globalSearchVisible.value = false
  router.push('/movies')
}

const goToModuleItem = (item) => {
  globalSearchVisible.value = false
  router.push(`/${item.module_name}/movies/${item.id}`)
}
const collapsed = ref(false)

// 暗黑模式（使用 Pinia theme store）
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)
const toggleDark = () => themeStore.toggleDark()

// 认证（使用 Pinia auth store）
const authStore = useAuthStore()
const currentUser = computed(() => authStore.username)

// NSFW 模式
const nsfwPopoverVisible = ref(false)
const nsfwLoading = ref(false)
const nsfwEnabled = ref(true)
const nsfwConfig = reactive({
  hide_cover: false,
  hide_title: false,
  hide_actor_avatar: false,
  blur_thumbnails: false,
  blur_intensity: 10
})

const applyNsfwMode = () => {
  // 通过 data-attribute 让全局 CSS 感知 NSFW 状态
  // data-nsfw: on/off（off 表示 NSFW 模式关闭 = 正常显示内容；on 表示隐藏敏感内容）
  // data-nsfw-hide-cover / hide-title / hide-actor-avatar: '1' 或 '0'
  // data-nsfw-blur: 模糊强度（0 表示不模糊）
  //
  // 重要：CSS 规则（index.css:823-834）使用 `html[data-nsfw="off"]` 选择器来模糊内容，
  // 因为原始语义是"data-nsfw=off 表示隐藏模式"（反向了）。为了保持命名一致，
  // 这里翻转映射：nsfwEnabled=true(开启 NSFW) → data-nsfw="off"（隐藏）
  //                nsfwEnabled=false(关闭 NSFW) → data-nsfw="on"（显示）
  const root = document.documentElement
  // 反向映射: 开启 NSFW → data-nsfw=off (CSS 触发模糊/隐藏)
  //           关闭 NSFW → data-nsfw=on  (CSS 不触发)
  root.setAttribute('data-nsfw', nsfwEnabled.value ? 'off' : 'on')
  root.setAttribute('data-nsfw-hide-cover', nsfwConfig.hide_cover ? '1' : '0')
  root.setAttribute('data-nsfw-hide-title', nsfwConfig.hide_title ? '1' : '0')
  root.setAttribute('data-nsfw-hide-avatar', nsfwConfig.hide_actor_avatar ? '1' : '0')
  root.setAttribute('data-nsfw-blur', nsfwConfig.blur_thumbnails ? String(nsfwConfig.blur_intensity) : '0')
  // 派发事件让页面组件感知（如 Play.vue 需要重新计算截图模糊）
  window.dispatchEvent(new CustomEvent('mdcx-nsfw-change', {
    detail: {
      enabled: nsfwEnabled.value,
      config: { ...nsfwConfig }
    }
  }))
  localStorage.setItem('mdcx_nsfw', nsfwEnabled.value ? '1' : '0')
}

const loadNsfwConfig = async () => {
  try {
    const data = await getNsfwConfig()
    nsfwEnabled.value = data.enabled
    nsfwConfig.hide_cover = data.hide_cover
    nsfwConfig.hide_title = data.hide_title
    nsfwConfig.hide_actor_avatar = data.hide_actor_avatar
    nsfwConfig.blur_thumbnails = data.blur_thumbnails
    nsfwConfig.blur_intensity = data.blur_intensity
    applyNsfwMode()
  } catch (e) {
    // 静默失败：未授权或后端不可用
    const cached = localStorage.getItem('mdcx_nsfw')
    if (cached !== null) {
      nsfwEnabled.value = cached === '1'
      applyNsfwMode()
    }
  }
}

const onNsfwToggle = async (val) => {
  nsfwLoading.value = true
  try {
    const data = await toggleNsfwMode()
    nsfwEnabled.value = data.enabled
    applyNsfwMode()
    ElMessage.success(nsfwEnabled.value ? 'NSFW 模式已开启' : 'NSFW 模式已关闭')
  } catch (e) {
    // 失败回滚
    nsfwEnabled.value = !val
  } finally {
    nsfwLoading.value = false
  }
}

const onNsfwConfigChange = async () => {
  try {
    await updateNsfwConfig({
      hide_cover: nsfwConfig.hide_cover,
      hide_title: nsfwConfig.hide_title,
      hide_actor_avatar: nsfwConfig.hide_actor_avatar,
      blur_thumbnails: nsfwConfig.blur_thumbnails,
      blur_intensity: nsfwConfig.blur_intensity
    })
    applyNsfwMode()
  } catch (e) {
    // 静默
  }
}

// ===== 底部状态栏：服务器健康 / 统计 / 任务进度 =====
const undoStore = useUndoStore()

// 头像刮削全局 Store（进度浮层 + 全局通知）
const avatarStore = useAvatarScrapeStore()

// 模块启用状态（默认全部启用，加载配置后更新）
const moduleEnabled = ref({
  jav: true,
  uncensored: true,
  fc2: true,
  chinese: true,
  pornhub: true,
  western: true
})

async function loadModuleConfig() {
  try {
    const config = await getModulesConfig()
    if (config) {
      for (const [name, cfg] of Object.entries(config)) {
        if (cfg && typeof cfg.enabled === 'boolean') {
          moduleEnabled.value[name] = cfg.enabled
        }
      }
    }
  } catch {
    // 静默失败，保持默认全部启用
  }
}

const healthStatus = ref('unknown') // ok / warn / error / unknown
const stats = reactive({
  movies: 0,
  actors: 0,
  tags: 0,
})
const taskProgress = reactive({
  total: 0,
  done: 0,
  active: 0,
})
let statusTimer = null

const healthLevel = computed(() => {
  if (healthStatus.value === 'ok') return 'ok'
  if (healthStatus.value === 'warn') return 'warn'
  if (healthStatus.value === 'error') return 'error'
  return 'unknown'
})

const healthText = computed(() => {
  const map = { ok: '服务器正常', warn: '服务器降级', error: '服务器异常', unknown: '未连接' }
  return map[healthStatus.value] || '未连接'
})

const healthIcon = computed(() => {
  if (healthStatus.value === 'ok') return CircleCheckFilled
  if (healthStatus.value === 'warn') return WarningFilled
  if (healthStatus.value === 'error') return CloseBold
  return WarningFilled
})

const taskPercent = computed(() => {
  if (taskProgress.total <= 0) return 0
  return Math.round((taskProgress.done / taskProgress.total) * 100)
})

async function loadHealthAndStats() {
  // 健康检查
  try {
    await getSystemHealth()
    healthStatus.value = 'ok'
  } catch (e) {
    healthStatus.value = e?.response ? 'error' : 'unknown'
  }
  // 统计信息（兼容后端返回嵌套对象 {total, completed} 或纯数字两种格式）
  try {
    const data = await getDashboardStats()
    const pick = (v, fallback) => v != null ? (typeof v === 'number' ? v : (v?.total ?? v ?? fallback)) : fallback
    stats.movies = pick(data?.movies ?? data?.movie_count, 0)
    stats.actors = pick(data?.actors ?? data?.actor_count, 0)
    stats.tags = pick(data?.tags ?? data?.tag_count, 0)
    if (!stats.tags) {
      getTags({ page: 1, page_size: 1 }).then(r => { stats.tags = r.total || 0 }).catch(() => {})
    }
  } catch (e) {
    // 静默
  }
  // 任务进度
  try {
    const data = await getTaskStats()
    const dist = data?.status_distribution || {}
    taskProgress.total = Object.values(dist).reduce((a, b) => a + b, 0)
    taskProgress.done = dist.success || 0
    taskProgress.active = dist.running || 0
  } catch (e) {
    // 静默
  }
}

onMounted(() => {
  // 主题已在 main.js 初始化，这里仅需加载 NSFW 配置
  loadNsfwConfig()
  // 加载模块启用状态配置
  loadModuleConfig()
  // 初始化 Electron 自动更新监听
  initUpdater()
  // 启动状态栏定时刷新（首次立即加载，之后每 30 秒刷新）
  loadHealthAndStats()
  statusTimer = setInterval(loadHealthAndStats, 30000)
  // 注册 Electron 桌面端事件监听（全局快捷键 / mdcx:// 协议 / 任务控制）
  initDesktopEvents()
  // 探测本地头像资料库状态（供演员/头像库页面使用）
  avatarStore.initLibrary()
})

onBeforeUnmount(() => {
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
  if (unbindNavigateRoute) {
    unbindNavigateRoute()
    unbindNavigateRoute = null
  }
  if (unbindOpenUrl) {
    unbindOpenUrl()
    unbindOpenUrl = null
  }
  if (unbindTaskControl) {
    unbindTaskControl()
    unbindTaskControl = null
  }
})

// ===== Electron 桌面端事件监听 =====
// - onNavigateRoute：来自全局快捷键 Ctrl+Alt+E 或 mdcx:// 协议的路由跳转请求
// - onOpenUrl：mdcx:// 协议唤起时携带的载荷（type/id/route）
// - onTaskControl：托盘菜单"暂停/继续任务"触发
let unbindNavigateRoute = null
let unbindOpenUrl = null
let unbindTaskControl = null

function initDesktopEvents() {
  const api = (typeof window !== 'undefined' && window.electronAPI) || null
  if (!api || !api.isElectron) return
  if (api.onNavigateRoute) {
    unbindNavigateRoute = api.onNavigateRoute((route) => {
      if (!route) return
      try {
        router.push(route).catch(() => {})
      } catch (e) {
        // 静默
      }
    })
  }
  if (api.onOpenUrl) {
    unbindOpenUrl = api.onOpenUrl(({ route } = {}) => {
      if (route) {
        router.push(route).catch(() => {})
      }
    })
  }
  if (api.onTaskControl) {
    unbindTaskControl = api.onTaskControl((action) => {
      // 派发自定义事件，由 Tasks.vue 等组件响应
      window.dispatchEvent(new CustomEvent('mdcx-task-control', { detail: action }))
    })
  }
}

// ===== Electron 自动更新 =====
const isElectron = computed(() => !!(window.electronAPI && window.electronAPI.isElectron))
const updateDialogVisible = ref(false)
const updateStatus = ref('')        // '' / 'checking' / 'available' / 'downloading' / 'downloaded' / 'not-available' / 'error'
const updateVersion = ref('')
const updateReleaseNotes = ref('')
const updateProgress = ref(0)
const updateTransferred = ref(0)
const updateTotal = ref(0)
const updateDownloading = ref(false)
const updateError = ref('')
const updateAvailable = ref(false)
const updateDownloaded = ref(false)

// 全局无障碍状态通告（aria-live 区域内容）：根据更新状态派生文案,供屏幕阅读器礼貌播报
const liveStatus = computed(() => {
  if (updateStatus.value === 'checking') return '正在检查更新'
  if (updateStatus.value === 'available') return `发现新版本 ${updateVersion.value}`
  if (updateStatus.value === 'downloading') return `正在下载更新,进度 ${updateProgress.value}%`
  if (updateStatus.value === 'downloaded') return '更新已就绪,可以安装'
  if (updateStatus.value === 'error') return '更新失败'
  if (updateStatus.value === 'not-available') return '已是最新版本'
  return ''
})

function initUpdater() {
  if (!isElectron.value || !window.electronAPI.onUpdaterEvent) return
  window.electronAPI.onUpdaterEvent((payload) => {
    switch (payload.type) {
      case 'checking':
        updateStatus.value = 'checking'
        break
      case 'available':
        updateStatus.value = 'available'
        updateVersion.value = payload.version || ''
        updateReleaseNotes.value = typeof payload.releaseNotes === 'string'
          ? payload.releaseNotes
          : (payload.releaseNotes?.notes || '')
        updateAvailable.value = true
        updateDialogVisible.value = true
        break
      case 'not-available':
        updateStatus.value = 'not-available'
        break
      case 'progress':
        updateStatus.value = 'downloading'
        updateDownloading.value = true
        updateProgress.value = Math.round(payload.percent || 0)
        updateTransferred.value = payload.transferred || 0
        updateTotal.value = payload.total || 0
        break
      case 'downloaded':
        updateStatus.value = 'downloaded'
        updateDownloading.value = false
        updateDownloaded.value = true
        updateVersion.value = payload.version || updateVersion.value
        break
      case 'error':
        updateStatus.value = 'error'
        updateError.value = payload.message || '未知错误'
        updateDownloading.value = false
        break
    }
  })
}

async function checkForUpdates() {
  if (!isElectron.value || !window.electronAPI.updaterCheck) return
  updateStatus.value = 'checking'
  try {
    const result = await window.electronAPI.updaterCheck()
    if (result && !result.ok) {
      updateStatus.value = 'error'
      updateError.value = result.error || '检查更新失败'
    }
  } catch (e) {
    updateStatus.value = 'error'
    updateError.value = String(e)
  }
}

async function downloadUpdate() {
  if (!isElectron.value || !window.electronAPI.updaterDownload) return
  updateDownloading.value = true
  updateStatus.value = 'downloading'
  try {
    await window.electronAPI.updaterDownload()
  } catch (e) {
    updateStatus.value = 'error'
    updateError.value = String(e)
    updateDownloading.value = false
  }
}

function installUpdate() {
  if (!isElectron.value || !window.electronAPI.updaterInstall) return
  window.electronAPI.updaterInstall()
}

function openUpdateDialog() {
  updateDialogVisible.value = true
  checkForUpdates()
}

// ===== 版本/更新日志 =====
const changelogVisible = ref(false)
const versionInfo = ref({ version: '0.01', patches: [], build_date: '', patch_level: '' })

async function openChangelog() {
  changelogVisible.value = true
  try {
    const data = await getVersion()
    versionInfo.value = data || versionInfo.value
  } catch (e) {
    console.error('获取版本信息失败:', e)
  }
}

// 启动时静默拉取版本号（用于侧边栏底部显示）
onMounted(async () => {
  try {
    const data = await getVersion()
    if (data) versionInfo.value = data
  } catch (e) { /* 静默失败 */ }
})

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024
    i++
  }
  return `${bytes.toFixed(1)} ${units[i]}`
}

const activeMenu = computed(() => route.path)

const pageTitle = computed(() => {
  const titles = {
    '/': '首页概览',
    '/movies': '番号库',
    '/actors': '演员',
    '/chinese': '国产影片',
    '/chinese/movies': '国产影片',
    '/chinese/actors': '国产演员',
    '/fc2': 'FC2 影片',
    '/fc2/movies': 'FC2 影片',
    '/uncensored': '无码影片',
    '/uncensored/movies': '无码影片',
    '/pornhub': 'PORNHub 影片',
    '/pornhub/movies': 'PORNHub 影片',
    '/western': '欧美影片',
    '/western/movies': '欧美影片',
    '/download': '下载管理',
    '/sites': '站点注册表',
    '/modules': '模块管理',
    '/crawlers': '爬虫管理',
    '/compare': '本地与在线对比',
    '/compare-actors': '对比演员库',
    '/favorites': '收藏夹',
    '/fingerprint': '视频指纹去重',
    '/patch': '补丁刮削',
    '/import': '批量导入',
    '/tags': '标签管理',
    '/tiers': '分级治理中心',
    '/log-stream': '实时日志流',
    '/webdav-import': 'WebDAV 导入',
    '/cloud-drive2': 'CloudDrive2 网盘',
    '/pan-115': '115 网盘离线下载',
    '/metatube-plugin': 'Metatube 插件（Jellyfin 兼容）',
    '/network-diag': '网络诊断中心',
    '/proxy-xray': '内置 Xray 代理',
    '/face-crop': 'AI 人脸裁剪',
    '/site-priority': '站点优先级',
    '/naming-template': '命名模板',
    '/emby-config': 'Emby 协议兼容',
    '/strm': 'STRM 文件生成',
    '/tvbox': 'TVBox/MacCMS 开放接口',
    '/downloaders': '下载器统一管理',
    '/themes': '皮肤主题',
    '/schema-settings': 'Schema 设置',
    '/deploy': '部署档位（四档渐进式）',
    '/backup': '自动备份管理',
    '/desktop-settings': '桌面设置',
    '/tasks': '任务中心',
    '/plugins': '插件系统',
    '/webhooks': 'Webhook 通知',
    '/subscriptions': '演员订阅',
    '/viewing-report': 'AI 观影报告',
    '/telegram-bot': 'Telegram Bot',
    '/view-status': '三态视频标记',
    '/file-organize': '文件整理',
    '/users': '用户管理',
    '/logs': '系统日志',
    '/mpv-settings': 'mpv 播放器设置',
    '/settings': '系统设置',
    '/poster-enhance': '海报增强',
    '/series-subscriptions': '系列订阅',
    '/movie-graph': '影片图谱',
    '/recommendations': '智能推荐',
    '/auto-organize': '自动整理',
    '/nfo-scrape': 'NFO 免改名刮削',
    '/workflows': '工作流管理',
    '/studios': '制片厂管理',
    '/files': '文件管理',
    '/system-status': '系统状态',
    '/source-merge': '多来源数据精选',
    '/refresh-folders': '文件夹刷新'
  }
  return titles[route.path] || 'MDCX'
})

const refresh = () => window.location.reload()

const logout = () => {
  authStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.layout-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.layout-container {
  flex: 1;
  height: 0; /* 让 flex 子项正确滚动 */
}

.sidebar {
  background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
  transition: width 0.28s;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
}

.logo-area {
  height: 60px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
}

.logo-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: linear-gradient(135deg, #409eff 0%, #6a5acd 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.logo-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
  overflow: hidden;
  white-space: nowrap;
}

.logo-text h2 {
  color: #fff;
  margin: 0;
  font-size: 16px;
  font-weight: 700;
}

.logo-text span {
  color: rgba(255, 255, 255, 0.5);
  font-size: 11px;
}

.menu {
  border-right: none;
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px 0;
}

.menu:not(.el-menu--collapse) {
  width: 220px;
}

.menu :deep(.el-menu-item),
.menu :deep(.el-sub-menu__title) {
  height: 44px;
  line-height: 44px;
  margin: 2px 8px;
  border-radius: 6px;
}

.menu :deep(.el-menu-item:hover),
.menu :deep(.el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, 0.06) !important;
}

.menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(64, 158, 255, 0.25) 0%, rgba(64, 158, 255, 0.08) 100%) !important;
  color: #fff !important;
  font-weight: 500;
  box-shadow: inset 3px 0 0 #409eff;
}

.menu :deep(.el-sub-menu .el-menu) {
  background: rgba(0, 0, 0, 0.15) !important;
}

.menu :deep(.el-sub-menu .el-menu .el-menu-item) {
  margin: 2px 8px 2px 24px;
}

.sidebar-footer {
  padding: 10px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  text-align: center;
  flex-shrink: 0;
}

.ver {
  color: rgba(255, 255, 255, 0.35);
  font-size: 11px;
}

.header {
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  height: 56px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  z-index: 10;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.collapse-btn {
  padding: 6px !important;
}

.breadcrumb {
  font-size: 14px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 4px;
}

.user-avatar {
  background: linear-gradient(135deg, #409eff 0%, #6a5acd 100%);
  color: #fff;
}

.user-name {
  font-size: 13px;
  color: #606266;
}

.main-content {
  background: #f0f2f5;
  padding: 20px;
  overflow-y: auto;
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.25s ease;
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.menu::-webkit-scrollbar {
  width: 6px;
}

.menu::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
  border-radius: 3px;
}

/* NSFW 模式按钮 */
.nsfw-btn {
  position: relative;
}

.nsfw-btn.nsfw-active {
  color: #f56c6c !important;
}

.nsfw-btn.nsfw-active::after {
  content: '';
  position: absolute;
  top: 4px;
  right: 4px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #f56c6c;
  box-shadow: 0 0 4px rgba(245, 108, 108, 0.6);
}

.nsfw-panel {
  padding: 4px 0;
}

.nsfw-panel-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}

.nsfw-panel-desc {
  font-size: 12px;
  color: #909399;
  margin-bottom: 12px;
  line-height: 1.5;
}

.nsfw-panel-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 13px;
  color: #606266;
}

.nsfw-panel :deep(.el-divider) {
  margin: 8px 0;
}

/* ===== 全局搜索结果 ===== */
.search-result-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.15s;
}
.search-result-item:hover {
  background: var(--el-color-primary-light-9, #ecf5ff);
}
.search-result-module {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: bold;
  min-width: 40px;
  text-align: center;
  flex-shrink: 0;
}
.mod-chinese { background: #fef0f0; color: #dc2626; }
.mod-uncensored { background: #fdf6ec; color: #e6a23c; }
.mod-fc2 { background: #ecf5ff; color: #409eff; }
.mod-pornhub { background: #f0fdf4; color: #16a34a; }
.mod-western { background: #fdf2f8; color: #db2777; }
.search-result-title {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.search-result-code {
  font-size: 11px;
  color: #999;
  flex-shrink: 0;
}

/* ===== 自动更新对话框 ===== */
.update-dialog-content .update-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 20px 0;
  text-align: center;
}
.update-dialog-content h3 {
  margin: 0;
  font-size: 18px;
}
.update-dialog-content .update-hint {
  color: #909399;
  font-size: 13px;
  margin: 0;
}
.update-dialog-content .update-error {
  color: #f56c6c;
  font-size: 13px;
  word-break: break-all;
}
.update-dialog-content .update-notes {
  max-height: 200px;
  overflow-y: auto;
  text-align: left;
  background: var(--el-bg-page, #f5f7fa);
  padding: 12px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
  width: 100%;
  box-sizing: border-box;
}
.update-dialog-content .update-progress-text {
  color: #909399;
  font-size: 12px;
  margin: 0;
}
.update-badge :deep(.el-badge__content) {
  font-size: 10px;
}

/* ===== 底部状态栏（§4.5.2.B 规范）===== */
.status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--statusbar-bg, var(--bg-card, #fff));
  border-top: 1px solid var(--border-color, #ebeef5);
  padding: 0 var(--space-4, 16px);
  height: var(--statusbar-height, 24px);
  font-size: var(--font-size-xs, 12px);
  color: var(--text-secondary, #606266);
  gap: var(--space-4, 16px);
  box-shadow: 0 -1px 4px rgba(0, 0, 0, 0.04);
  z-index: 5;
}

.status-left,
.status-right {
  display: flex;
  align-items: center;
  gap: var(--space-3, 12px);
}

.status-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1, 4px);
  white-space: nowrap;
}

.status-item .el-icon {
  font-size: var(--font-size-sm, 13px);
}

.status-item.muted {
  color: var(--text-placeholder, #c0c4cc);
}

.status-item.undo-state.disabled {
  color: var(--text-placeholder, #c0c4cc);
  opacity: 0.6;
}

/* 健康状态指示器（§4.5.2.B .statusbar__indicator 规范）*/
/* .status-dot 用作 el-icon 容器,保留图标显示;补充纯圆点指示器 .statusbar__indicator */
.statusbar__indicator {
  display: inline-block;
  width: var(--statusbar-indicator-size, 6px);
  height: var(--statusbar-indicator-size, 6px);
  border-radius: 50%;
  background: var(--success-color, #67c23a);
  box-shadow: 0 0 6px var(--success-color, #67c23a);
}

.status-dot.health-ok {
  color: var(--success-color, #67c23a);
}

/* 健康状态颜色 */
.status-item.health-ok {
  color: var(--el-color-success, #67c23a);
}
.status-item.health-warn {
  color: var(--el-color-warning, #e6a23c);
}
.status-item.health-error {
  color: var(--el-color-danger, #f56c6c);
}
.status-item.health-unknown {
  color: var(--text-placeholder, #c0c4cc);
}

/* 任务进度 */
.task-progress .is-loading {
  animation: rotating 1.5s linear infinite;
}

.status-progress {
  width: 80px;
}

.status-bar :deep(.el-divider--vertical) {
  margin: 0 4px;
}

@keyframes rotating {
  from { transform: rotate(0); }
  to { transform: rotate(360deg); }
}

/* ===== 全局头像刮削进度浮层 ===== */
.avatar-scrape-float {
  position: fixed;
  top: 72px;
  right: 20px;
  width: 300px;
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 12px;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.18);
  padding: 14px 16px;
  z-index: 2000;
}

.avatar-scrape-float .asf-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.avatar-scrape-float .asf-spin {
  color: #409eff;
  animation: rotating 1.5s linear infinite;
}

.avatar-scrape-float .asf-title {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #303133);
}

.avatar-scrape-float .asf-cancel {
  padding: 2px 8px !important;
  font-size: 12px;
  color: #f56c6c;
}

.avatar-scrape-float .asf-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.avatar-scrape-float .asf-text {
  font-size: 12px;
  color: var(--text-secondary, #606266);
}

.avatar-scrape-float .asf-current {
  font-size: 12px;
  color: var(--text-placeholder, #909399);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
