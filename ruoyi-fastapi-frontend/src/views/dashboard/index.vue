<template>
  <div class="app-container device-service-page">
    <div class="page-head">
      <div class="head-title-row">
        <span class="head-title">设备服务</span>
        <span class="hint">当前已打开的 CAN / 串口 / UDP 监听服务。可在此绑定/修改组装器与解释器并关闭连接。</span>
      </div>
      <div class="head-toolbar">
        <div class="create-actions">
          <el-button type="primary" plain icon="Plus" @click="dlg.can = true">新建 CAN 连接</el-button>
          <el-button type="primary" plain icon="Plus" @click="dlg.udp = true">新建 UDP 连接</el-button>
          <el-button type="primary" plain icon="Plus" @click="dlg.serial = true">新建串口连接</el-button>
        </div>
        <div class="head-actions">
          <el-button type="primary" plain :loading="loading" @click="refresh(true)">刷新</el-button>
          <el-button
            type="danger"
            plain
            :loading="closingAll"
            :disabled="!rows.length"
            @click="handleCloseAll"
          >关闭所有连接</el-button>
          <el-checkbox v-model="autoRefresh">自动刷新</el-checkbox>
        </div>
      </div>
    </div>

    <el-table
      class="device-table"
      :data="rows"
      style="width: 100%"
      empty-text="暂无已打开的设备服务"
    >
        <el-table-column label="类型" prop="kindLabel" width="80" align="center" />
        <el-table-column label="设备 ID" prop="deviceId" min-width="120" show-overflow-tooltip />
        <el-table-column label="连接信息" prop="detail" min-width="180" show-overflow-tooltip />
        <el-table-column label="来源" prop="sourceLabel" width="110" align="center" />
        <el-table-column min-width="120" align="center">
          <template #header>
            <span>组装器</span>
            <el-tooltip :content="ASSEMBLER_TIP" placement="top">
              <el-icon class="label-tip"><question-filled /></el-icon>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <span>{{ assemblerLabel(row.assemblerId) }}</span>
          </template>
        </el-table-column>
        <el-table-column min-width="140" align="center">
          <template #header>
            <span>解释器</span>
            <el-tooltip :content="PARSER_TIP" placement="top">
              <el-icon class="label-tip"><question-filled /></el-icon>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <span v-if="row.parserId">{{ parserLabel(row.parserId) }}</span>
            <span v-else class="muted">未绑定</span>
          </template>
        </el-table-column>
        <el-table-column label="打开时间" prop="openedAt" width="170" align="center" />
        <el-table-column label="操作" width="180" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openBindParser(row)">修改</el-button>
            <el-button
              link
              type="danger"
              :loading="row.closing"
              @click="handleClose(row)"
            >
              关闭连接
            </el-button>
          </template>
        </el-table-column>
      </el-table>

    <CanConnectDialog
      v-model="dlg.can"
      source="home"
      prefs-key="payload:control:canPrefs"
      show-binding-tips
      @success="onConnectSuccess"
    />
    <UdpConnectDialog
      v-model="dlg.udp"
      source="home"
      prefs-key="payload:control:udpPrefs"
      show-binding-tips
      @success="onConnectSuccess"
    />
    <SerialConnectDialog
      v-model="dlg.serial"
      source="home"
      mode="free"
      prefs-key="payload:control:serialPrefs"
      show-binding-tips
      @success="onSerialSuccess"
    />

    <!-- 修改组装器 / 解释器 -->
    <el-dialog v-model="dlg.bind" title="修改绑定" width="480px" destroy-on-close>
      <el-form label-width="100px" class="conn-form">
        <el-form-item label="设备">
          <span>{{ bindForm.kindLabel }} · {{ bindForm.deviceId }}</span>
        </el-form-item>
        <el-form-item label="连接信息">
          <span class="bind-detail">{{ bindForm.detail || '—' }}</span>
        </el-form-item>
        <el-form-item>
          <template #label>
            组装器
            <el-tooltip :content="ASSEMBLER_TIP" placement="top">
              <el-icon class="label-tip"><question-filled /></el-icon>
            </el-tooltip>
          </template>
          <el-select
            v-model="bindForm.assemblerId"
            :clearable="bindForm.kind !== 'can'"
            :placeholder="bindForm.kind === 'can' ? '请选择组装器' : '默认透传'"
            class="conn-ctrl"
            :disabled="bindSaving"
          >
            <el-option v-for="a in bindAssemblerOptions" :key="a.id" :label="a.name" :value="a.id" />
          </el-select>
          <div class="field-tip">
            {{ bindForm.kind === 'can' ? '透传=协议 NONE；CAN-BIU / CAN-XL 为协议组帧' : '清空则使用透传' }}
          </div>
        </el-form-item>
        <el-form-item>
          <template #label>
            解释器
            <el-tooltip :content="PARSER_TIP" placement="top">
              <el-icon class="label-tip"><question-filled /></el-icon>
            </el-tooltip>
          </template>
          <el-select
            v-model="bindForm.parserId"
            clearable
            placeholder="请选择解释器"
            class="conn-ctrl"
            :disabled="bindSaving"
          >
            <el-option v-for="p in parserOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <div class="field-tip">清空并保存表示解绑；不绑定则不解析数据</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="bindSaving" @click="submitBindParser">保存</el-button>
          <el-button :disabled="bindSaving" @click="dlg.bind = false">取消</el-button>
        </el-form-item>
      </el-form>
    </el-dialog>
  </div>
