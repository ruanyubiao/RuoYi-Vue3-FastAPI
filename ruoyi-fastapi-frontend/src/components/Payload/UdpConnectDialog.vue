<template>
  <el-dialog
    :model-value="modelValue"
    width="520px"
    destroy-on-close
    class="udp-connect-dialog"
    @update:model-value="onVisibleChange"
    @opened="onOpened"
  >
    <template #header>
      <span class="dlg-title">{{ title }}</span>
    </template>
    <el-form label-width="100px" class="conn-form">
      <el-form-item label="本机地址">
        <div class="port-row">
          <el-select
            v-model="form.localHost"
            filterable
            allow-create
            default-first-option
            :disabled="opening || fieldsLocked"
            class="conn-ctrl"
          >
            <el-option v-for="a in localAddresses" :key="a" :label="a" :value="a" />
          </el-select>
          <el-button
            type="primary"
            plain
            icon="Refresh"
            :loading="refreshing"
            :disabled="opening || fieldsLocked"
            @click="refreshAddresses"
          >
            刷新
          </el-button>
        </div>
      </el-form-item>
      <el-form-item label="本机端口">
        <el-input-number
          v-model="form.localPort"
          :disabled="opening || fieldsLocked"
          :min="1"
          :max="65535"
          class="conn-ctrl"
          controls-position="right"
        />
      </el-form-item>
      <!-- 远程对端仅作默认发送目标，不参与 deviceId（仍为本机 udp:host:port） -->
      <el-form-item label="远程地址">
        <el-input
          v-model="form.remoteHost"
          :disabled="opening || fieldsLocked"
          clearable
          placeholder="可空"
          class="conn-ctrl"
        />
      </el-form-item>
      <el-form-item label="远程端口">
        <el-input-number
          v-model="form.remotePort"
          :disabled="opening || fieldsLocked"
          :min="0"
          :max="65535"
          class="conn-ctrl"
          controls-position="right"
        />
        <div class="field-tip">可只填远程地址，远程端口 0 表示不指定；<br />填了非 0 端口（1–65535）则必须同时有地址</div>
      </el-form-item>
      <el-form-item>
        <template #label>
          组装器
          <el-tooltip :content="ASSEMBLER_TIP" placement="top">
            <el-icon class="label-tip"><question-filled /></el-icon>
          </el-tooltip>
        </template>
        <el-select
          v-model="form.assemblerId"
          placeholder="默认透传"
          class="conn-ctrl"
          :clearable="!assemblerLocked"
          :disabled="opening || assemblerLocked"
        >
          <el-option v-for="a in assemblerOptions" :key="a.id" :label="a.name" :value="a.id" />
        </el-select>
        <div v-if="showBindingTips" class="field-tip">拆分包需选对应组装器；默认透传</div>
      </el-form-item>
      <el-form-item>
        <template #label>
          解释器
          <el-tooltip :content="PARSER_TIP" placement="top">
            <el-icon class="label-tip"><question-filled /></el-icon>
          </el-tooltip>
        </template>
        <el-select
          v-model="form.parserId"
          placeholder="请选择解释器"
          class="conn-ctrl"
          :clearable="!parserLocked"
          :disabled="opening || parserLocked"
        >
          <el-option v-for="p in parserOptions" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <div v-if="showBindingTips" class="field-tip">不绑定则不解析数据</div>
      </el-form-item>
      <el-form-item>
        <el-button
          type="primary"
          :loading="opening"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ confirmLabel }}
        </el-button>
        <el-button @click="onVisibleChange(false)">取消</el-button>
      </el-form-item>
    </el-form>
  </el-dialog>
</template>

<script setup>
/**
 * 新建 UDP 连接。
 * 远程地址、端口均可空（端口 0 = 未指定）。可只填地址不填端口。
 * 填了非 0 端口则必须同时有地址。deviceId 只含本机，远程写入采集默认发送对端。
 *
 * 本机地址+端口已有存活连接且 allowReuse 时按钮为「使用」，成功提示复用并绑定本页参数；
 * 否则「打开」。allowReuse=false（首页）时已占用口保持「打开」并禁用。
 *
 * 传入 preset（页面绑定 cfg_device_connect 的 key）时：
 * 本机/远程锁定；assemblerId/parserId 仅当配置非空时锁定。首页不传 preset，不限制。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listLocalAddresses, listNetOpened, openNet } from '@/api/payload/device'
import { setActiveDevice } from '@/utils/deviceSnapshotCache'
import { isConnectCfgFieldLocked, isConnectCfgParserLocked, udpRemotePeerError } from '@/utils/deviceConnectDefaults'
import { ASSEMBLER_TIP, PARSER_TIP } from '@/utils/pipelineTips'
import {
  ASSEMBLER_PASSTHROUGH,
  FALLBACK_ASSEMBLERS_UDP,
  FALLBACK_PARSERS_CAN
} from '@/utils/pipelineIds'
import {
  confirmOpenLabel,
  isAlreadyOpen,
  loadAssemblerOptions,
  loadParserOptions,
  reuseSuccessMessage
} from '@/utils/useConnectPipelineOptions'
import cache from '@/plugins/cache'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '新建 UDP 连接' },
  source: { type: String, default: 'home' },
  prefsKey: { type: String, default: 'payload:control:udpPrefs' },
  showBindingTips: { type: Boolean, default: true },
  /** cfg_device_connect 预填；有值则锁死本机/远程；assemblerId/parserId 非空才锁对应下拉 */
  preset: { type: Object, default: null },
  /** false=禁止复用已开本机地址+端口（首页新建）；确认键保持「打开」并禁用 */
  allowReuse: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelValue', 'success'])

