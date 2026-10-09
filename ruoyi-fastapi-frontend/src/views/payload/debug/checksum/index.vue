<template>
  <div class="app-container checksum-page">
    <div class="hex-view" @click="openEdit">
      <template v-if="hexPairs.length">
        <span
          v-for="(pair, i) in hexPairs"
          :key="i"
          :class="{ 'hex-token': true, 'is-range': inRange(i) }"
        >{{ pair }}</span>
      </template>
      <span v-else class="hex-placeholder">点击编辑输入 HEX，或选择文件</span>
    </div>

    <el-form :inline="true" class="checksum-bar" @submit.prevent>
      <el-form-item>
        <template #label>
          校验起始位置（含）
          <el-tooltip placement="top" :show-after="200">
            <template #content>
              大于等于 0：从开头数，0 是第一个字节。<br />
              负数与 Python 下标相同：实际位置 = 字节数 + 该负数。<br />
              -1 是最后一个字节（字节数 − 1），-2 是倒数第二个。<br />
              不能等于字节数。起止位置都包含在计算范围内。
            </template>
            <el-icon class="index-tip" @click.stop><QuestionFilled /></el-icon>
          </el-tooltip>
        </template>
        <el-input-number
          v-model="startIndex"
          :min="bounds.min"
          :max="bounds.max"
          :step="1"
          :precision="0"
          controls-position="right"
          style="width: 140px"
        />
      </el-form-item>
      <el-form-item>
        <template #label>
          校验结束位置（含）
          <el-tooltip placement="top" :show-after="200">
            <template #content>
              大于等于 0：从开头数，0 是第一个字节。<br />
              负数与 Python 下标相同：实际位置 = 字节数 + 该负数。<br />
              -1 是最后一个字节（字节数 − 1），-2 是倒数第二个。<br />
              不能等于字节数。起止位置都包含在计算范围内。
            </template>
            <el-icon class="index-tip" @click.stop><QuestionFilled /></el-icon>
          </el-tooltip>
        </template>
        <el-input-number
          v-model="endIndex"
          :min="bounds.min"
          :max="bounds.max"
          :step="1"
          :precision="0"
          controls-position="right"
          style="width: 140px"
        />
      </el-form-item>
      <el-form-item>
        <el-button v-if="!running" type="primary" @click="onCalc">计算</el-button>
        <el-button v-else type="warning" @click="onStop">停止</el-button>
      </el-form-item>
      <el-form-item>
        <el-button @click="drawerOpen = true">算法选择</el-button>
      </el-form-item>
      <el-form-item label="字节数：">
        <span class="byte-len">{{ bytes.length }}</span>
      </el-form-item>
    </el-form>

    <el-table :data="rows" border stripe empty-text="请选择算法后计算" class="result-table">
      <el-table-column prop="name" label="校验方法" min-width="180" />
      <el-table-column label="校验值HEX" min-width="140">
        <template #default="{ row }">
          <span class="num-cell" @dblclick="copyCell(row.hex)">{{ row.hex }}</span>
        </template>
      </el-table-column>
      <el-table-column label="DEC" min-width="140">
        <template #default="{ row }">
          <span class="num-cell" @dblclick="copyCell(row.dec)">{{ row.dec }}</span>
        </template>
      </el-table-column>
      <el-table-column label="OCT" min-width="140">
        <template #default="{ row }">
          <span class="num-cell" @dblclick="copyCell(row.oct)">{{ row.oct }}</span>
        </template>
      </el-table-column>
      <el-table-column label="BIN" min-width="280">
        <template #default="{ row }">
          <span class="num-cell" @dblclick="copyCell(row.bin)">{{ row.bin }}</span>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="drawerOpen" title="算法选择" size="360px">
      <el-tree
        ref="treeRef"
        :data="algoTree"
        show-checkbox
        node-key="id"
        default-expand-all
        :default-checked-keys="checkedIds"
        @check="onTreeCheck"
      />
    </el-drawer>

    <el-dialog v-model="editOpen" title="输入 HEX" width="640px" append-to-body :close-on-click-modal="false">
      <div class="edit-row">
        <el-input
          v-model="editText"
          type="textarea"
          :autosize="{ minRows: 4, maxRows: 12 }"
          placeholder="HEX 文本，空格可选"
          @blur="onEditBlur"
        />
        <el-button @click="pickFile">选择文件</el-button>
        <input ref="fileInput" type="file" class="hidden-file" @change="onFileChosen" />
      </div>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" @click="confirmEdit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="Checksum">
/** 调试-校验和：纯前端 CRC，弹窗录入 HEX/文件，区间着色后逐算法计算。 */
import { ElMessage } from 'element-plus'
import cache from '@/plugins/cache'
import { bytesToHex, hexToBytes, isHexText, normalizeHexDisplay } from '@/utils/payloadRawData'
import { indexBounds, resolveRange, sliceBytes } from '@/utils/checksumRange'
import { CHECKSUM_ALGORITHMS, checksumAlgoTree, computeChecksum, formatCrcValue, getChecksumAlgorithm } from '@/vendor/crc'

const PREFS_KEY = 'payload:checksum:algos:v1'
const algoTree = checksumAlgoTree()
const leafIds = CHECKSUM_ALGORITHMS.map(a => a.id)

function loadChecked() {
  const saved = cache.local.getJSON(PREFS_KEY, [])
  if (!Array.isArray(saved)) return []
  return saved.filter(id => leafIds.includes(id))
}

