<template>
  <el-config-provider :locale="zhCn">
    <!--
      窗口控制条提升到最外层：登录页 / 播放页 / 任何未套布局的页面都必须能
      最小化、最大化、关闭、拖动。之前只有 Layout 内部才有，导致无边框窗口
      停在登录页时「没有任何关闭入口」。
    -->
    <TitleBar v-if="showTitleBar" />
    <router-view />
  </el-config-provider>
</template>

<script setup>
import { computed } from 'vue'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import TitleBar from '@/components/TitleBar.vue'

const showTitleBar = computed(
  () => !!(typeof window !== 'undefined' && window.electronAPI?.isElectron)
)
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  font-family: 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

/* 桌面端无边框窗口：整页禁止选中文字造成的拖拽干扰由 TitleBar 自行放开 */
html.electron, body.electron {
  overflow: hidden;
}
</style>
