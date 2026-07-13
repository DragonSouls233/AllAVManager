<template>
  <div class="users-page">
    <!-- 顶部 -->
    <el-card shadow="never" class="header-card">
      <div class="header">
        <h2 class="page-title">
          <el-icon><UserFilled /></el-icon>
          用户管理
        </h2>
        <div class="header-right">
          <el-button type="warning" plain @click="ensureAdmin">
            <el-icon><Key /></el-icon> 初始化默认管理员
          </el-button>
          <el-button type="primary" @click="openCreateDialog">
            <el-icon><Plus /></el-icon> 新建用户
          </el-button>
          <el-button @click="loadUsers">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 用户列表 -->
    <el-card shadow="never" class="list-card">
      <el-table :data="users" stripe v-loading="loading">
        <el-table-column label="用户" min-width="180">
          <template #default="{ row }">
            <div class="user-cell">
              <div class="user-avatar">
                <img
                  v-if="row.avatar_url"
                  :src="getAvatarUrl(row.avatar_url)"
                  :alt="row.username"
                  @error="handleAvatarError"
                />
                <span v-else>{{ (row.username || '?').slice(0, 1).toUpperCase() }}</span>
              </div>
              <div class="user-meta">
                <div class="user-name">{{ row.display_name || row.username }}</div>
                <div class="user-username">@{{ row.username }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" effect="dark" size="small">
              {{ row.role === 'admin' ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" effect="plain" size="small">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="NSFW" width="80">
          <template #default="{ row }">
            <el-tag :type="row.nsfw_allowed ? 'warning' : 'info'" effect="plain" size="small">
              {{ row.nsfw_allowed ? '允许' : '禁止' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" width="160">
          <template #default="{ row }">
            {{ row.last_login_at ? formatTime(row.last_login_at) : '从未' }}
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openSessionDialog(row)">
              <el-icon><Monitor /></el-icon> 会话
            </el-button>
            <el-button size="small" type="primary" plain @click="openEditDialog(row)">
              编辑
            </el-button>
            <el-popconfirm
              :title="`确定删除用户「${row.username}」吗？`"
              @confirm="removeUser(row)"
            >
              <template #reference>
                <el-button size="small" type="danger" plain :disabled="row.role === 'admin'">
                  删除
                </el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建/编辑用户对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editMode ? '编辑用户' : '新建用户'"
      width="480px"
    >
      <el-form :model="form" label-width="100px">
        <el-form-item label="用户名" v-if="!editMode">
          <el-input v-model="form.username" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item label="用户名" v-else>
          <el-input :model-value="form.username" disabled />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="form.display_name" placeholder="可选，用于显示" />
        </el-form-item>
        <el-form-item :label="editMode ? '新密码' : '密码'">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="editMode ? '留空则不修改' : '登录密码'"
          />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
        <el-form-item label="NSFW 权限">
          <el-switch v-model="form.nsfw_allowed" />
        </el-form-item>
        <el-form-item label="头像 URL">
          <el-input v-model="form.avatar_url" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveUser">保存</el-button>
      </template>
    </el-dialog>

    <!-- 会话管理对话框 -->
    <el-dialog v-model="sessionDialogVisible" title="设备会话管理" width="640px">
      <div v-if="sessionUser">
        <div class="session-user-info">
          <span>用户：{{ sessionUser.username }}</span>
          <el-button size="small" type="danger" plain @click="revokeAllSessions(sessionUser)">
            注销所有会话
          </el-button>
        </div>
        <el-table :data="sessions" stripe size="small" v-loading="sessionLoading" style="margin-top: 12px">
          <el-table-column prop="device_name" label="设备" min-width="120" />
          <el-table-column prop="device_type" label="类型" width="80" />
          <el-table-column prop="ip_address" label="IP" width="120" />
          <el-table-column label="登录时间" width="160">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="过期时间" width="160">
            <template #default="{ row }">{{ formatTime(row.expires_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-popconfirm title="确定注销此会话？" @confirm="revokeSession(sessionUser, row)">
                <template #reference>
                  <el-button size="small" type="danger" plain>注销</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  UserFilled, Plus, Refresh, Key, Monitor
} from '@element-plus/icons-vue'
import {
  listUsers, createUser, updateUser, deleteUser,
  listUserSessions, revokeUserSession, revokeAllUserSessions,
  ensureDefaultAdmin
} from '@/api'
import { getServerBaseUrl, getFileProxyUrl } from '@/utils/media'

const loading = ref(false)
const saving = ref(false)
const users = ref([])
const dialogVisible = ref(false)
const editMode = ref(false)
const form = ref({
  id: null,
  username: '',
  display_name: '',
  password: '',
  role: 'user',
  is_active: true,
  nsfw_allowed: true,
  avatar_url: ''
})

// 会话管理
const sessionDialogVisible = ref(false)
const sessionUser = ref(null)
const sessions = ref([])
const sessionLoading = ref(false)

const getAvatarUrl = (avatar) => {
  if (/^https?:\/\//i.test(avatar)) return avatar
  return getFileProxyUrl(avatar)
}

const handleAvatarError = (e) => {
  e.target.style.display = 'none'
}

const formatTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit'
  })
}

const loadUsers = async () => {
  loading.value = true
  try {
    const res = await listUsers()
    users.value = res.items || []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const openCreateDialog = () => {
  editMode.value = false
  form.value = {
    id: null,
    username: '',
    display_name: '',
    password: '',
    role: 'user',
    is_active: true,
    nsfw_allowed: true,
    avatar_url: ''
  }
  dialogVisible.value = true
}

const openEditDialog = (user) => {
  editMode.value = true
  form.value = {
    id: user.id,
    username: user.username,
    display_name: user.display_name || '',
    password: '',
    role: user.role,
    is_active: user.is_active,
    nsfw_allowed: user.nsfw_allowed,
    avatar_url: user.avatar_url || ''
  }
  dialogVisible.value = true
}

const saveUser = async () => {
  saving.value = true
  try {
    if (editMode.value) {
      const data = {
        display_name: form.value.display_name || null,
        role: form.value.role,
        is_active: form.value.is_active,
        nsfw_allowed: form.value.nsfw_allowed,
        avatar_url: form.value.avatar_url || null
      }
      if (form.value.password) data.password = form.value.password
      await updateUser(form.value.id, data)
      ElMessage.success('用户已更新')
    } else {
      if (!form.value.username || !form.value.password) {
        ElMessage.warning('请填写用户名和密码')
        saving.value = false
        return
      }
      await createUser({
        username: form.value.username,
        password: form.value.password,
        display_name: form.value.display_name || null,
        role: form.value.role,
        nsfw_allowed: form.value.nsfw_allowed
      })
      ElMessage.success('用户已创建')
    }
    dialogVisible.value = false
    loadUsers()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const removeUser = async (user) => {
  try {
    await deleteUser(user.id)
    ElMessage.success('用户已删除')
    loadUsers()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

const ensureAdmin = async () => {
  try {
    const res = await ensureDefaultAdmin()
    if (res.created) {
      ElMessage.success('默认管理员已创建：admin / admin，请尽快修改密码')
    } else {
      ElMessage.info('已存在用户，无需初始化')
    }
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

// 会话管理
const openSessionDialog = async (user) => {
  sessionUser.value = user
  sessionDialogVisible.value = true
  sessionLoading.value = true
  try {
    const res = await listUserSessions(user.id)
    sessions.value = res.items || []
  } catch (e) {
    console.error(e)
  } finally {
    sessionLoading.value = false
  }
}

const revokeSession = async (user, session) => {
  try {
    await revokeUserSession(user.id, session.id)
    sessions.value = sessions.value.filter(s => s.id !== session.id)
    ElMessage.success('会话已注销')
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

const revokeAllSessions = async (user) => {
  try {
    const res = await revokeAllUserSessions(user.id)
    ElMessage.success(`已注销 ${res.revoked || 0} 个会话`)
    sessions.value = []
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

onMounted(() => loadUsers())
</script>

<style scoped>
.users-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.header-card,
.list-card {
  border-radius: 8px !important;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.page-title {
  margin: 0;
  font-size: 18px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-right {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* 用户单元格 */
.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--primary-color);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  overflow: hidden;
  flex-shrink: 0;
}

.user-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.user-meta {
  min-width: 0;
}

.user-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.user-username {
  font-size: 12px;
  color: var(--text-secondary);
}

/* 会话对话框 */
.session-user-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--bg-card);
  border-radius: 6px;
  font-weight: 600;
}
</style>