</template>

<script setup name="Index">
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getDeviceSnapshot,
  closeCanChannel,
  closeSerialPort,
  closeNet,
  closeAllDevices,
  listParsers,
  listAssemblers,
  bindDeviceParser
} from '@/api/payload/device'
import CanConnectDialog from '@/components/Payload/CanConnectDialog.vue'
import UdpConnectDialog from '@/components/Payload/UdpConnectDialog.vue'
import SerialConnectDialog from '@/components/Payload/SerialConnectDialog.vue'
import {
  takeDeviceSnapshot,
  saveDeviceSnapshot,
  invalidateDeviceSnapshot,
  setActiveDevice,
  getActiveDevice,
  clearActiveDevice
} from '@/utils/deviceSnapshotCache'
import { ASSEMBLER_TIP, PARSER_TIP } from '@/utils/pipelineTips'

const loading = ref(false)
const closingAll = ref(false)
const autoRefresh = ref(true)
const rows = ref([])
let timer = null
let refreshing = false

const KIND_LABEL = { can: 'CAN', serial: '串口', udp: 'UDP' }
const SOURCE_LABEL = {
  home: '首页',
  camera_ctrl: '相机·控制',
  camera_image: '相机·图像',
  rkdj: '热控电机',
  zk: 'CPA-ZK',
  biu_can_a: 'BIU CAN-A',
  biu_can_b: 'BIU CAN-B',
  xl_can_a: 'XL CAN-A',
  xl_can_b: 'XL CAN-B'
}

function sourceLabel(source) {
  const id = String(source || '').trim()
  if (!id) return '—'
  return SOURCE_LABEL[id] || id
}

const dlg = reactive({ can: false, udp: false, serial: false, bind: false })
const parserOptions = ref([])
const assemblerOptions = ref([])
const bindAssemblerOptions = ref([])
const bindSaving = ref(false)
const bindForm = reactive({
  deviceId: '',
  kind: '',
  kindLabel: '',
  detail: '',
  parserId: '',
  assemblerId: 'passthrough'
})

async function loadParsers() {
  try {
    const res = await listParsers()
    const list = res.data?.parsers || res.data || []
    parserOptions.value = Array.isArray(list)
      ? list.map(p =>
          typeof p === 'string'
            ? { id: p, name: p }
            : { id: p.id || p.parserId, name: p.name || p.label || p.id || p.parserId }
        )
      : []
  } catch {
    parserOptions.value = [
      { id: 'tm_can_biu', name: 'BIU-CAN遥测复合帧' },
      { id: 'tm_can_xl', name: 'XL-CAN遥测复合帧' }
    ]
  }
}

function mapAssemblerList(list) {
  return Array.isArray(list)
    ? list.map(a =>
        typeof a === 'string'
          ? { id: a, name: a }
          : { id: a.id || a.assemblerId, name: a.name || a.label || a.id || a.assemblerId }
      )
    : []
}

