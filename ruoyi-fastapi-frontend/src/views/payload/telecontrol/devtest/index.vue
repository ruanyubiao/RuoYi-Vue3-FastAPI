<template>
  <div class="app-container">
    <el-alert
      title="「开发测试」已迁移到菜单：调试 → 数据模拟"
      type="info"
      show-icon
      :closable="false"
    />
  </div>
</template>

<script setup name="DevTestRedirect">
import { useRouter } from 'vue-router'
const router = useRouter()
onMounted(() => {
  router.replace('/debug/simulate')
})
</script>
