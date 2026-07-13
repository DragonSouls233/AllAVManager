<template>
  <div class="favorites">
    <el-card class="control-card">
      <div class="header-row">
        <el-radio-group v-model="entityType" @change="loadGroups">
          <el-radio-button label="movie">影片</el-radio-button>
          <el-radio-button label="actor">演员</el-radio-button>
          <el-radio-button label="studio">厂商</el-radio-button>
          <el-radio-button label="series">系列</el-radio-button>
        </el-radio-group>
        <el-button type="primary" @click="showCreate = true">
          <el-icon><Plus /></el-icon> 新建收藏夹
        </el-button>
      </div>
    </el-card>

    <el-row :gutter="16">
      <!-- 收藏夹列表 -->
      <el-col :span="6">
        <el-card v-loading="loadingGroups" class="groups-card">
          <el-empty v-if="!groups.length" description="暂无收藏夹" :image-size="60" />
          <div
            v-for="g in groups"
            :key="g.id"
            class="group-item"
            :class="{ active: selectedGroupId === g.id }"
            @click="selectGroup(g.id)"
          >
            <div class="group-info">
              <div class="group-name">{{ g.name }}</div>
              <el-tag size="small" type="info">{{ g.item_count }} 项</el-tag>
            </div>
            <el-dropdown trigger="click" @command="handleGroupCommand($event, g)">
              <el-icon class="group-more"><MoreFilled /></el-icon>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </el-card>
      </el-col>

      <!-- 条目列表 -->
      <el-col :span="18">
        <el-card v-loading="loadingItems" class="items-card">
          <template #header>
            <div class="items-header">
              <span>{{ selectedGroup?.name || '请选择收藏夹' }}</span>
              <el-button v-if="selectedGroupId" size="small" @click="refreshItems">刷新</el-button>
            </div>
          </template>

          <el-empty v-if="!selectedGroupId" description="请从左侧选择收藏夹" />
          <el-empty v-else-if="!items.length" description="收藏夹为空" />
          <div v-else class="items-grid">
            <div v-for="item in items" :key="item.id" class="item-card">
              <div class="item-cover" @click="goToEntity(item)">
                <img
                  v-if="item.entity_cover"
                  :src="item.entity_cover"
                  :alt="item.entity_name"
                  @error="handleCoverError"
                >
                <div v-else class="item-cover-placeholder">
                  <el-icon size="32"><Picture /></el-icon>
                </div>
              </div>
              <div class="item-info">
                <div class="item-name">{{ item.entity_name || `#${item.entity_id}` }}</div>
                <el-button size="small" type="danger" link @click="removeItem(item)">
                  <el-icon><Delete /></el-icon> 移除
                </el-button>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 新建收藏夹对话框 -->
    <el-dialog v-model="showCreate" title="新建收藏夹" width="400px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="newGroupName" placeholder="收藏夹名称" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="newGroupType" style="width: 100%">
            <el-option label="影片" value="movie" />
            <el-option label="演员" value="actor" />
            <el-option label="厂商" value="studio" />
            <el-option label="系列" value="series" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="createGroup">创建</el-button>
      </template>
    </el-dialog>

    <!-- 重命名对话框 -->
    <el-dialog v-model="showRename" title="重命名收藏夹" width="400px">
      <el-input v-model="renameValue" placeholder="新名称" />
      <template #footer>
        <el-button @click="showRename = false">取消</el-button>
        <el-button type="primary" @click="doRename">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, MoreFilled, Delete, Picture } from '@element-plus/icons-vue'
import {
  getFavoriteGroups, createFavoriteGroup, updateFavoriteGroup, deleteFavoriteGroup,
  getFavoriteItems, removeFavoriteItem,
} from '@/api'
import { defaultCover } from '@/utils/media'

const router = useRouter()

const entityType = ref('movie')
const groups = ref([])
const selectedGroupId = ref(null)
const items = ref([])
const loadingGroups = ref(false)
const loadingItems = ref(false)

