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
            :disabled="opening"
            class="conn-ctrl"
          >
            <el-option v-for="a in localAddresses" :key="a" :label="a" :value="a" />
          </el-select>
          <el-button
            type="primary"
            plain
            icon="Refresh"
            :loading="refreshing"
            :disabled="opening"
            @click="refreshAddresses"
          >
            刷新
          </el-button>
        </div>
      </el-form-item>
      <el-form-item label="本机端口">
        <el-input-number
          v-model="form.localPort"
          :disabled="opening"
          :min="1"
          :max="65535"
          class="conn-ctrl"
          controls-position="right"
        />
      </el-form-item>
      <el-form-item>
        <template #label>
          组装器
          <el-tooltip :content="ASSEMBLER_TIP" placement="top">
            <el-icon class="label-tip"><question-filled /></el-icon>
          </el-tooltip>
        </template>
        <el-select v-model="form.assemblerId" clearable placeholder="默认透传" class="conn-ctrl" :disabled="opening">
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
        <el-select v-model="form.parserId" clearable placeholder="请选择解释器" class="conn-ctrl" :disabled="opening">
          <el-option v-for="p in parserOptions" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <div v-if="showBindingTips" class="field-tip">不绑定则不解析数据</div>
      </el-form-item>
      <el-form-item>
        <el-button
          type="primary"
          :loading="opening"
          :disabled="!form.localHost || !form.localPort"
          @click="submit"
        >
          打开
        </el-button>
        <el-button @click="onVisibleChange(false)">取消</el-button>
      </el-form-item>
    </el-form>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listLocalAddresses, listParsers, listAssemblers, openNet } from '@/api/payload/device'
import { setActiveDevice } from '@/utils/deviceSnapshotCache'
import { ASSEMBLER_TIP, PARSER_TIP } from '@/utils/pipelineTips'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '新建 UDP 连接' },
  source: { type: String, default: 'home' },
  prefsKey: { type: String, default: 'payload:control:udpPrefs' },
  showBindingTips: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelValue', 'success'])

const form = reactive({
  localHost: '0.0.0.0',
  localPort: 9000,
  assemblerId: 'passthrough',
  parserId: ''
})

const opening = ref(false)
const refreshing = ref(false)
const localAddresses = ref(['0.0.0.0', '127.0.0.1'])
const parserOptions = ref([])
const assemblerOptions = ref([])

function onVisibleChange(v) {
  emit('update:modelValue', v)
}

function readPrefs() {
  try {
    const raw = localStorage.getItem(props.prefsKey)
    if (!raw) return null
    const obj = JSON.parse(raw)
    return obj && typeof obj === 'object' ? obj : null
  } catch {
    return null
  }
}

function writePrefs(data) {
  try {
    localStorage.setItem(props.prefsKey, JSON.stringify({ ...(readPrefs() || {}), ...data }))
  } catch {
    /* ignore */
  }
}

function applyPrefs() {
  const p = readPrefs()
  if (!p) return
  if (p.localHost) form.localHost = String(p.localHost)
  if (p.localPort != null) {
    const port = Number(p.localPort)
    form.localPort = Number.isFinite(port) && port > 0 ? port : 9000
  }
  if (p.parserId !== undefined) form.parserId = p.parserId || ''
  if (p.assemblerId !== undefined) form.assemblerId = p.assemblerId || 'passthrough'
}

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
    parserOptions.value = [{ id: 'tm_can_yc', name: 'CAN遥测复合帧' }]
  }
}

async function loadAssemblers() {
  try {
    const res = await listAssemblers()
    const list = res.data?.assemblers || res.data || []
    assemblerOptions.value = Array.isArray(list)
      ? list.map(a =>
          typeof a === 'string'
            ? { id: a, name: a }
            : { id: a.id || a.assemblerId, name: a.name || a.label || a.id || a.assemblerId }
        )
      : []
  } catch {
    assemblerOptions.value = [
      { id: 'passthrough', name: '透传（默认）' },
      { id: 'eng_tm_subpkt', name: '工程遥测子包组装' }
    ]
  }
}

async function refreshAddresses() {
  refreshing.value = true
  try {
    const res = await listLocalAddresses()
    const list = res.data || []
    localAddresses.value = list.length ? list : ['0.0.0.0', '127.0.0.1']
    if (!localAddresses.value.includes(form.localHost)) {
      form.localHost = localAddresses.value[0]
    }
  } finally {
    refreshing.value = false
  }
}

async function onOpened() {
  applyPrefs()
  await Promise.all([loadParsers(), loadAssemblers(), refreshAddresses()])
}

async function submit() {
  if (!form.localHost || !form.localPort || opening.value) return
  opening.value = true
  try {
    const res = await openNet({
      proto: 'udp',
      localHost: form.localHost,
      localPort: form.localPort,
      parserId: form.parserId || '',
      assemblerId: form.assemblerId || 'passthrough',
      source: props.source
    })
    const deviceId = res.data?.deviceId
    if (deviceId) setActiveDevice('udp', deviceId)
    writePrefs({
      localHost: form.localHost,
      localPort: form.localPort,
      parserId: form.parserId || '',
      assemblerId: form.assemblerId || 'passthrough'
    })
    if (res.data?.status === 'already_open') {
      ElMessage.error('设备已打开')
      return
    }
    ElMessage.success('UDP 已打开')
    onVisibleChange(false)
    emit('success', { response: res, deviceId })
  } finally {
    opening.value = false
  }
}

watch(
  () => props.modelValue,
  v => {
    if (!v) return
    applyPrefs()
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
