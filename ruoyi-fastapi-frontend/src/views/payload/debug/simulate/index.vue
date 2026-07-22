<template>
  <div class="app-container">
    <el-card shadow="never" class="block-card">
      <template #header><span>通用数据发送模拟</span></template>
      <el-form label-width="120px" class="dev-form dev-form-full">
        <el-form-item label="帧组装类型">
          <el-select v-model="pipeAssemblerId" placeholder="选择组装器" style="width: 320px">
            <el-option
              v-for="a in assemblerOptions"
              :key="a.id"
              :label="a.name"
              :value="a.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="帧解析类型">
          <el-select v-model="pipeParserId" placeholder="选择解析器" style="width: 320px">
            <el-option
              v-for="p in parserOptions"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="Hex 文本" class="hex-form-item">
          <el-input
            v-model="pipeHexText"
            type="textarea"
            :rows="4"
            placeholder="输入 Hex 文本（空格可选；可为粘包多帧）"
            class="hex-input hex-input-full"
          />
        </el-form-item>
        <el-form-item label=" ">
          <el-button
            type="primary"
            class="action-btn"
            :loading="pipeSending"
            :disabled="pipeSending"
            @click="handlePipeSend"
            v-hasPermi="['payload:devtest:view']"
          >
            发送
          </el-button>
          <el-button :disabled="pipeSending" @click="pipeHexText = ''">清空</el-button>
        </el-form-item>
      </el-form>
      <div class="result-slot">
        <el-alert
          v-if="pipeLastResult"
          :title="pipeResultTitle"
          type="success"
          show-icon
          :closable="false"
          class="result-alert"
        />
      </div>
      <div class="hint">
        说明：先经组装器还原完整载荷，再交给解析器写入 Redis（来源 http:devtest）。例：CAN 遥测选「透传」+「CAN遥测复合帧」；LVDS 工程帧选「工程遥测子包(LVDS)」+「CAN遥测复合帧」。可在「遥测」菜单查看结果。
      </div>
    </el-card>

    <el-card shadow="never" class="block-card">
      <template #header><span>CAN遥测复合帧数据模拟</span></template>
      <el-form label-width="110px" class="dev-form dev-form-full">
        <el-form-item label="CAN遥测数据" class="hex-form-item">
          <el-input
            v-model="hexText"
            type="textarea"
            :rows="4"
            :disabled="simulating"
            placeholder="输入CAN遥测数据（完整复合帧 HEX，空格可选）"
            class="hex-input hex-input-full"
          />
        </el-form-item>
        <el-form-item label=" ">
          <el-button
            type="primary"
            class="action-btn"
            :loading="manualSending"
            :disabled="simulating"
            @click="handleSend"
            v-hasPermi="['payload:devtest:view']"
          >
            发送
          </el-button>
          <el-button
            class="action-btn"
            :type="simulating ? 'danger' : 'success'"
            @click="toggleSimulate"
            v-hasPermi="['payload:devtest:view']"
          >
            {{ simulating ? '停止模拟' : '开始模拟' }}
          </el-button>
          <el-button :disabled="simulating" @click="fillSample">填入样例</el-button>
          <el-button :disabled="simulating" @click="hexText = ''">清空</el-button>
        </el-form-item>
        <el-form-item v-if="simulating" label="模拟状态">
          <span class="sim-status">
            索引4: <strong>{{ simSnapshot.b4 }}</strong>
            · 索引5: <strong>{{ simSnapshot.b5 }}</strong>
            · 索引6: <strong>{{ simSnapshot.b6 }}</strong>
            · 已发送 {{ simSendCount }} 次
          </span>
        </el-form-item>
      </el-form>
      <div class="result-slot">
        <el-alert
          v-if="lastResult"
          :title="`已写入 Redis · 类型 0x${lastResult.dataType} · ${lastResult.name || ''} · 字段 ${lastResult.fieldCount} · ${lastResult.ts}`"
          type="success"
          show-icon
          :closable="false"
          class="result-alert"
        />
      </div>
      <div class="hint">
        说明：此处模拟 CAN 库多帧组包后的完整遥测应答复合帧（模拟源 http:devtest）。发送后经校验/解析写入 Redis，可在「遥测」菜单查看。
      </div>
    </el-card>
  </div>
