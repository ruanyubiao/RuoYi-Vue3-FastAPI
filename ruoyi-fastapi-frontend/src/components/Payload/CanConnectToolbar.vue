<template>
  <div class="can-connect-toolbar">
    <el-button
      v-if="!slotA.connected"
      type="primary"
      size="small"
      @click="openDialog('a')"
    >新建CAN连接-A</el-button>
    <el-button
      v-else
      type="success"
      plain
      size="small"
      class="btn-connected"
      @click="closeSlot('a')"
    >关闭CAN-A · {{ slotA.shortId }}</el-button>

    <el-button
      v-if="!slotB.connected"
      type="primary"
      size="small"
      @click="openDialog('b')"
    >新建CAN连接-B</el-button>
    <el-button
      v-else
      type="success"
      plain
      size="small"
      class="btn-connected"
      @click="closeSlot('b')"
    >关闭CAN-B · {{ slotB.shortId }}</el-button>

    <span class="send-label">当前发送</span>
    <el-radio-group
      v-model="sendDeviceId"
      size="small"
      :disabled="!connectedOptions.length"
      @change="onSendChange"
    >
      <el-radio-button
        v-for="opt in connectedOptions"
        :key="opt.deviceId"
        :label="opt.deviceId"
      >{{ opt.label }}</el-radio-button>
    </el-radio-group>
    <template v-if="isBiu">
      <span class="send-label">目标地址</span>
      <el-select
        v-model="nodeAddrTo"
        size="small"
        class="node-addr-select"
        @change="onNodeAddrChange"
      >
        <el-option
          v-for="n in nodeAddrOptions"
          :key="n.value"
          :label="n.label"
          :value="n.value"
        />
      </el-select>
    </template>
    <span v-if="!connectedOptions.length" class="hint">请先打开 CAN-A 或 CAN-B</span>

    <CanConnectDialog
      v-model="dlgVisible"
      :title="dlgTitle"
      :source="dlgSource"
      :prefs-key="dlgPrefsKey"
      :cable-flag="dlgCableFlag"
      :show-binding-tips="false"
      :lock-baud="true"
      :preset="dlgPreset"
      @success="onConnectSuccess"
    />
  </div>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import CanConnectDialog from '@/components/Payload/CanConnectDialog.vue'
import { closeCanChannel, listDeviceSessions, setCanCable } from '@/api/payload/device'
import { getDeviceConnectEntry, toCanPreset } from '@/utils/deviceConnectDefaults'
import { getActiveDevice, setActiveDevice, clearActiveDevice } from '@/utils/deviceSnapshotCache'

const props = defineProps({
  /** biu | xl：决定打开时的组装器/解释器默认，以及 session.source */
  family: { type: String, default: 'biu' }
})

const emit = defineEmits(['update:deviceId', 'change'])

const FAMILY_DEFAULTS = {
  biu: { assemblerId: 'can_biu', parserId: 'tm_can_biu' },
  xl: { assemblerId: 'can_xl', parserId: 'tm_can_xl' }
}

const nodeAddrOptions = [
  { value: 0x0d, label: '0x0D：激光终端B' },
  { value: 0x0c, label: '0x0C：激光终端A' }
]

const isBiu = computed(() => (props.family || 'biu').toLowerCase() !== 'xl')
const familyKey = computed(() => ((props.family || 'biu').toLowerCase() === 'xl' ? 'xl' : 'biu'))

function sourceOf(ab) {
  return `${familyKey.value}_can_${ab}`
}

const NODE_ADDR_PREFS = 'payload:can:biu:nodeAddrTo'
function readNodeAddr() {
  try {
    const v = Number(localStorage.getItem(NODE_ADDR_PREFS))
    if (v === 0x0c || v === 0x0d) return v
  } catch { /* ignore */ }
  return 0x0d
}
const nodeAddrTo = ref(readNodeAddr())

const slotA = reactive({ connected: false, deviceId: '', shortId: '' })
const slotB = reactive({ connected: false, deviceId: '', shortId: '' })
const sendDeviceId = ref('')
const dlgVisible = ref(false)
const dlgSource = ref('biu_can_a')
const dlgTitle = ref('新建 CAN 连接-A')
const dlgPrefsKey = ref('payload:can:biu:can_a')
const dlgCableFlag = ref(0)
const dlgPreset = ref(null)
let pollTimer = null

const connectedOptions = computed(() => {
  const out = []
  if (slotA.connected && slotA.deviceId) out.push({ deviceId: slotA.deviceId, label: 'CAN-A', slot: 'a' })
  if (slotB.connected && slotB.deviceId) out.push({ deviceId: slotB.deviceId, label: 'CAN-B', slot: 'b' })
  return out
})

