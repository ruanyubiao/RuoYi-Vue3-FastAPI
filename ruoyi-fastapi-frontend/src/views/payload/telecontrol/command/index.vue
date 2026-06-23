<template>
  <div class="app-container command-page">
    <el-row :gutter="12" class="command-row">
      <el-col :span="6" class="panel">
        <el-input v-model="filterText" placeholder="搜索指令代号/名称" clearable class="mb8" />
        <el-tree
          ref="treeRef"
          :data="treeData"
          :props="{ label: 'label', children: 'children' }"
          highlight-current
          @node-click="onSelectOrder"
        />
      </el-col>
      <el-col :span="12" class="panel">
        <el-card shadow="never" v-if="currentOrder">
          <template #header>{{ currentOrder.id }} {{ currentOrder.name }}</template>
          <el-descriptions :column="2" border size="small" class="mb8">
            <el-descriptions-item label="指令代号">{{ currentOrder.id }}</el-descriptions-item>
            <el-descriptions-item label="参数长度">{{ assembled.length }} 字节</el-descriptions-item>
            <el-descriptions-item label="指令参数" :span="2">{{ assembled.hex || '-' }}</el-descriptions-item>
          </el-descriptions>
          <el-form label-width="120px">
            <el-form-item
              v-for="(comp, idx) in editableComponents"
              :key="idx"
              :label="comp.title || comp.name || `参数${idx + 1}`"
            >
              <el-input-number v-if="comp.componentType === 'number'" v-model="compValues[idx]" style="width: 200px" />
              <el-select v-else-if="comp.componentType === 'select'" v-model="compValues[idx]" style="width: 200px">
                <el-option v-for="(label, key) in comp.options || {}" :key="key" :label="label" :value="key" />
              </el-select>
              <el-input v-else v-model="compValues[idx]" style="width: 240px" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="handleAssemble">预览组帧</el-button>
              <el-button type="success" @click="handleSend" v-hasPermi="['payload:telecontrol:send']">发送指令</el-button>
            </el-form-item>
          </el-form>
        </el-card>
        <el-empty v-else description="请从左侧选择指令" />
      </el-col>
      <el-col :span="6" class="panel">
        <div class="history-header">
          <span>发送历史</span>
          <el-button link type="danger" @click="history = []">清空</el-button>
        </div>
        <el-scrollbar height="calc(100vh - 200px)">
          <div v-for="(h, i) in history" :key="i" class="history-item">
            <div class="history-time">{{ h.ts }}</div>
            <div>{{ h.name }}</div>
            <div class="history-hex">{{ h.hex }}</div>
            <el-tag :type="h.success ? 'success' : 'danger'" size="small">{{ h.message }}</el-tag>
          </div>
        </el-scrollbar>
      </el-col>
    </el-row>
  </div>
</template>

<script setup name="PayloadCommand">
import { getTelecontrolConfig } from '@/api/payload/config'
import { assembleTelecontrol, sendTelecontrol, getTelecontrolHistory } from '@/api/payload/telecontrol'

const ACTIVE_KEY = 'payload:activeDeviceId'
const filterText = ref('')
const treeData = ref([])
const rawPages = ref([])
const rawOrders = ref({})
const currentOrder = ref(null)
const compValues = ref([])
const assembled = reactive({ hex: '', length: 0, allChannel: false })
const history = ref([])
let historyTimer = null

const editableComponents = computed(() => {
  if (!currentOrder.value) return []
  return (currentOrder.value.component || []).filter(c => (c.componentType || '').toLowerCase() !== 'fixed')
})

function buildTree() {
  const pages = rawPages.value || []
  const orders = rawOrders.value || {}
  const kw = filterText.value.trim().toLowerCase()
  treeData.value = pages.map(page => ({
    label: page.name || page.id,
    children: (page.orderList || [])
      .map(oid => orders[oid])
      .filter(Boolean)
      .filter(o => !kw || `${o.id} ${o.name}`.toLowerCase().includes(kw))
      .map(o => ({ label: `[${o.id}] ${o.name}`, order: o }))
  })).filter(p => p.children.length)
}

function onSelectOrder(node) {
  if (!node.order) return
  currentOrder.value = node.order
  const comps = node.order.component || []
  compValues.value = comps.map(c => c.defaultVal ?? '')
  handleAssemble()
}

async function handleAssemble() {
  if (!currentOrder.value) return
  const res = await assembleTelecontrol({
    orderId: currentOrder.value.id,
    components: currentOrder.value.component,
    values: compValues.value
  })
  assembled.hex = res.data.hex
  assembled.length = res.data.length
  assembled.allChannel = !!res.data.allChannel
}

async function handleSend() {
  const deviceId = localStorage.getItem(ACTIVE_KEY)
  if (!deviceId) {
    ElMessage.warning('请先在控制开关页打开 CAN 通道')
    return
  }
  await handleAssemble()
  const sendRes = await sendTelecontrol({
    deviceId,
    orderId: currentOrder.value.id,
    name: currentOrder.value.name,
    hex: assembled.hex,
    broadcast: assembled.allChannel
  })
  ElMessage[sendRes.data.success ? 'success' : 'error'](sendRes.data.message || '已发送')
  refreshHistory()
}

async function refreshHistory() {
  const deviceId = localStorage.getItem(ACTIVE_KEY)
  if (!deviceId) return
  const res = await getTelecontrolHistory(deviceId)
  history.value = res.data || []
}

watch(filterText, buildTree)

onMounted(async () => {
  const res = await getTelecontrolConfig()
  rawPages.value = res.data.page || []
  rawOrders.value = res.data.order || {}
  buildTree()
  refreshHistory()
  historyTimer = setInterval(refreshHistory, 3000)
})
onUnmounted(() => clearInterval(historyTimer))
</script>

<style scoped>
.command-row { min-height: calc(100vh - 140px); }
.panel { background: var(--el-bg-color); border: 1px solid var(--el-border-color-lighter); border-radius: 4px; padding: 12px; min-height: 500px; }
.history-header { display: flex; justify-content: space-between; margin-bottom: 8px; font-weight: 600; }
.history-item { border-bottom: 1px dashed var(--el-border-color); padding: 8px 0; font-size: 12px; }
.history-time { color: var(--el-text-color-secondary); }
.history-hex { font-family: monospace; word-break: break-all; margin: 4px 0; }
</style>
