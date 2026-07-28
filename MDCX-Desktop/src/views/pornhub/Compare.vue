<template>
  <div class="pornhub-compare">
    <div class="page-header">
      <h3>🌐 PORNHub - 本地对比查重</h3>
      <p class="page-desc">基于 PornSimilarityPlatform 引擎，在线 vs 本地视频对比，自动识别缺失影片</p>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="10">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">
              <el-icon><Search /></el-icon> 对比配置
            </span>
          </template>
          <el-form label-position="top">
            <el-form-item label="PORNHub 演员 URL">
              <el-input v-model="form.actress_url" placeholder="https://www.pornhub.com/model/xxx" clearable />
            </el-form-item>
            <el-form-item label="本地视频目录">
              <el-input v-model="form.local_directory" placeholder="留空则使用模块 media_dirs 配置" clearable />
            </el-form-item>
            <el-row :gutter="8">
              <el-col :span="12">
                <el-form-item label="抓取页数">
                  <el-input-number v-model="form.max_pages" :min="1" :max="20" size="small" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="相似度阈值">
                  <el-slider v-model="form.similarity_threshold" :min="0.5" :max="1" :step="0.05" show-input size="small" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-button type="primary" @click="startCompare" :loading="comparing" style="width:100%">
              <el-icon><DataAnalysis /></el-icon> 开始对比
            </el-button>
          </el-form>
        </el-card>

        <el-card shadow="never" style="margin-top:12px">
          <template #header>
            <span class="card-title"><el-icon><EditPen /></el-icon> 标题归一化测试</span>
          </template>
          <el-input v-model="testTitle" placeholder="输入 PORNHub 视频标题" clearable style="margin-bottom:8px" />
          <el-button @click="testNormalize" size="small">测试归一化</el-button>
          <div v-if="testResult" class="test-result">
            <div><label>原始：</label><span class="old">{{ testTitle }}</span></div>
            <div><label>归一化：</label><span class="new">{{ testResult }}</span></div>
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="14">
        <el-card shadow="never" v-if="!result">
          <template #header>
            <span class="card-title"><el-icon><InfoFilled /></el-icon> 使用说明</span>
          </template>
          <ol style="line-height:2;font-size:13px;color:#666">
            <li>输入 PORNHub 演员页面的 URL（如 https://www.pornhub.com/model/xxx）</li>
            <li>选择本地视频目录（或留空使用模块配置的目录）</li>
            <li>点击"开始对比"，系统将抓取在线视频列表并扫描本地文件</li>
            <li>通过标题归一化 + 模糊匹配，自动识别<strong>已匹配</strong>和<strong>缺失</strong>的影片</li>
            <li>匹配算法参考 PornSimilarityPlatform 的 TitleNormalizer</li>
          </ol>
        </el-card>

        <el-card shadow="never" v-if="result" class="result-card">
          <template #header>
            <div class="card-header">
              <span class="card-title"><el-icon><DataAnalysis /></el-icon> 对比结果</span>
              <div class="result-stats">
                <el-tag size="small" type="info">{{ result.online_count }} 在线</el-tag>
                <el-tag size="small" type="success">{{ result.matched_count }} 匹配</el-tag>
                <el-tag size="small" type="warning">{{ result.missing_count }} 缺失</el-tag>
                <el-tag size="small">{{ result.local_count }} 本地</el-tag>
              </div>
            </div>
          </template>

          <el-tabs v-model="resultTab">
            <el-tab-pane label="缺失影片" name="missing">
              <div v-if="!result.missing_videos.length" style="text-align:center;padding:30px;color:#999">
                <el-icon :size="40" color="#67c23a"><CircleCheck /></el-icon>
                <p>全部匹配！没有缺失影片 🎉</p>
              </div>
              <el-table v-else :data="result.missing_videos" size="small" stripe max-height="480">
                <el-table-column label="标题" min-width="200">
                  <template #default="{ row }">
                    <a :href="row.url" target="_blank" class="video-link">{{ row.title || '未知' }}</a>
                  </template>
                </el-table-column>
                <el-table-column prop="duration" label="时长" width="80" />
                <el-table-column label="操作" width="80">
                  <template #default="{ row }">
                    <el-button size="small" text type="primary" @click="openUrl(row.url)" v-if="row.url">
                      打开
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="本地视频" name="local">
              <el-table v-if="result.local_videos.length" :data="result.local_videos" size="small" stripe max-height="480">
                <el-table-column label="文件名" min-width="250">
                  <template #default="{ row }">{{ row.file_name }}</template>
                </el-table-column>
                <el-table-column label="大小" width="100">
                  <template #default="{ row }">{{ row.size_mb }} MB</template>
                </el-table-column>
              </el-table>
              <el-empty v-else description="无本地视频" />
            </el-tab-pane>
            <el-tab-pane label="在线视频" name="online">
              <el-table v-if="result.online_videos.length" :data="result.online_videos" size="small" stripe max-height="480">
                <el-table-column label="标题" min-width="250">
                  <template #default="{ row }">{{ row.title || '未知' }}</template>
                </el-table-column>
                <el-table-column prop="duration" label="时长" width="80" />
              </el-table>
              <el-empty v-else description="无在线视频" />
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, DataAnalysis, EditPen, InfoFilled, CircleCheck } from '@element-plus/icons-vue'
import { pornhubCompare, pornhubTestNormalize } from '@/api/pornhub'

const comparing = ref(false)
const result = ref(null)
const resultTab = ref('missing')
const testTitle = ref('Step Sister Sucks My Dick While Mom Is Away - PornHub.com')
const testResult = ref('')

const form = reactive({
  actress_url: '',
  local_directory: '',
  max_pages: 5,
  similarity_threshold: 0.85,
})

async function startCompare() {
  if (!form.actress_url.trim()) {
    ElMessage.warning('请输入 PORNHub 演员 URL')
    return
  }
  comparing.value = true
  result.value = null
  try {
    const res = await pornhubCompare({
      actress_url: form.actress_url.trim(),
      local_directory: form.local_directory.trim() || undefined,
      max_pages: form.max_pages,
      similarity_threshold: form.similarity_threshold,
    })
    result.value = res
    ElMessage.success(`对比完成：${res.matched_count} 匹配，${res.missing_count} 缺失`)
  } catch (e) {
    ElMessage.error('对比失败: ' + (e.message || e))
  } finally {
    comparing.value = false
  }
}

async function testNormalize() {
  if (!testTitle.value.trim()) return
  try {
    const res = await pornhubTestNormalize(testTitle.value.trim())
    testResult.value = res.normalized
  } catch (e) {
    testResult.value = '归一化失败: ' + (e.message || e)
  }
}

function openUrl(url) {
  if (url) window.open(url, '_blank')
}
</script>

<style scoped>
.pornhub-compare { max-width: 1400px; margin: 0 auto; }
.page-header { margin-bottom: 16px; }
.page-header h3 { margin: 0 0 4px; }
.page-desc { color: #999; font-size: 13px; margin: 0; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 14px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.result-stats { display: flex; gap: 6px; }
.video-link { color: var(--el-color-primary); text-decoration: none; font-size: 12px; }
.video-link:hover { text-decoration: underline; }
.test-result { margin-top: 10px; padding: 10px; background: #f5f7fa; border-radius: 6px; font-size: 12px; line-height: 1.8; }
.test-result .old { color: #f56c6c; }
.test-result .new { color: #67c23a; font-weight: bold; }
.result-card :deep(.el-tabs__content) { overflow: auto; }
</style>