const showCreate = ref(false)
const newGroupName = ref('')
const newGroupType = ref('movie')

const showRename = ref(false)
const renameValue = ref('')
const renameTarget = ref(null)

const selectedGroup = computed(() => groups.value.find(g => g.id === selectedGroupId.value))

const loadGroups = async () => {
  loadingGroups.value = true
  try {
    const res = await getFavoriteGroups(entityType.value)
    groups.value = res.items ? res : (res.data || res)
  } catch (e) {
    ElMessage.error('加载收藏夹失败')
  } finally {
    loadingGroups.value = false
  }
}

const selectGroup = async (id) => {
  selectedGroupId.value = id
  await loadItems()
}

const loadItems = async () => {
  if (!selectedGroupId.value) return
  loadingItems.value = true
  try {
    const res = await getFavoriteItems(selectedGroupId.value)
    items.value = res.items ? res : (res.data || res)
  } catch (e) {
    ElMessage.error('加载条目失败')
  } finally {
    loadingItems.value = false
  }
}

const refreshItems = () => loadItems()

const createGroup = async () => {
  if (!newGroupName.value) {
    ElMessage.warning('请输入名称')
    return
  }
  try {
    await createFavoriteGroup(newGroupName.value, newGroupType.value)
    ElMessage.success('创建成功')
    showCreate.value = false
    newGroupName.value = ''
    entityType.value = newGroupType.value
    await loadGroups()
  } catch (e) {
    ElMessage.error('创建失败')
  }
}

const handleGroupCommand = (command, group) => {
  if (command === 'rename') {
    renameTarget.value = group
    renameValue.value = group.name
    showRename.value = true
  } else if (command === 'delete') {
    ElMessageBox.confirm(`确定删除收藏夹「${group.name}」？`, '提示', { type: 'warning' })
      .then(async () => {
        await deleteFavoriteGroup(group.id)
        ElMessage.success('已删除')
        if (selectedGroupId.value === group.id) {
          selectedGroupId.value = null
          items.value = []
        }
        await loadGroups()
      })
      .catch(() => {})
  }
}

const doRename = async () => {
  if (!renameValue.value || !renameTarget.value) return
  try {
    await updateFavoriteGroup(renameTarget.value.id, { name: renameValue.value })
    ElMessage.success('已重命名')
    showRename.value = false
    await loadGroups()
  } catch (e) {
    ElMessage.error('重命名失败')
  }
}

const removeItem = async (item) => {
  try {
    await removeFavoriteItem(item.group_id, item.entity_id)
    ElMessage.success('已移除')
    await loadItems()
    await loadGroups()
  } catch (e) {
    ElMessage.error('移除失败')
  }
}

const goToEntity = (item) => {
  if (item.entity_type === 'movie') {
    router.push(`/movie/${item.entity_id}`)
  } else if (item.entity_type === 'actor') {
    router.push(`/actors/${item.entity_id}`)
  }
}

const handleCoverError = (event) => {
  event.target.src = defaultCover()
}

onMounted(() => {
  loadGroups()
})
</script>

<style scoped>
.favorites {
  max-width: 1200px;
  margin: 0 auto;
}
.header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.control-card {
  margin-bottom: 16px;
}
.groups-card {
  min-height: 400px;
}
.group-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 4px;
}
.group-item:hover {
  background: #f5f7fa;
}
.group-item.active {
  background: #ecf5ff;
}
.group-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}
.group-name {
  font-weight: 500;
}
.group-more {
  cursor: pointer;
  color: #909399;
}
.items-card {
  min-height: 400px;
}
.items-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.items-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 16px;
}
.item-card {
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  border: 1px solid #ebeef5;
}
.item-cover {
  height: 200px;
  background: #f5f7fa;
  cursor: pointer;
  overflow: hidden;
}
.item-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.item-cover-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #c0c4cc;
}
.item-info {
  padding: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.item-name {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100px;
}
</style>
