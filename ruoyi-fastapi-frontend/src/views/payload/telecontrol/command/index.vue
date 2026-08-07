<template>
  <div class="command-page">
    <CanConnectToolbar
      ref="toolbarRef"
      :family="family"
      v-model:device-id="sendDeviceId"
    />
    <div class="command-body">
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
          :expand-on-click-node="false"
          highlight-current
          @node-click="onTreeNodeClick"
          @node-expand="onTreeNodeExpand"
          @node-collapse="onTreeNodeCollapse"
        />
      </el-scrollbar>
    </div>
    <div class="panel panel-detail">
      <template v-if="displayedOrders.length">
        <el-scrollbar class="panel-scroll">
          <div class="order-list">
            <div v-for="ord in displayedOrders" :key="ord.id" class="order-card">
              <div class="detail-header">
                {{ ord.id }} - {{ ord.name }} - {{ assembledLen(ord.id) || '-' }} 字节
              </div>
              <div class="detail-body">
                <div class="order-desc mb8">
                  <el-descriptions :column="1" border size="small" label-width="120px" class="order-desc-hex">
                    <el-descriptions-item label="指令参数">{{ assembledHexOf(ord.id) || '-' }}</el-descriptions-item>
                  </el-descriptions>
                </div>
                <el-form label-width="300px">
                  <el-form-item
                    v-for="entry in editableEntries(ord)"
                    :key="`${ord.id}-${entry.index}`"
                    :label="entry.comp.title || entry.comp.name || `参数${entry.index + 1}`"
                  >
                    <el-input-number
                      v-if="entry.type === 'number'"
                      v-model="compValuesByOrder[ord.id][entry.index]"
                      class="comp-field"
                      :precision="numberPrecision(entry.comp)"
                      :step="numberStep(entry.comp)"
                      :step-strictly="isIntegerDataType(entry.comp.dataType)"
                      @change="(val) => onOrderCompChange(ord, entry.index, entry.comp, val)"
                    />
                    <el-select
                      v-else-if="entry.type === 'select'"
                      v-model="compValuesByOrder[ord.id][entry.index]"
                      class="comp-field"
                      @change="() => onOrderCompChange(ord)"
                    >
                      <el-option
                        v-for="(label, key) in entry.comp.options || {}"
                        :key="key"
                        :label="label"
                        :value="key"
                      />
                    </el-select>
                    <el-input
                      v-else
                      v-model="compValuesByOrder[ord.id][entry.index]"
                      class="comp-field"
                      @change="() => onOrderCompChange(ord)"
                    />
                  </el-form-item>
                  <el-form-item>
                    <el-button
                      v-if="editableEntries(ord).length"
                      type="primary"
                      :loading="!!assemblingIds[ord.id]"
                      @click="handleAssemble(ord)"
                    >预览组帧</el-button>
                    <el-button
                      type="success"
                      :loading="!!sendingIds[ord.id]"
                      v-hasPermi="['payload:telecontrol:send']"
                      @click="handleSend(ord)"
                    >发送指令</el-button>
                  </el-form-item>
                </el-form>
              </div>
            </div>
          </div>
        </el-scrollbar>
      </template>
      <el-empty v-else class="detail-empty" :description="emptyDetailText" />
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
              <el-tag :type="h.success ? 'success' : 'danger'" size="small" class="history-tag">{{ h.channel || h.message }}</el-tag>
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
  </div>
</template>

<script setup name="Command">
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import CanConnectToolbar from '@/components/Payload/CanConnectToolbar.vue'
import { getTelecontrolConfig } from '@/api/payload/config'
import { assembleTelecontrol, sendTelecontrol, getTelecontrolHistory, clearTelecontrolHistory } from '@/api/payload/telecontrol'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import usePayloadCommandStore from '@/store/modules/payloadCommand'
import { resolveTelecontrolFamily } from '@/utils/telecontrolFamily'

const route = useRoute()
const family = ref(resolveTelecontrolFamily(route))
const sendDeviceId = ref('')
const toolbarRef = ref(null)
/** 本页发送历史对应的 A/B 通道（切换「当前发送」不切换历史） */
const histDevices = reactive({ a: '', b: '' })

