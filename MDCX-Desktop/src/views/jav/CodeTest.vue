<template>
  <div class="code-test">
    <el-card shadow="never">
      <template #header>
        <span class="card-title">
          <el-icon><Search /></el-icon> 🔍 番号提取测试
        </span>
      </template>
      <el-alert title="输入文件名，测试 MDCX 的番号提取能力。参考 JavBoss v1.8.0 番号提取测试工具。" type="info" show-icon :closable="false" style="margin-bottom:16px" />

      <el-input v-model="filename" placeholder="输入视频文件名，如 IPX-633-C.mp4 或 SSIS-001_ch.avi" clearable style="margin-bottom:12px">
        <template #prepend>文件名</template>
        <template #append>
          <el-button @click="testExtract" :loading="testing" type="primary">
            <el-icon><Search /></el-icon> 提取
          </el-button>
        </template>
      </el-input>

      <el-row :gutter="16">
        <el-col :xs="24" :lg="8" v-for="(sample, i) in samples" :key="i" style="margin-bottom:8px">
          <el-card shadow="hover" class="sample-card" @click="filename = sample; testExtract()">
            <div class="sample-path">{{ sample }}</div>
          </el-card>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" v-if="result" style="margin-top:16px">
      <template #header>
        <span class="card-title"><el-icon><CircleCheck /></el-icon> 提取结果</span>
      </template>
      <el-descriptions :column="2" size="small" border>
        <el-descriptions-item label="文件名" :span="2">{{ result.filename }}</el-descriptions-item>
        <el-descriptions-item label="提取番号数">{{ result.count }}</el-descriptions-item>
        <el-descriptions-item label="是否中字">{{ result.codes[0]?.is_chinese }}</el-descriptions-item>
      </el-descriptions>
      <el-table v-if="result.codes.length" :data="result.codes" stripe size="small" style="margin-top:12px">
        <el-table-column type="index" width="50" />
        <el-table-column prop="code" label="番号" />
        <el-table-column prop="type" label="类型" width="120" />
        <el-table-column prop="is_chinese" label="中字" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_chinese ? 'success' : 'info'" size="small">{{ row.is_chinese ? '是' : '否' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="is_uncensored" label="无码" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_uncensored ? 'warning' : 'info'" size="small">{{ row.is_uncensored ? '是' : '否' }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Search, CircleCheck } from '@element-plus/icons-vue'
import { testCodeExtract } from '@/api/jav'

const filename = ref('IPX-633-C')
const testing = ref(false)
const result = ref(null)

const samples = [
  'IPX-633-C',
  'SSIS-001_ch.mp4',
  'FC2-123456.mp4',
  'MIDE-777_unc.mp4',
  'T28-123 中文字幕.mp4',
  '200GANA-1234.mp4',
]

async function testExtract() {
  if (!filename.value.trim()) return
  testing.value = true
  try {
    const res = await testCodeExtract(filename.value.trim())
    result.value = res
  } catch (e) {
    result.value = { filename: filename.value, codes: [], count: 0, error: e.message }
  } finally {
    testing.value = false
  }
}
</script>

<style scoped>
.code-test { max-width: 900px; margin: 0 auto; }
.card-title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 15px; }
.sample-card { cursor: pointer; transition: all .15s; }
.sample-card:hover { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.sample-path { font-size: 13px; font-family: monospace; word-break: break-all; padding: 4px; }
</style>
