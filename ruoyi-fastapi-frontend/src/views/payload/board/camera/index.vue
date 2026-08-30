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
              placeholder="搜索指令代号/名称/参数标题（空格分词）"
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
                        :precision="numberPrecision(comp)"
                        :step="numberStep(comp)"
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
        <div class="panel panel-image">
          <CameraImageView
            :image-src="imageSrc"
            :width="imgMeta.width"
            :height="imgMeta.height"
            :image-no="imgMeta.imageNo"
            :frame-ts="frameTs"
            :refresh-time="imageRefreshTime"
            :show-centroid="showCentroid"
            :centroid="centroidOverlay"
            :tm-stats="tmStatsDisplay"
          >
            <template #toolbar>
              <el-form class="image-toolbar image-toolbar-vertical" size="small">
                <div class="toolbar-label">分辨率</div>
                <el-form-item class="toolbar-item-block">
                  <el-select
                    v-model="resolution"
                    size="small"
                    class="image-select-compact"
                    clearable
                    placeholder="请选择"
                    :disabled="!imageConnected || imageRefreshing"
                    @change="onResolutionUserChange"
                  >
                    <el-option v-for="r in resolutionOptions" :key="r" :label="r" :value="r" />
                  </el-select>
                </el-form-item>
                <div class="toolbar-label">图像索引</div>
                <el-form-item class="toolbar-item-block">
                  <el-select
                    v-model="imageNo"
                    size="small"
                    class="image-select-compact"
                    :disabled="!imageConnected || imageRefreshing"
                  >
                    <el-option v-for="n in imageNoOptions" :key="n" :label="String(n)" :value="n" />
                  </el-select>
                </el-form-item>
                <el-form-item class="toolbar-item-block">
                  <el-tooltip
                    placement="left"
                    :show-after="300"
                    content="勾选后，刷新前会先发送左侧「CAM_A10 - 拍照」指令；缓存数量、间隔等参数请在该指令控件中设置。"
                  >
                    <el-checkbox v-model="autoCapture" :disabled="imageRefreshing || imageOnceBusy">
                      自动拍照
                    </el-checkbox>
                  </el-tooltip>
                </el-form-item>
                <el-form-item class="toolbar-item-block toolbar-item-btn">
                  <el-button
                    type="primary"
                    plain
                    size="small"
                    class="toolbar-btn-compact"
                    :disabled="!imageConnected || imageRefreshing || imageOnceBusy"
                    :loading="imageOnceBusy"
                    @click="refreshOnce"
                  >图片刷新</el-button>
                </el-form-item>
                <el-form-item class="toolbar-item-block toolbar-item-btn">
                  <el-button
                    v-if="!imageRefreshing"
                    type="primary"
                    size="small"
                    class="toolbar-btn-compact"
                    :disabled="!imageConnected || imageOnceBusy"
                    @click="startRefresh"
                  >图片连续刷新</el-button>
                  <el-button
                    v-else
                    type="danger"
                    size="small"
                    class="btn-stop-refresh toolbar-btn-compact"
                    @click="stopRefresh"
                  >停止刷新</el-button>
                </el-form-item>
                <el-form-item class="toolbar-item-block toolbar-item-btn">
                  <el-button
                    type="success"
                    size="small"
                    class="toolbar-btn-compact"
                    :disabled="!imageSrc"
                    @click="saveCurrentImage"
                  >图片保存</el-button>
                </el-form-item>
                <el-form-item class="toolbar-item-block toolbar-item-btn">
                  <input
                    ref="imageUploadRef"
                    type="file"
                    accept=".png,.bmp,image/png,image/bmp,image/x-ms-bmp"
                    class="hidden-file-input"
                    @change="onLocalImageSelected"
                  >
                  <el-button
                    type="primary"
                    plain
                    size="small"
                    class="toolbar-btn-compact"
                    :disabled="imageRefreshing || imageOnceBusy"
                    @click="pickLocalImage"
                  >图片上传</el-button>
                </el-form-item>
                <el-form-item class="toolbar-item-block">
                  <el-checkbox v-model="showCentroid">显示质心位置</el-checkbox>
                </el-form-item>
              </el-form>
            </template>
          </CameraImageView>
        </div>
        <div class="panel panel-tm">
          <PayloadTelemetryTable
            ref="tmTableRef"
            v-model:type="tmTableKey"
            level="t3"
            :types="tmTypes"
            auto-switch-type
            @snaps-change="onTmSnapsChange"
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
      :baud-editable="
        serialDlg.kind === 'image'
          ? !!imageConnectCfg.baudEditable || imageBaudChoices.length > 1
          : !!ctrlConnectCfg.baudEditable || ctrlBaudChoices.length > 1
      "
      :match-baud-mode="
        serialDlg.kind === 'image'
          ? imageConnectCfg.matchBaudMode || (imageBaudChoices.length > 1 ? 'allowlist' : 'exact')
          : ctrlConnectCfg.matchBaudMode || (ctrlBaudChoices.length > 1 ? 'allowlist' : 'exact')
      "
      :preferred-port="serialDlg.kind === 'ctrl' ? ctrlPort : imagePort"
      :fallback-parsers="FALLBACK_PARSERS_CAMERA"
      :fallback-assemblers="FALLBACK_ASSEMBLERS_CAMERA"
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
import { useLinkStatusPoll } from '@/utils/useLinkStatusPoll'
import {
  getDeviceConnectEntry,
  toBaudChoices,
  toSerialPreset
} from '@/utils/deviceConnectDefaults'
import {
  ASSEMBLER_PASSTHROUGH,
  ASSEMBLER_CAMERA_IMAGE_D6,
  PARSER_CAMERA_SC_LINK41EP,
  FALLBACK_PARSERS_CAMERA,
  FALLBACK_ASSEMBLERS_CAMERA
} from '@/utils/pipelineIds'
import { numBound, numberPrecision, numberStep } from '@/utils/telecontrolComponent'
import { orderMatchesFilter } from '@/utils/telecontrolOrderMatch'
import { saveDeviceImageCache, takeDeviceImageCache } from '@/utils/cameraDeviceImageCache'

