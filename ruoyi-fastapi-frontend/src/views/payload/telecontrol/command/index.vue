<template>
  <div class="command-page">
    <div class="panel panel-tree">
      <el-input v-model="filterText" placeholder="搜索指令代号/名称" clearable class="panel-search" />
      <el-scrollbar class="panel-scroll">
        <el-tree
          ref="treeRef"
          :key="treeRenderKey"
          :data="treeData"
          node-key="nodeKey"
          :props="{ label: 'label', children: 'children' }"
          :default-expand-all="autoExpandAll"
          :default-expanded-keys="treeDefaultExpandedKeys"
          :expand-on-click-node="true"
          highlight-current
          @node-click="onSelectOrder"
          @node-expand="onTreeNodeExpand"
          @node-collapse="onTreeNodeCollapse"
        />
      </el-scrollbar>
    </div>
    <div class="panel panel-detail">
      <template v-if="currentOrder">
        <div :key="currentOrderId" class="detail-panel">
          <div class="detail-header">{{ currentOrder.id }} {{ currentOrder.name }}</div>
          <el-scrollbar class="panel-scroll">
            <div class="detail-body">
              <div class="order-desc mb8">
                <el-descriptions :column="2" border size="small" label-width="120px" class="order-desc-meta">
                  <el-descriptions-item label="指令代号">{{ currentOrder.id }}</el-descriptions-item>
                  <el-descriptions-item label="参数长度">{{ assembled.length }} 字节</el-descriptions-item>
                </el-descriptions>
                <el-descriptions :column="1" border size="small" label-width="120px" class="order-desc-hex">
                  <el-descriptions-item label="指令参数">{{ assembled.hex || '-' }}</el-descriptions-item>
                </el-descriptions>
              </div>
              <el-form label-width="300px">
                <el-form-item
                  v-for="entry in editableComponentEntries"
                  :key="entry.index"
                  :label="entry.comp.title || entry.comp.name || `参数${entry.index + 1}`"
                >
                  <el-input-number
                    v-if="entry.type === 'number'"
                    v-model="compValues[entry.index]"
                    class="comp-field"
                    :precision="numberPrecision(entry.comp)"
                    :step="numberStep(entry.comp)"
                    :step-strictly="isIntegerDataType(entry.comp.dataType)"
                    @change="(val) => normalizeIntegerValue(entry.index, entry.comp, val)"
                  />
                  <el-select v-else-if="entry.type === 'select'" v-model="compValues[entry.index]" class="comp-field">
                    <el-option v-for="(label, key) in entry.comp.options || {}" :key="key" :label="label" :value="key" />
                  </el-select>
                  <el-input v-else v-model="compValues[entry.index]" class="comp-field" />
                </el-form-item>
                <el-form-item>
                  <el-button v-if="editableComponentEntries.length" type="primary" :loading="assembling" @click="handleAssemble">预览组帧</el-button>
                  <el-button type="success" :loading="sending" @click="handleSend" v-hasPermi="['payload:telecontrol:send']">发送指令</el-button>
                </el-form-item>
              </el-form>
            </div>
          </el-scrollbar>
        </div>
      </template>
      <el-empty v-else class="detail-empty" description="请从左侧选择指令" />
    </div>
    <div class="panel panel-history">
      <div class="history-header">
        <span>发送历史</span>
        <el-button link type="danger" @click="handleClearHistory">清空</el-button>
      </div>
      <el-scrollbar class="panel-scroll">
        <div v-if="history.length" class="history-list">
          <div v-for="(h, i) in history" :key="i" class="history-item">
            <div class="history-summary">
              <el-tag :type="h.success ? 'success' : 'danger'" size="small" class="history-tag">{{ h.message }}</el-tag>
              <span class="history-time">{{ h.ts }}</span>
              <span class="history-name">{{ h.name }}</span>
            </div>
            <div class="history-hex">{{ h.hex }}</div>
          </div>
        </div>
        <el-empty v-else class="history-empty" description="暂无发送记录" :image-size="64" />
      </el-scrollbar>
    </div>
  </div>
</template>