</template>

<script setup name="DevTest">
import { ElMessage } from 'element-plus'
import { listAssemblers, listParsers } from '@/api/payload/device'
import { injectCanYcTest, injectPipelineTest } from '@/api/payload/telemetry'

const SAMPLE_HEX =
  '00 BF 3A FF 33 00 00 00 00 00 00 00 00 00 45 00 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2 05 97 00 81 00 00 00 02 11 01 C8 0C B1 42 70 00 00 3F 2D 74 BE 44 C3 61 9A 41 6E BF 80 00 00 6D C3 80 26 00 00 55 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 02 00 21 1F AA AA AA AA 00 00 00 00 00 00 30 FF 0C 00 FC 00 00 10 00 00 00 00 00 00 03 00 CC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 4C'

const PREFS_KEY = 'payload:debug:simulate:prefs'

function readPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function writePrefs(data) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(data))
  } catch {
    /* quota / private mode */
  }
}

const cachedPrefs = readPrefs() || {}

const hexText = ref(typeof cachedPrefs.hexText === 'string' ? cachedPrefs.hexText : '')
const manualSending = ref(false)
const lastResult = ref(null)
const simulating = ref(false)
const simSendCount = ref(0)
const simSnapshot = ref({ b4: 0, b5: 0, b6: 0 })

const assemblerOptions = ref([])
const parserOptions = ref([])
const pipeAssemblerId = ref(cachedPrefs.pipeAssemblerId || 'passthrough')
const pipeParserId = ref(cachedPrefs.pipeParserId || 'tm_can_yc')
const pipeHexText = ref(typeof cachedPrefs.pipeHexText === 'string' ? cachedPrefs.pipeHexText : '')
const pipeSending = ref(false)
const pipeLastResult = ref(null)

const pipeResultTitle = computed(() => {
  const r = pipeLastResult.value
  if (!r) return ''
  return (
    `已写入 Redis · 组装 ${r.assembledCount || 0} · 解析 ${r.parsedCount || 0}` +
    ` · 类型 0x${r.dataType || ''} · ${r.name || ''} · 字段 ${r.fieldCount ?? '-'} · ${r.ts || ''}`
  )
})

let simTimer = null
let frameBytes = null

function parseHex(text) {
  const cleaned = (text || '').replace(/\s+/g, '')
  if (!cleaned) throw new Error('HEX 为空')
  if (cleaned.length % 2) throw new Error('HEX 长度必须为偶数')
  if (!/^[0-9a-fA-F]+$/.test(cleaned)) throw new Error('HEX 含非法字符')
  const bytes = new Uint8Array(cleaned.length / 2)
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16)
  }
  return bytes
}

function formatHex(bytes) {
  return Array.from(bytes)
    .map(b => b.toString(16).toUpperCase().padStart(2, '0'))
    .join(' ')
}

function checksumIndex(bytes) {
  if (bytes.length < 5) throw new Error('帧过短')
  const dataLen = (bytes[0] << 8) | bytes[1]
  const idx = dataLen + 2
  if (idx >= bytes.length) throw new Error(`校验和位置越界: ${idx}`)
  return idx
}

function recalcChecksum(bytes) {
  const idx = checksumIndex(bytes)
  let sum = 0
  for (let i = 0; i < idx; i++) sum += bytes[i]
  bytes[idx] = sum & 0xff
  return bytes
}

function loadFrameFromHex(text) {
  const bytes = parseHex(text)
  checksumIndex(bytes)
  return bytes
}

function readU16BE(bytes, off) {
  return (bytes[off] << 8) | bytes[off + 1]
}

function writeU16BE(bytes, off, val) {
  bytes[off] = (val >> 8) & 0xff
  bytes[off + 1] = val & 0xff
}

function readU32BE(bytes, off) {
  return (
    ((bytes[off] << 24) | (bytes[off + 1] << 16) | (bytes[off + 2] << 8) | bytes[off + 3]) >>> 0
  )
}

