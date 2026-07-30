<template>
  <div class="app-container tm-page">
    <PayloadTelemetryTable level="t1" :types="tmTypes" />
  </div>
</template>

<script setup name="PayloadTelemetryTablePage">
import { useRoute } from 'vue-router'
import PayloadTelemetryTable from '@/components/Payload/PayloadTelemetryTable.vue'

const route = useRoute()

/** 优先从路径 tmFF 解析类型，兼容旧链接 ?type=FF */
function resolveTmType(r = route) {
  const fromQuery = r.query?.type
  if (fromQuery) return String(fromQuery).toUpperCase()
  const seg = (r.path || '').split('/').filter(Boolean).pop() || ''
  if (/^tm[0-9A-Fa-f]{2}$/i.test(seg)) return seg.slice(2).toUpperCase()
  return 'FF'
}

const tmTypes = computed(() => [resolveTmType()])
</script>

<style scoped>
.tm-page {
  height: 100%;
  max-height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
