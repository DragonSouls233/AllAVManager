import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'

/**
 * 操作可撤销/重试机制 Store
 *
 * 设计：
 * - undoStack：已执行操作栈（最近执行的在栈顶），undo 时弹出并执行其 undo 回调
 * - redoStack：被撤销操作栈，redo 时弹出并重新执行其 redo 回调
 * - pushAction(desc, { undo, redo })：在执行风险操作"前"调用，登记撤销/重做回调
 * - undo()：撤销最近一次操作
 * - redo()：重做最近一次撤销的操作
 * - clear()：清空两个栈（如切换页面/用户时调用）
 *
 * 说明：
 * - 回调可为异步函数，返回值会被 await
 * - 单条记录保留快照与描述，便于在 UI 中展示"撤销 XXX"提示
 */
export const useUndoStore = defineStore('undo', () => {
  const undoStack = ref([])
  const redoStack = ref([])
  // 最多保留 50 条历史，防止内存膨胀
  const MAX_STACK = 50

  const canUndo = computed(() => undoStack.value.length > 0)
  const canRedo = computed(() => redoStack.value.length > 0)
  const undoCount = computed(() => undoStack.value.length)
  const redoCount = computed(() => redoStack.value.length)

  /**
   * 登记一个可撤销操作
   * @param {string} description 操作描述，用于提示，如"删除影片"
   * @param {Object} handlers
   * @param {Function} handlers.undo 撤销回调（恢复到操作前状态）
   * @param {Function} handlers.redo  重做回调（重新执行该操作）
   * @returns {number} 操作记录 id
   */
  function pushAction(description, { undo, redo }) {
    const id = Date.now() + Math.random()
    const record = {
      id,
      description: description || '未命名操作',
      undo: typeof undo === 'function' ? undo : () => {},
      redo: typeof redo === 'function' ? redo : () => {},
      timestamp: id,
    }
    undoStack.value.push(record)
    // 新操作清空 redo 栈（标准撤销/重做语义）
    redoStack.value = []
    // 超出上限丢弃最旧记录
    if (undoStack.value.length > MAX_STACK) {
      undoStack.value.shift()
    }
    return id
  }

  /**
   * 撤销最近一次操作
   */
  async function undo() {
    if (!undoStack.value.length) {
      ElMessage.info('没有可撤销的操作')
      return false
    }
    const record = undoStack.value.pop()
    try {
      await record.undo()
      redoStack.value.push(record)
      if (redoStack.value.length > MAX_STACK) {
        redoStack.value.shift()
      }
      ElMessage.success(`已撤销：${record.description}`)
      return true
    } catch (e) {
      // 撤销失败时把记录放回栈顶，保持状态一致
      undoStack.value.push(record)
      ElMessage.error(`撤销失败：${e?.message || '未知错误'}`)
      return false
    }
  }

  /**
   * 重做最近一次被撤销的操作
   */
  async function redo() {
    if (!redoStack.value.length) {
      ElMessage.info('没有可重做的操作')
      return false
    }
    const record = redoStack.value.pop()
    try {
      await record.redo()
      undoStack.value.push(record)
      if (undoStack.value.length > MAX_STACK) {
        undoStack.value.shift()
      }
      ElMessage.success(`已重做：${record.description}`)
      return true
    } catch (e) {
      redoStack.value.push(record)
      ElMessage.error(`重做失败：${e?.message || '未知错误'}`)
      return false
    }
  }

  /**
   * 清空历史记录
   */
  function clear() {
    undoStack.value = []
    redoStack.value = []
  }

  /**
   * 获取最近一次操作描述（用于 UI 提示）
   */
  const lastAction = computed(() => {
    return undoStack.value.length ? undoStack.value[undoStack.value.length - 1] : null
  })

  return {
    undoStack,
    redoStack,
    canUndo,
    canRedo,
    undoCount,
    redoCount,
    lastAction,
    pushAction,
    undo,
    redo,
    clear,
  }
})
