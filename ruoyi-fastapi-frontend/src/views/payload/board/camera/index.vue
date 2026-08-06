<template>
  <div class="app-container camera-page">
    <div class="main-grid">
      <div class="col-left">
        <el-form :inline="true" class="left-toolbar" size="small">
          <el-form-item>
            <el-button
              v-if="!ctrlConnected"
              type="primary"
              size="small"
              @click="openSerialDialog('ctrl')"
            >新建控制串口连接</el-button>
            <el-button
              v-else
              type="success"
              plain
              size="small"
              class="btn-connected"
              @click="closeCtrl"
            >关闭控制串口 · {{ ctrlPort }}</el-button>
          </el-form-item>
          <el-form-item>
            <el-button
              v-if="!imageConnected"
              type="primary"
              size="small"
              @click="openSerialDialog('image')"
            >新建图像串口连接</el-button>
            <el-button
              v-else
              type="success"
              plain
              size="small"
              class="btn-connected"
              @click="closeImage"
            >关闭图像串口 · {{ imagePort }}</el-button>
          </el-form-item>
        </el-form>

        <div class="panel panel-tc">
          <div class="panel-head">
            <span class="panel-title">遥控</span>
            <el-button class="export-tc-btn" link type="primary" @click="exportPreviewOrders">导出</el-button>
            <el-input
              v-model="filterText"
              clearable
              size="small"
              placeholder="搜索指令代号/名称（空格分词）"
              class="filter-input"
            />
          </div>
          <el-scrollbar class="panel-body">
            <div v-if="filteredOrders.length" class="order-list">
              <div v-for="ord in filteredOrders" :key="ord.id" class="order-card">
                <div class="order-title">
                  {{ ord.id }} - {{ ord.name }} - {{ orderByteLen(ord) }} 字节
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
                    <el-form-item
                      v-if="compType(comp) !== 'fixed'"
                      :label="comp.title || `参数${idx + 1}`"
                    >
                      <el-input-number
                        v-if="compType(comp) === 'number'"
                        v-model="compValues[ord.id][idx]"
                        class="comp-field"
                        :min="numBound(comp.minVal)"
                        :max="numBound(comp.maxVal)"
                        @change="() => previewOrder(ord, { showLoading: false })"
                      />
                      <el-select
                        v-else-if="compType(comp) === 'select'"
                        v-model="compValues[ord.id][idx]"
                        class="comp-field"
                        @change="() => previewOrder(ord, { showLoading: false })"
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
                        @change="() => previewOrder(ord, { showLoading: false })"
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
                      :disabled="!ctrlConnected"
                      @click="sendOrder(ord)"
                    >发送指令</el-button>
                  </el-form-item>
                </el-form>
              </div>
            </div>
            <el-empty v-else description="无匹配指令" :image-size="64" />
          </el-scrollbar>
        </div>

        <div class="panel panel-xfer">
          <PayloadTransferInfo
            v-model="xferDeviceId"
            title="传输信息"
            :devices="xferDevices"
          />
        </div>
      </div>

      <div class="col-right">
        <el-form :inline="true" class="image-toolbar" size="small">
          <el-form-item label="分辨率">
            <el-select
              v-model="resolution"
              size="small"
              class="image-select-res"
              clearable
              placeholder="请选择"
              :disabled="!imageConnected || imageRefreshing"
              @change="onResolutionUserChange"
            >
              <el-option v-for="r in resolutions" :key="r" :label="r" :value="r" />
            </el-select>
          </el-form-item>
          <el-form-item label="图像序号">
            <el-select
              v-model="imageNo"
              size="small"
              class="image-select-no"
              :disabled="!imageConnected || imageRefreshing"
            >
              <el-option v-for="n in imageNoOptions" :key="n" :label="String(n)" :value="n" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button
              v-if="!imageRefreshing"
              type="primary"
              size="small"
              :disabled="!imageConnected"
              @click="startRefresh"
            >图片刷新</el-button>
            <el-button
              v-else
              type="danger"
              size="small"
              class="btn-stop-refresh"
              @click="stopRefresh"
            >停止刷新</el-button>
          </el-form-item>
          <el-form-item class="image-toolbar-right">
            <el-button type="success" size="small" :disabled="!imageSrc" @click="saveCurrentImage">
              图片保存
            </el-button>
          </el-form-item>
        </el-form>
        <div class="panel panel-image">
          <CameraImageView
            :image-src="imageSrc"
            :width="imgMeta.width"
            :height="imgMeta.height"
            :image-no="imgMeta.imageNo"
            :frame-ts="frameTs"
            :refresh-time="imageRefreshTime"
          />
        </div>
        <div class="panel panel-tm">
          <PayloadTelemetryTable
            v-model:type="tmTableKey"
            level="t3"
            :types="tmTypes"
            @data-change="onTmDataChange"
          />
        </div>
      </div>
    </div>

    <SerialConnectDialog
      v-model="serialDlg.visible"
      :title="serialDlg.kind === 'ctrl' ? '新建控制串口连接' : '新建图像串口连接'"
      :source="serialDlg.kind === 'ctrl' ? SOURCE_CAMERA_CTRL : SOURCE_CAMERA_IMAGE"
      mode="preset"
      :preset="serialDlg.kind === 'image' ? IMAGE_PRESET : CTRL_PRESET"
      :baud-choices="serialDlg.kind === 'image' ? imageBaudChoices : ctrlBaudChoices"
      :baud-editable="serialDlg.kind === 'image'"
      :match-baud-mode="serialDlg.kind === 'image' ? 'allowlist' : 'exact'"
      :preferred-port="serialDlg.kind === 'ctrl' ? ctrlPort : imagePort"
      :fallback-parsers="[{ id: 'camera_sc_link41ep', name: '相机SC-LINK41EP(D8)' }]"
      :fallback-assemblers="[
        { id: 'passthrough', name: '透传（默认）' },
        { id: 'camera_image_d6', name: '相机图像(D6)' }
      ]"
      @success="onSerialSuccess"
    />
  </div>