function shortDeviceId(id) {
  if (!id) return ''
  const parts = String(id).split(':')
  return parts.length >= 4 ? `ch${parts[3]}` : id
}

async function openDialog(ab) {
  const src = sourceOf(ab)
  dlgSource.value = src
  dlgTitle.value = ab === 'b' ? '新建 CAN 连接-B' : '新建 CAN 连接-A'
  dlgPrefsKey.value = `payload:can:${familyKey.value}:can_${ab}`
  // CAN-A → 线A(0)，CAN-B → 线B(1)；不由 cfg 配置
  dlgCableFlag.value = ab === 'b' ? 1 : 0
  const fam = familyKey.value
  const entry = await getDeviceConnectEntry(src)
  dlgPreset.value = toCanPreset(entry, {
    ...FAMILY_DEFAULTS[fam],
    nodeAddrTo: fam === 'biu' ? Number(nodeAddrTo.value) : undefined
  })
  dlgVisible.value = true
}

async function refreshSlots() {
  try {
    const res = await listDeviceSessions()
    const sessions = res.data || []
    const srcA = sourceOf('a')
    const srcB = sourceOf('b')
    const bySource = {}
    for (const s of sessions) {
      if (s?.srcKind !== 'can' || !s?.srcParam) continue
      const src = String(s.source || '').trim()
      if (src === srcA || src === srcB) bySource[src] = s.srcParam
    }
    slotA.connected = !!bySource[srcA]
    slotA.deviceId = bySource[srcA] || ''
    slotA.shortId = shortDeviceId(slotA.deviceId)
    slotB.connected = !!bySource[srcB]
    slotB.deviceId = bySource[srcB] || ''
    slotB.shortId = shortDeviceId(slotB.deviceId)

    const opts = connectedOptions.value
    if (!opts.length) {
      sendDeviceId.value = ''
      clearActiveDevice('can')
      emit('update:deviceId', '')
      return
    }
    if (opts.length === 1) {
      sendDeviceId.value = opts[0].deviceId
    } else if (!opts.some(o => o.deviceId === sendDeviceId.value)) {
      const saved = getActiveDevice('can')
      sendDeviceId.value = opts.some(o => o.deviceId === saved) ? saved : opts[0].deviceId
    }
    setActiveDevice('can', sendDeviceId.value)
    emit('update:deviceId', sendDeviceId.value)
  } catch {
    /* ignore */
  }
}

function onSendChange(id) {
  if (id) setActiveDevice('can', id)
  else clearActiveDevice('can')
  emit('update:deviceId', id || '')
  emit('change', id || '')
}

async function onNodeAddrChange(val) {
  try {
    localStorage.setItem(NODE_ADDR_PREFS, String(val))
  } catch { /* ignore */ }
  const targets = connectedOptions.value.map(o => o.deviceId).filter(Boolean)
  for (const deviceId of targets) {
    try {
      await setCanCable({ deviceId, nodeAddrTo: Number(val) })
    } catch { /* interceptor */ }
  }
}

async function onConnectSuccess() {
  await refreshSlots()
}

async function closeSlot(ab) {
  const deviceId = ab === 'b' ? slotB.deviceId : slotA.deviceId
  if (!deviceId) return
  try {
    await ElMessageBox.confirm(`确认关闭 ${ab === 'b' ? 'CAN-B' : 'CAN-A'}？`, '提示', {
      type: 'warning'
    })
  } catch {
    return
  }
  const parts = String(deviceId).split(':')
  try {
    await closeCanChannel({
      vendor: Number(parts[1]) || 0,
      devIndex: Number(parts[2]) || 0,
      canIndex: Number(parts[3]) || 0
    })
    ElMessage.success('已关闭')
  } catch {
    /* interceptor */
  }
  await refreshSlots()
}

watch(
  () => props.family,
  () => {
    refreshSlots()
  }
)

function startPoll() {
  stopPoll()
  pollTimer = setInterval(refreshSlots, 3000)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(() => {
  refreshSlots()
  startPoll()
})
onActivated(() => {
  refreshSlots()
  startPoll()
})
onDeactivated(stopPoll)
onUnmounted(stopPoll)

defineExpose({ refreshSlots, sendDeviceId, slotA, slotB })
</script>

<style scoped>
.can-connect-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.btn-connected {
  max-width: 220px;
}
.send-label {
  margin-left: 4px;
  color: var(--el-text-color-regular);
  font-size: 13px;
}
.node-addr-select {
  width: 180px;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