const form = reactive({
  localHost: '0.0.0.0',
  localPort: 9000,
  remoteHost: '',
  remotePort: 0,
  assemblerId: ASSEMBLER_PASSTHROUGH,
  parserId: '',
  fullDuplex: true
})

const opening = ref(false)
const refreshing = ref(false)
const localAddresses = ref(['0.0.0.0', '127.0.0.1'])
const parserOptions = ref([])
const assemblerOptions = ref([])
/** 已打开的网口，用于判断本机地址+端口是否可复用 */
const netOpened = ref([])

/** 本机地址+端口已有存活 UDP */
const isExistingOpen = computed(() => {
  const host = String(form.localHost || '').trim()
  const port = Number(form.localPort)
  if (!host || !Number.isFinite(port) || port <= 0) return false
  return netOpened.value.some(d => {
    if (d?.alive === false) return false
    const proto = String(d.proto || 'udp').toLowerCase()
    if (proto !== 'udp') return false
    return String(d.localHost || '').trim() === host && Number(d.localPort) === port
  })
})
/** 已开且允许复用 → 按钮「使用」；否则「打开」 */
const canReuseExisting = computed(() => props.allowReuse && isExistingOpen.value)
const confirmLabel = computed(() => confirmOpenLabel(canReuseExisting.value))
const canSubmit = computed(() => {
  if (!form.localHost || !form.localPort) return false
  // 首页禁止复用：已占用本机口时禁用「打开」
  if (!props.allowReuse && isExistingOpen.value) return false
  return true
})
/** 绑定了 cfg key（有 preset）则锁本机/远程；首页无 preset 可改 */
const fieldsLocked = computed(() => !!(props.preset && typeof props.preset === 'object'))
/** assemblerId/parserId 仅当 cfg 字段非空才锁；空字符串可改 */
const assemblerLocked = computed(() => {
  if (!fieldsLocked.value) return false
  if (typeof props.preset.lockAssembler === 'boolean') return props.preset.lockAssembler
  return isConnectCfgFieldLocked(props.preset?.assemblerId)
})
const parserLocked = computed(() => {
  if (!fieldsLocked.value) return false
  if (typeof props.preset.lockParser === 'boolean') return props.preset.lockParser
  return isConnectCfgParserLocked(props.preset?.parserId)
})

function onVisibleChange(v) {
  emit('update:modelValue', v)
}

function readPrefs() {
  if (!props.prefsKey) return null
  const obj = cache.local.getJSON(props.prefsKey)
  return obj && typeof obj === 'object' ? obj : null
}

function writePrefs(data) {
  if (!props.prefsKey) return
  cache.local.setJSON(props.prefsKey, data)
}

/** 从 cfg 预设灌入；锁定字段以预设为准，可编辑字段仍可被 prefs 覆盖。 */
function applyPreset() {
  const p = props.preset
  if (!p || typeof p !== 'object') return
  if (p.localHost) form.localHost = String(p.localHost)
  if (p.localPort != null) {
    const port = Number(p.localPort)
    if (Number.isFinite(port) && port > 0) form.localPort = port
  }
  if (p.remoteHost != null) form.remoteHost = String(p.remoteHost)
  if (p.remotePort != null) {
    const rp = Number(p.remotePort)
    form.remotePort = Number.isFinite(rp) && rp >= 0 ? rp : 0
  }
  if (p.assemblerId !== undefined) form.assemblerId = p.assemblerId || ASSEMBLER_PASSTHROUGH
  if (p.parserId !== undefined) form.parserId = p.parserId || ''
  if (p.fullDuplex != null) form.fullDuplex = p.fullDuplex === true
}