const commandStore = usePayloadCommandStore()
const { filterText, currentOrderId, expandedTreeKeys } = storeToRefs(commandStore)
const treeRef = ref(null)
const treeRenderKey = ref(0)
const treeData = ref([])
const rawPages = ref([])
const rawOrders = ref({})
const history = ref([])
/** none | page | order */
const viewMode = ref('none')
const selectedPageKey = ref('')
const compValuesByOrder = reactive({})
const assembledByOrder = reactive({})
const assemblingIds = reactive({})
const sendingIds = reactive({})
const assemblePromises = {}
let historyTimer = null

const autoExpandAll = computed(() => getFilterKeywords(filterText.value).length > 0)

const treeDefaultExpandedKeys = computed(() => (
  autoExpandAll.value ? [] : [...expandedTreeKeys.value]
))

const displayedOrders = computed(() => {
  const keywords = getFilterKeywords(filterText.value)
  if (viewMode.value === 'order' && currentOrderId.value) {
    const o = rawOrders.value[currentOrderId.value]
    if (!o) return []
    // 单指令选中：搜索不匹配时中间也清空，复用空状态提示
    if (keywords.length && !matchesAllKeywords(`${o.id} ${o.name}`, keywords)) return []
    return [o]
  }
  if (viewMode.value === 'page' && selectedPageKey.value) {
    // 优先用已过滤的树节点；目录被筛掉时仍按原文+关键词过滤
    const page = treeData.value.find(p => p.nodeKey === selectedPageKey.value)
    if (page) {
      return (page.children || []).map(c => c.order).filter(Boolean)
    }
    const pageId = String(selectedPageKey.value).replace(/^page-/, '')
    const raw = (rawPages.value || []).find(p => String(p.id) === pageId)
    if (!raw) return []
    return (raw.orderList || [])
      .map(oid => rawOrders.value[oid])
      .filter(Boolean)
      .filter(o => matchesAllKeywords(`${o.id} ${o.name}`, keywords))
  }
  return []
})

const emptyDetailText = '请从左侧选择目录或指令'

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
    pageId: page.id,
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
      highlightCurrentSelection()
      return
    }
    const validKeys = expandedTreeKeys.value.filter(key =>
      treeData.value.some(page => page.nodeKey === key)
    )
    treeRef.value.store.setDefaultExpandedKeys(validKeys)
    highlightCurrentSelection()
  })
}

function highlightCurrentSelection() {
  nextTick(() => {
    if (viewMode.value === 'order' && currentOrderId.value) {
      treeRef.value?.setCurrentKey(currentOrderId.value)
    } else if (viewMode.value === 'page' && selectedPageKey.value) {
      treeRef.value?.setCurrentKey(selectedPageKey.value)
    }
  })
}

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

function editableEntries(ord) {
  return (ord?.component || [])
    .map((comp, index) => ({
      comp,
      index,
      type: (comp.componentType || '').toLowerCase()
    }))
    .filter(entry => entry.type !== 'fixed')
}

function assembledHexOf(orderId) {
  return assembledByOrder[orderId]?.hex || ''
}

function assembledLen(orderId) {
  return assembledByOrder[orderId]?.length || 0
}

function ensureOrderState(order) {
  if (!order?.id) return
  const id = order.id
  if (!compValuesByOrder[id]) {
    const draft = commandStore.orderDrafts[id]
    if (draft?.compValues?.length) {
      compValuesByOrder[id] = [...draft.compValues]
      assembledByOrder[id] = {
        hex: draft.assembledHex || '',
        length: draft.assembledLength || 0,
        allChannel: !!draft.assembledAllChannel
      }
    } else {
      compValuesByOrder[id] = (order.component || []).map(resolveComponentValue)
      assembledByOrder[id] = { hex: '', length: 0, allChannel: false }
    }
  }
}

