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
import { getTelemetryConfig } from '@/api/payload/config'
import { resolveTelecontrolFamily } from '@/utils/telecontrolFamily'

const route = useRoute()
const router = useRouter()

/** 从 query.family 或路径段解析 xl/biu */
function resolveFamily(r = route) {
  const q = String(r.query?.family || '').toLowerCase()
  if (q === 'xl' || q === 'biu') return q
  const seg = (r.path || '').split('/').filter(Boolean).pop() || ''
  if (/tableXl/i.test(seg) || /tmXl/i.test(seg)) return 'xl'
  if (/tableBiu/i.test(seg) || /tmBiu/i.test(seg)) return 'biu'
  // 兼容 /telemetry/... 下含 xl/biu 段
  return resolveTelecontrolFamily(r)
}

/** xl | biu，决定拉哪套遥测配置 */
const family = ref(resolveFamily())
const tmPages = ref([])
/** 当前表 key（与 PayloadTelemetryTable v-model:type 同步） */
const tmType = ref('')

/** 下拉选项：id=存储键，localKey=页面展示编号 */
const typeOptions = computed(() =>
  (tmPages.value || []).map(p => ({
    id: p.key,
    localKey: p.localKey || p.id || '',
    name: p.name || ''
  }))
)

/** 拉遥测页配置；优先 URL ?type=，否则保持当前或第一项 */
async function loadPages() {
  const res = await getTelemetryConfig(false, family.value)
  const list = res.data?.page || []
  tmPages.value = Array.isArray(list) ? list : []
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
  // 切表写回 URL，便于从曲线页返回时还原
  router.replace({ query: { ...route.query, type: key, family: family.value } })
})

watch(
  () => route.fullPath,
  () => {
    family.value = resolveFamily()
    loadPages()
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