<script setup name="Command">
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { getTelecontrolConfig } from '@/api/payload/config'
import { assembleTelecontrol, sendTelecontrol, getTelecontrolHistory, clearTelecontrolHistory } from '@/api/payload/telecontrol'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import usePayloadCommandStore from '@/store/modules/payloadCommand'

const ACTIVE_KEY = 'payload:activeDeviceId'
const commandStore = usePayloadCommandStore()
const { filterText, currentOrderId, compValues, expandedTreeKeys } = storeToRefs(commandStore)
const treeRef = ref(null)
const treeRenderKey = ref(0)
const treeData = ref([])
const rawPages = ref([])
const rawOrders = ref({})
const history = ref([])
const assembling = ref(false)
const sending = ref(false)
let historyTimer = null
let assemblePromise = null

const currentOrder = computed(() => {
  if (!currentOrderId.value) return null
  return rawOrders.value[currentOrderId.value] || null
})

const assembled = computed(() => ({
  hex: commandStore.assembledHex,
  length: commandStore.assembledLength,
  allChannel: commandStore.assembledAllChannel
}))

const autoExpandAll = computed(() => getFilterKeywords(filterText.value).length > 0)

const treeDefaultExpandedKeys = computed(() => (
  autoExpandAll.value ? [] : [...expandedTreeKeys.value]
))

function getFilterKeywords(text) {
  return String(text || '').trim().split(/\s+/).filter(Boolean)
}

function matchesAllKeywords(text, keywords) {
  if (!keywords.length) return true
  const hay = String(text || '').toLowerCase()
  return keywords.every(kw => hay.includes(String(kw).toLowerCase()))
}

function buildTree() {
  const pages = rawPages.value || []
  const orders = rawOrders.value || {}
  const keywords = getFilterKeywords(filterText.value)
  treeData.value = pages.map(page => ({
    nodeKey: `page-${page.id}`,
    label: page.name || page.id,
    children: (page.orderList || [])
      .map(oid => orders[oid])
      .filter(Boolean)
      .filter(o => matchesAllKeywords(`${o.id} ${o.name}`, keywords))
      .map(o => ({ nodeKey: o.id, label: `[${o.id}] ${o.name}`, order: o }))
  })).filter(p => p.children.length)
}

function onTreeNodeExpand(data) {
  if (data?.nodeKey) commandStore.addExpandedTreeKey(data.nodeKey)
}

function onTreeNodeCollapse(data) {
  if (data?.nodeKey) commandStore.removeExpandedTreeKey(data.nodeKey)
}

function ensurePageExpandedForOrder(orderId) {
  const page = treeData.value.find(p => p.children?.some(c => c.nodeKey === orderId))
  if (page) commandStore.addExpandedTreeKey(page.nodeKey)
}

function collectExpandedPageKeys() {
  const store = treeRef.value?.store
  if (!store?.nodesMap) return []
  const keys = []
  for (const node of Object.values(store.nodesMap)) {
    if (node.expanded && node.data?.nodeKey?.startsWith?.('page-')) {
      keys.push(node.data.nodeKey)
    }
  }
  return keys
}

function syncExpandedTreeKeysFromTree() {
  if (autoExpandAll.value) return
  const keys = collectExpandedPageKeys()
  if (keys.length) commandStore.setExpandedTreeKeys(keys)
}

function restoreTreeExpansion() {
  nextTick(() => {
    if (!treeRef.value?.store) return
    if (autoExpandAll.value) {
      highlightCurrentOrder()
      return
    }
    const validKeys = expandedTreeKeys.value.filter(key =>
      treeData.value.some(page => page.nodeKey === key)
    )
    treeRef.value.store.setDefaultExpandedKeys(validKeys)
    highlightCurrentOrder()
  })
}

function highlightCurrentOrder() {
  if (!currentOrderId.value) return
  nextTick(() => {
    treeRef.value?.setCurrentKey(currentOrderId.value)
  })
}

const editableComponentEntries = computed(() => {
  if (!currentOrder.value) return []
  return (currentOrder.value.component || [])
    .map((comp, index) => ({
      comp,
      index,
      type: (comp.componentType || '').toLowerCase()
    }))
    .filter(entry => entry.type !== 'fixed')
})