</template>

<script setup name="Camera">
import { ElMessage, ElMessageBox } from 'element-plus'
import { saveAs } from 'file-saver'
import {
  closeSerialPort,
  getDeviceSnapshot
} from '@/api/payload/device'
import {
  startCamera,
  stopCamera,
  getCameraImage,
  getCameraTelecontrolConfig,
  assembleCameraTelecontrol,
  sendCameraTelecontrol
} from '@/api/payload/camera'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import CameraImageView from '@/components/Payload/CameraImageView.vue'
import PayloadTransferInfo from '@/components/Payload/PayloadTransferInfo.vue'
import PayloadTelemetryTable from '@/components/Payload/PayloadTelemetryTable.vue'
import SerialConnectDialog from '@/components/Payload/SerialConnectDialog.vue'
import { prefetchDeviceSnapshot } from '@/utils/deviceSnapshotCache'

const SOURCE_CAMERA_CTRL = 'camera_ctrl'
const SOURCE_CAMERA_IMAGE = 'camera_image'

const PREFS_KEY = 'payload:board:camera:prefs'
const resolutions = ['400×400', '256×256', '128×128', '64×64']
const imageNoOptions = Array.from({ length: 64 }, (_, i) => i + 1)
/** CAM027 开窗模式 value/hex → 分辨率 */
const CAM027_RES_MAP = {
  '0': '400×400',
  '00': '400×400',
  '0x00': '400×400',
  '1': '256×256',
  '01': '256×256',
  '0x01': '256×256',
  '2': '128×128',
  '02': '128×128',
  '0x02': '128×128',
  '3': '64×64',
  '03': '64×64',
  '0x03': '64×64'
}

const ctrlBaudChoices = [{ value: 2000000, label: '2000000' }]
/** 图像串口协议允许的两种波特率 */
const imageBaudChoices = [
  { value: 2000000, label: '2000000(默认)' },
  { value: 11000000, label: '11000000' }
]

const CTRL_PRESET = {
  baudChoice: 2000000,
  baudrate: 2000000,
  dataBits: 8,
  stopBits: 1,
  parity: 'O',
  flowControl: 'NONE',
  assemblerId: 'passthrough',
  parserId: 'camera_sc_link41ep'
}
const IMAGE_PRESET = {
  baudChoice: 2000000,
  baudrate: 2000000,
  dataBits: 8,
  stopBits: 1,
  parity: 'O',
  flowControl: 'NONE',
  assemblerId: 'camera_image_d6',
  parserId: ''
}