const drawerOpen = ref(false)
const treeRef = ref(null)
const checkedIds = ref(loadChecked())
const hexText = ref('')
const startIndex = ref(0)
const endIndex = ref(-1)
const running = ref(false)
const rows = ref([])
const editOpen = ref(false)
const editText = ref('')
const fileInput = ref(null)
let stopFlag = false

const bytes = computed(() => hexToBytes(hexText.value) || new Uint8Array())
const hexPairs = computed(() => (hexText.value ? hexText.value.split(/\s+/).filter(Boolean) : []))
const bounds = computed(() => indexBounds(bytes.value.length))
const range = computed(() => resolveRange(startIndex.value, endIndex.value, bytes.value.length))

watch(bounds, b => {
  const clamp = n => Math.min(b.max, Math.max(b.min, n))
  const nextStart = clamp(startIndex.value)
  const nextEnd = clamp(endIndex.value)
  if (nextStart !== startIndex.value) startIndex.value = nextStart
  if (nextEnd !== endIndex.value) endIndex.value = nextEnd
})

function inRange(i) {
  return range.value != null && i >= range.value.lo && i <= range.value.hi
}

function persistChecked(ids) {
  checkedIds.value = ids
  cache.local.setJSON(PREFS_KEY, ids)
}

function onTreeCheck(_data, info) {
  const ids = (info.checkedKeys || []).filter(id => leafIds.includes(id))
  persistChecked(ids)
}

function openEdit() {
  editText.value = hexText.value
  editOpen.value = true
}

function onEditBlur() {
  if (!editText.value.trim()) return
  const formatted = normalizeHexDisplay(editText.value)
  if (formatted) editText.value = formatted
}

watch(drawerOpen, open => {
  if (!open) return
  nextTick(() => treeRef.value?.setCheckedKeys?.(checkedIds.value))
})

function pickFile() {
  fileInput.value?.click()
}

async function onFileChosen(ev) {
  const file = ev.target.files && ev.target.files[0]
  ev.target.value = ''
  if (!file) return
  const buf = await file.arrayBuffer()
  editText.value = bytesToHex(new Uint8Array(buf))
}

function confirmEdit() {
  onEditBlur()
  if (editText.value.trim() && !isHexText(editText.value)) {
    ElMessage.warning('HEX 文本不合法')
    return
  }
  hexText.value = editText.value.trim() ? normalizeHexDisplay(editText.value) : ''
  editOpen.value = false
}

function copyCell(text) {
  const s = String(text || '')
  if (!s) return
  navigator.clipboard.writeText(s).then(
    () => ElMessage.success('复制成功'),
    () => ElMessage.error('复制失败')
  )
}

function onStop() {
  stopFlag = true
}

async function onCalc() {
  if (hexText.value.trim()) {
    const formatted = normalizeHexDisplay(hexText.value)
    if (formatted) hexText.value = formatted
  }
  if (!hexText.value) {
    ElMessage.warning('请输入 HEX')
    return
  }
  const data = hexToBytes(hexText.value)
  if (!data || !data.length) {
    ElMessage.warning('HEX 文本不合法')
    return
  }
  const slice = sliceBytes(data, startIndex.value, endIndex.value)
  if (!slice) {
    ElMessage.warning('校验起止位置不合法')
    return
  }
  const ids = checkedIds.value.filter(id => leafIds.includes(id))
  if (!ids.length) {
    ElMessage.warning('请选择校验算法')
    return
  }
  stopFlag = false
  running.value = true
  rows.value = ids.map(id => {
    const algo = getChecksumAlgorithm(id)
    return { id, name: algo?.name || id, hex: '', dec: '', oct: '', bin: '' }
  })
  try {
    for (let i = 0; i < ids.length; i++) {
      if (stopFlag) break
      await new Promise(r => setTimeout(r, 0))
      if (stopFlag) break
      const algo = getChecksumAlgorithm(ids[i])
      const value = computeChecksum(ids[i], slice)
      const formatted = formatCrcValue(value, algo.width)
      rows.value[i] = { id: ids[i], name: algo.name, ...formatted }
    }
  } finally {
    running.value = false
    stopFlag = false
  }
}

</script>

<style scoped>
.checksum-bar {
  margin-bottom: 8px;
}
.checksum-bar :deep(.el-form-item) {
  margin-bottom: 8px;
}
.index-tip {
  margin-left: 4px;
  vertical-align: middle;
  cursor: help;
}
.byte-len {
  display: inline-block;
  min-width: 3em;
  font-variant-numeric: tabular-nums;
}
.hex-view {
  min-height: 120px;
  max-height: 240px;
  overflow: auto;
  padding: 10px 12px;
  margin-bottom: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-fill-color-blank);
  font-family: ui-monospace, Consolas, monospace;
  font-size: 13px;
  line-height: 1.7;
  cursor: pointer;
  white-space: pre-wrap;
  word-break: break-all;
}
.hex-token {
  margin-right: 0.4em;
}
.hex-token.is-range {
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 18%, transparent);
  border-radius: 2px;
}
.hex-placeholder {
  color: var(--el-text-color-placeholder);
}
.result-table {
  width: 100%;
}
.num-cell {
  font-family: ui-monospace, Consolas, monospace;
  cursor: copy;
  user-select: none;
}
.edit-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.edit-row :deep(.el-textarea) {
  flex: 1;
}
.hidden-file {
  display: none;
}
</style>
