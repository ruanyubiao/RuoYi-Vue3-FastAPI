<template>
  <div class="app-container">
    <div class="tm-header">
      <h3>遥测监控 · {{ tableName }} (0x{{ tmType }})</h3>
      <el-tag :type="connected ? 'success' : 'danger'">{{ connected ? '已连接' : '未连接' }}</el-tag>
      <el-select v-model="deviceId" style="width: 220px; margin-left: 12px" @change="onDeviceChange">
        <el-option v-for="d in deviceOptions" :key="d" :label="d" :value="d" />
      </el-select>
    </div>
    <el-table :data="rows" v-loading="loading" border stripe height="calc(100vh - 180px)">
      <el-table-column prop="id" label="编号" width="100" />
      <el-table-column prop="name" label="参数名称" min-width="180" show-overflow-tooltip />
      <el-table-column label="当前值" width="160">
        <template #default="{ row }">
          <span
            :class="cellClass(row.id)"
            class="value-cell"
            @click="goCurve(row)"
          >{{ row.show ?? row.value }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="unit" label="单位" width="80" />
      <el-table-column prop="hex" label="描述/HEX" min-width="120" show-overflow-tooltip />
    </el-table>
  </div>
</template>

<script setup name="PayloadTelemetryTable">
import { useRoute, useRouter } from 'vue-router'
import { getTelemetryDef } from '@/api/payload/config'
import { getTelemetryTable } from '@/api/payload/telemetry'
import { listCanChannels } from '@/api/payload/device'

const route = useRoute()
const router = useRouter()
const ACTIVE_KEY = 'payload:activeDeviceId'
const tmType = computed(() => (route.query.type || route.meta?.query?.type || 'FF').toString().toUpperCase())
const tableName = ref('')
const rows = ref([])
const prevValues = ref({})
const changedIds = ref(new Set())
const loading = ref(false)
const connected = ref(false)
const deviceId = ref(localStorage.getItem(ACTIVE_KEY) || 'can:0:0:0')
const deviceOptions = ref([deviceId.value])
let pollTimer = null

function cellClass(id) {
  return changedIds.value.has(id) ? 'cell-changed' : ''
}

function goCurve(row) {
  router.push({ path: '/telemetry/curve', query: { type: tmType.value, field: row.id } })
}

async function loadDef() {
  const res = await getTelemetryDef(tmType.value)
  tableName.value = res.data?.name || tmType.value
}

async function refresh() {
  loading.value = true
  try {
    const res = await getTelemetryTable(deviceId.value, tmType.value)
    const data = res.data || {}
    connected.value = !!data.ts
    const next = data.rows || []
    const changed = new Set()
    next.forEach(r => {
      const key = r.id
      const val = String(r.show ?? r.value)
      if (prevValues.value[key] !== undefined && prevValues.value[key] !== val) changed.add(key)
      prevValues.value[key] = val
    })
    changedIds.value = changed
    rows.value = next
  } finally {
    loading.value = false
  }
}

async function loadDevices() {
  const res = await listCanChannels()
  const list = (res.data || []).map(d => d.deviceId).filter(Boolean)
  if (list.length) deviceOptions.value = list
}

function onDeviceChange() {
  localStorage.setItem(ACTIVE_KEY, deviceId.value)
  prevValues.value = {}
  refresh()
}

onMounted(async () => {
  await loadDef()
  await loadDevices()
  refresh()
  pollTimer = setInterval(refresh, 1000)
})
onUnmounted(() => clearInterval(pollTimer))
</script>

<style scoped>
.tm-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.value-cell { cursor: pointer; }
.cell-changed { color: #409eff; font-weight: 600; animation: flash 1s ease; }
@keyframes flash { from { background: #ecf5ff; } to { background: transparent; } }
</style>
