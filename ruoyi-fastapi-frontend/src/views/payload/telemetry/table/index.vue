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
import cache from '@/plugins/cache'
import { loadTelemetryPagesCached } from '@/utils/telemetryPages'

const LIVE_PREFS_KEY = 'payload:telemetry:live:prefs:v1'
const livePrefs = cache.local.getJSON(LIVE_PREFS_KEY, {}) || {}

const tmPages = ref([])
/** 当前表 key（与 PayloadTelemetryTable v-model:type 同步） */
const tmType = ref(String(livePrefs.tmType || ''))

/** 下拉选项：全量 XL+BIU+相机，带 family 以便分组 */
const typeOptions = computed(() =>
  (tmPages.value || []).map(p => ({
    id: p.key,
    localKey: p.localKey || p.id || '',
    name: p.name || '',
    family: p.family || ''
  }))
)

function writeLivePrefs() {
  cache.local.setJSON(LIVE_PREFS_KEY, { tmType: tmType.value || '' })
}

/** 拉全部遥测页；优先本地偏好，否则保持当前或第一项（不写 URL query） */
async function loadPages() {
  tmPages.value = await loadTelemetryPagesCached()
  if (tmType.value && tmPages.value.some(p => p.key === tmType.value)) {
    return
  }
  const saved = String((cache.local.getJSON(LIVE_PREFS_KEY, {}) || {}).tmType || '')
  const hit = saved && tmPages.value.find(p => p.key === saved)
  tmType.value = hit?.key || tmPages.value[0]?.key || ''
}

watch(tmType, writeLivePrefs)

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