function resolveSelectDefault(comp) {
  const options = comp.options || {}
  const keys = Object.keys(options)
  const raw = comp.defaultVal
  if (raw !== '' && raw !== null && raw !== undefined) {
    const str = String(raw)
    if (Object.prototype.hasOwnProperty.call(options, str)) return str
    for (const [key, label] of Object.entries(options)) {
      if (label === str || key === str) return key
    }
  }
  return keys[0] ?? ''
}

function isIntegerDataType(dataType) {
  const dt = (dataType || 'INT16').toUpperCase()
  return dt !== 'FLOAT' && dt !== 'DOUBLE'
}

function numberPrecision(comp) {
  return isIntegerDataType(comp.dataType) ? 0 : undefined
}

function numberStep(comp) {
  return isIntegerDataType(comp.dataType) ? 1 : 0.01
}

function normalizeIntegerValue(index, comp, val) {
  if (!isIntegerDataType(comp.dataType)) return
  if (val === null || val === undefined || val === '') return
  const n = Math.trunc(Number(val))
  if (Number.isFinite(n) && compValues.value[index] !== n) {
    compValues.value[index] = n
  }
}

function resolveComponentValue(comp) {
  const type = (comp.componentType || '').toLowerCase()
  const raw = comp.defaultVal
  if (type === 'number') {
    if (raw === '' || raw === null || raw === undefined) return 0
    const num = Number(raw)
    const val = Number.isFinite(num) ? num : 0
    return isIntegerDataType(comp.dataType) ? Math.trunc(val) : val
  }
  if (type === 'select') {
    return resolveSelectDefault(comp)
  }
  if (type === 'scientific') {
    if (raw === '' || raw === null || raw === undefined) return '0'
    return String(raw)
  }
  if (raw === '' || raw === null || raw === undefined) return ''
  return String(raw)
}

function onSelectOrder(data) {
  if (!data?.order?.id) return
  const orderId = data.order.id
  ensurePageExpandedForOrder(orderId)
  const comps = data.order.component || []
  const isNewOrder = orderId !== currentOrderId.value
  const hadDraft = !!commandStore.orderDrafts[orderId]
  if (isNewOrder) {
    commandStore.switchOrder(orderId, comps.map(resolveComponentValue))
  }
  highlightCurrentOrder()
  if (isNewOrder && (!hadDraft || !commandStore.assembledHex)) {
    handleAssemble().catch(() => {})
  }
}

async function handleAssemble() {
  if (!currentOrder.value) return
  // 切换指令时已触发组装：发送前复用进行中的 Promise，避免连打两次 assemble
  if (assemblePromise) {
    return assemblePromise
  }
  assembling.value = true
  assemblePromise = (async () => {
    const res = await assembleTelecontrol({
      orderId: currentOrder.value.id,
      components: currentOrder.value.component,
      values: compValues.value
    })
    commandStore.setAssembled({
      hex: res.data.hex,
      length: res.data.length,
      allChannel: !!res.data.allChannel
    })
  })()
  try {
    await assemblePromise
  } finally {
    assembling.value = false
    assemblePromise = null
  }
}

async function handleSend() {
  const deviceId = localStorage.getItem(ACTIVE_KEY)
  if (!deviceId) {
    ElMessage.warning('请先在控制开关页打开 CAN 通道')
    return
  }
  if (sending.value) return
  sending.value = true
  try {
    await handleAssemble()
    if (!assembled.value.hex) {
      ElMessage.warning('组帧结果为空，无法发送')
      return
    }
    const sendRes = await sendTelecontrol({
      deviceId,
      orderId: currentOrder.value.id,
      name: currentOrder.value.name,
      hex: assembled.value.hex,
      broadcast: assembled.value.allChannel
    })
    notifyPayloadSendResult(sendRes, { deviceId })
    await refreshHistory()
  } catch (e) {
    // 全局拦截器已提示时不再重复；无 message 时兜底
    if (e && !e.message) {
      ElMessage.error('发送失败')
    }
  } finally {
    sending.value = false
  }
}

async function refreshHistory() {
  const deviceId = localStorage.getItem(ACTIVE_KEY)
  if (!deviceId) return
  const res = await getTelecontrolHistory(deviceId)
  history.value = res.data || []
}