function writeU32BE(bytes, off, val) {
  bytes[off] = (val >> 24) & 0xff
  bytes[off + 1] = (val >> 16) & 0xff
  bytes[off + 2] = (val >> 8) & 0xff
  bytes[off + 3] = val & 0xff
}

function incrementSimFields(bytes) {
  if (bytes.length < 15) throw new Error('帧长度不足，无法递增索引4~14')
  bytes[4] = (bytes[4] + 1) & 0xff
  bytes[5] = (bytes[5] + 1) & 0xff
  bytes[6] = (bytes[6] + 1) & 0xff
  writeU16BE(bytes, 7, (readU16BE(bytes, 7) + 1) & 0xffff)
  writeU16BE(bytes, 9, (readU16BE(bytes, 9) + 1) & 0xffff)
  writeU32BE(bytes, 11, (readU32BE(bytes, 11) + 1) >>> 0)
  recalcChecksum(bytes)
  return bytes
}

function fillSample() {
  hexText.value = SAMPLE_HEX
}

async function loadPipeOptions() {
  try {
    const [aRes, pRes] = await Promise.all([listAssemblers(), listParsers()])
    const aList = aRes.data?.assemblers || aRes.data || []
    assemblerOptions.value = Array.isArray(aList)
      ? aList.map(a =>
          typeof a === 'string'
            ? { id: a, name: a }
            : { id: a.id || a.assemblerId, name: a.name || a.label || a.id || a.assemblerId }
        )
      : []
    const pList = pRes.data?.parsers || pRes.data || []
    parserOptions.value = Array.isArray(pList)
      ? pList.map(p =>
          typeof p === 'string'
            ? { id: p, name: p }
            : { id: p.id || p.parserId, name: p.name || p.label || p.id || p.parserId }
        )
      : []
  } catch {
    assemblerOptions.value = [
      { id: 'passthrough', name: '透传（默认）' },
      { id: 'eng_tm_subpkt', name: '工程遥测子包(LVDS)' }
    ]
    parserOptions.value = [{ id: 'tm_can_yc', name: 'CAN遥测复合帧' }]
  }
  if (!assemblerOptions.value.some(a => a.id === pipeAssemblerId.value)) {
    pipeAssemblerId.value = assemblerOptions.value[0]?.id || 'passthrough'
  }
  if (!parserOptions.value.some(p => p.id === pipeParserId.value)) {
    pipeParserId.value = parserOptions.value[0]?.id || 'tm_can_yc'
  }
}

async function handlePipeSend() {
  if (!pipeHexText.value.trim()) {
    ElMessage.warning('请输入 Hex 文本')
    return
  }
  if (!pipeAssemblerId.value) {
    ElMessage.warning('请选择帧组装类型')
    return
  }
  if (!pipeParserId.value) {
    ElMessage.warning('请选择帧解析类型')
    return
  }
  try {
    parseHex(pipeHexText.value)
  } catch (e) {
    ElMessage.error(e.message || 'HEX 无效')
    return
  }
  pipeSending.value = true
  try {
    const res = await injectPipelineTest({
      hex: pipeHexText.value,
      assemblerId: pipeAssemblerId.value,
      parserId: pipeParserId.value
    })
    pipeLastResult.value = res.data || {}
    ElMessage.success(res.msg || '注入成功')
  } catch (e) {
    ElMessage.error(e.message || e.msg || '发送失败')
  } finally {
    pipeSending.value = false
  }
}

async function sendFrame(bytes, { quiet = false } = {}) {
  if (!quiet) manualSending.value = true
  try {
    const res = await injectCanYcTest({ hex: formatHex(bytes) })
    lastResult.value = res.data || {}
    if (!quiet) ElMessage.success(res.msg || '注入成功')
    return res
  } finally {
    if (!quiet) manualSending.value = false
  }
}

