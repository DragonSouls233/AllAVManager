import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getModules, getModuleStats, scanModule } from '@/api/modules'

export const useModulesStore = defineStore('modules', () => {
  const modules = ref([])
  const stats = ref({})

  async function loadModules() {
    const res = await getModules()
    modules.value = res || []
    return modules.value
  }

  async function loadStats(name) {
    const res = await getModuleStats(name)
    stats.value[name] = res
    return res
  }

  async function triggerScan(name) {
    return await scanModule(name)
  }

  return { modules, stats, loadModules, loadStats, triggerScan }
})