async function handleClearHistory() {
  const deviceId = localStorage.getItem(ACTIVE_KEY)
  if (deviceId) {
    try {
      await clearTelecontrolHistory(deviceId)
    } catch {
      return
    }
  }
  history.value = []
}

watch(filterText, () => {
  buildTree()
  treeRenderKey.value += 1
  restoreTreeExpansion()
})

watch(compValues, () => {
  commandStore.persistCurrentDraft()
}, { deep: true })

function startHistoryTimer() {
  if (historyTimer) return
  refreshHistory()
  // 发送成功会立刻 refresh；定时器作兜底，间隔缩短以免看起来“卡”
  historyTimer = setInterval(refreshHistory, 1000)
}

function stopHistoryTimer() {
  if (!historyTimer) return
  clearInterval(historyTimer)
  historyTimer = null
}

onMounted(async () => {
  const res = await getTelecontrolConfig()
  rawPages.value = res.data.page || []
  rawOrders.value = res.data.order || {}
  buildTree()
  restoreTreeExpansion()
  if (currentOrderId.value && !commandStore.assembledHex) {
    await handleAssemble().catch(() => {})
  }
  startHistoryTimer()
})

onActivated(() => {
  if (rawPages.value.length) {
    buildTree()
    restoreTreeExpansion()
  }
  startHistoryTimer()
})

onDeactivated(() => {
  syncExpandedTreeKeysFromTree()
  stopHistoryTimer()
})
onUnmounted(stopHistoryTimer)
</script>

<style scoped>
.command-page {
  margin: 0;
  border: 0;
  padding: 0;
  position: relative;
  width: 100%;
  height: calc(100vh - 84px);
  overflow: hidden;
  display: grid;
  grid-template-columns: 1fr 2fr 1fr;
  gap: 0;
  box-sizing: border-box;
}
.panel {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 0;
  padding: 12px;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.panel:not(:first-child) {
  border-left: none;
}
.panel-search {
  flex-shrink: 0;
  margin-bottom: 8px;
}
.panel-scroll {
  flex: 1;
  min-height: 0;
  height: 0;
  width: 100%;
}
.panel-scroll :deep(.el-scrollbar) {
  height: 100%;
}
.panel-scroll :deep(.el-scrollbar__wrap) {
  overflow-x: hidden !important;
}
.panel-scroll :deep(.el-scrollbar__bar.is-vertical) {
  right: 0;
}
.panel-detail .detail-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-detail .detail-header {
  flex-shrink: 0;
  margin-bottom: 8px;
  padding-bottom: 8px;
  font-weight: 600;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.panel-detail .detail-body {
  padding-right: 4px;
}
.panel-detail .detail-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.history-header {
  flex-shrink: 0;
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-weight: 600;
}
.history-list {
  padding-right: 4px;
}
.history-empty {
  padding: 24px 0;
}
.history-item { border-bottom: 1px dashed var(--el-border-color); padding: 8px 0; font-size: 12px; }
.history-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.history-tag { flex-shrink: 0; }
.history-time {
  flex-shrink: 0;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.history-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-hex { font-family: monospace; word-break: break-all; margin-top: 4px; }
.order-desc {
  --order-desc-label-width: 70px;
}
.order-desc :deep(.el-descriptions__label) {
  width: var(--order-desc-label-width) !important;
  min-width: var(--order-desc-label-width);
  max-width: var(--order-desc-label-width);
  box-sizing: border-box;
}
.order-desc-meta :deep(.el-descriptions__body),
.order-desc-hex :deep(.el-descriptions__body) { margin-bottom: 0; }
.order-desc-hex :deep(.el-descriptions__body) { margin-top: -1px; }
.order-desc-hex :deep(.el-descriptions__content) {
  word-break: break-all;
  font-family: monospace;
  font-size: 12px;
  line-height: 1.5;
  vertical-align: top;
}
.order-desc-meta :deep(.el-descriptions__cell) { vertical-align: middle; }
.comp-field {
  width: 240px;
}
.comp-field.el-input-number {
  width: 240px;
}
</style>