const ctrlPort = ref('')
const imagePort = ref('')
const ctrlConnected = ref(false)
const imageConnected = ref(false)
const resolution = ref('')
/** 用户是否手动改过分辨率（含清空） */
const resolutionUserTouched = ref(false)
/** 上次从 CAM027 解析到的分辨率，用于判断遥测是否变化 */
const lastCam027Res = ref('')
const imageNo = ref(1)
const imageRefreshing = ref(false)
const statusText = ref('就绪')
const filterText = ref('')
const rawOrders = ref({})
const orderIds = ref([])
const compValues = reactive({})
const assembledMap = reactive({})
const sendingId = ref('')
const previewingId = ref('')
const frameSeq = ref(0)

const imageSrc = ref('')
const imgMeta = reactive({ width: 0, height: 0, imageNo: null })
const frameTs = ref(0)
const imageRefreshTime = ref('-')

const tmTableKey = ref('D8')
const tmTypes = [
  { id: 'D8', name: '慢遥测(全窗)' },
  { id: 'D9', name: '快遥测(开窗)' }
]

const xferDeviceId = ref('')

const serialDlg = reactive({ visible: false, kind: 'ctrl' })

let imageTimer = null
let linkTimer = null
/** 用户主动关闭时跳过断连提示 */
let closingCtrl = false
let closingImage = false

const ctrlDeviceId = computed(() => (ctrlPort.value ? `serial:${ctrlPort.value}` : ''))
/** 传输信息按功能来源聚合（与具体 COM 解耦） */
const xferCtrlId = `source:${SOURCE_CAMERA_CTRL}`
const xferImageId = `source:${SOURCE_CAMERA_IMAGE}`

const xferDevices = computed(() => {
  const list = []
  if (ctrlConnected.value) {
    list.push({ id: xferCtrlId, label: '控制串口' })
  }
  if (imageConnected.value) {
    list.push({ id: xferImageId, label: '图像串口' })
  }
  return list
})

function getFilterKeywords(text) {
  return String(text || '').trim().split(/\s+/).filter(Boolean)
}

function matchesAllKeywords(text, keywords) {
  if (!keywords.length) return true
  const hay = String(text || '').toLowerCase()
  return keywords.every(kw => hay.includes(String(kw).toLowerCase()))
}

const filteredOrders = computed(() => {
  const keywords = getFilterKeywords(filterText.value)
  return orderIds.value
    .map(id => rawOrders.value[id])
    .filter(Boolean)
    .filter(o => matchesAllKeywords(`${o.id} ${o.name}`, keywords))
})

function compType(comp) {
  return String(comp?.componentType || 'fixed').toLowerCase()
}

function numBound(v) {
  if (v === '' || v == null) return undefined
  const n = Number(v)
  return Number.isFinite(n) ? n : undefined
}

function initCompValues(orders) {
  for (const [id, ord] of Object.entries(orders || {})) {
    if (!compValues[id]) compValues[id] = {}
    ;(ord.component || []).forEach((comp, idx) => {
      if (compValues[id][idx] === undefined) {
        const def = comp.defaultVal
        if (compType(comp) === 'number') {
          const n = Number(def)
          compValues[id][idx] = Number.isFinite(n) ? n : 0
        } else {
          compValues[id][idx] = def ?? ''
        }
      }
    })
  }
}

function valuesForOrder(ord) {
  return (ord.component || []).map((comp, idx) => {
    if (compType(comp) === 'fixed') return comp.defaultVal
    const v = compValues[ord.id]?.[idx]
    return v === undefined || v === null || v === '' ? comp.defaultVal : v
  })
}

/** 帧总长：优先组帧结果；否则按协议头 9 字节 + dataLen */
function orderByteLen(ord) {
  const n = assembledMap[ord.id]?.length
  if (n != null && n > 0) return n
  const dataLen = Number(ord?.dataLen)
  if (Number.isFinite(dataLen) && dataLen >= 0) return 9 + dataLen
  return '-'
}

function onResolutionUserChange() {
  resolutionUserTouched.value = true
}

function onTmDataChange(payload) {
  syncResolutionFromTm(payload?.rows || [])
}

