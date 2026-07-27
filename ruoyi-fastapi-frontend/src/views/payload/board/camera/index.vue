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
            <span>遥控</span>
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
          <div class="panel-head">
            <span class="tm-head-left">
              遥测 ·
              <el-select v-model="tmTableKey" size="small" class="tm-key-select" @change="onTmTableChange">
                <el-option
                  v-for="p in tmPages"
                  :key="p.key || p.id"
                  :label="`${p.id || p.key}：${p.name || ''}`"
                  :value="String(p.key || p.id).toUpperCase()"
                />
              </el-select>
              <span class="tm-key-tag">(0x{{ tmTableKey }})</span>
            </span>
            <span v-if="tmTs" class="tm-ts">{{ tmTs }}</span>
          </div>
          <el-table :data="tmRows" size="small" height="100%" border stripe empty-text="暂无数据">
            <el-table-column label="编号" width="80">
              <template #default="{ row }">
                <el-tooltip
                  v-if="tmDefById[row.id]"
                  placement="right"
                  :show-after="200"
                  effect="light"
                  popper-class="tm-cfg-tooltip"
                >
                  <template #content>
                    <pre class="tm-cfg-json">{{ tmCfgJson(row.id) }}</pre>
                  </template>
                  <span class="tm-id-cell">{{ row.id }}</span>
                </el-tooltip>
                <span v-else>{{ row.id }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="参数名称" min-width="140" show-overflow-tooltip />
            <el-table-column label="当前值" width="120">
              <template #default="{ row }">{{ row.show ?? row.value }}</template>
            </el-table-column>
            <el-table-column prop="unit" label="单位" width="64" />
            <el-table-column prop="hex" label="HEX" min-width="90" show-overflow-tooltip />
          </el-table>
        </div>
      </div>
    </div>

    <el-dialog
      v-model="serialDlg.visible"
      :title="serialDlg.kind === 'ctrl' ? '新建控制串口连接' : '新建图像串口连接'"
      width="560px"
      destroy-on-close
      @opened="onSerialDlgOpened"
    >
      <el-form label-width="100px" class="conn-form">
        <el-form-item label="串口号">
          <div class="port-row">
            <el-select
              v-model="serialForm.port"
              filterable
              :disabled="serialOpening"
              class="conn-ctrl"
              @change="onSerialPortChange"
            >
              <el-option
                v-for="p in serialPortOptions"
                :key="p.port"
                :label="p.label"
                :value="p.port"
                :disabled="p.disabled"
              />
            </el-select>
            <el-button
              type="primary"
              plain
              :loading="serialRefreshing"
              :disabled="serialOpening"
              @click="refreshPorts"
            >刷新</el-button>
          </div>
        </el-form-item>
        <el-form-item label="波特率">
          <el-select
            v-model="serialForm.baudChoice"
            :disabled="baudSelectDisabled"
            class="conn-ctrl"
            @change="onBaudChoiceChange"
          >
            <el-option v-for="b in activeBaudChoices" :key="b.value" :label="b.label" :value="b.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="数据位">
          <el-select v-model="serialForm.dataBits" disabled class="conn-ctrl">
            <el-option v-for="d in dataBitsOptions" :key="d" :label="String(d)" :value="d" />
          </el-select>
        </el-form-item>
        <el-form-item label="停止位">
          <el-select v-model="serialForm.stopBits" disabled class="conn-ctrl">
            <el-option v-for="s in stopBitsOptions" :key="s" :label="String(s)" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="校验位">
          <el-select v-model="serialForm.parity" disabled class="conn-ctrl">
            <el-option v-for="p in parityOptions" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="流控制">
          <el-select v-model="serialForm.flowControl" disabled class="conn-ctrl">
            <el-option v-for="f in flowOptions" :key="f.value" :label="f.label" :value="f.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="组装器">
          <el-select v-model="serialForm.assemblerId" disabled class="conn-ctrl">
            <el-option v-for="a in assemblerOptions" :key="a.id" :label="a.name" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="解释器">
          <el-select v-model="serialForm.parserId" disabled clearable placeholder="不绑定" class="conn-ctrl">
            <el-option v-for="p in parserOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="serialOpening"
            :disabled="!serialForm.port || selectedPortDisabled"
            @click="submitSerial"
          >{{ canReuseSelectedPort ? '使用' : '打开' }}</el-button>
          <el-button @click="serialDlg.visible = false">取消</el-button>
        </el-form-item>
      </el-form>
    </el-dialog>
  </div>
</template>

<script setup name="Camera">
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  openSerialPort,
  closeSerialPort,
  getDeviceSnapshot
} from '@/api/payload/device'
import {
  startCamera,
  stopCamera,
  getCameraImage,
  getCameraTelecontrolConfig,
  getCameraTelemetryTable,
  assembleCameraTelecontrol,
  sendCameraTelecontrol
} from '@/api/payload/camera'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import CameraImageView from '@/components/Payload/CameraImageView.vue'
import PayloadTransferInfo from '@/components/Payload/PayloadTransferInfo.vue'

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

