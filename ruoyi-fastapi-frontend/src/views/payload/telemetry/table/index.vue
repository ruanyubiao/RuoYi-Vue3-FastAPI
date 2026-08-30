<template>
  <div class="app-container tm-page">
    <PayloadTelemetryTable
      v-if="typeOptions.length"
      level="t1"
      v-model:type="tmType"
      :types="typeOptions"
    />
  </div>
</template>

<script setup name="PayloadTelemetryTablePage">
import PayloadTelemetryTable from '@/components/Payload/PayloadTelemetryTable.vue'
import { loadTelemetryPagesCached } from '@/utils/telemetryPagesCache'

const tmPages = ref([])
/** 当前表 key（与 PayloadTelemetryTable v-model:type 同步） */
const tmType = ref('')

/** 下拉选项：全量 XL+BIU+相机，带 family 以便分组 */
const typeOptions = computed(() =>
  (tmPages.value || []).map(p => ({
    id: p.key,
    localKey: p.localKey || p.id || '',
    name: p.name || '',
    family: p.family || ''
  }))
)

/** 拉全部遥测页；保持当前选中或默认第一项（不写 URL query） */
async function loadPages() {
  tmPages.value = await loadTelemetryPagesCached()
  if (!tmPages.value.some(p => p.key === tmType.value)) {
    tmType.value = tmPages.value[0]?.key || ''
  }
}

onMounted(loadPages)
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
.tm-page :deep(.payload-tm-table) {
  flex: 1;
  min-height: 0;
}
</style>