/** 从遥测行解析 CAM027 → 分辨率选项值，匹配失败返回 '' */
function parseCam027Resolution(rows) {
  const row = (rows || []).find(r => String(r?.id || '').toUpperCase() === 'CAM027')
  if (!row) return ''
  const show = String(row.show ?? '').trim()
  if (show) {
    for (const r of resolutions) {
      if (show === r || show.startsWith(r)) return r
    }
  }
  const candidates = [row.value, row.hex, row.raw]
    .map(v => String(v ?? '').trim().toLowerCase().replace(/\s+/g, ''))
    .filter(Boolean)
  for (const c of candidates) {
    const key = c.startsWith('0x') ? c : c.replace(/^0+/, '') || '0'
    const mapped =
      CAM027_RES_MAP[c] ||
      CAM027_RES_MAP[`0x${c.replace(/^0x/, '')}`] ||
      CAM027_RES_MAP[key.padStart(2, '0')] ||
      CAM027_RES_MAP[`0x${key.padStart(2, '0')}`]
    if (mapped) return mapped
  }
  return ''
}

/**
 * 按 CAM027 同步分辨率下拉（禁用状态也可改）：
 * - 用户尚未选择 → 设置
 * - 遥测开窗模式相对上次有变化 → 设置
 * - 未变化 → 不覆盖（可能是用户手选）
 */
function syncResolutionFromTm(rows) {
  const next = parseCam027Resolution(rows)
  if (!next) return
  const prev = lastCam027Res.value
  const changed = Boolean(prev) && prev !== next
  lastCam027Res.value = next
  if (!resolution.value || !resolutionUserTouched.value || changed) {
    resolution.value = next
  }
}

function loadPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    const p = raw ? JSON.parse(raw) : {}
    if (p.ctrlPort) ctrlPort.value = p.ctrlPort
    if (p.imagePort) imagePort.value = p.imagePort
    // 分辨率默认不选择，不从本地偏好恢复
    if (p.imageNo) imageNo.value = p.imageNo
    if (p.filterText) filterText.value = p.filterText
  } catch {
    /* ignore */
  }
}

function savePrefs() {
  try {
    localStorage.setItem(
      PREFS_KEY,
      JSON.stringify({
        ctrlPort: ctrlPort.value,
        imagePort: imagePort.value,
        resolution: resolution.value,
        imageNo: imageNo.value,
        filterText: filterText.value
      })
    )
  } catch {
    /* ignore */
  }
}

watch([ctrlPort, imagePort, resolution, imageNo, filterText], savePrefs)

function openSerialDialog(kind) {
  serialDlg.kind = kind
  serialDlg.visible = true
}

function onSerialSuccess({ port }) {
  applyConnectedState(port)
  savePrefs()
}

function clearOtherRoleOnPort(port, keepKind) {
  const portUp = String(port || '').trim().toUpperCase()
  if (!portUp) return
  if (
    keepKind !== 'ctrl' &&
    ctrlConnected.value &&
    String(ctrlPort.value).trim().toUpperCase() === portUp
  ) {
    ctrlConnected.value = false
  }
  if (
    keepKind !== 'image' &&
    imageConnected.value &&
    String(imagePort.value).trim().toUpperCase() === portUp
  ) {
    imageConnected.value = false
    stopRefresh()
  }
}

function assignXferSource(id) {
  // 已有选中且仍是当前已打开来源之一 → 不因新开连接而切换
  const openIds = []
  if (ctrlConnected.value) openIds.push(xferCtrlId)
  if (imageConnected.value) openIds.push(xferImageId)
  if (xferDeviceId.value && openIds.includes(xferDeviceId.value)) return
  xferDeviceId.value = id
}

function applyConnectedState(port) {
  if (serialDlg.kind === 'ctrl') {
    clearOtherRoleOnPort(port, 'ctrl')
    ctrlPort.value = port
    ctrlConnected.value = true
    assignXferSource(xferCtrlId)
    statusText.value = `控制串口已打开 ${port}`
  } else {
    clearOtherRoleOnPort(port, 'image')
    imagePort.value = port
    imageConnected.value = true
    assignXferSource(xferImageId)
    statusText.value = `图像串口已打开 ${port}`
  }
}