function persistOrderState(orderId) {
  if (!orderId || !compValuesByOrder[orderId]) return
  const asm = assembledByOrder[orderId] || {}
  commandStore.saveOrderDraft(orderId, {
    compValues: compValuesByOrder[orderId],
    assembledHex: asm.hex || '',
    assembledLength: asm.length || 0,
    assembledAllChannel: !!asm.allChannel
  })
}

function onOrderCompChange(ord, index, comp, val) {
  if (!ord?.id) return
  if (comp && index != null && isIntegerDataType(comp.dataType)) {
    if (val !== null && val !== undefined && val !== '') {
      const n = Math.trunc(Number(val))
      if (Number.isFinite(n) && compValuesByOrder[ord.id][index] !== n) {
        compValuesByOrder[ord.id][index] = n
      }
    }
  }
  persistOrderState(ord.id)
  if (viewMode.value === 'order' && ord.id === currentOrderId.value) {
    commandStore.compValues = [...(compValuesByOrder[ord.id] || [])]
  }
}

function onTreeNodeClick(data) {
  if (data?.order?.id) {
    selectOrder(data.order)
    return
  }
  if (data?.nodeKey?.startsWith('page-') || Array.isArray(data?.children)) {
    selectPage(data)
  }
}

function selectOrder(order) {
  if (!order?.id) return
  viewMode.value = 'order'
  selectedPageKey.value = ''
  ensurePageExpandedForOrder(order.id)
  ensureOrderState(order)
  const isNew = order.id !== currentOrderId.value
  commandStore.switchOrder(order.id, compValuesByOrder[order.id])
  // store 可能带回草稿，同步到本地 map
  compValuesByOrder[order.id] = Array.isArray(commandStore.compValues)
    ? [...commandStore.compValues]
    : [...(compValuesByOrder[order.id] || [])]
  assembledByOrder[order.id] = {
    hex: commandStore.assembledHex || '',
    length: commandStore.assembledLength || 0,
    allChannel: !!commandStore.assembledAllChannel
  }
  highlightCurrentSelection()
  if (isNew && !assembledByOrder[order.id].hex) {
    handleAssemble(order).catch(() => {})
  }
}

function selectPage(pageNode) {
  if (!pageNode?.nodeKey) return
  viewMode.value = 'page'
  selectedPageKey.value = pageNode.nodeKey
  commandStore.clearCurrentOrder()
  const orders = (pageNode.children || []).map(c => c.order).filter(Boolean)
  for (const o of orders) {
    ensureOrderState(o)
    if (!assembledByOrder[o.id]?.hex) {
      handleAssemble(o).catch(() => {})
    }
  }
  nextTick(() => treeRef.value?.setCurrentKey(pageNode.nodeKey))
}

async function handleAssemble(ord) {
  if (!ord?.id) return
  if (assemblePromises[ord.id]) return assemblePromises[ord.id]
  ensureOrderState(ord)
  assemblingIds[ord.id] = true
  assemblePromises[ord.id] = (async () => {
    const res = await assembleTelecontrol({
      orderId: ord.id,
      components: ord.component,
      values: compValuesByOrder[ord.id]
    })
    assembledByOrder[ord.id] = {
      hex: res.data?.hex || '',
      length: res.data?.length || 0,
      allChannel: !!res.data?.allChannel
    }
    persistOrderState(ord.id)
    if (viewMode.value === 'order' && ord.id === currentOrderId.value) {
      commandStore.setAssembled(assembledByOrder[ord.id])
    }
  })()
  try {
    await assemblePromises[ord.id]
  } finally {
    assemblingIds[ord.id] = false
    delete assemblePromises[ord.id]
  }
}

async function handleSend(ord) {
  const deviceId = sendDeviceId.value
  if (!deviceId) {
    ElMessage.warning('请先打开 CAN-A/B 并选择当前发送口')
    return
  }
  if (!ord?.id || sendingIds[ord.id]) return
  sendingIds[ord.id] = true
  try {
    await handleAssemble(ord)
    const asm = assembledByOrder[ord.id]
    if (!asm?.hex) {
      ElMessage.warning('组帧结果为空，无法发送')
      return
    }
    const sendRes = await sendTelecontrol({
      deviceId,
      orderId: ord.id,
      name: ord.name,
      hex: asm.hex,
      broadcast: !!asm.allChannel
    })
    notifyPayloadSendResult(sendRes, { deviceId })
    syncHistDevices()
    await refreshHistory()
  } catch (e) {
    if (e && !e.message) {
      ElMessage.error('发送失败')
    }
  } finally {
    sendingIds[ord.id] = false
  }
}

