<template>
  <div class="actor-detail" v-loading="loading">
    <el-button text @click="goBack" style="margin-bottom: 16px">
      <el-icon><ArrowLeft /></el-icon> 返回演员列表
    </el-button>

    <div v-if="actor" class="detail-content">
      <div class="avatar-section">
        <img :src="actor.avatar_url || defaultAvatar" alt="">
        <h2>{{ actor.name }}</h2>
        <el-tag v-if="actor.source" type="info" size="small">{{ actor.source }}</el-tag>
        <div class="stats">
          <span>{{ actor.movie_count }} 部作品</span>
        </div>
      </div>

      <div class="info-section">
        <el-descriptions :column="2" border size="small" v-if="hasInfo">
          <el-descriptions-item label="性别" v-if="actor.gender">{{ actor.gender }}</el-descriptions-item>
          <el-descriptions-item label="出生日期" v-if="actor.birthdate">{{ actor.birthdate }}</el-descriptions-item>
          <el-descriptions-item label="国家" v-if="actor.country">{{ actor.country }}</el-descriptions-item>
          <el-descriptions-item label="族裔" v-if="actor.ethnicity">{{ actor.ethnicity }}</el-descriptions-item>
          <el-descriptions-item label="身高" v-if="actor.height">{{ actor.height }} cm</el-descriptions-item>
          <el-descriptions-item label="体重" v-if="actor.weight">{{ actor.weight }} kg</el-descriptions-item>
          <el-descriptions-item label="三围" v-if="actor.measurements" :span="2">{{ actor.measurements }}</el-descriptions-item>
          <el-descriptions-item label="Twitter" v-if="actor.twitter" :span="2">
            <a :href="actor.twitter" target="_blank">{{ actor.twitter }}</a>
          </el-descriptions-item>
          <el-descriptions-item label="Instagram" v-if="actor.instagram" :span="2">
            <a :href="actor.instagram" target="_blank">{{ actor.instagram }}</a>
          </el-descriptions-item>
        </el-descriptions>

        <div class="alias-section" v-if="actor.alias">
          <h3>别名</h3>
          <p>{{ actor.alias }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWesternStore } from '@/stores/western'
import defaultAvatar from '@/assets/default-avatar.png'

const route = useRoute()
const router = useRouter()
const store = useWesternStore()
const actor = ref(null)
const loading = ref(true)

const hasInfo = computed(() => {
  if (!actor.value) return false
  return actor.value.gender || actor.value.birthdate || actor.value.country ||
         actor.value.ethnicity || actor.value.height || actor.value.weight ||
         actor.value.measurements || actor.value.twitter || actor.value.instagram
})

function goBack() {
  router.push('/western/actors')
}

onMounted(async () => {
  try {
    actor.value = await store.loadActorDetail(route.params.id)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.actor-detail { padding: 20px; }
.detail-content { display: flex; gap: 24px; }
.avatar-section { flex-shrink: 0; width: 200px; text-align: center; }
.avatar-section img { width: 150px; height: 150px; border-radius: 50%; object-fit: cover; margin-bottom: 12px; }
.avatar-section h2 { font-size: 18px; margin-bottom: 8px; }
.stats { font-size: 13px; color: #999; margin-top: 8px; }
.info-section { flex: 1; }
.alias-section { margin-top: 16px; }
.alias-section h3 { font-size: 14px; margin-bottom: 8px; }
.alias-section p { line-height: 1.6; color: #666; font-size: 13px; }
</style>
