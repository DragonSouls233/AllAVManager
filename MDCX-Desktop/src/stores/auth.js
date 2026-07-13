import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const TOKEN_KEY = 'token'
const USER_KEY = 'mdcx_user'

/**
 * 认证 Store
 * 统一管理 token、用户信息和登录态
 */
export const useAuthStore = defineStore('auth', () => {
  // ============== State ==============
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const user = ref(JSON.parse(localStorage.getItem(USER_KEY) || 'null'))

  // ============== Getters ==============
  const isAuthenticated = computed(() => !!token.value)
  const username = computed(() => user.value?.username || '管理员')

  // ============== Actions ==============
  /**
   * 设置 token（登录成功或自动登录）
   * @param {string} newToken
   * @param {object} [userInfo] 用户信息（可选）
   */
  function setToken(newToken, userInfo = null) {
    token.value = newToken
    if (newToken) {
      localStorage.setItem(TOKEN_KEY, newToken)
    } else {
      localStorage.removeItem(TOKEN_KEY)
    }
    if (userInfo) {
      setUser(userInfo)
    }
  }

  /**
   * 设置用户信息
   */
  function setUser(userInfo) {
    user.value = userInfo
    if (userInfo) {
      localStorage.setItem(USER_KEY, JSON.stringify(userInfo))
    } else {
      localStorage.removeItem(USER_KEY)
    }
  }

  /**
   * 登出：清空 token 和用户信息
   */
  function logout() {
    setToken('')
    setUser(null)
  }

  return {
    // state
    token,
    user,
    // getters
    isAuthenticated,
    username,
    // actions
    setToken,
    setUser,
    logout
  }
})