async function closeCtrl() {
  if (!ctrlPort.value) return
  try {
    await ElMessageBox.confirm(`确认关闭控制串口「${ctrlPort.value}」？`, '关闭连接', {
      type: 'warning',
      confirmButtonText: '关闭',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  closingCtrl = true
  let offline = false
  try {
    await closeSerialPort(ctrlPort.value)
  } catch (e) {
    offline = isBackendOfflineError(e)
    if (!offline) {
      ElMessage.error(e?.message || '关闭控制串口失败')
      closingCtrl = false
      return
    }
  }
  ctrlConnected.value = false
  if (xferDeviceId.value === xferCtrlId) {
    xferDeviceId.value = imageConnected.value ? xferImageId : ''
  }
  statusText.value = offline ? '后端已离线，已清除本页控制串口状态' : '控制串口已关闭'
  if (offline) {
    ElMessage.warning(statusText.value)
  }
  closingCtrl = false
}

async function closeImage() {
  if (!imagePort.value) return
  try {
    await ElMessageBox.confirm(`确认关闭图像串口「${imagePort.value}」？`, '关闭连接', {
      type: 'warning',
      confirmButtonText: '关闭',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  closingImage = true
  stopRefresh()
  let offline = false
  try {
    await closeSerialPort(imagePort.value)
  } catch (e) {
    offline = isBackendOfflineError(e)
    if (!offline) {
      ElMessage.error(e?.message || '关闭图像串口失败')
      closingImage = false
      return
    }
  }
  imageConnected.value = false
  if (xferDeviceId.value === xferImageId) {
    xferDeviceId.value = ctrlConnected.value ? xferCtrlId : ''
  }
  statusText.value = offline ? '后端已离线，已清除本页图像串口状态' : '图像串口已关闭'
  if (offline) {
    ElMessage.warning(statusText.value)
  }
  closingImage = false
}

function isBackendOfflineError(e) {
  const msg = String(e?.message || e || '')
  return /连接异常|Network Error|ECONNREFUSED|Failed to fetch|接口请求超时|status code 5\d\d|服务正在关闭/i.test(msg)
}

async function checkLinkStatus() {
  const watchCtrl = ctrlConnected.value && ctrlPort.value && !closingCtrl
  const watchImage = imageConnected.value && imagePort.value && !closingImage
  if (!watchCtrl && !watchImage) return
  try {
    const res = await getDeviceSnapshot(['serialOpened'])
    const opened = res.data?.serialOpened || []
    const alivePorts = new Set(
      opened.filter(p => p && p.alive !== false).map(p => String(p.port || '').toUpperCase())
    )
    const msgs = []
    if (watchCtrl && !alivePorts.has(String(ctrlPort.value).toUpperCase())) {
      ctrlConnected.value = false
      if (xferDeviceId.value === xferCtrlId) {
        xferDeviceId.value = imageConnected.value ? xferImageId : ''
      }
      msgs.push(`控制串口已断开（${ctrlPort.value}）`)
    }
    if (watchImage && !alivePorts.has(String(imagePort.value).toUpperCase())) {
      stopRefresh()
      imageConnected.value = false
      if (xferDeviceId.value === xferImageId) {
        xferDeviceId.value = ctrlConnected.value ? xferCtrlId : ''
      }
      msgs.push(`图像串口已断开（${imagePort.value}）`)
    }
    if (msgs.length) {
      statusText.value = msgs.join('；')
      ElMessage.warning(msgs.join('；'))
    }
  } catch (e) {
    if ((watchCtrl || watchImage) && isBackendOfflineError(e)) {
      statusText.value = '后端已离线（本页仍显示原连接，可点关闭清除本地状态）'
    }
  }
}

async function previewOrder(ord, { showLoading = true } = {}) {
  if (showLoading) previewingId.value = ord.id
  try {
    const res = await assembleCameraTelecontrol({
      orderId: ord.id,
      values: valuesForOrder(ord),
      seq: frameSeq.value
    })
    assembledMap[ord.id] = {
      hex: res.data?.hex || '',
      length: res.data?.length ?? 0
    }
  } catch (e) {
    ElMessage.error(e?.message || '组帧失败')
  } finally {
    if (showLoading && previewingId.value === ord.id) previewingId.value = ''
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
  saveAs(blob, 'camera-tc-preview.json')
  ElMessage.success(`已导出 ${list.length} 条指令`)
}

async function sendOrder(ord) {
  if (!ctrlConnected.value || !ctrlDeviceId.value) {
    ElMessage.warning('请先打开控制串口')
    return
  }
  sendingId.value = ord.id
  try {
    const seq = frameSeq.value
    const res = await sendCameraTelecontrol({
      deviceId: ctrlDeviceId.value,
      orderId: ord.id,
      name: ord.name,
      values: valuesForOrder(ord),
      seq
    })
    frameSeq.value = (seq + 1) & 0xffff
    if (res.data?.hex) {
      assembledMap[ord.id] = { hex: res.data.hex, length: res.data.hex.split(/\s+/).filter(Boolean).length }
    }
    notifyPayloadSendResult(res, { deviceId: ctrlDeviceId.value })
  } catch (e) {
    ElMessage.error(e?.message || '发送失败')
  } finally {
    sendingId.value = ''
  }
}

async function startRefresh() {
  if (!imageConnected.value || !imagePort.value) {
    ElMessage.warning('请先打开图像串口')
    return
  }
  if (!resolution.value) {
    ElMessage.warning('请先选择分辨率')
    return
  }
  if (imageRefreshing.value) return
  try {
    await startCamera({
      port: imagePort.value,
      resolution: resolution.value,
      imageNo: Number(imageNo.value) || 1
    })
    imageRefreshing.value = true
    statusText.value = '图像采集中...'
    fetchImage()
    if (imageTimer) clearInterval(imageTimer)
    imageTimer = setInterval(fetchImage, 1200)
  } catch (e) {
    imageRefreshing.value = false
    ElMessage.error(e?.message || '启动图像刷新失败')
  }
}

async function stopRefresh() {
  if (imageTimer) clearInterval(imageTimer)
  imageTimer = null
  imageRefreshing.value = false
  if (imagePort.value) {
    try {
      await stopCamera(imagePort.value)
    } catch {
      /* ignore */
    }
  }
  statusText.value = '已停止采集'
}

function saveCurrentImage() {
  const src = imageSrc.value
  if (!src) {
    ElMessage.warning('暂无图像可保存')
    return
  }
  const w = imgMeta.width || 0
  const h = imgMeta.height || 0
  const no = imgMeta.imageNo ?? imageNo.value ?? ''
  const ts = new Date()
  const pad = n => String(n).padStart(2, '0')
  const stamp = `${ts.getFullYear()}${pad(ts.getMonth() + 1)}${pad(ts.getDate())}_${pad(ts.getHours())}${pad(ts.getMinutes())}${pad(ts.getSeconds())}`
  const resPart = w && h ? `${w}x${h}` : 'image'
  const filename = `camera_${resPart}_no${no}_${stamp}.png`
  const a = document.createElement('a')
  a.href = src
  a.download = filename
  a.click()
  ElMessage.success('图片已保存')
}

function formatImageRefreshTime(ms) {
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return '-'
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function fetchImage() {
  if (!imageConnected.value || !imagePort.value) return
  try {
    const res = await getCameraImage(imagePort.value)
    const payload = res.data || {}
    const st = payload.status || {}
    if (st.message) statusText.value = st.message
    const image = payload.image || {}
    const meta = image.meta || {}
    if (meta.width) imgMeta.width = meta.width
    if (meta.height) imgMeta.height = meta.height
    if (meta.imageNo != null) imgMeta.imageNo = meta.imageNo
    if (image.data) {
      const fmt = image.format || meta.format || 'png'
      imageSrc.value = `data:image/${fmt === 'raw' ? 'png' : fmt};base64,${image.data}`
      frameTs.value = Date.now()
      imageRefreshTime.value = meta.ts || formatImageRefreshTime(frameTs.value)
    }
  } catch {
    statusText.value = '拉取图像失败'
  }
}

async function loadTcConfig() {
  try {
    const res = await getCameraTelecontrolConfig()
    rawOrders.value = res.data?.order || {}
    const pages = res.data?.page || []
    orderIds.value = pages[0]?.orderList || Object.keys(rawOrders.value)
    initCompValues(rawOrders.value)
    // 全部预览一次，标题字节数与 HEX 用默认参数即可确定
    await Promise.all(orderIds.value.map(id => {
      const ord = rawOrders.value[id]
      return ord ? previewOrder(ord, { showLoading: false }) : Promise.resolve()
    }))
  } catch (e) {
    ElMessage.error(e?.message || '加载相机遥控配置失败，请确认后端已重启')
  }
}

async function restoreCameraLinks() {
  try {
    const res = await getDeviceSnapshot(['serialOpened', 'sessions'])
    const opened = res.data?.serialOpened || []
    const alive = new Map()
    for (const p of opened) {
      if (p?.alive === false) continue
      const port = String(p.port || '').trim()
      if (port) alive.set(port.toUpperCase(), port)
    }
    const sessions = res.data?.sessions || []
    for (const s of sessions) {
      const source = String(s.source || '').trim()
      const param = String(s.srcParam || '')
      if (!param.startsWith('serial:')) continue
      const port = param.slice('serial:'.length)
      if (!alive.has(port.toUpperCase())) continue
      if (source === SOURCE_CAMERA_CTRL) {
        ctrlPort.value = port
        ctrlConnected.value = true
        assignXferSource(xferCtrlId)
      } else if (source === SOURCE_CAMERA_IMAGE) {
        imagePort.value = port
        imageConnected.value = true
        assignXferSource(xferImageId)
      }
    }
    savePrefs()
    // 恢复图像串口连接后不自动刷新，用户手动点「图片刷新」
  } catch {
    /* ignore */
  }
}

onMounted(async () => {
  loadPrefs()
  // 串口状态优先于遥测，便于进入后立刻新建连接
  await prefetchDeviceSnapshot()
  await restoreCameraLinks()
  linkTimer = setInterval(checkLinkStatus, 2000)
  // 遥控配置后置，不阻塞串口弹窗
  loadTcConfig().catch(() => {})
})

onUnmounted(() => {
  stopRefresh()
  if (linkTimer) clearInterval(linkTimer)
})
</script>

<style scoped>
.camera-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 84px);
  min-height: 520px;
}
.left-toolbar,
.image-toolbar {
  flex-shrink: 0;
  height: 32px;
  margin: 0;
  padding: 0;
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  width: 100%;
}
.left-toolbar :deep(.el-form-item),
.image-toolbar :deep(.el-form-item) {
  margin-bottom: 0;
  margin-right: 10px;
  display: inline-flex;
  align-items: center;
}
.image-toolbar :deep(.image-toolbar-right) {
  margin-left: auto;
  margin-right: 0;
}
.left-toolbar :deep(.el-form-item__label),
.image-toolbar :deep(.el-form-item__label) {
  height: 24px;
  line-height: 24px;
  padding: 0 8px 0 0;
}
.left-toolbar :deep(.el-form-item__content),
.image-toolbar :deep(.el-form-item__content) {
  line-height: 24px;
}
.left-toolbar :deep(.el-button),
.image-toolbar :deep(.el-button) {
  height: 24px;
  padding: 5px 11px;
}
.btn-connected {
  --el-button-bg-color: var(--el-color-success-light-9);
  --el-button-border-color: var(--el-color-success);
  --el-button-text-color: var(--el-color-success);
}
.btn-stop-refresh {
  --el-button-bg-color: var(--el-color-danger);
  --el-button-border-color: var(--el-color-danger);
  --el-button-text-color: #fff;
}
.image-select-res {
  width: 100px !important;
}
.image-select-res :deep(.el-select__wrapper) {
  width: 100px;
  min-height: 24px;
  height: 24px;
}
.image-select-no {
  width: 60px !important;
}
.image-select-no :deep(.el-select__wrapper) {
  width: 60px;
  min-height: 24px;
  height: 24px;
}
.panel-image :deep(.cam-image-view) {
  flex: 1;
  min-height: 0;
}
.status-text {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.main-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(380px, 44%) 1fr;
  gap: 10px;
}
.col-left,
.col-right {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}
.col-left .panel-tc,
.col-right .panel-image {
  flex: 1.2;
  min-height: 0;
}
.col-left .panel-xfer,
.col-right .panel-tm {
  flex: 0.8;
  min-height: 0;
}
.panel-tm {
  padding: 4px 8px;
  box-sizing: border-box;
}
.panel-tm :deep(.payload-tm-table) {
  height: 100%;
}
.panel {
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
  transform: translateY(5px);
}
.filter-input {
  margin-left: auto;
  width: 220px;
}
.panel-body {
  flex: 1;
  min-height: 0;
}
.panel-image,
.panel-xfer {
  border: none;
}
.order-list {
  padding: 8px;
}
.order-card {
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background: var(--el-fill-color-blank);
}
.order-title {
  font-weight: 600;
  margin-bottom: 8px;
  font-size: 14px;
}
.order-desc {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.order-desc-hex :deep(.el-descriptions__body) {
  background: transparent;
}
.comp-field {
  width: 200px;
}
</style>
