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
import { useRoute, useRouter } from 'vue-router'
import PayloadTelemetryTable from '@/components/Payload/PayloadTelemetryTable.vue'
import { loadTelemetryPagesCached } from '@/utils/telemetryPagesCache'

const route = useRoute()
const router = useRouter()

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

/** 拉全部遥测页；优先 URL ?type=，否则保持当前或第一项 */
async function loadPages() {
  tmPages.value = await loadTelemetryPagesCached()
  const fromQuery = route.query?.type ? String(route.query.type).toUpperCase() : ''
  const hit =
    (fromQuery && tmPages.value.find(p => String(p.key).toUpperCase() === fromQuery)) ||
    (fromQuery &&
      tmPages.value.find(p => String(p.localKey || p.id || '').toUpperCase() === fromQuery)) ||
    null
  if (hit) {
    tmType.value = hit.key
  } else if (!tmPages.value.some(p => p.key === tmType.value)) {
    tmType.value = tmPages.value[0]?.key || ''
  }
}

watch(tmType, key => {
  if (!key) return
  const cur = String(route.query?.type || '')
  if (cur === key) return
  router.replace({ query: { ...route.query, type: key } })
})

watch(
  () => route.query?.type,
  t => {
    if (!tmPages.value.length) return
    const key = t ? String(t).toUpperCase() : ''
    if (!key) return
    const hit =
      tmPages.value.find(p => String(p.key).toUpperCase() === key) ||
      tmPages.value.find(p => String(p.localKey || p.id || '').toUpperCase() === key)
    if (hit && tmType.value !== hit.key) tmType.value = hit.key
  }
)

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