function syncHistDevices() {
  const tb = toolbarRef.value
  const aId = tb?.slotA?.deviceId || ''
  const bId = tb?.slotB?.deviceId || ''
  if (aId) histDevices.a = aId
  if (bId) histDevices.b = bId
}

function historyTsKey(ts) {
  const s = String(ts || '')
  const t = Date.parse(s.replace(/-/g, '/'))
  return Number.isFinite(t) ? t : 0
}

async function fetchDeviceHistory(deviceId, channel) {
  if (!deviceId) return []
  try {
    const res = await getTelecontrolHistory(deviceId, 50)
    return (res.data || []).map(h => ({
      ...h,
      deviceId,
      channel,
      // 标签展示通道，不再用 OK
      message: channel
    }))
  } catch {
    return []
  }
}

async function refreshHistory() {
  syncHistDevices()
  const [listA, listB] = await Promise.all([
    fetchDeviceHistory(histDevices.a, 'CAN-A'),
    fetchDeviceHistory(histDevices.b, 'CAN-B')
  ])
  const merged = [...listA, ...listB].sort((x, y) => historyTsKey(y.ts) - historyTsKey(x.ts))
  history.value = merged.slice(0, 50)
}

async function handleClearHistory() {
  syncHistDevices()
  const ids = [...new Set([histDevices.a, histDevices.b].filter(Boolean))]
  for (const deviceId of ids) {
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
  // 保持目录/指令选中；中间区由 displayedOrders 随关键词过滤，无结果时走空状态提示
  restoreTreeExpansion()
  highlightCurrentSelection()
})

watch(currentOrderId, () => {
  if (viewMode.value === 'order') highlightCurrentSelection()
})

function startHistoryTimer() {
  stopHistoryTimer()
  refreshHistory()
  historyTimer = setInterval(refreshHistory, 3000)
}

function stopHistoryTimer() {
  if (historyTimer) clearInterval(historyTimer)
  historyTimer = null
}

onMounted(async () => {
  try {
    const res = await getTelecontrolConfig(false, family.value)
    const data = res.data || {}
    rawPages.value = data.page || []
    rawOrders.value = data.order || {}
    buildTree()
    // 恢复上次单指令选中
    if (currentOrderId.value && rawOrders.value[currentOrderId.value]) {
      viewMode.value = 'order'
      ensureOrderState(rawOrders.value[currentOrderId.value])
    }
    restoreTreeExpansion()
  } catch (e) {
    ElMessage.error(e?.message || '加载遥控配置失败')
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
  padding: 8px 8px 0;
  position: relative;
  width: 100%;
  height: 100%;
  max-height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.command-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 1fr 2fr 1fr;
  gap: 0;
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
.panel-tree {
  padding-right: 3px;
}
.panel-detail {
  padding-right: 3px;
}
.panel-history {
  padding-right: 3px;
}
.panel-search {
  flex-shrink: 0;
  margin-bottom: 8px;
}
.panel-tree :deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: color-mix(in srgb, var(--el-color-primary) 22%, transparent) !important;
  color: var(--el-color-primary);
  font-weight: 600;
  border-left: 3px solid var(--el-color-primary);
  padding-left: 5px;
}
.panel-tree :deep(.el-tree-node.is-current > .el-tree-node__content:hover) {
  background: color-mix(in srgb, var(--el-color-primary) 28%, transparent) !important;
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
.order-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 8px;
}
.order-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 10px 12px;
  background: var(--el-fill-color-blank);
}
.detail-header {
  flex-shrink: 0;
  margin-bottom: 8px;
  padding-bottom: 8px;
  font-weight: 600;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.detail-body {
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
.mb8 {
  margin-bottom: 8px;
}
</style>