const serialBaudChoices = [
  { value: 9600, label: '9600' },
  { value: 115200, label: '115200' },
  { value: 921600, label: '921600' },
  { value: 2000000, label: '2000000' }
]
/** 图像串口协议允许的两种波特率 */
const IMAGE_BAUD_RATES = [2000000, 11000000]
const imageBaudChoices = [
  { value: 2000000, label: '2000000(默认)' },
  { value: 11000000, label: '11000000' }
]
const dataBitsOptions = [5, 6, 7, 8]
const stopBitsOptions = [1, 1.5, 2]
const parityOptions = [
  { value: 'N', label: 'NONE' },
  { value: 'E', label: 'EVEN' },
  { value: 'O', label: 'ODD' },
  { value: 'M', label: 'MARK' },
  { value: 'S', label: 'SPACE' }
]
const flowOptions = [
  { value: 'NONE', label: 'NONE' },
  { value: 'XON/XOFF', label: 'XON/XOFF' },
  { value: 'RTS/CTS', label: 'RTS/CTS' },
  { value: 'DTR/DSR', label: 'DTR/DSR' }
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

const serialPorts = ref([])
/** 已打开串口详情：portUpper -> { port, baudrate, dataBits, ... } */
const openedPortMap = ref(new Map())
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

const tmName = ref('')
const tmTableKey = ref('D8')
const tmPages = ref([
  { id: 'D8', key: 'D8', name: '慢遥测(全窗)' },
  { id: 'D9', key: 'D9', name: '快遥测(开窗)' },
])
const tmTs = ref('')
const tmRows = ref([])
const tmDataId = ref(null)
const tmCfgRows = ref([])
/** 遥测配置行 id → 完整定义，供编号列 tooltip */
const tmDefById = ref({})

const xferDeviceId = ref('')
const parserOptions = ref([])
const assemblerOptions = ref([])

const serialDlg = reactive({ visible: false, kind: 'ctrl' })
const serialForm = reactive({
  port: '',
  baudChoice: 2000000,
  baudrate: 2000000,
  dataBits: 8,
  stopBits: 1,
  parity: 'O',
  flowControl: 'NONE',
  assemblerId: 'passthrough',
  parserId: ''
})
const serialOpening = ref(false)
const serialRefreshing = ref(false)

let imageTimer = null
let tmTimer = null
let linkTimer = null
/** 用户主动关闭时跳过断连提示 */
let closingCtrl = false
let closingImage = false

const ctrlDeviceId = computed(() => (ctrlPort.value ? `serial:${ctrlPort.value}` : ''))
const imageDeviceId = computed(() => (imagePort.value ? `serial:${imagePort.value}` : ''))

const xferDevices = computed(() => {
  const list = []
  if (ctrlConnected.value && ctrlDeviceId.value) {
    list.push({ id: ctrlDeviceId.value, label: `控制 ${ctrlPort.value}` })
  }
  if (imageConnected.value && imageDeviceId.value && imageDeviceId.value !== ctrlDeviceId.value) {
    list.push({ id: imageDeviceId.value, label: `图像 ${imagePort.value}` })
  }
  return list
})

function applyOpenedPorts(list) {
  const map = new Map()
  for (const p of list || []) {
    if (p?.alive === false) continue
    const port = String(p?.port || '').trim()
    if (!port) continue
    map.set(port.toUpperCase(), { ...p, port })
  }
  openedPortMap.value = map
}

function normParity(v) {
  const s = String(v || 'N').trim().toUpperCase()
  if (s === 'NONE') return 'N'
  if (s === 'EVEN') return 'E'
  if (s === 'ODD') return 'O'
  if (s === 'MARK') return 'M'
  if (s === 'SPACE') return 'S'
  return s.slice(0, 1) || 'N'
}

function normFlow(v) {
  const s = String(v || 'NONE').trim().toUpperCase().replace(/[\s_-]/g, '')
  if (!s || s === 'NONE' || s === 'NO') return 'NONE'
  if (s.includes('XON')) return 'XON/XOFF'
  if (s.includes('RTS')) return 'RTS/CTS'
  if (s.includes('DTR')) return 'DTR/DSR'
  return s
}

/** 已打开串口的物理参数是否与当前页预设一致（不含解释器/组装器） */
function serialParamsMatch(opened, preset, kind = 'ctrl') {
  if (!opened || !preset) return false
  const baud = Number(opened.baudrate)
  if (!Number.isFinite(baud)) return false
  if (kind === 'image') {
    // 图像串口：波特率须为协议允许的两种之一
    if (!IMAGE_BAUD_RATES.includes(baud)) return false
  } else {
    const needBaud = Number(preset.baudChoice || preset.baudrate)
    if (baud !== needBaud) return false
  }
  if (Number(opened.dataBits) !== Number(preset.dataBits)) return false
  if (Number(opened.stopBits) !== Number(preset.stopBits)) return false
  if (normParity(opened.parity) !== normParity(preset.parity)) return false
  if (normFlow(opened.flowControl) !== normFlow(preset.flowControl)) return false
  return true
}

function currentPreset() {
  return serialDlg.kind === 'image' ? IMAGE_PRESET : CTRL_PRESET
}

const activeBaudChoices = computed(() => {
  if (serialDlg.kind === 'image') return imageBaudChoices
  return serialBaudChoices.filter(b => b.value === CTRL_PRESET.baudChoice)
})

function onBaudChoiceChange(v) {
  const baud = Number(v)
  serialForm.baudChoice = baud
  serialForm.baudrate = baud
}

/** 选中串口后：已连接符合则填入其实参并锁定；未连接则恢复页面对应预设（保留当前可选波特率） */
function applyPortSelection(port, { resetBaud = true } = {}) {
  const preset = currentPreset()
  const opened = getOpenedInfo(port)
  const reusable = serialParamsMatch(opened, preset, serialDlg.kind)
  if (reusable && opened) {
    const baud = Number(opened.baudrate)
    serialForm.baudChoice = baud
    serialForm.baudrate = baud
    serialForm.dataBits = Number(opened.dataBits)
    serialForm.stopBits = Number(opened.stopBits)
    serialForm.parity = normParity(opened.parity)
    serialForm.flowControl = normFlow(opened.flowControl)
    serialForm.assemblerId = preset.assemblerId
    serialForm.parserId = preset.parserId || ''
    return
  }
  if (resetBaud) {
    serialForm.baudChoice = preset.baudChoice
    serialForm.baudrate = preset.baudrate
  } else if (serialDlg.kind === 'image') {
    const cur = Number(serialForm.baudChoice || serialForm.baudrate)
    if (!IMAGE_BAUD_RATES.includes(cur)) {
      serialForm.baudChoice = preset.baudChoice
      serialForm.baudrate = preset.baudrate
    }
  } else {
    serialForm.baudChoice = preset.baudChoice
    serialForm.baudrate = preset.baudrate
  }
  serialForm.dataBits = preset.dataBits
  serialForm.stopBits = preset.stopBits
  serialForm.parity = preset.parity
  serialForm.flowControl = preset.flowControl
  serialForm.assemblerId = preset.assemblerId
  serialForm.parserId = preset.parserId || ''
}

function getOpenedInfo(port) {
  if (!port) return null
  return openedPortMap.value.get(String(port).toUpperCase()) || null
}

const serialPortOptions = computed(() => {
  const preset = currentPreset()
  const kind = serialDlg.kind
  return (serialPorts.value || []).map(p => {
    const port = p?.port || ''
    const base = p?.description ? `${port} (${p.description})` : port
    const opened = getOpenedInfo(port)
    if (!opened) {
      return { port, label: base, disabled: false, reusable: false }
    }
    const match = serialParamsMatch(opened, preset, kind)
    return {
      port,
      label: match ? `${base} - 已连接` : `${base} - 已连接 - 连接参数不符`,
      disabled: !match,
      reusable: match
    }
  })
})

const canReuseSelectedPort = computed(() => {
  const port = serialForm.port
  if (!port) return false
  return serialParamsMatch(getOpenedInfo(port), currentPreset(), serialDlg.kind)
})

/** 已连接且参数符合：锁定物理参数；未连接图像串口才允许改波特率 */
const baudSelectDisabled = computed(() => {
  if (serialOpening.value) return true
  if (canReuseSelectedPort.value) return true
  return serialDlg.kind !== 'image'
})

const selectedPortDisabled = computed(() => {
  const hit = serialPortOptions.value.find(p => p.port === serialForm.port)
  return !!hit?.disabled
})

function ensurePortSelectable() {
  if (!serialForm.port) return
  const hit = serialPortOptions.value.find(p => p.port === serialForm.port)
  if (hit?.disabled) {
    const first = serialPortOptions.value.find(p => !p.disabled)
    serialForm.port = first?.port || ''
    applyPortSelection(serialForm.port)
  }
}

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

function rowsFromCfg(cfgRows) {
  return (cfgRows || []).map(r => ({
    id: r.id || '',
    name: r.name || '',
    value: '',
    show: '',
    unit: r.unit || '',
    hex: ''
  }))
}

function applyTmCfgRows(cfgRows) {
  tmCfgRows.value = cfgRows || []
  const map = {}
  for (const r of tmCfgRows.value) {
    if (r?.id) map[r.id] = r
  }
  tmDefById.value = map
}

function tmCfgJson(id) {
  const cfg = tmDefById.value[id]
  return cfg ? JSON.stringify(cfg, null, 2) : ''
}

function onResolutionUserChange() {
  resolutionUserTouched.value = true
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

function pickDefaultPort(preferred) {
  const options = serialPortOptions.value
  if (preferred && options.some(p => p.port === preferred && !p.disabled)) return preferred
  const firstOk = options.find(p => !p.disabled)
  return firstOk?.port || ''
}

function syncSelectedPort() {
  if (!serialDlg.visible) return
  if (!serialPorts.value.length) {
    serialForm.port = ''
    return
  }
  if (!serialForm.port || !serialPorts.value.some(p => p.port === serialForm.port)) {
    serialForm.port = pickDefaultPort('')
    return
  }
  ensurePortSelectable()
}

async function refreshPorts() {
  serialRefreshing.value = true
  try {
    const res = await getDeviceSnapshot(['serialList', 'serialOpened'])
    serialPorts.value = res.data?.serialList || []
    applyOpenedPorts(res.data?.serialOpened)
    syncSelectedPort()
  } finally {
    serialRefreshing.value = false
  }
}

function applyOptionsFromSnapshot(data) {
  const plist = data?.parsers || []
  if (Array.isArray(plist) && plist.length) {
    parserOptions.value = plist.map(p =>
      typeof p === 'string' ? { id: p, name: p } : { id: p.id || p.parserId, name: p.name || p.id }
    )
  }
  const alist = data?.assemblers || []
  if (Array.isArray(alist) && alist.length) {
    assemblerOptions.value = alist.map(a =>
      typeof a === 'string' ? { id: a, name: a } : { id: a.id || a.assemblerId, name: a.name || a.id }
    )
  }
}

/** 串口弹窗/页初始化：一次快照拉取串口列表 +（按需）解析器/组装器 */
async function loadSerialDialogMeta({ needOptions = true } = {}) {
  serialRefreshing.value = true
  try {
    const parts = ['serialList', 'serialOpened']
    if (needOptions || !parserOptions.value.length || !assemblerOptions.value.length) {
      parts.push('parsers', 'assemblers')
    }
    const res = await getDeviceSnapshot(parts)
    const data = res.data || {}
    serialPorts.value = data.serialList || []
    applyOpenedPorts(data.serialOpened)
    applyOptionsFromSnapshot(data)
    if (!parserOptions.value.length || !assemblerOptions.value.length) {
      parserOptions.value = parserOptions.value.length
        ? parserOptions.value
        : [{ id: 'camera_sc_link41ep', name: '相机SC-LINK41EP(D8)' }]
      assemblerOptions.value = assemblerOptions.value.length
        ? assemblerOptions.value
        : [
            { id: 'passthrough', name: '透传（默认）' },
            { id: 'camera_image_d6', name: '相机图像(D6)' }
          ]
    }
    if (serialDlg.visible) {
      syncSelectedPort()
    }
  } catch {
    if (!parserOptions.value.length) {
      parserOptions.value = [{ id: 'camera_sc_link41ep', name: '相机SC-LINK41EP(D8)' }]
    }
    if (!assemblerOptions.value.length) {
      assemblerOptions.value = [
        { id: 'passthrough', name: '透传（默认）' },
        { id: 'camera_image_d6', name: '相机图像(D6)' }
      ]
    }
  } finally {
    serialRefreshing.value = false
  }
}

function onSerialPortChange(port) {
  applyPortSelection(port)
}

function applyPreset(kind) {
  const preset = kind === 'image' ? IMAGE_PRESET : CTRL_PRESET
  Object.assign(serialForm, preset)
  const preferred =
    kind === 'ctrl' && ctrlPort.value
      ? ctrlPort.value
      : kind === 'image' && imagePort.value
        ? imagePort.value
        : ''
  serialForm.port = pickDefaultPort(preferred)
  applyPortSelection(serialForm.port)
}

function openSerialDialog(kind) {
  serialDlg.kind = kind
  applyPreset(kind)
  serialDlg.visible = true
}

async function onSerialDlgOpened() {
  await loadSerialDialogMeta({ needOptions: !parserOptions.value.length || !assemblerOptions.value.length })
  applyPreset(serialDlg.kind)
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
    resetTmToEmptyTable()
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

function applyConnectedState(port) {
  if (serialDlg.kind === 'ctrl') {
    clearOtherRoleOnPort(port, 'ctrl')
    ctrlPort.value = port
    ctrlConnected.value = true
    xferDeviceId.value = `serial:${port}`
    statusText.value = `控制串口已打开 ${port}`
    refreshTm({ needCfg: true })
  } else {
    clearOtherRoleOnPort(port, 'image')
    imagePort.value = port
    imageConnected.value = true
    xferDeviceId.value = `serial:${port}`
    statusText.value = `图像串口已打开 ${port}`
  }
}

async function submitSerial() {
  if (!serialForm.port || serialOpening.value || selectedPortDisabled.value) return
  serialOpening.value = true
  try {
    const reuse = canReuseSelectedPort.value
    const opened = getOpenedInfo(serialForm.port)
    // 复用已打开串口时必须用其实际波特率，避免与下拉框选择不一致导致后端拒绝
    let baud = Number(serialForm.baudChoice) || serialForm.baudrate
    if (reuse && opened && Number.isFinite(Number(opened.baudrate))) {
      baud = Number(opened.baudrate)
      serialForm.baudChoice = baud
      serialForm.baudrate = baud
    }
    const res = await openSerialPort({
      port: serialForm.port,
      baudrate: baud,
      dataBits: serialForm.dataBits,
      stopBits: serialForm.stopBits,
      parity: serialForm.parity,
      flowControl: serialForm.flowControl,
      parserId: serialForm.parserId || '',
      assemblerId: serialForm.assemblerId || 'passthrough',
      source: serialDlg.kind === 'ctrl' ? SOURCE_CAMERA_CTRL : SOURCE_CAMERA_IMAGE
    })
    applyConnectedState(serialForm.port)
    // 打开图像串口后不自动拉图，由用户点击「图片刷新」
    const reused = reuse || res.data?.status === 'already_open'
    ElMessage.success(reused ? '已使用现有串口并绑定本页参数' : '串口已打开')
    serialDlg.visible = false
    savePrefs()
  } catch (e) {
    ElMessage.error(e?.message || '打开串口失败')
  } finally {
    serialOpening.value = false
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
  if (xferDeviceId.value === `serial:${ctrlPort.value}`) {
    xferDeviceId.value = imageConnected.value && imagePort.value ? `serial:${imagePort.value}` : ''
  }
  statusText.value = offline ? '后端已离线，已清除本页控制串口状态' : '控制串口已关闭'
  if (offline) {
    ElMessage.warning(statusText.value)
  }
  closingCtrl = false
  resetTmToEmptyTable()
  refreshTm({ needCfg: !tmCfgRows.value.length })
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
  if (xferDeviceId.value === `serial:${imagePort.value}`) {
    xferDeviceId.value = ctrlConnected.value && ctrlPort.value ? `serial:${ctrlPort.value}` : ''
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
      if (xferDeviceId.value === `serial:${ctrlPort.value}`) {
        xferDeviceId.value = imageConnected.value && imagePort.value ? `serial:${imagePort.value}` : ''
      }
      resetTmToEmptyTable()
      msgs.push(`控制串口已断开（${ctrlPort.value}）`)
    }
    if (watchImage && !alivePorts.has(String(imagePort.value).toUpperCase())) {
      stopRefresh()
      imageConnected.value = false
      if (xferDeviceId.value === `serial:${imagePort.value}`) {
        xferDeviceId.value = ctrlConnected.value && ctrlPort.value ? `serial:${ctrlPort.value}` : ''
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

async function refreshTm({ needCfg = false } = {}) {
  // 未连接控制串口：只展示配置空表（无当前值/HEX）
  if (!ctrlConnected.value) {
    if (!needCfg && tmRows.value.length) return
    try {
      const res = await getCameraTelemetryTable(null, true, tmTableKey.value)
      const data = res.data || {}
      if (data.name) tmName.value = data.name
      if (data.tableKey) tmTableKey.value = String(data.tableKey).toUpperCase()
      if (Array.isArray(data.pages) && data.pages.length) {
        tmPages.value = data.pages
      }
      if (data.cfg?.row) {
        applyTmCfgRows(data.cfg.row)
        if (data.cfg.name) tmName.value = data.cfg.name
      }
      tmDataId.value = null
      tmTs.value = ''
      // 强制空值/空 HEX，避免残留热数据
      const src = tmCfgRows.value.length
        ? tmCfgRows.value
        : (data.cfg?.row || data.rows || [])
      tmRows.value = (src || []).filter(r => r?.id).map(r => ({
        id: r.id || '',
        name: r.name || '',
        value: '',
        show: '',
        unit: r.unit || '',
        hex: ''
      }))
    } catch {
      resetTmToEmptyTable()
    }
    return
  }
  try {
    const res = await getCameraTelemetryTable(tmDataId.value, needCfg, tmTableKey.value)
    const data = res.data || {}
    if (data.name) tmName.value = data.name
    if (data.ts) tmTs.value = data.ts
    if (data.tableKey) tmTableKey.value = String(data.tableKey).toUpperCase()
    if (needCfg && Array.isArray(data.pages) && data.pages.length) {
      tmPages.value = data.pages
    }
    if (needCfg && data.cfg?.row) {
      applyTmCfgRows(data.cfg.row)
      if (data.cfg.name) tmName.value = data.cfg.name
    }
    if (data.changed === false) return
    tmDataId.value = data.dataId ?? null
    const rows = data.rows || []
    tmRows.value = rows.length ? rows : rowsFromCfg(tmCfgRows.value)
    syncResolutionFromTm(tmRows.value)
  } catch {
    if (!tmRows.value.length && tmCfgRows.value.length) {
      tmRows.value = rowsFromCfg(tmCfgRows.value)
    }
  }
}

function resetTmToEmptyTable() {
  tmDataId.value = null
  tmTs.value = ''
  if (tmCfgRows.value.length) {
    tmRows.value = rowsFromCfg(tmCfgRows.value)
  } else {
    tmRows.value = []
  }
}

async function onTmTableChange() {
  tmDataId.value = null
  tmRows.value = []
  tmCfgRows.value = []
  tmDefById.value = {}
  tmTs.value = ''
  await refreshTm({ needCfg: true })
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
    applyOpenedPorts(opened)
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
        xferDeviceId.value = param
      } else if (source === SOURCE_CAMERA_IMAGE) {
        imagePort.value = port
        imageConnected.value = true
        if (!xferDeviceId.value) xferDeviceId.value = param
      }
    }
    savePrefs()
    // 恢复图像串口连接后不自动刷新，用户手动点「图片刷新」
    if (ctrlConnected.value) {
      await refreshTm({ needCfg: true })
    }
  } catch {
    /* ignore */
  }
}

onMounted(async () => {
  loadPrefs()
  await loadSerialDialogMeta({ needOptions: true })
  await restoreCameraLinks()
  await loadTcConfig()
  // 未连接时也先展示遥测配置空表（编号/名称/单位有值，当前值与 HEX 为空）
  await refreshTm({ needCfg: true })
  tmTimer = setInterval(() => {
    if (ctrlConnected.value) refreshTm({ needCfg: false })
  }, 1000)
  linkTimer = setInterval(checkLinkStatus, 2000)
})

onUnmounted(() => {
  stopRefresh()
  if (tmTimer) clearInterval(tmTimer)
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
.filter-input {
  margin-left: auto;
  width: 220px;
}
.tm-ts {
  margin-left: auto;
  font-weight: 400;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.tm-head-left {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.tm-key-select {
  width: 140px;
}
.tm-key-tag {
  font-weight: 400;
  color: var(--el-text-color-secondary);
}
.panel-body {
  flex: 1;
  min-height: 0;
}
.panel-tm :deep(.el-table) {
  flex: 1;
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
.conn-form .conn-ctrl {
  width: 280px;
}
.port-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.port-row .conn-ctrl {
  width: 220px;
}
.tm-id-cell {
  cursor: help;
}
</style>

<!-- 与遥测表页共用：编号配置 tooltip -->
<style>
.tm-cfg-tooltip .tm-cfg-json {
  margin: 0;
  padding: 0;
  max-height: 60vh;
  overflow: auto;
  white-space: pre;
  color: inherit;
  font-family: var(--el-font-family-mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace);
  font-size: 12px;
  line-height: 1.45;
}
</style>