async function handleSend() {
  if (!hexText.value.trim()) {
    ElMessage.warning('请输入 CAN 遥测数据')
    return
  }
  try {
    const bytes = loadFrameFromHex(hexText.value)
    recalcChecksum(bytes)
    hexText.value = formatHex(bytes)
    await sendFrame(bytes)
  } catch (e) {
    ElMessage.error(e.message || '发送失败')
  }
}

function syncSimSnapshot(bytes) {
  simSnapshot.value = { b4: bytes[4], b5: bytes[5], b6: bytes[6] }
}

async function simTick() {
  if (!frameBytes) return
  try {
    incrementSimFields(frameBytes)
    syncSimSnapshot(frameBytes)
    hexText.value = formatHex(frameBytes)
    simSendCount.value += 1
    await sendFrame(frameBytes, { quiet: true })
  } catch (e) {
    stopSimulate()
    ElMessage.error(e.message || '模拟发送失败')
  }
}

function startSimulate() {
  try {
    if (!hexText.value.trim()) hexText.value = SAMPLE_HEX
    frameBytes = loadFrameFromHex(hexText.value)
    recalcChecksum(frameBytes)
    syncSimSnapshot(frameBytes)
    hexText.value = formatHex(frameBytes)
    simSendCount.value = 0
    simulating.value = true
    simTick()
    simTimer = setInterval(simTick, 1000)
  } catch (e) {
    frameBytes = null
    ElMessage.error(e.message || '无法启动模拟')
  }
}

function stopSimulate() {
  simulating.value = false
  if (simTimer) {
    clearInterval(simTimer)
    simTimer = null
  }
}

function persistPrefs() {
  writePrefs({
    pipeAssemblerId: pipeAssemblerId.value,
    pipeParserId: pipeParserId.value,
    pipeHexText: pipeHexText.value,
    hexText: hexText.value
  })
}

watch([pipeAssemblerId, pipeParserId, pipeHexText, hexText], persistPrefs)

function toggleSimulate() {
  if (simulating.value) stopSimulate()
  else startSimulate()
}

onMounted(loadPipeOptions)
onUnmounted(stopSimulate)
</script>

<style scoped>
.page-card,
.block-card {
  margin-bottom: 16px;
}
.dev-form {
  max-width: 960px;
}
.dev-form-full {
  max-width: none;
  width: 100%;
}
.hex-form-item :deep(.el-form-item__content) {
  flex: 1;
  max-width: 100%;
}
.hex-input :deep(textarea),
.hex-input :deep(.el-textarea__inner) {
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
  line-height: 1.5;
  padding: 10px 12px;
  box-sizing: border-box;
  /* 滚动条随主题（对齐数据收发 IoLogPanel / Element 变量） */
  scrollbar-width: thin;
  scrollbar-color: var(--el-text-color-secondary) var(--el-fill-color-light);
}
.hex-input :deep(.el-textarea__inner::-webkit-scrollbar) {
  width: 6px;
  height: 6px;
}
.hex-input :deep(.el-textarea__inner::-webkit-scrollbar-track) {
  background-color: var(--el-fill-color-light);
  border-radius: 3px;
}
.hex-input :deep(.el-textarea__inner::-webkit-scrollbar-thumb) {
  background-color: var(--el-text-color-secondary);
  border-radius: 3px;
  opacity: 0.5;
}
.hex-input :deep(.el-textarea__inner::-webkit-scrollbar-thumb:hover) {
  background-color: var(--el-text-color-regular);
}
.hex-input-full {
  width: 100%;
}
.hex-input-full :deep(.el-textarea__inner) {
  width: 100%;
}
.result-slot {
  margin-top: 8px;
  min-height: 40px;
  height: 40px;
}
.result-alert {
  margin: 0;
  height: 40px;
}
.result-alert :deep(.el-alert) {
  height: 40px;
  padding-top: 8px;
  padding-bottom: 8px;
}
.result-alert :deep(.el-alert__content) {
  overflow: hidden;
}
.result-alert :deep(.el-alert__title) {
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sim-status {
  color: var(--el-text-color-regular);
  font-size: 13px;
}
.hint {
  margin-top: 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.page-hint {
  margin-top: 0;
}
.action-btn {
  min-width: 104px;
}
</style>