async function loadAssemblers(srcKind) {
  try {
    const res = await listAssemblers(srcKind)
    return mapAssemblerList(res.data?.assemblers || res.data || [])
  } catch {
    if (srcKind === 'can') {
      return [
        { id: 'passthrough', name: '透传' },
        { id: 'can_biu', name: 'CAN-BIU' },
        { id: 'can_xl', name: 'CAN-XL' }
      ]
    }
    return [
      { id: 'passthrough', name: '透传（默认）' },
      { id: 'eng_tm_subpkt', name: '工程遥测子包组装' }
    ]
  }
}
async function onConnectSuccess() {
  await refresh(false)
}

async function onSerialSuccess({ response }) {
  const deviceId = response?.data?.deviceId
  if (deviceId) setActiveDevice('serial', deviceId)
  await refresh(false)
}

function sessionMap(sessions) {
  const map = new Map()
  for (const s of sessions || []) {
    if (s?.srcParam) map.set(s.srcParam, s)
  }
  return map
}

function parserLabel(parserId) {
  if (!parserId) return ''
  const hit = parserOptions.value.find(p => p.id === parserId)
  return hit?.name || parserId
}

function assemblerLabel(assemblerId) {
  const id = assemblerId || 'passthrough'
  const hit = assemblerOptions.value.find(a => a.id === id)
  return hit?.name || id
}

function buildRows(canList, serialList, netList, sessions) {
  const sm = sessionMap(sessions)
  const out = []

  for (const d of canList || []) {
    if (d.demo || !d.alive) continue
    const sid = d.deviceId
    const sess = sm.get(sid) || {}
    out.push({
      kind: 'can',
      kindLabel: KIND_LABEL.can,
      deviceId: sid,
      detail: [
        `vendor=${d.vendor}`,
        `卡${d.devIndex}`,
        `通道${d.canIndex}`,
        d.baudRate != null ? `${d.baudRate}kbps` : null
      ].filter(Boolean).join(' · '),
      source: sess.source || '',
      sourceLabel: sourceLabel(sess.source),
      parserId: sess.parserId || '',
      assemblerId: sess.assemblerId || 'passthrough',
      openedAt: sess.openedAt || '—',
      closing: false,
      closeArgs: { vendor: d.vendor, devIndex: d.devIndex, canIndex: d.canIndex }
    })
  }

  for (const d of serialList || []) {
    if (!d.alive) continue
    const sid = d.deviceId
    const sess = sm.get(sid) || {}
    const parity = String(d.parity || 'N').toUpperCase().slice(0, 1) || 'N'
    const flow = String(d.flowControl || 'NONE').toUpperCase()
    const bits = [
      d.port || sid,
      d.baudrate != null ? `${d.baudrate}bps` : null,
      d.dataBits != null ? `${d.dataBits}${parity}${d.stopBits ?? 1}` : null,
      flow && flow !== 'NONE' ? `${d.flowControl}` : null
    ].filter(Boolean)
    out.push({
      kind: 'serial',
      kindLabel: KIND_LABEL.serial,
      deviceId: sid,
      detail: bits.join(' · '),
      source: sess.source || '',
      sourceLabel: sourceLabel(sess.source),
      parserId: sess.parserId || '',
      assemblerId: sess.assemblerId || 'passthrough',
      openedAt: sess.openedAt || '—',
      closing: false,
      closeArgs: { port: d.port }
    })
  }

  for (const d of netList || []) {
    if (!d.alive) continue
    const sid = d.deviceId
    const sess = sm.get(sid) || {}
    const local = `${d.localHost || '?'}:${d.localPort ?? '?'}`
    const remote = d.remoteHost && d.remotePort ? ` → ${d.remoteHost}:${d.remotePort}` : ''
    out.push({
      kind: 'udp',
      kindLabel: KIND_LABEL.udp,
      deviceId: sid,
      detail: `${(d.proto || 'udp').toUpperCase()} ${local}${remote}`,
      source: sess.source || '',
      sourceLabel: sourceLabel(sess.source),
      parserId: sess.parserId || '',
      assemblerId: sess.assemblerId || 'passthrough',
      openedAt: sess.openedAt || '—',
      closing: false,
      closeArgs: {
        proto: d.proto || 'udp',
        localHost: d.localHost,
        localPort: d.localPort
      }
    })
  }

  out.sort((a, b) => String(a.deviceId).localeCompare(String(b.deviceId)))
  return out
}

