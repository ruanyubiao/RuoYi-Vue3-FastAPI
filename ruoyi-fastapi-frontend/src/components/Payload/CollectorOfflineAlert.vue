<template>
  <el-alert
    v-if="host && online === false"
    class="collector-offline"
    type="warning"
    show-icon
    :closable="false"
    :title="`采集机 ${host} 已离线`"
  />
</template>

<script setup>
defineProps({
  host: { type: String, default: '' },
  online: { type: Boolean, default: true }
})
</script>

<style scoped>
.collector-offline {
  margin-bottom: 12px;
}
</style>
