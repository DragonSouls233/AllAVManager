<template>
  <div class="mpv-settings">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>mpv 播放器设置</span>
          <el-tag :type="config.mpv_installed ? 'success' : 'danger'">
            {{ config.mpv_installed ? '已安装' : '未安装' }}
          </el-tag>
        </div>
      </template>

      <el-alert v-if="!config.mpv_installed" type="warning" :closable="false" style="margin-bottom: 20px">
        未检测到 mpv，请先安装。<a href="https://mpv.io/installation/" target="_blank" style="color: #409eff">安装指南</a>
      </el-alert>

      <el-form label-width="120px" style="max-width: 600px">
        <el-form-item label="默认音量">
          <el-slider v-model="config.volume" :min="0" :max="100" show-input style="max-width: 400px" />
        </el-form-item>

        <el-form-item label="窗口置顶">
          <el-switch v-model="config.on_top" />
        </el-form-item>

        <el-form-item label="窗口宽度">
          <el-input-number v-model="config.window_width" :min="320" :max="3840" :placeholder="1280" />
        </el-form-item>

        <el-form-item label="窗口高度">
          <el-input-number v-model="config.window_height" :min="240" :max="2160" :placeholder="720" />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="saveConfig" :loading="saving">保存配置</el-button>
          <el-button @click="loadConfig">重新加载</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card style="margin-top: 16px">
      <template #header>
        <div class="card-header">
          <span>热键配置</span>
          <el-button size="small" @click="resetHotkeys">恢复默认</el-button>
        </div>
      </template>

      <el-table :data="config.hotkeys" border style="width: 100%">
        <el-table-column label="按键" width="120">
          <template #default="{ row }">
            <el-input v-model="row.key" style="width: 100px" />
          </template>
        </el-table-column>
        <el-table-column label="动作" width="150">
          <template #default="{ row }">
            <el-select v-model="row.action" style="width: 130px">
              <el-option label="快进/快退" value="seek" />
              <el-option label="音量调节" value="volume" />
              <el-option label="截图" value="screenshot" />
              <el-option label="暂停/继续" value="pause" />
              <el-option label="退出" value="quit" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="数值" width="120">
          <template #default="{ row }">
            <el-input-number
              v-if="row.action === 'seek' || row.action === 'volume'"
              v-model="row.amount"
              :min="-300" :max="300"
              style="width: 100px"
            />
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="说明">
          <template #default="{ row }">
            {{ describeHotkey(row) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ $index }">
            <el-button type="danger" size="small" link @click="removeHotkey($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="margin-top: 12px">
        <el-button size="small" @click="addHotkey">+ 添加热键</el-button>
        <el-button type="primary" size="small" @click="saveConfig" :loading="saving">保存热键</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getMpvConfig, saveMpvConfig, getDefaultHotkeys } from '@/api'

const config = ref({
  volume: 70,
  on_top: true,
  window_width: null,
  window_height: null,
  hotkeys: [],
  mpv_installed: false,
  mpv_path: null,
})
const saving = ref(false)

const loadConfig = async () => {
  try {
    const res = await getMpvConfig()
    const data = res.items ? res : (res.data || res)
    config.value = {
      volume: data.volume ?? 70,
      on_top: data.on_top ?? true,
      window_width: data.window_width ?? null,
      window_height: data.window_height ?? null,
      hotkeys: data.hotkeys || [],
      mpv_installed: data.mpv_installed ?? false,
      mpv_path: data.mpv_path ?? null,
    }
  } catch (e) {
    ElMessage.error('加载配置失败')
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await saveMpvConfig({
      volume: config.value.volume,
      on_top: config.value.on_top,
      window_width: config.value.window_width,
      window_height: config.value.window_height,
      hotkeys: config.value.hotkeys,
    })
    ElMessage.success('配置已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const resetHotkeys = async () => {
  try {
    const res = await getDefaultHotkeys()
    config.value.hotkeys = (res.items ? res : (res.data || res)).hotkeys
    ElMessage.success('已恢复默认热键')
  } catch (e) {
    ElMessage.error('加载默认热键失败')
  }
}

const addHotkey = () => {
  config.value.hotkeys.push({ key: '', action: 'seek', amount: 5 })
}

const removeHotkey = (index) => {
  config.value.hotkeys.splice(index, 1)
}

const describeHotkey = (hk) => {
  if (hk.action === 'seek') {
    return `进度 ${hk.amount > 0 ? '+' : ''}${hk.amount} 秒`
  } else if (hk.action === 'volume') {
    return `音量 ${hk.amount > 0 ? '+' : ''}${hk.amount}%`
  } else if (hk.action === 'screenshot') {
    return '截取当前画面'
  } else if (hk.action === 'pause') {
    return '暂停/继续'
  } else if (hk.action === 'quit') {
    return '退出播放器'
  }
  return ''
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.mpv-settings {
  max-width: 900px;
  margin: 0 auto;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
