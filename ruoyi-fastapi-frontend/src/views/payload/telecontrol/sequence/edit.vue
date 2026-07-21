<template>
  <div class="seq-edit-page">
    <!-- 左：指令树 -->
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
          highlight-current
          :expand-on-click-node="true"
          @node-click="onSelectOrder"
        />
      </el-scrollbar>
    </div>

    <!-- 中：选中指令序列项后可编辑 -->
    <div class="panel panel-detail">
      <template v-if="selectedIndex >= 0">
        <div class="detail-panel">
          <div class="detail-header">
            <span v-if="currentOrder">{{ currentOrder.id }} {{ currentOrder.name }}</span>
            <span v-else>编辑指令序列项</span>
            <el-tag size="small" type="warning" style="margin-left: 8px">已选中序列项 #{{ selectedIndex + 1 }}</el-tag>
          </div>
          <el-scrollbar class="panel-scroll">
            <div class="detail-body">
              <div class="order-desc mb8">
                <el-descriptions :column="1" border size="small" label-width="90px" class="order-desc-meta">
                  <el-descriptions-item label="指令代号">{{ currentOrder?.id || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="参数长度">{{ assembled.length }} 字节</el-descriptions-item>
                </el-descriptions>
                <el-descriptions :column="1" border size="small" label-width="90px" class="order-desc-hex">
                  <el-descriptions-item label="指令参数">{{ assembled.hex || selectedCmd?.hex || '-' }}</el-descriptions-item>
                </el-descriptions>
              </div>

              <el-form label-width="280px" :disabled="!canEditMiddle">
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
                    @change="onCompUserEdit"
                  />
                  <el-select
                    v-else-if="entry.type === 'select'"
                    v-model="compValues[entry.index]"
                    class="comp-field"
                    @change="onCompUserEdit"
                  >
                    <el-option v-for="(label, key) in entry.comp.options || {}" :key="key" :label="label" :value="key" />
                  </el-select>
                  <el-input
                    v-else
                    v-model="compValues[entry.index]"
                    class="comp-field"
                    @change="onCompUserEdit"
                    @input="onCompUserEdit"
                  />
                </el-form-item>
                <el-form-item>
                  <el-button
                    v-if="hasEditableInputs"
                    type="primary"
                    :loading="assembling"
                    :disabled="!currentOrder"
                    @click="handleAssemble"
                  >预览组帧</el-button>
                  <el-button type="success" :loading="assembling" :disabled="!canApply" @click="applyToSelected">设置指令</el-button>
                </el-form-item>
              </el-form>
              <el-alert
                v-if="!currentOrder"
                type="info"
                :closable="false"
                show-icon
                title="请从左侧选择遥控指令进行组帧；名称与间隔请在右侧指令列表中修改。"
                style="margin-top: 8px"
              />
            </div>
          </el-scrollbar>
        </div>
      </template>
      <el-empty v-else class="detail-empty" description="请在右侧指令列表中选中一行后再编辑" />
    </div>

    <!-- 右：整栏滚动（元数据 + 指令列表） -->
    <div class="panel panel-seq">
      <div ref="seqScrollRef" class="seq-scroll">
        <div class="seq-header">指令序列</div>
        <el-form ref="formRef" :model="form" :rules="rules" label-width="80px" class="seq-meta" size="small">
          <el-form-item label="序列名称" prop="seqName">
            <el-input v-model="form.seqName" placeholder="请输入序列名称" />
          </el-form-item>
          <el-form-item label="默认间隔" prop="defaultInterval">
            <el-input-number
              v-model="form.defaultInterval"
              :min="0"
              :step="100"
              controls-position="right"
              class="seq-interval-field"
            />
            <span class="seq-interval-unit">ms</span>
          </el-form-item>
          <el-form-item label="状态" prop="status">
            <el-radio-group v-model="form.status">
              <el-radio v-for="dict in sys_normal_disable" :key="dict.value" :value="dict.value">{{ dict.label }}</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="备注" prop="remark">
            <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="备注" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" @click="submitForm">保 存</el-button>
            <el-button @click="goBack">取 消</el-button>
          </el-form-item>
        </el-form>

        <div class="seq-list-head">
          <span class="seq-list-title">指令列表</span>
          <el-button
            class="seq-clear-btn"
            link
            type="danger"
            :disabled="!form.commandList.length"
            @click="clearCommands"
          >清理指令</el-button>
        </div>
        <div v-if="form.commandList.length" class="cmd-list">
          <div
            v-for="(cmd, index) in form.commandList"
            :key="cmd._uid"
            :data-cmd-index="index"
            class="cmd-item"
            :class="{ active: index === selectedIndex, 'is-invalid-hex': invalidHexIndexes.includes(index) }"
            @click="selectCommand(index)"
          >
            <div class="cmd-item-top">
              <span class="cmd-idx">#{{ index + 1 }}</span>
              <span class="cmd-order-id">{{ cmd.orderId || '-' }}</span>
              <el-input
                v-model="cmd.name"
                size="small"
                :placeholder="cmdNamePlaceholder(cmd)"
                class="cmd-name-input"
                @click.stop
              />
              <el-input-number
                v-model="cmd.interval"
                size="small"
                :min="-1"
                :step="100"
                controls-position="right"
                class="cmd-interval-input"
                @click.stop
              />
              <span class="seq-interval-unit">ms</span>
            </div>
            <div class="cmd-hex">{{ cmd.hex || '(空)' }}</div>
            <div class="cmd-actions">
              <el-tooltip content="在本指令后插入一行" placement="top" :show-after="300" popper-class="theme-aware-tooltip">
                <el-button link type="primary" icon="Plus" @click.stop="insertAfter(index)" />
              </el-tooltip>
              <el-tooltip content="上移" placement="top" :show-after="300" popper-class="theme-aware-tooltip">
                <el-button link type="primary" icon="Top" :disabled="index === 0" @click.stop="moveCommand(index, -1)" />
              </el-tooltip>
              <el-tooltip content="下移" placement="top" :show-after="300" popper-class="theme-aware-tooltip">
                <el-button
                  link
                  type="primary"
                  icon="Bottom"
                  :disabled="index === form.commandList.length - 1"
                  @click.stop="moveCommand(index, 1)"
                />
              </el-tooltip>
              <el-tooltip content="删除" placement="top" :show-after="300" popper-class="theme-aware-tooltip">
                <el-button link type="danger" icon="Delete" @click.stop="removeCommand(index)" />
              </el-tooltip>
            </div>
          </div>
        </div>
        <div v-else class="cmd-list-empty">
          <el-button type="primary" plain icon="Plus" @click="addCommand">添加指令</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup name="PayloadSequenceEdit">
import { ElMessage, ElMessageBox } from 'element-plus'
import { getTelecontrolConfig } from '@/api/payload/config'
import { assembleTelecontrol } from '@/api/payload/telecontrol'
import { addSequence, getSequence, updateSequence, copySequence } from '@/api/payload/sequence'

const route = useRoute()
const { proxy } = getCurrentInstance()
const { sys_normal_disable } = proxy.useDict('sys_normal_disable')

const DEFAULT_INTERVAL = 2000
const USE_DEFAULT_INTERVAL = -1
let uidSeq = 1
function nextUid() {
  return `c-${Date.now()}-${uidSeq++}`
}

const formRef = ref(null)
const treeRef = ref(null)
const seqScrollRef = ref(null)
const treeRenderKey = ref(0)
const treeData = ref([])
const rawPages = ref([])
const rawOrders = ref({})
const filterText = ref('')
const saving = ref(false)
const assembling = ref(false)
const selectedIndex = ref(-1)
const invalidHexIndexes = ref([])
const currentOrderId = ref('')
const compValues = ref([])
const assembledHex = ref('')
const assembledLength = ref(0)
/** 用户是否手动改过中间参数输入框 */
const userEditedInputs = ref(false)
/** 加载/保存后的参数值基线 */
let valuesBaseline = ''

const form = reactive({
  seqId: undefined,
  seqName: '',
  defaultInterval: DEFAULT_INTERVAL,
  commandList: [],
  status: '0',
  remark: ''
})

const rules = {
  seqName: [{ required: true, message: '序列名称不能为空', trigger: 'blur' }]
}

const currentOrder = computed(() => {
  if (!currentOrderId.value) return null
  return rawOrders.value[currentOrderId.value] || null
})

const assembled = computed(() => ({
  hex: assembledHex.value,
  length: assembledLength.value
}))

const selectedCmd = computed(() => {
  if (selectedIndex.value < 0) return null
  return form.commandList[selectedIndex.value] || null
})

const canEditMiddle = computed(() => selectedIndex.value >= 0)

const canApply = computed(() => selectedIndex.value >= 0 && !!currentOrderId.value)

const autoExpandAll = computed(() => getFilterKeywords(filterText.value).length > 0)

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

/** 单帧（无可编辑输入控件）不显示预览组帧 */
const hasEditableInputs = computed(() => editableComponentEntries.value.length > 0)

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
  treeData.value = pages
    .map(page => ({
      nodeKey: `page-${page.id}`,
      label: page.name || page.id,
      children: (page.orderList || [])
        .map(oid => orders[oid])
        .filter(Boolean)
        .filter(o => matchesAllKeywords(`${o.id} ${o.name}`, keywords))
        .map(o => ({ nodeKey: o.id, label: `[${o.id}] ${o.name}`, order: o }))
    }))
    .filter(p => p.children.length)
  treeRenderKey.value += 1
}

watch(filterText, () => buildTree())

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

function resolveSelectDefault(comp) {
  const options = comp.options || {}
  const keys = Object.keys(options)
  const raw = comp.defaultVal
  if (raw !== '' && raw !== null && raw !== undefined) {
    const str = String(raw)
    if (Object.prototype.hasOwnProperty.call(options, str)) return str
  }
  return keys[0] ?? ''
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
  if (type === 'select') return resolveSelectDefault(comp)
  if (type === 'scientific') return raw === '' || raw == null ? '0' : String(raw)
  if (raw === '' || raw === null || raw === undefined) return ''
  return String(raw)
}

function emptyCommand() {
  return {
    _uid: nextUid(),
    name: '',
    hex: '',
    interval: USE_DEFAULT_INTERVAL,
    orderId: '',
    values: []
  }
}

function normalizeInterval(value) {
  if (value === '' || value === null || value === undefined) return USE_DEFAULT_INTERVAL
  const num = Number(value)
  return Number.isFinite(num) ? num : USE_DEFAULT_INTERVAL
}

function normalizeCommands(list) {
  return (list || []).map(item => ({
    _uid: nextUid(),
    name: item.name || '',
    hex: (item.hex || '').toUpperCase(),
    interval: normalizeInterval(item.interval),
    orderId: item.orderId || item.order_id || '',
    values: Array.isArray(item.values) ? [...item.values] : []
  }))
}

function cmdNamePlaceholder(cmd) {
  if (!cmd?.orderId) return '名称'
  const order = rawOrders.value[cmd.orderId]
  return order?.name || cmd.orderId || '名称'
}

function resolveCompValuesForOrder(order, savedValues) {
  const comps = order?.component || []
  if (!Array.isArray(savedValues) || !savedValues.length) {
    return comps.map(resolveComponentValue)
  }
  return comps.map((comp, index) => {
    const saved = savedValues[index]
    if (saved === undefined || saved === null || saved === '') {
      return resolveComponentValue(comp)
    }
    return saved
  })
}

function ensurePageExpandedForOrder(orderId) {
  if (!orderId || !treeRef.value) return
  const page = treeData.value.find(p => p.children?.some(c => c.nodeKey === orderId))
  if (!page) return
  const node = treeRef.value.getNode?.(page.nodeKey)
  if (node && !node.expanded) node.expand()
}

function highlightOrderInTree(orderId) {
  nextTick(() => {
    if (!orderId) {
      treeRef.value?.setCurrentKey?.(null)
      return
    }
    ensurePageExpandedForOrder(orderId)
    nextTick(() => treeRef.value?.setCurrentKey?.(orderId))
  })
}

/** 兼容旧版数组，以及 { defaultInterval, items } 对象格式 */
function parseCommandsPayload(raw) {
  let data = raw
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data || '[]')
    } catch {
      data = []
    }
  }
  if (Array.isArray(data)) {
    return { defaultInterval: DEFAULT_INTERVAL, items: data }
  }
  if (data && typeof data === 'object') {
    const di = Number(data.defaultInterval ?? data.default_interval)
    return {
      defaultInterval: Number.isFinite(di) && di >= 0 ? di : DEFAULT_INTERVAL,
      items: data.items || data.commands || []
    }
  }
  return { defaultInterval: DEFAULT_INTERVAL, items: [] }
}