function applySnapshotData(data) {
  const plist = data?.parsers || []
  parserOptions.value = Array.isArray(plist)
    ? plist.map(p =>
        typeof p === 'string'
          ? { id: p, name: p }
          : { id: p.id || p.parserId, name: p.name || p.label || p.id || p.parserId }
      )
    : []
  const alist = data?.assemblers || []
  assemblerOptions.value = Array.isArray(alist)
    ? alist.map(a =>
        typeof a === 'string'
          ? { id: a, name: a }
          : { id: a.id || a.assemblerId, name: a.name || a.label || a.id || a.assemblerId }
      )
    : []
  if (!assemblerOptions.value.length) {
    assemblerOptions.value = [
      { id: 'passthrough', name: '透传（默认）' },
      { id: 'eng_tm_subpkt', name: '工程遥测子包(LVDS)' }
    ]
  }
  rows.value = buildRows(
    data?.can || [],
    data?.serialOpened || [],
    data?.netOpened || [],
    data?.sessions || []
  )
}

async function refresh(manual = false) {
  if (refreshing) return
  refreshing = true
  if (manual) loading.value = true
  try {
    const res = await getDeviceSnapshot([
      'can',
      'serialList',
      'serialOpened',
      'netOpened',
      'sessions',
      'parsers',
      'assemblers'
    ])
    const data = res.data || {}
    saveDeviceSnapshot(data)
    applySnapshotData(data)
  } finally {
    refreshing = false
    if (manual) loading.value = false
  }
}

function clearLocalActive(row) {
  if (row.kind === 'can' && getActiveDevice('can') === row.deviceId) {
    clearActiveDevice('can')
  }
  if (row.kind === 'serial' && getActiveDevice('serial') === row.deviceId) {
    clearActiveDevice('serial')
  }
  if (row.kind === 'udp' && getActiveDevice('udp') === row.deviceId) {
    clearActiveDevice('udp')
  }
}

