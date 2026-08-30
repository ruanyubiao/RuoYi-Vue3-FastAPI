<template>
  <el-config-provider :message="messageConfig">
    <router-view />
  </el-config-provider>
</template>

<script setup>
import { reactive, onMounted, nextTick } from 'vue'
import useSettingsStore from '@/store/modules/settings'
import { handleThemeStyle } from '@/utils/theme'

const messageConfig = reactive({
  duration: 2000, // ElMessage 默认显示 2 秒
})

onMounted(() => {
  nextTick(() => {
    // 初始化主题样式
    handleThemeStyle(useSettingsStore().theme)
  })
})
</script>