function takeValuesSnapshot() {
  return JSON.stringify(compValues.value)
}

function markMiddleClean() {
  valuesBaseline = takeValuesSnapshot()
  userEditedInputs.value = false
}

function onCompUserEdit() {
  if (selectedIndex.value < 0) return
  userEditedInputs.value = true
}

/** 仅当：用户手动改过输入框，且当前值与基线不同，才算未保存修改 */
function isMiddleDirty() {
  if (selectedIndex.value < 0) return false
  if (!userEditedInputs.value) return false
  if (!editableComponentEntries.value.length) return false
  return takeValuesSnapshot() !== valuesBaseline
}

function withMiddleLoad(fn) {
  fn()
  markMiddleClean()
  nextTick(() => nextTick(() => markMiddleClean()))
}

function confirmLeaveMiddle() {
  if (!isMiddleDirty()) return Promise.resolve(true)
  return ElMessageBox.confirm('当前编辑尚未保存到指令列表，是否放弃修改？', '提示', {
    type: 'warning',
    confirmButtonText: '放弃修改',
    cancelButtonText: '继续编辑'
  })
    .then(() => true)
    .catch(() => false)
}

function clearMiddleEditor() {
  withMiddleLoad(() => {
    currentOrderId.value = ''
    compValues.value = []
    assembledHex.value = ''
    assembledLength.value = 0
    highlightOrderInTree('')
  })
}

