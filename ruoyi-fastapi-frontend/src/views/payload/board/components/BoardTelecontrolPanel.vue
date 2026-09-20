<template>
  <div class="panel board-tc-panel">
    <div class="panel-head">
      <span class="panel-title">遥控</span>
      <el-button class="export-tc-btn" link type="primary" @click="exportPreviewOrders">导出</el-button>
      <el-input
        v-model="filterText"
        clearable
        size="small"
        :placeholder="TELECONTROL_ORDER_FILTER_PLACEHOLDER"
        class="filter-input"
      />
    </div>
    <el-scrollbar class="panel-body">
      <div v-if="filteredOrders.length" class="order-list">
        <div v-for="ord in filteredOrders" :key="ord.id" class="order-card">
          <div class="order-title">
            <TelecontrolOrderTitle :order="ord" :byte-len="orderByteLen(ord)" />
          </div>
          <div class="order-desc mb8">
            <el-descriptions :column="1" border size="small" label-width="100px" class="order-desc-hex">
              <el-descriptions-item label="指令参数">
                {{ assembledMap[ord.id]?.hex || '-' }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
          <el-form label-width="140px" size="small" class="order-form">
            <template v-for="(comp, idx) in ord.component || []" :key="`${ord.id}-${idx}`">
              <el-form-item v-if="compType(comp) !== 'fixed'">
                <template #label>
                  <TelecontrolCompLabel :comp="comp" :index="idx" />
                </template>
                <el-input-number
                  v-if="compType(comp) === 'number'"
                  v-model="compValues[ord.id][idx]"
                  class="comp-field"
                  :min="numBound(comp.minVal)"
                  :max="numBound(comp.maxVal)"
                  :precision="numberPrecision(comp)"
                  :step="numberStep(comp)"
                  @change="() => onCompChange(ord)"
                />
                <el-select
                  v-else-if="compType(comp) === 'select'"
                  v-model="compValues[ord.id][idx]"
                  class="comp-field"
                  @change="() => onCompChange(ord)"
                >
                  <el-option
                    v-for="(label, key) in comp.options || {}"
                    :key="key"
                    :label="`${key} ${label}`"
                    :value="key"
                  />
                </el-select>
                <el-input
                  v-else
                  v-model="compValues[ord.id][idx]"
                  class="comp-field"
                  @change="() => onCompChange(ord)"
                />
              </el-form-item>
            </template>
            <el-form-item>
              <el-button
                type="primary"
                size="small"
                :loading="previewingId === ord.id"
                @click="previewOrder(ord)"
              >预览组帧</el-button>
              <el-button
                type="success"
                size="small"
                :loading="sendingId === ord.id"
                :disabled="!connected"
                @click="sendOrder(ord)"
              >发送指令</el-button>
            </el-form-item>
          </el-form>
        </div>
      </div>
      <el-empty v-else description="无匹配指令" :image-size="64" />
    </el-scrollbar>
  </div>
</template>

<script setup name="PayloadBoardTelecontrolPanel">
/**
 * 单板遥控区。参数改动通过 @comp-change 通知页面（摇杆等）。
 * 页面可用 ref 调用 setCompValues / previewOrderById / sendOrderById。
 */
import { ElMessage } from 'element-plus'
import { saveAs } from 'file-saver'
import {
  getXlBoardTelecontrolConfig,
  assembleXlBoardTelecontrol,
  sendXlBoardTelecontrol
} from '@/api/payload/xlBoard'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import TelecontrolCompLabel from '@/components/Payload/TelecontrolCompLabel.vue'
import TelecontrolOrderTitle from '@/components/Payload/TelecontrolOrderTitle.vue'
import cache from '@/plugins/cache'
import {
  numberPrecision,
  numberStep,
  numBound
} from '@/utils/telecontrolComponent'
import { orderMatchesFilter, TELECONTROL_ORDER_FILTER_PLACEHOLDER } from '@/utils/telecontrolOrderMatch'

const props = defineProps({
  /** rkdj | zk | dj | cpazx */
  board: { type: String, required: true },
  connected: { type: Boolean, default: false },
  deviceId: { type: String, default: '' },
  /** serial | udp，仅用于未连接时的提示 */
  connectKind: { type: String, default: 'serial' },
  prefsKey: { type: String, default: '' }
})

const emit = defineEmits(['comp-change', 'loaded'])

const isUdp = computed(() => String(props.connectKind || '').toLowerCase() === 'udp')
const boardId = computed(() => String(props.board || '').toLowerCase())

const filterText = ref('')
const rawOrders = ref({})
const orderIds = ref([])
const compValues = reactive({})
const assembledMap = reactive({})
const sendingId = ref('')
const previewingId = ref('')

const filteredOrders = computed(() => {
  const list = orderIds.value.map(id => rawOrders.value[id]).filter(Boolean)
  return list.filter(o => orderMatchesFilter(o, filterText.value))
})

function mergePrefs(patch) {
  if (!props.prefsKey) return
  const cur = cache.local.getJSON(props.prefsKey, {}) || {}
  cache.local.setJSON(props.prefsKey, { ...cur, ...patch })
}

function loadPrefs() {
  if (!props.prefsKey) return
  const p = cache.local.getJSON(props.prefsKey, {}) || {}
  if (p.filterText) filterText.value = p.filterText
}

function saveFilterPrefs() {
  mergePrefs({ filterText: filterText.value })
}

watch(filterText, saveFilterPrefs)

function compType(comp) {
  return String(comp?.componentType || 'fixed').toLowerCase()
}

function orderByteLen(ord) {
  const n = assembledMap[ord.id]?.length
  if (n != null && n > 0) return n
  const hex = assembledMap[ord.id]?.hex
  if (hex) {
    const s = String(hex).replace(/[^0-9A-Fa-f]/g, '')
    return Math.floor(s.length / 2) || '-'
  }
  return '-'
}

function firstSelectOptionKey(comp) {
  const opts = comp?.options || {}
  const keys = Object.keys(opts)
  return keys.length ? keys[0] : ''
}

function initCompValues(orders) {
  for (const [id, ord] of Object.entries(orders || {})) {
    if (!compValues[id]) compValues[id] = {}
    ;(ord.component || []).forEach((comp, idx) => {
      const t = compType(comp)
      if (compValues[id][idx] === undefined) {
        const def = comp.defaultVal
        if (t === 'number') {
          const n = Number(def)
          compValues[id][idx] = Number.isFinite(n) ? n : 0
        } else if (t === 'select') {
          const opts = comp.options || {}
          const defStr = def == null || def === '' ? '' : String(def)
          compValues[id][idx] =
            defStr && Object.prototype.hasOwnProperty.call(opts, defStr)
              ? defStr
              : firstSelectOptionKey(comp)
        } else {
          compValues[id][idx] = def ?? ''
        }
      } else if (t === 'select') {
        const cur = compValues[id][idx]
        if (cur === '' || cur == null) {
          compValues[id][idx] = firstSelectOptionKey(comp)
        }
      }
    })
  }
}

function onCompChange(ord) {
  previewOrder(ord, { showLoading: false })
  emit('comp-change', {
    orderId: ord.id,
    order: ord,
    values: { ...(compValues[ord.id] || {}) }
  })
}

function valuesForOrder(ord) {
  return (ord.component || []).map((comp, idx) => {
    if (compType(comp) === 'fixed') return comp.defaultVal
    const v = compValues[ord.id]?.[idx]
    if (compType(comp) === 'select') {
      if (v !== undefined && v !== null && v !== '') return v
      const def = comp.defaultVal
      const opts = comp.options || {}
      const defStr = def == null || def === '' ? '' : String(def)
      if (defStr && Object.prototype.hasOwnProperty.call(opts, defStr)) return defStr
      return firstSelectOptionKey(comp)
    }
    return v === undefined || v === null || v === '' ? comp.defaultVal : v
  })
}

async function previewOrder(ord, { showLoading = true } = {}) {
  if (!ord) return
  if (showLoading) previewingId.value = ord.id
  try {
    const res = await assembleXlBoardTelecontrol(boardId.value, {
      orderId: ord.id,
      values: valuesForOrder(ord)
    })
    assembledMap[ord.id] = { hex: res.data?.hex || '', length: res.data?.length || 0 }
    if (showLoading && res.data?.tip) {
      ElMessage.warning(res.data.tip)
    }
  } catch (e) {
    if (showLoading) ElMessage.error(e?.message || '组帧失败')
  } finally {
    if (showLoading) previewingId.value = ''
  }
}

function exportPreviewOrders() {
  const list = orderIds.value.map((id) => {
    const ord = rawOrders.value[id] || {}
    const asm = assembledMap[id] || {}
    const hex = asm.hex || ''
    const len = asm.length || hex.trim().split(/\s+/).filter(Boolean).length
    return {
      id: ord.id || id,
      name: ord.name || '',
      hex,
      len
    }
  })
  const blob = new Blob([JSON.stringify(list, null, 2) + '\n'], {
    type: 'application/json;charset=utf-8'
  })
  saveAs(blob, `${boardId.value}-tc-preview.json`)
  ElMessage.success(`已导出 ${list.length} 条指令`)
}

async function sendOrder(ord, extra = {}) {
  if (!ord) return
  const silent = !!extra.silent
  if (!props.connected || !props.deviceId) {
    if (!silent) ElMessage.warning(isUdp.value ? '请先连接 UDP' : '请先连接串口')
    return
  }
  if (!silent) sendingId.value = ord.id
  try {
    const payload = {
      deviceId: props.deviceId,
      orderId: ord.id,
      values: valuesForOrder(ord),
      name: ord.name
    }
    if (extra.wait === false) payload.wait = false
    if (extra.t != null) payload.t = extra.t
    const res = await sendXlBoardTelecontrol(boardId.value, payload)
    if (res.data?.hex) {
      assembledMap[ord.id] = { hex: res.data.hex, length: res.data.length || 0 }
    }
    if (!silent && res.data?.tip) {
      ElMessage.warning(res.data.tip)
    }
    if (!silent) notifyPayloadSendResult(res)
    return res
  } catch (e) {
    if (!silent) ElMessage.error(e?.message || '发送失败')
    throw e
  } finally {
    if (!silent) sendingId.value = ''
  }
}

async function loadOrders() {
  const res = await getXlBoardTelecontrolConfig(boardId.value)
  const data = res.data || {}
  rawOrders.value = data.order || {}
  const pages = data.page || []
  const ids = []
  if (pages.length) {
    for (const pg of pages) {
      for (const id of pg.orderList || []) {
        if (rawOrders.value[id] && !ids.includes(id)) ids.push(id)
      }
    }
  }
  if (!ids.length) ids.push(...Object.keys(rawOrders.value))
  orderIds.value = ids
  initCompValues(rawOrders.value)
  emit('loaded', { orders: rawOrders.value, orderIds: ids })
  await Promise.all(
    orderIds.value.map(id => {
      const ord = rawOrders.value[id]
      return ord ? previewOrder(ord, { showLoading: false }) : Promise.resolve()
    })
  )
}

function getOrder(id) {
  return rawOrders.value[id] || null
}

function getCompValues(id) {
  return compValues[id] || {}
}

function setCompValues(id, patch) {
  if (!compValues[id]) compValues[id] = {}
  Object.assign(compValues[id], patch)
}

function previewOrderById(id, opts) {
  const ord = rawOrders.value[id]
  if (ord) return previewOrder(ord, opts)
}

function sendOrderById(id, extra) {
  const ord = rawOrders.value[id]
  if (!ord) return Promise.resolve()
  return sendOrder(ord, extra)
}

defineExpose({
  getOrder,
  getCompValues,
  setCompValues,
  previewOrderById,
  sendOrderById
})

onMounted(async () => {
  loadPrefs()
  try {
    await loadOrders()
  } catch (e) {
    ElMessage.error(e?.message || '加载遥控配置失败')
  }
})
</script>

<style scoped>
.board-tc-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  overflow: hidden;
  background: var(--el-bg-color);
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--el-border-color);
  font-weight: 600;
  font-size: 13px;
  flex-shrink: 0;
}
.panel-title {
  line-height: 1.2;
}
.export-tc-btn {
  font-size: 12px !important;
  font-weight: 400 !important;
  height: auto !important;
  padding: 0 !important;
  margin: 0 !important;
  line-height: 1.2 !important;
  transform: translateY(1px);
}
.filter-input {
  margin-left: auto;
  width: 240px;
}
.panel-body {
  flex: 1;
  min-height: 0;
}
.order-list {
  padding: 8px;
}
.order-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 8px 10px;
  margin-bottom: 8px;
}
.order-title {
  font-weight: 600;
  margin-bottom: 6px;
  font-size: 13px;
}
.order-desc-hex :deep(.el-descriptions__content) {
  word-break: break-all;
  font-family: monospace;
  font-size: 12px;
}
.comp-field {
  width: 200px;
}
</style>