function applyPrefs() {
  const p = readPrefs()
  if (!p) return
  // 绑定 cfg key 时不读本机/远程历史，避免地检页被首页调试值改掉
  if (!fieldsLocked.value && p.localHost) form.localHost = String(p.localHost)
  if (!fieldsLocked.value && p.localPort != null) {
    const port = Number(p.localPort)
    form.localPort = Number.isFinite(port) && port > 0 ? port : 9000
  }
  if (!fieldsLocked.value && p.remoteHost != null) form.remoteHost = String(p.remoteHost)
  if (!fieldsLocked.value && p.remotePort != null) {
    const rp = Number(p.remotePort)
    form.remotePort = Number.isFinite(rp) && rp >= 0 ? rp : 0
  }
  if (!parserLocked.value && p.parserId !== undefined) form.parserId = p.parserId || ''
  if (!assemblerLocked.value && p.assemblerId !== undefined) form.assemblerId = p.assemblerId || ASSEMBLER_PASSTHROUGH
}

function remoteValidationError() {
  return udpRemotePeerError(form.remoteHost, form.remotePort)
}

async function loadPipelineLists() {
  const [parsers, assemblers] = await Promise.all([
    loadParserOptions(FALLBACK_PARSERS_CAN),
    loadAssemblerOptions('udp', FALLBACK_ASSEMBLERS_UDP)
  ])
  parserOptions.value = parsers
  assemblerOptions.value = assemblers
}

async function refreshAddresses() {
  refreshing.value = true
  try {
    const res = await listLocalAddresses()
    const list = res.data || []
    localAddresses.value = list.length ? list : ['0.0.0.0', '127.0.0.1']
    if (fieldsLocked.value) return
    if (!localAddresses.value.includes(form.localHost)) {
      form.localHost = localAddresses.value[0]
    }
  } finally {
    refreshing.value = false
  }
}

async function refreshOpenedNets() {
  try {
    const res = await listNetOpened()
    const list = res.data || []
    netOpened.value = Array.isArray(list) ? list : []
  } catch {
    netOpened.value = []
  }
}

async function onOpened() {
  applyPreset()
  applyPrefs()
  applyPreset()
  await Promise.all([loadPipelineLists(), refreshAddresses(), refreshOpenedNets()])
}

async function submit() {
  if (!form.localHost || !form.localPort || opening.value) return
  const remoteErr = remoteValidationError()
  if (remoteErr) {
    ElMessage.warning(remoteErr)
    return
  }
  opening.value = true
  try {
    const remoteHost = String(form.remoteHost || '').trim()
    const remotePort = Number(form.remotePort)
    const res = await openNet({
      proto: 'udp',
      localHost: form.localHost,
      localPort: form.localPort,
      remoteHost,
      remotePort,
      parserId: form.parserId || '',
      assemblerId: form.assemblerId || ASSEMBLER_PASSTHROUGH,
      source: props.source,
      fullDuplex: form.fullDuplex !== false
    })
    const deviceId = res.data?.deviceId
    if (deviceId) setActiveDevice('udp', deviceId)
    writePrefs({
      localHost: form.localHost,
      localPort: form.localPort,
      remoteHost,
      remotePort,
      parserId: form.parserId || '',
      assemblerId: form.assemblerId || ASSEMBLER_PASSTHROUGH
    })
    const reused = isAlreadyOpen(res)
    ElMessage.success(reused ? reuseSuccessMessage('udp') : 'UDP 已打开')
    onVisibleChange(false)
    emit('success', {
      response: res,
      deviceId,
      reused,
      localHost: form.localHost,
      localPort: form.localPort,
      remoteHost,
      remotePort
    })
  } finally {
    opening.value = false
  }
}

watch(
  () => props.modelValue,
  v => {
    if (!v) return
    applyPreset()
    applyPrefs()
    applyPreset()
  }
)
</script>

<style scoped>
.dlg-title {
  display: block;
  padding-left: 0;
  font-size: var(--el-dialog-title-font-size, 16px);
  line-height: 1.5;
  color: var(--el-text-color-primary);
}
.port-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.conn-form :deep(.el-form-item__content) {
  flex-wrap: wrap;
}
.conn-ctrl {
  width: 240px !important;
}
.conn-ctrl.el-input-number :deep(.el-input__inner) {
  text-align: left;
}
.conn-ctrl :deep(.el-select__selected-item),
.conn-ctrl :deep(.el-select__placeholder) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.field-tip {
  width: 100%;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
}
.label-tip {
  margin-left: 4px;
  vertical-align: middle;
  cursor: help;
  color: var(--el-text-color-secondary);
}
</style>

<style>
.udp-connect-dialog.el-dialog .el-dialog__header {
  padding: 16px 20px 8px;
  margin-right: 0;
}
.udp-connect-dialog.el-dialog .el-dialog__body {
  padding: 8px 20px 20px;
}
.udp-connect-dialog.el-dialog .el-dialog__headerbtn {
  top: 16px;
  right: 16px;
}
</style>