/** 控制串口会话 source */
const SOURCE_CAMERA_CTRL = 'camera_ctrl'
/** 图像串口会话 source */
const SOURCE_CAMERA_IMAGE = 'camera_image'

const PREFS_KEY = 'payload:board:camera:prefs'
/** 分辨率下拉固定项；开窗遥测值映射到其中 */
const resolutions = ['400×400', '256×256', '128×128', '64×64']
/** 当前值不在固定项时插入首位，避免下拉丢值 */
const resolutionOptions = computed(() => {
  const cur = String(resolution.value || '').trim()
  if (cur && !resolutions.includes(cur)) return [cur, ...resolutions]
  return resolutions
})
/** 图像索引 1–64 */
const imageNoOptions = Array.from({ length: 64 }, (_, i) => i + 1)
/** 开窗模式/缓存图像大小 value/hex → 分辨率（D8 CAM036/038 与 D9 CAMF029/027 枚举相同） */
const WINDOW_RES_MAP = {
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
/** D8 慢遥(全窗)分辨率：开窗模式 CAM036、缓存图像大小 CAM038 */
const D8_RES_FIELD_IDS = ['CAM036', 'CAM038']
/** D9 快遥(开窗)分辨率：开窗模式 CAMF029、缓存图像大小 CAMF027；切表后必须用这组，不可回落 D8 */
const D9_RES_FIELD_IDS = ['CAMF029', 'CAMF027']

/** 控制串口默认物理参数（会被 device_connect 覆盖） */
const FALLBACK_CTRL = {
  baudrate: 2000000,
  baudChoices: [2000000, 11000000],
  dataBits: 8,
  stopBits: 1,
  parity: 'O',
  flowControl: 'NONE',
  assemblerId: ASSEMBLER_PASSTHROUGH,
  parserId: PARSER_CAMERA_SC_LINK41EP,
  /** 全双工：遥控发送与遥测接收并行 */
  fullDuplex: true
}
/** 图像串口默认参数；组装器为相机图像(D6) */
const FALLBACK_IMAGE = {
  baudrate: 2000000,
  baudChoices: [2000000, 11000000],
  dataBits: 8,
  stopBits: 1,
  parity: 'O',
  flowControl: 'NONE',
  assemblerId: ASSEMBLER_CAMERA_IMAGE_D6,
  parserId: '',
  baudEditable: true,
  matchBaudMode: 'allowlist',
  /** 全双工：连续收图时不阻塞 */
  fullDuplex: true
}

/** 控制串口连接默认值（含波特率白名单、全双工） */
const ctrlConnectCfg = ref({ ...FALLBACK_CTRL })
/** 图像串口连接默认值 */
const imageConnectCfg = ref({ ...FALLBACK_IMAGE })
const CTRL_PRESET = computed(() => toSerialPreset(ctrlConnectCfg.value))
const IMAGE_PRESET = computed(() => toSerialPreset(imageConnectCfg.value))
const ctrlBaudChoices = computed(() => toBaudChoices(ctrlConnectCfg.value))
const imageBaudChoices = computed(() => toBaudChoices(imageConnectCfg.value))

/** 控制串口号 */
const ctrlPort = ref('')
/** 图像串口号 */
const imagePort = ref('')
const ctrlConnected = ref(false)
const imageConnected = ref(false)
/** 分辨率下拉当前值；空表示未选，收图前必选 */
const resolution = ref('')
/** 用户是否手动改过分辨率（含清空） */
const resolutionUserTouched = ref(false)
/** 上次从当前遥测表开窗字段解析到的分辨率，用于判断遥测是否变化 */
const lastCam027Res = ref('')
/** 图像索引（1–64） */
const imageNo = ref(1)
/** 连续刷新进行中 */
const imageRefreshing = ref(false)
/** 单次「图片刷新」进行中（完整收图前按钮不可点） */
const imageOnceBusy = ref(false)
/** 连续刷新轮次（提示「第 n 次…」） */
const imageRefreshRound = ref(0)
/** 点「图片刷新」前先发 CAM_A10 拍照 */
const autoCapture = ref(true)
const statusText = ref('就绪')
const filterText = ref('')
const rawOrders = ref({})
const orderIds = ref([])
/** 遥控指令各控件当前值：orderId → { idx: value } */
const compValues = reactive({})
/** 组帧预览：orderId → { hex, length } */
const assembledMap = reactive({})
const sendingId = ref('')
const previewingId = ref('')
/** 遥控帧序号，发送后自增 */
const frameSeq = ref(0)

/** 当前画面 data URL */
const imageSrc = ref('')
const imgMeta = reactive({ width: 0, height: 0, imageNo: null })
const imageUploadRef = ref(null)
/** 本帧到达时间戳(ms)，用于帧率 */
const frameTs = ref(0)
const imageRefreshTime = ref('-')
const showCentroid = ref(true)

/** D8/D9 遥测缓存（从 PayloadTelemetryTable snap 同步，关控制串口时清空） */
const tmSnap = reactive({
  D8: { rows: [], dataId: 0, ts: '' },
  D9: { rows: [], dataId: 0, ts: '' }
})

/** 当前遥测表下拉：D8 慢遥(全窗) / D9 快遥(开窗)；切表会改分辨率字段来源 */
const tmTableKey = ref('D8')
const tmTableRef = ref(null)
const tmTypes = [
  { id: 'D8', name: '慢遥测(全窗)' },
  { id: 'D9', name: '快遥测(开窗)' }
]

const xferDeviceId = ref('')

/** 串口连接弹窗：kind 为 ctrl | image */
const serialDlg = reactive({ visible: false, kind: 'ctrl' })

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

const filteredOrders = computed(() => {
  return orderIds.value
    .map(id => rawOrders.value[id])
    .filter(Boolean)
    .filter(o => orderMatchesFilter(o, filterText.value))
})

function compType(comp) {
  return String(comp?.componentType || 'fixed').toLowerCase()
}

/** 按遥控配置初始化各指令控件默认值（已有值不覆盖） */
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

/** 组帧/发送用：fixed 取 defaultVal，其余取控件当前值 */
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

/** 按字段 id 取遥测行展示值（优先 show，否则 value） */
function tmRowVal(rows, id) {
  const row = (rows || []).find(r => String(r?.id || '').toUpperCase() === String(id || '').toUpperCase())
  if (!row) return ''
  const show = row.show
  if (show !== '' && show != null && String(show).trim() !== '') return String(show).trim()
  const v = row.value
  if (v !== '' && v != null && String(v).trim() !== '') return String(v).trim()
  return ''
}

/** 质心坐标展示：`x, y`；缺一侧则只显示有值的一侧 */
function formatCoordPair(rows, xId, yId) {
  const x = tmRowVal(rows, xId)
  const y = tmRowVal(rows, yId)
  if (!x && !y) return ''
  if (!x) return y
  if (!y) return x
  return `${x}, ${y}`
}

/** 质心坐标字符串 → 数字（去掉千分位逗号） */
function parseCoordNum(val) {
  if (val === '' || val == null) return NaN
  const n = Number(String(val).replace(/,/g, '').trim())
  return Number.isFinite(n) ? n : NaN
}

const TM_TABLE_LABEL = {
  D8: 'D8：慢遥(全窗)',
  D9: 'D9：快遥(开窗)'
}

/** 遥测数据时间字符串 → ms；用于 D8/D9 比新 */
function parseDataTsMs(ts) {
  if (!ts) return 0
  const t = Date.parse(String(ts).trim().replace(/-/g, '/'))
  return Number.isFinite(t) ? t : 0
}

/** 遥测行是否至少有一个非空 show/value */
function tmRowsHaveValues(rows) {
  return (rows || []).some(r => {
    const s = r?.show ?? r?.value
    return s !== '' && s != null && String(s).trim() !== ''
  })
}

/** snap 是否有真实遥测（有 ts/dataId 且行有值） */
function tmSnapHasValidData(key) {
  const snap = tmSnap[key]
  if (!snap) return false
  const hasReal = !!(snap.ts || (snap.dataId != null && Number(snap.dataId) > 0))
  return hasReal && tmRowsHaveValues(snap.rows)
}

/**
 * 当前 snap 是否含统计区字段（质心/能量/过阈值/饱和/灰度）。
 * D8：CAM004/005 坐标、CAM006 过阈值、CAM007 饱和、CAM008 平均灰度、CAM010 光斑能量。
 * D9：对应 CAMF004/005、CAMF006、CAMF007、CAMF008、CAMF010。
 */
function tmSnapHasStats(key) {
  const rows = tmSnap[key]?.rows
  if (!rows?.length) return false
  if (key === 'D9') {
    return !!(
      tmRowVal(rows, 'CAMF004') ||
      tmRowVal(rows, 'CAMF005') ||
      tmRowVal(rows, 'CAMF006') ||
      tmRowVal(rows, 'CAMF007') ||
      tmRowVal(rows, 'CAMF008') ||
      tmRowVal(rows, 'CAMF010')
    )
  }
  return !!(
    tmRowVal(rows, 'CAM004') ||
    tmRowVal(rows, 'CAM005') ||
    tmRowVal(rows, 'CAM006') ||
    tmRowVal(rows, 'CAM007') ||
    tmRowVal(rows, 'CAM008') ||
    tmRowVal(rows, 'CAM010')
  )
}

/**
 * 统计区/质心用哪张表：优先表格 getEffectiveType（数据最新且有效），
 * 否则 D8/D9 里取数据时间较新的；无统计字段则改用另一张。
 */
function pickActiveTmKey() {
  const fromTable = tmTableRef.value?.getEffectiveType?.() || ''
  if (fromTable && tmSnapHasStats(fromTable)) return fromTable
  const d8Ok = tmSnapHasValidData('D8')
  const d9Ok = tmSnapHasValidData('D9')
  let key = ''
  if (d8Ok && d9Ok) {
    const d8 = parseDataTsMs(tmSnap.D8.ts)
    const d9 = parseDataTsMs(tmSnap.D9.ts)
    if (!d8 && !d9) key = 'D8'
    else key = d9 >= d8 ? 'D9' : 'D8'
  } else if (d9Ok) {
    key = 'D9'
  } else if (d8Ok) {
    key = 'D8'
  }
  if (!key) return ''
  if (!tmSnapHasStats(key)) {
    const other = key === 'D9' ? 'D8' : 'D9'
    if (tmSnapHasStats(other)) return other
  }
  return key
}

/** 从 PayloadTelemetryTable 缓存同步到本页 tmSnap */
function syncTmSnapFromTable() {
  const all = tmTableRef.value?.getAllSnaps?.() || {}
  for (const key of ['D8', 'D9']) {
    const s = all[key]
    if (!s) continue
    tmSnap[key].rows = Array.isArray(s.rows) ? s.rows : []
    tmSnap[key].ts = s.ts || ''
    tmSnap[key].dataId = Number(s.dataId) || 0
  }
  syncResolutionFromActiveTm()
}

/** 表格 snap 变化：同步本页 D8/D9 缓存并按当前表刷新分辨率 */
function onTmSnapsChange() {
  syncTmSnapFromTable()
}

/** 左侧统计表：按有效表填 D8 或 D9 字段（另一侧留空） */
const tmStatsDisplay = computed(() => {
  const key = pickActiveTmKey()
  if (!key) {
    return {
      tableLabel: '',
      coordD8: '',
      coordD9: '',
      energyD8: '',
      energyD9: '',
      overThD8: '',
      overThD9: '',
      satD8: '',
      satD9: '',
      grayD8: '',
      grayD9: ''
    }
  }
  if (key === 'D9') {
    // D9 快遥：CAMF004/005 坐标、CAMF010 能量、CAMF006 过阈值、CAMF007 饱和、CAMF008 灰度
    return {
      tableLabel: TM_TABLE_LABEL.D9,
      coordD8: '',
      coordD9: formatCoordPair(tmSnap.D9.rows, 'CAMF004', 'CAMF005'),
      energyD8: '',
      energyD9: tmRowVal(tmSnap.D9.rows, 'CAMF010'),
      overThD8: '',
      overThD9: tmRowVal(tmSnap.D9.rows, 'CAMF006'),
      satD8: '',
      satD9: tmRowVal(tmSnap.D9.rows, 'CAMF007'),
      grayD8: '',
      grayD9: tmRowVal(tmSnap.D9.rows, 'CAMF008')
    }
  }
  // D8 慢遥：CAM004/005、CAM010、CAM006、CAM007、CAM008
  return {
    tableLabel: TM_TABLE_LABEL.D8,
    coordD8: formatCoordPair(tmSnap.D8.rows, 'CAM004', 'CAM005'),
    coordD9: '',
    energyD8: tmRowVal(tmSnap.D8.rows, 'CAM010'),
    energyD9: '',
    overThD8: tmRowVal(tmSnap.D8.rows, 'CAM006'),
    overThD9: '',
    satD8: tmRowVal(tmSnap.D8.rows, 'CAM007'),
    satD9: '',
    grayD8: tmRowVal(tmSnap.D8.rows, 'CAM008'),
    grayD9: ''
  }
})

/** 质心十字星：D9 用 CAMF004/005，D8 用 CAM004/005 */
const centroidOverlay = computed(() => {
  const key = pickActiveTmKey()
  if (!key) return null
  const rows = tmSnap[key].rows
  const xId = key === 'D9' ? 'CAMF004' : 'CAM004'
  const yId = key === 'D9' ? 'CAMF005' : 'CAM005'
  const x = parseCoordNum(tmRowVal(rows, xId))
  const y = parseCoordNum(tmRowVal(rows, yId))
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null
  return { x, y }
})

/** 关控制串口/断连时清空本页 D8/D9 缓存 */
function clearTmSnapLocal() {
  tmSnap.D8.rows = []
  tmSnap.D8.dataId = 0
  tmSnap.D8.ts = ''
  tmSnap.D9.rows = []
  tmSnap.D9.dataId = 0
  tmSnap.D9.ts = ''
}

/** 用户改分辨率下拉（含清空）：有值则锁定，不再被遥测覆盖 */
function onResolutionUserChange(val) {
  resolutionUserTouched.value = Boolean(val)
}

function onTmDataChange() {
  // 切表展示变化时也同步一份缓存（snaps-change 为主）
  syncTmSnapFromTable()
}

/** 从遥测行解析开窗模式/缓存图像大小 → 分辨率选项值；ids 按表传入 D8 或 D9 字段 */
function parseResolutionFromRows(rows, ids = D8_RES_FIELD_IDS) {
  for (const id of ids) {
    const row = (rows || []).find(r => String(r?.id || '').toUpperCase() === id)
    if (!row) continue
    const show = String(row.show ?? '').trim()
    if (show) {
      // 展示文本已含「400×400」等，直接匹配
      for (const r of resolutions) {
        if (show === r || show.startsWith(r)) return r
      }
    }
    // 否则用 value/hex/raw 的 0/1/2/3 或 0x00–0x03 映射
    const candidates = [row.value, row.hex, row.raw]
      .map(v => String(v ?? '').trim().toLowerCase().replace(/\s+/g, ''))
      .filter(Boolean)
    for (const c of candidates) {
      const key = c.startsWith('0x') ? c : c.replace(/^0+/, '') || '0'
      const mapped =
        WINDOW_RES_MAP[c] ||
        WINDOW_RES_MAP[`0x${c.replace(/^0x/, '')}`] ||
        WINDOW_RES_MAP[key.padStart(2, '0')] ||
        WINDOW_RES_MAP[`0x${key.padStart(2, '0')}`]
      if (mapped) return mapped
    }
  }
  return ''
}

/**
 * 按当前遥测表同步分辨率下拉（连续刷新下一帧会读 resolution）：
 * D8 用 CAM036/CAM038，D9 用 CAMF029/CAMF027；收图宽高是请求回显，不可信。
 */
function syncResolutionFromActiveTm() {
  const key = String(tmTableKey.value || pickActiveTmKey() || '').toUpperCase()
  let next = ''
  if (key === 'D8') {
    next = parseResolutionFromRows(tmSnap.D8.rows, D8_RES_FIELD_IDS)
  } else if (key === 'D9') {
    // 切到 D9 只用 CAMF029/CAMF027，不再回落 D8 的 CAM036/038
    next = parseResolutionFromRows(tmSnap.D9.rows, D9_RES_FIELD_IDS)
  }
  if (!next) return
  lastCam027Res.value = next
  // 手选后（含刷新过程中）不再用遥测改下拉；清空后才重新跟开窗字段
  if (!resolution.value || !resolutionUserTouched.value) {
    resolution.value = next
  }
}

/** 恢复串口号、图像索引、搜索词；分辨率不从偏好恢复 */
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
watch(tmTableKey, () => {
  // 下拉切 D8↔D9：改用对应开窗字段重算分辨率
  syncResolutionFromActiveTm()
})

/** kind: 'ctrl' 控制串口 | 'image' 图像串口 */
function openSerialDialog(kind) {
  serialDlg.kind = kind
  serialDlg.visible = true
}

/** 弹窗打开成功：写入对应角色的口状态 */
function onSerialSuccess({ port }) {
  applyConnectedState(port)
  savePrefs()
}

/** 同一物理口不能同时充当控制/图像；保留 keepKind，清掉另一角色 */
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

/** 按弹窗 kind 标记控制/图像已连接，并切传输信息来源 */
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
  clearTmSnapLocal()
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

/** 网络/后端离线类错误（关串口时走本地清状态） */
function isBackendOfflineError(e) {
  const msg = String(e?.message || e || '')
  return /连接异常|Network Error|ECONNREFUSED|Failed to fetch|接口请求超时|status code 5\d\d|服务正在关闭/i.test(msg)
}

/** 轮询已开串口；控制口断开时清空 tmSnap */
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
      clearTmSnapLocal()
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

const { start: startLinkPoll } = useLinkStatusPoll(checkLinkStatus)

/** 预览组帧，写入 assembledMap（HEX / 长度） */
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

/** 导出全部指令预览 HEX 为 JSON */
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

/** 经控制串口发送遥控指令；seq 发送后自增 */
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

/** 自动拍照参数：取左侧 CAM_A10 控件；图像索引大于缓存数量时把缓存数量抬到索引 */
function autoCaptureValues(ord) {
  const idxNo = Math.max(1, Math.min(64, Number(imageNo.value) || 1))
  const comps = ord?.component || []
  if (!Array.isArray(comps) || !comps.length) {
    return ['0x01', idxNo, 0]
  }
  const values = valuesForOrder(ord)
  const cacheIdx = comps.findIndex(c => String(c.title || '').includes('缓存数量'))
  if (cacheIdx < 0) return values
  const cur = Number(values[cacheIdx])
  const cache = Number.isFinite(cur) ? cur : 0
  if (idxNo > cache) {
    const maxVal = Number(comps[cacheIdx].maxVal)
    const next = Number.isFinite(maxVal) && maxVal > 0 ? Math.min(idxNo, maxVal) : idxNo
    values[cacheIdx] = next
    if (!compValues[ord.id]) compValues[ord.id] = {}
    compValues[ord.id][cacheIdx] = next
  }
  return values
}

/** 自动拍照：组帧发送 CAM_A10（seq 自增；参数取左侧控件；刷新预览不弹成功提示） */
async function sendAutoCapturePhoto() {
  if (!ctrlConnected.value || !ctrlDeviceId.value) {
    ElMessage.warning('自动拍照需要先打开控制串口')
    return false
  }
  const ord = rawOrders.value.CAM_A10
  if (!ord) {
    ElMessage.error('未找到 CAM_A10 拍照指令配置')
    return false
  }
  try {
    const seq = frameSeq.value
    const values = autoCaptureValues(ord)
    const res = await sendCameraTelecontrol({
      deviceId: ctrlDeviceId.value,
      orderId: 'CAM_A10',
      name: ord.name || '拍照',
      values,
      seq
    })
    frameSeq.value = (seq + 1) & 0xffff
    // 同步左侧「指令参数」预览帧（与手动发送一致），但不弹「发送成功」
    if (res.data?.hex) {
      assembledMap.CAM_A10 = {
        hex: res.data.hex,
        length: res.data.hex.split(/\s+/).filter(Boolean).length
      }
    }
    if (!res.data?.success) {
      ElMessage.error(res.data?.message || '自动拍照发送失败')
      return false
    }
    return true
  } catch (e) {
    ElMessage.error(e?.message || '自动拍照发送失败')
    return false
  }
}

function sleepMs(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

/** 把 getCameraImage 响应应用到画面。ready=有图；failed=后端已停不再重试；wait=继续等 */
function applyImagePayload(payload) {
  const st = payload?.status || {}
  const image = payload?.image || {}
  const meta = image.meta || {}
  const phase = String(st.imagePhase || meta.phase || '').toLowerCase()
  const msg = st.message || meta.message || ''
  if (msg) statusText.value = msg
  if (meta.width) imgMeta.width = meta.width
  if (meta.height) imgMeta.height = meta.height
  const parsedNo = Number(meta.imageNo)
  if (Number.isFinite(parsedNo) && parsedNo > 0) {
    imgMeta.imageNo = parsedNo
  } else if (imageNo.value) {
    imgMeta.imageNo = imageNo.value
  }
  if (image.data) {
    const fmt = image.format || meta.format || 'png'
    imageSrc.value = `data:image/${fmt === 'raw' ? 'png' : fmt};base64,${image.data}`
    frameTs.value = Date.now()
    imageRefreshTime.value = meta.ts || formatImageRefreshTime(frameTs.value)
    saveDeviceImageCache({
      src: imageSrc.value,
      width: imgMeta.width,
      height: imgMeta.height,
      imageNo: imgMeta.imageNo,
      refreshTime: imageRefreshTime.value
    })
    return 'ready'
  }
  if (phase === 'failed') return 'failed'
  return 'wait'
}

/**
 * 一轮完整传图：可选拍照 → 10ms → once 采图 → 等到 Redis 新图。
 * @returns {Promise<boolean>} 是否收到完整图像
 */
async function runImageCycle({ continuous = false } = {}) {
  if (!imageConnected.value || !imagePort.value) {
    ElMessage.warning('请先打开图像串口')
    return false
  }
  if (!resolution.value) {
    ElMessage.warning('请先选择分辨率')
    return false
  }
  if (autoCapture.value) {
    const ok = await sendAutoCapturePhoto()
    if (!ok) return false
    await sleepMs(10)
    const tip = continuous
      ? `第 ${imageRefreshRound.value} 次拍照并获取图片`
      : '开始拍照并获取图片'
    ElMessage.success(tip)
    statusText.value = tip
  } else {
    const tip = continuous
      ? `第 ${imageRefreshRound.value} 次获取图片`
      : '开始获取图片'
    ElMessage.success(tip)
    statusText.value = tip
  }
  if (continuous && !imageRefreshing.value) return false

  await startCamera({
    port: imagePort.value,
    resolution: resolution.value,
    imageNo: Number(imageNo.value) || 1,
    once: true
  })

  const deadline = Date.now() + 90000
  while (Date.now() < deadline) {
    if (continuous && !imageRefreshing.value) {
      // stopRefresh 已调 stopCamera；此处只退出轮询
      return false
    }
    if (!continuous && !imageOnceBusy.value) {
      return false
    }
    try {
      const res = await getCameraImage(imagePort.value)
      const hit = applyImagePayload(res.data || {})
      if (hit === 'ready') {
        statusText.value = continuous ? '图像采集中...' : '已刷新一次'
        return true
      }
      if (hit === 'failed') {
        const tip = statusText.value || '图像采集失败'
        ElMessage.error(tip)
        try {
          await stopCamera(imagePort.value)
        } catch {
          /* ignore */
        }
        return false
      }
    } catch {
      /* keep polling */
    }
    await sleepMs(500)
  }
  ElMessage.error('等待图像超时')
  try {
    await stopCamera(imagePort.value)
  } catch {
    /* ignore */
  }
  return false
}

/** 连续刷新：循环 runImageCycle，直到停止或一轮失败 */
async function startRefresh() {
  if (!imageConnected.value || !imagePort.value) {
    ElMessage.warning('请先打开图像串口')
    return
  }
  if (!resolution.value) {
    ElMessage.warning('请先选择分辨率')
    return
  }
  if (imageRefreshing.value || imageOnceBusy.value) return
  imageRefreshing.value = true
  imageRefreshRound.value = 0
  statusText.value = '图像采集中...'
  try {
    while (imageRefreshing.value) {
      imageRefreshRound.value += 1
      const ok = await runImageCycle({ continuous: true })
      if (!imageRefreshing.value) break
      if (!ok) {
        imageRefreshing.value = false
        statusText.value = '连续刷新已中断'
        break
      }
    }
  } catch (e) {
    imageRefreshing.value = false
    ElMessage.error(e?.message || '连续刷新失败')
  } finally {
    imageRefreshRound.value = 0
  }
}

/** 单次：完整收图后按钮才恢复 */
async function refreshOnce() {
  if (!imageConnected.value || !imagePort.value) {
    ElMessage.warning('请先打开图像串口')
    return
  }
  if (!resolution.value) {
    ElMessage.warning('请先选择分辨率')
    return
  }
  if (imageRefreshing.value || imageOnceBusy.value) return
  imageOnceBusy.value = true
  try {
    await runImageCycle({ continuous: false })
  } finally {
    imageOnceBusy.value = false
  }
}

/** 停止连续采集并通知后端 stopCamera */
async function stopRefresh() {
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

/** 触发隐藏 file input，选本地 PNG/BMP */
function pickLocalImage() {
  imageUploadRef.value?.click()
}

function isAllowedLocalImage(file) {
  const name = String(file?.name || '').toLowerCase()
  const type = String(file?.type || '').toLowerCase()
  return (
    name.endsWith('.png') ||
    name.endsWith('.bmp') ||
    type === 'image/png' ||
    type === 'image/bmp' ||
    type === 'image/x-ms-bmp'
  )
}

/** 本地图上屏，并把分辨率下拉锁到图片宽高 */
function applyLocalImage(src, width, height) {
  const w = Number(width) || 0
  const h = Number(height) || 0
  imageSrc.value = src
  imgMeta.width = w
  imgMeta.height = h
  frameTs.value = Date.now()
  imageRefreshTime.value = formatImageRefreshTime(frameTs.value)
  const label = w && h ? `${w}×${h}` : ''
  if (label) {
    resolution.value = label
    resolutionUserTouched.value = true
  }
  statusText.value = label ? `已加载本地图片 ${label}` : '已加载本地图片'
}

function onLocalImageSelected(ev) {
  const input = ev?.target
  const file = input?.files?.[0]
  if (input) input.value = ''
  if (!file) return
  if (!isAllowedLocalImage(file)) {
    ElMessage.warning('仅支持 PNG、BMP 图片')
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    const src = String(reader.result || '')
    if (!src) {
      ElMessage.error('读取图片失败')
      return
    }
    const img = new Image()
    img.onload = () => {
      applyLocalImage(src, img.naturalWidth || img.width, img.naturalHeight || img.height)
    }
    img.onerror = () => ElMessage.error('图片无法解析，请确认是有效的 PNG 或 BMP')
    img.src = src
  }
  reader.onerror = () => ElMessage.error('读取文件失败')
  reader.readAsDataURL(file)
}

/** 当前画面另存为 PNG */
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
    applyImagePayload(res.data || {})
  } catch {
    statusText.value = '拉取图像失败'
  }
}

/** 加载相机遥控配置，默认参数全部预览一次 */
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

/** 按会话 source 恢复控制/图像串口已开状态（不自动收图） */
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

/** 从设备图像缓存恢复上次画面（跨页返回） */
function restoreDeviceImageCache() {
  const cached = takeDeviceImageCache()
  if (!cached?.src) return
  imageSrc.value = cached.src
  if (cached.width) imgMeta.width = cached.width
  if (cached.height) imgMeta.height = cached.height
  if (cached.imageNo != null) imgMeta.imageNo = cached.imageNo
  frameTs.value = cached.at
  imageRefreshTime.value = cached.refreshTime || formatImageRefreshTime(cached.at)
  const label = cached.width && cached.height ? `${cached.width}×${cached.height}` : ''
  if (label && !resolution.value) {
    resolution.value = label
  }
  statusText.value = '已恢复缓存图像'
}

onMounted(async () => {
  loadPrefs()
  restoreDeviceImageCache()
  const [ctrlEntry, imageEntry] = await Promise.all([
    getDeviceConnectEntry(SOURCE_CAMERA_CTRL),
    getDeviceConnectEntry(SOURCE_CAMERA_IMAGE)
  ])
  if (ctrlEntry) ctrlConnectCfg.value = { ...FALLBACK_CTRL, ...ctrlEntry }
  if (imageEntry) imageConnectCfg.value = { ...FALLBACK_IMAGE, ...imageEntry }
  // 串口状态优先于遥测，便于进入后立刻新建连接
  await prefetchDeviceSnapshot()
  await restoreCameraLinks()
  startLinkPoll()
  // 遥控配置后置，不阻塞串口弹窗
  loadTcConfig().catch(() => {})
})

onDeactivated(() => {
  stopRefresh()
})

onUnmounted(() => {
  stopRefresh()
  clearTmSnapLocal()
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
  height: auto;
  min-height: 32px;
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
  height: 100%;
}
.panel-image :deep(.image-toolbar-vertical) {
  display: flex;
  flex-direction: column;
  width: auto;
  align-items: flex-start;
}
.panel-image :deep(.image-toolbar-vertical .toolbar-label) {
  font-size: 12px;
  line-height: 1.2;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}
.panel-image :deep(.image-toolbar-vertical .toolbar-item-block) {
  width: auto;
  margin-right: 0;
  margin-bottom: 8px;
}
.panel-image :deep(.image-toolbar-vertical .toolbar-item-block:last-child) {
  margin-bottom: 0;
}
.panel-image :deep(.image-toolbar-vertical .el-form-item__content) {
  line-height: 1;
  margin-left: 0 !important;
}
.panel-image :deep(.image-select-compact) {
  width: 96px !important;
}
.panel-image :deep(.image-select-compact .el-select__wrapper) {
  width: 96px;
  min-height: 24px;
  height: 24px;
}
.panel-image :deep(.toolbar-btn-compact) {
  width: 96px;
  min-width: 96px;
  padding: 5px 0;
  justify-content: center;
}
.hidden-file-input {
  display: none;
}
.status-text {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.main-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(320px, 1fr) 2fr;
  gap: 10px;
}
.col-left,
.col-right {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}
.col-left .panel-tc {
  flex: 1.4;
  min-height: 0;
}
.col-left .panel-xfer {
  flex: 0.8;
  min-height: 0;
}
.col-right .panel-image {
  flex: 1.2;
  min-height: 0;
}
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