async function handleClose(row) {
  try {
    await ElMessageBox.confirm(`确认关闭 ${row.kindLabel}「${row.deviceId}」？`, '关闭连接', {
      type: 'warning',
      confirmButtonText: '关闭',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  row.closing = true
  try {
    if (row.kind === 'can') await closeCanChannel(row.closeArgs)
    else if (row.kind === 'serial') await closeSerialPort(row.closeArgs.port)
    else if (row.kind === 'udp') await closeNet(row.closeArgs)
    clearLocalActive(row)
    invalidateDeviceSnapshot()
    ElMessage.success('连接已关闭')
    await refresh(false)
  } finally {
    row.closing = false
  }
}

async function handleCloseAll() {
  const list = [...rows.value]
  if (!list.length) {
    ElMessage.info('当前没有已打开的连接')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认关闭全部 ${list.length} 个连接（CAN / 串口 / UDP）？`,
      '关闭所有连接',
      {
        type: 'warning',
        confirmButtonText: '全部关闭',
        cancelButtonText: '取消'
      }
    )
  } catch {
    return
  }
  closingAll.value = true
  try {
    const res = await closeAllDevices()
    const data = res.data || {}
    const ok = Number(data.ok || 0)
    const fail = Number(data.fail || 0)
    clearActiveDevice('can')
    clearActiveDevice('serial')
    clearActiveDevice('udp')
    invalidateDeviceSnapshot()
    if (fail) ElMessage.warning(`已关闭 ${ok} 个，失败 ${fail} 个`)
    else ElMessage.success(`已关闭全部 ${ok} 个连接`)
    await refresh(false)
  } catch {
    /* interceptor */
  } finally {
    closingAll.value = false
  }
}

async function openBindParser(row) {
  if (!row) return
  await loadParsers()
  const [allAsm, kindAsm] = await Promise.all([
    loadAssemblers(),
    loadAssemblers(row.kind === 'can' ? 'can' : row.kind || 'serial')
  ])
  assemblerOptions.value = allAsm
  bindAssemblerOptions.value = kindAsm.length ? kindAsm : allAsm
  bindForm.deviceId = row.deviceId
  bindForm.kind = row.kind
  bindForm.kindLabel = row.kindLabel
  bindForm.detail = row.detail || ''
  bindForm.parserId = row.parserId || ''
  if (row.kind === 'can') {
    const aid = row.assemblerId || 'can_biu'
    bindForm.assemblerId = bindAssemblerOptions.value.some(a => a.id === aid)
      ? aid
      : bindAssemblerOptions.value[0]?.id || 'can_biu'
  } else {
    bindForm.assemblerId = row.assemblerId || 'passthrough'
  }
  dlg.bind = true
}

async function submitBindParser() {
  if (!bindForm.deviceId || bindSaving.value) return
  bindSaving.value = true
  try {
    const defaultAsm = bindForm.kind === 'can' ? 'can_biu' : 'passthrough'
    await bindDeviceParser({
      srcParam: bindForm.deviceId,
      srcKind: bindForm.kind,
      parserId: bindForm.parserId || '',
      assemblerId: bindForm.assemblerId || defaultAsm,
      updateAssembler: true
    })
    ElMessage.success('绑定已更新')
    dlg.bind = false
    await refresh(false)
  } finally {
    bindSaving.value = false
  }
}

watch(autoRefresh, v => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  if (v) timer = setInterval(() => refresh(false), 3000)
})

onMounted(async () => {
  const cached = takeDeviceSnapshot()
  if (cached) applySnapshotData(cached)
  await refresh(true)
  if (autoRefresh.value) timer = setInterval(() => refresh(false), 3000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.device-service-page {
  background: transparent;
  border: none;
  box-shadow: none;
}
.page-head {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 12px;
  width: 100%;
  margin-bottom: 16px;
}
.head-title-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  min-width: 0;
}
.head-title {
  flex-shrink: 0;
  font-weight: 600;
  font-size: 16px;
  line-height: 1.2;
  white-space: nowrap;
}
.hint {
  margin: 0;
  min-width: 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.2;
  padding-bottom: 1px;
}
.head-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  width: 100%;
}
.create-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.device-table {
  width: 100%;
}
.muted {
  color: var(--el-text-color-placeholder);
}
.field-tip {
  width: 100%;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
}
.bind-detail {
  color: var(--el-text-color-regular);
  word-break: break-all;
}
.conn-form :deep(.el-form-item__content) {
  flex-wrap: wrap;
}
.conn-ctrl {
  width: 240px !important;
}
.conn-ctrl :deep(.el-select__selected-item),
.conn-ctrl :deep(.el-select__placeholder) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.label-tip {
  margin-left: 4px;
  vertical-align: middle;
  cursor: help;
  color: var(--el-text-color-secondary);
}
</style>

<!-- 覆盖全局 ruoyi/dark 表格 !important，保证表头/斑马纹/悬停可见 -->
<style>
.device-service-page .device-table.el-table {
  --el-table-header-bg-color: var(--el-fill-color, #f8f8f9);
  --el-table-header-text-color: var(--el-text-color-regular, #515a6e);
  --el-table-row-hover-bg-color: var(--el-fill-color-light, #f5f7fa);
}

.device-service-page .device-table.el-table .el-table__header-wrapper th.el-table__cell,
.device-service-page .device-table.el-table .el-table__fixed-header-wrapper th.el-table__cell,
.device-service-page .device-table.el-table thead th.el-table__cell {
  background-color: var(--el-fill-color, #f8f8f9) !important;
  color: var(--el-text-color-regular, #515a6e) !important;
  font-size: 13px !important;
  font-weight: 600;
  height: 40px !important;
}

.device-service-page .device-table.el-table .el-table__body tr:hover > td.el-table__cell {
  background-color: var(--el-fill-color-light, #f5f7fa) !important;
}

html.dark .device-service-page .device-table.el-table .el-table__header-wrapper th.el-table__cell,
html.dark .device-service-page .device-table.el-table .el-table__fixed-header-wrapper th.el-table__cell,
html.dark .device-service-page .device-table.el-table thead th.el-table__cell {
  background-color: var(--el-fill-color-dark, #262727) !important;
}

html.dark .device-service-page .device-table.el-table .el-table__body tr:hover > td.el-table__cell {
  background-color: var(--el-fill-color, #303030) !important;
}
</style>
