<template>
  <div class="app-container log-download-page">
    <RecvFileBrowserDialog embedded mode="download" :multiple="true" />
  </div>
</template>

<script setup>
import RecvFileBrowserDialog from '@/components/Payload/RecvFileBrowserDialog.vue'
</script>

<style scoped>
.log-download-page {
  min-height: calc(100vh - 120px);
}
</style>