function loadMiddleFromCommand(cmd) {
  withMiddleLoad(() => {
    assembledHex.value = cmd.hex || ''
    assembledLength.value = cmd.hex ? cmd.hex.trim().split(/\s+/).filter(Boolean).length : 0
    if (cmd.orderId && rawOrders.value[cmd.orderId]) {
      const order = rawOrders.value[cmd.orderId]
      currentOrderId.value = cmd.orderId
      compValues.value = resolveCompValuesForOrder(order, cmd.values)
      highlightOrderInTree(cmd.orderId)
    } else {
      currentOrderId.value = cmd.orderId || ''
      compValues.value = Array.isArray(cmd.values) ? [...cmd.values] : []
      highlightOrderInTree(cmd.orderId || '')
    }
  })
}

function scrollCmdIntoView(index) {
  nextTick(() => {
    const root = seqScrollRef.value
    if (!root) return
    const el = root.querySelector(`[data-cmd-index="${index}"]`)
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}

async function selectCommand(index) {
  if (index === selectedIndex.value) return
  const ok = await confirmLeaveMiddle()
  if (!ok) return
  if (index < 0 || index >= form.commandList.length) {
    selectedIndex.value = -1
    clearMiddleEditor()
    return
  }
  selectedIndex.value = index
  loadMiddleFromCommand(form.commandList[index])
  scrollCmdIntoView(index)
}

async function addCommand() {
  const ok = await confirmLeaveMiddle()
  if (!ok) return
  const cmd = emptyCommand()
  form.commandList.push(cmd)
  selectedIndex.value = form.commandList.length - 1
  loadMiddleFromCommand(cmd)
  scrollCmdIntoView(selectedIndex.value)
}

async function insertAfter(index) {
  const ok = await confirmLeaveMiddle()
  if (!ok) return
  const cmd = emptyCommand()
  form.commandList.splice(index + 1, 0, cmd)
  selectedIndex.value = index + 1
  loadMiddleFromCommand(cmd)
  scrollCmdIntoView(selectedIndex.value)
}

function moveCommand(index, delta) {
  const target = index + delta
  if (target < 0 || target >= form.commandList.length) return
  const list = form.commandList
  const tmp = list[index]
  list[index] = list[target]
  list[target] = tmp
  if (selectedIndex.value === index) selectedIndex.value = target
  else if (selectedIndex.value === target) selectedIndex.value = index
}

function isEmptyCommand(cmd) {
  return !(cmd?.hex || '').trim() && !(cmd?.orderId || '').trim()
}

function doRemoveCommand(index) {
  const leavingSelected = selectedIndex.value === index
  form.commandList.splice(index, 1)
  invalidHexIndexes.value = invalidHexIndexes.value
    .filter(i => i !== index)
    .map(i => (i > index ? i - 1 : i))
  if (!form.commandList.length) {
    selectedIndex.value = -1
    clearMiddleEditor()
    return
  }
  if (leavingSelected) {
    markMiddleClean()
    const next = Math.min(index, form.commandList.length - 1)
    selectedIndex.value = next
    loadMiddleFromCommand(form.commandList[next])
  } else if (selectedIndex.value > index) {
    selectedIndex.value -= 1
  }
}

function removeCommand(index) {
  const cmd = form.commandList[index]
  if (isEmptyCommand(cmd)) {
    doRemoveCommand(index)
    return
  }
  ElMessageBox.confirm(`确认删除指令列表第 ${index + 1} 条？`, '提示', { type: 'warning' })
    .then(() => doRemoveCommand(index))
    .catch(() => {})
}

function clearCommands() {
  ElMessageBox.confirm('确认清理指令列表中的全部指令？', '提示', { type: 'warning' })
    .then(() => {
      markMiddleClean()
      form.commandList = []
      selectedIndex.value = -1
      clearMiddleEditor()
    })
    .catch(() => {})
}

async function onSelectOrder(data) {
  if (!canEditMiddle.value) {
    ElMessage.warning('请先在右侧选中一条指令')
    return
  }
  if (!data?.order?.id) return
  const order = data.order
  if (order.id === currentOrderId.value) return
  if (isMiddleDirty()) {
    const ok = await confirmLeaveMiddle()
    if (!ok) {
      highlightOrderInTree(currentOrderId.value)
      return
    }
  }
  currentOrderId.value = order.id
  const row = form.commandList[selectedIndex.value]
  // 切回「当前列表项已设置」的同一指令编号时，恢复已保存的参数值；切到其他指令用默认值
  if (row?.orderId && order.id === row.orderId) {
    compValues.value = resolveCompValuesForOrder(order, row.values)
    assembledHex.value = row.hex || ''
    assembledLength.value = row.hex ? row.hex.trim().split(/\s+/).filter(Boolean).length : 0
  } else {
    compValues.value = (order.component || []).map(resolveComponentValue)
    assembledHex.value = ''
    assembledLength.value = 0
  }
  ensurePageExpandedForOrder(order.id)
  markMiddleClean()
  handleAssemble().catch(() => {})
}

async function handleAssemble() {
  if (!currentOrder.value) {
    ElMessage.warning('请先从左侧选择遥控指令')
    return false
  }
  assembling.value = true
  try {
    const res = await assembleTelecontrol({
      orderId: currentOrder.value.id,
      components: currentOrder.value.component,
      values: compValues.value
    })
    assembledHex.value = res.data?.hex || ''
    assembledLength.value = res.data?.length || 0
    return !!assembledHex.value
  } finally {
    assembling.value = false
  }
}

async function applyToSelected() {
  if (selectedIndex.value < 0) return
  if (!currentOrderId.value) {
    ElMessage.warning('请先从左侧选择遥控指令（需记住指令编号）')
    return
  }
  const ok = await handleAssemble()
  if (!ok) {
    ElMessage.warning('组帧失败，未写入指令列表')
    return
  }
  const hex = (assembledHex.value || '').trim().toUpperCase()
  if (!hex) {
    ElMessage.warning('指令 HEX 为空，请检查参数后重试')
    return
  }
  const row = form.commandList[selectedIndex.value]
  row.hex = hex
  row.orderId = currentOrderId.value
  row.values = Array.isArray(compValues.value) ? [...compValues.value] : []
  // name 保持用户输入；默认为空，列表用指令原名作占位
  invalidHexIndexes.value = invalidHexIndexes.value.filter(i => i !== selectedIndex.value)
  markMiddleClean()
  ElMessage.success('已设置到指令列表')
}

function goBack() {
  proxy.$tab.closeOpenPage({ path: '/telecontrol/sequence' })
}

function submitForm() {
  formRef.value?.validate(valid => {
    if (!valid) return
    const items = form.commandList.map(({ name, hex, interval, orderId, values }) => ({
      name: name || '',
      hex: (hex || '').toUpperCase(),
      interval: normalizeInterval(interval),
      orderId: orderId || '',
      values: Array.isArray(values) ? values : []
    }))
    if (items.some(item => !item.hex || !item.hex.trim())) {
      invalidHexIndexes.value = items
        .map((item, index) => (!item.hex || !item.hex.trim() ? index : -1))
        .filter(index => index >= 0)
      ElMessage.warning('存在空的指令 HEX，请填写或删除该行')
      return
    }
    invalidHexIndexes.value = []
    if (items.some(item => !item.orderId)) {
      ElMessage.warning('存在未关联指令编号的项，请选中后从左侧选择指令并点「设置指令」')
      return
    }
    const defaultInterval =
      form.defaultInterval != null && Number(form.defaultInterval) >= 0
        ? Number(form.defaultInterval)
        : DEFAULT_INTERVAL
    const payload = {
      seqId: form.seqId,
      seqName: form.seqName,
      status: form.status,
      remark: form.remark,
      commands: JSON.stringify({ defaultInterval, items })
    }
    saving.value = true
    const isUpdate = payload.seqId != null
    const req = isUpdate ? updateSequence(payload) : addSequence(payload)
    req
      .then(res => {
        if (!isUpdate) {
          const newId = res?.data?.seqId ?? res?.data?.seq_id
          if (newId != null) form.seqId = newId
        }
        ElMessage.success(isUpdate ? '修改成功' : '新增成功')
        // 通知列表页下次激活时刷新
        sessionStorage.setItem('payload:sequence:needRefresh', '1')
      })
      .finally(() => {
        saving.value = false
      })
  })
}

function applySequenceDetail(detail, { clearSeqId = false } = {}) {
  form.seqId = clearSeqId ? undefined : detail.seqId
  form.seqName = detail.seqName || ''
  form.status = detail.status || '0'
  form.remark = detail.remark || ''
  const parsed = parseCommandsPayload(detail.commands)
  form.defaultInterval = parsed.defaultInterval
  form.commandList = normalizeCommands(parsed.items)
}

async function loadPage() {
  const res = await getTelecontrolConfig()
  rawPages.value = res.data?.page || []
  rawOrders.value = res.data?.order || {}
  buildTree()

  const seqId = route.query.seqId
  const copyFrom = route.query.copyFrom
  if (copyFrom) {
    const draftRes = await copySequence(copyFrom)
    applySequenceDetail(draftRes.data || {}, { clearSeqId: true })
  } else if (seqId) {
    const detailRes = await getSequence(seqId)
    applySequenceDetail(detailRes.data || {})
  } else {
    form.seqId = undefined
    form.seqName = ''
    form.defaultInterval = DEFAULT_INTERVAL
    form.status = '0'
    form.remark = ''
    form.commandList = []
  }
  selectedIndex.value = -1
  clearMiddleEditor()
}

onMounted(loadPage)
watch(
  () => route.fullPath,
  () => loadPage()
)
</script>

<style scoped>
.seq-edit-page {
  margin: 0;
  padding: 0;
  width: 100%;
  /* 变量来自 AppMain，自动适配 tagsView / footerVisible，避免双滚动条 */
  height: calc(100vh - var(--app-main-offset, 84px) - var(--app-footer-offset, 0px));
  overflow: hidden;
  display: grid;
  grid-template-columns: 1fr 2fr 1.2fr;
  box-sizing: border-box;
}
.panel {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
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
/* 左侧树当前选中：滚动时也容易辨认 */
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
}
.panel-scroll :deep(.el-scrollbar__wrap) {
  overflow-x: hidden !important;
}
.detail-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.detail-header {
  flex-shrink: 0;
  margin-bottom: 8px;
  padding-bottom: 8px;
  font-weight: 600;
  border-bottom: 1px solid var(--el-border-color-lighter);
  display: flex;
  align-items: center;
}
.detail-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.order-desc :deep(.el-descriptions__label) {
  width: 90px !important;
  box-sizing: border-box;
}
.order-desc-hex :deep(.el-descriptions__body) {
  margin-top: -1px;
}
.order-desc-hex :deep(.el-descriptions__content) {
  word-break: break-all;
  font-family: monospace;
  font-size: 12px;
}
.comp-field {
  width: 220px;
}
.seq-header {
  font-weight: 600;
  margin-bottom: 8px;
  flex-shrink: 0;
}
.seq-meta {
  flex-shrink: 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 8px;
  padding-bottom: 4px;
}
.seq-interval-field {
  width: 140px;
}
.seq-interval-unit {
  margin-left: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.panel-seq {
  padding-right: 4px;
}
/* 右侧整栏一条滚动条 */
.seq-scroll {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
}
.seq-list-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.seq-list-title {
  font-weight: 600;
  font-size: 14px;
  line-height: 1.2;
}
.seq-clear-btn {
  font-size: 12px !important;
  height: auto !important;
  padding: 0 2px !important;
}
.cmd-list {
  padding-right: 2px;
}
.cmd-list-empty {
  display: flex;
  justify-content: flex-start;
  padding: 12px 0 8px;
}
.cmd-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 8px;
  margin-bottom: 8px;
  cursor: pointer;
  background: transparent;
  transition: border-color 0.15s, background-color 0.15s;
}
.cmd-item:hover {
  border-color: var(--el-color-primary-light-5);
}
.cmd-item.active {
  border-color: var(--el-color-warning);
}
/* 空 HEX：用底色提示；选中/悬停边框优先级更高 */
.cmd-item.is-invalid-hex {
  background: color-mix(in srgb, var(--el-color-danger) 16%, transparent);
}
.cmd-item.is-invalid-hex:hover {
  border-color: var(--el-color-primary-light-5);
}
.cmd-item.is-invalid-hex.active {
  border-color: var(--el-color-warning);
}
.cmd-item-top {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  margin-bottom: 4px;
}
.cmd-idx {
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
  min-width: 22px;
}
.cmd-order-id {
  flex-shrink: 0;
  max-width: 72px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: monospace;
  font-size: 12px;
  color: var(--el-color-primary);
}
.cmd-name-input {
  flex: 1;
  min-width: 0;
}
.cmd-interval-input {
  width: 64px;
  flex-shrink: 0;
}
.cmd-interval-input :deep(.el-input__wrapper) {
  padding-left: 2px;
  padding-right: 2px;
}
.cmd-interval-input :deep(.el-input-number__decrease),
.cmd-interval-input :deep(.el-input-number__increase) {
  width: 18px;
}
.cmd-hex {
  font-family: monospace;
  font-size: 12px;
  word-break: break-all;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}
.cmd-actions {
  display: flex;
  justify-content: flex-end;
  gap: 2px;
}
</style>

<style>
/* teleported tooltip：跟随主题变量，dark 下不再刺眼/发白 */
.theme-aware-tooltip.el-popper,
.seq-cmd-tooltip.el-popper {
  background: var(--el-bg-color-overlay) !important;
  color: var(--el-text-color-primary) !important;
  border: 1px solid var(--el-border-color) !important;
  box-shadow: var(--el-box-shadow-light);
}
.theme-aware-tooltip.el-popper .el-popper__arrow::before,
.seq-cmd-tooltip.el-popper .el-popper__arrow::before {
  background: var(--el-bg-color-overlay) !important;
  border: 1px solid var(--el-border-color) !important;
}
</style>
