<template>
  <el-dialog
    v-if="!embedded"
    :model-value="modelValue"
    :title="isDownload ? '下载文件' : '选择文件'"
    width="960px"
    append-to-body
    destroy-on-close
    @close="onClose"
  >
    <BrowserPanel
      :entries="entries"
      :crumb-items="crumbItems"
      :show-all="showAll"
      :is-download="isDownload"
      :has-selection="hasSelection"
      :downloading="downloading"
      :table-height="360"
      :include-footer="false"
      :multiple="multiple"
      @go-crumb="goCrumb"
      @pick-upload="onPickUpload"
      @row-click="onRowClick"
      @row-dblclick="onRowDblClick"
      @download-name="onDownloadNameClick"
      @refresh="onRefresh"
      @update:show-all="onShowAllModel"
      @primary="onPrimary"
      @cancel="onClose"
      @set-table-ref="setTableRef"
      @selection-change="onSelectionChange"
    />
    <template #footer>
      <div class="browser-footer">
        <div class="browser-footer-left">
          <el-button circle icon="Refresh" title="刷新" @click="onRefresh" />
          <el-checkbox :model-value="showAll" @update:model-value="onShowAllModel">
            显示所有文件
          </el-checkbox>
        </div>
        <div>
          <el-button @click="onClose">取消</el-button>
          <el-button
            type="primary"
            :disabled="!hasSelection"
            :loading="downloading"
            @click="onPrimary"
          >
            {{ isDownload ? '下载' : '确认' }}
          </el-button>
        </div>
      </div>
    </template>
    <input
      v-if="!isDownload"
      ref="fileInput"
      type="file"
      class="hidden-file"
      accept=".bin"
      @change="onFileChosen"
    />
    <el-dialog
      v-if="!isDownload"
      v-model="uploadOpen"
      title="上传文件"
      width="420px"
      append-to-body
      :close-on-click-modal="false"
      @close="onUploadDialogClose"
    >
      <el-progress :percentage="uploadPct" :status="uploadStatus" />
      <p class="upload-name">{{ uploadName }}</p>
      <template #footer>
        <el-button @click="onUploadDialogClose">关闭</el-button>
      </template>
    </el-dialog>
  </el-dialog>

  <div v-else class="recv-file-browser-embed">
    <BrowserPanel
      :entries="entries"
      :crumb-items="crumbItems"
      :show-all="showAll"
      :is-download="isDownload"
      :has-selection="hasSelection"
      :downloading="downloading"
      :table-height="'calc(100vh - 220px)'"
      :show-cancel="false"
      :multiple="multiple"
      @go-crumb="goCrumb"
      @pick-upload="onPickUpload"
      @row-click="onRowClick"
      @row-dblclick="onRowDblClick"
      @download-name="onDownloadNameClick"
      @refresh="onRefresh"
      @update:show-all="onShowAllModel"
      @primary="onPrimary"
      @cancel="onClose"
      @set-table-ref="setTableRef"
      @selection-change="onSelectionChange"
    />
  </div>
</template>

<script setup>
/** 选回放文件 / 日志下载。默认只列 .bin；「显示所有文件」记在 localStorage。 */
import { ElMessage, ElMessageBox } from 'element-plus'
import { saveAs } from 'file-saver'
import {
  browseTelemetryFiles,
  downloadTelemetryFilesZip,
  locateTelemetryFile,
  statTelemetryUpload,
  uploadTelemetryFileChunk
} from '@/api/payload/telemetry'
import { blobValidate } from '@/utils/ruoyi'
import { baseNameAny } from '@/utils/fsPath'
import BrowserPanel from './RecvFileBrowserPanel.vue'

const CHUNK = 2 * 1024 * 1024
const SHOW_ALL_KEY = 'payload:fileBrowser:showAll'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** 路径输入框当前值；打开时若文件在白名单内则定位到所在目录 */
  currentPath: { type: String, default: '' },
  /** select=确认回传路径；download=打包 ZIP 下载 */
  mode: { type: String, default: 'select' },
  /** 作为页面主体嵌入，不用弹窗 */
  embedded: { type: Boolean, default: false },
  /** 文件多选（仅文件名；目录不可勾选）。选择文件界面保持 false */
  multiple: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'select'])

const isDownload = computed(() => props.mode === 'download')
const tableRef = ref(null)
const fileInput = ref(null)
const atHome = ref(true)
const root = ref('')
const relPath = ref('')
const absPath = ref('')
const entries = ref([])
const selectedFile = ref(null)
const selectedFiles = ref([])
const uploadOpen = ref(false)
const uploadPct = ref(0)
const uploadStatus = ref('')
const uploadName = ref('')
const downloading = ref(false)
const showAll = ref(
  props.mode === 'download' ? true : localStorage.getItem(SHOW_ALL_KEY) === '1'
)
let abortCtl = null

const hasSelection = computed(() => {
  if (props.multiple) {
    return selectedFiles.value.some(r => r && !r.isDir && r.selectable)
  }
  return !!(selectedFile.value && !selectedFile.value.isDir && selectedFile.value.selectable)
})

const crumbItems = computed(() => {
  const items = [{ key: 'home', label: '首页', kind: 'home' }]
  if (atHome.value) return items
  const rootLabel = root.value === 'upload' ? '上传文件' : '本地日志'
  items.push({ key: 'root', label: rootLabel, kind: 'root', root: root.value, path: '' })
  const parts = String(relPath.value || '').replace(/\\/g, '/').split('/').filter(Boolean)
  let acc = ''
  for (const part of parts) {
    acc = acc ? `${acc}/${part}` : part
    items.push({ key: `p:${acc}`, label: part, kind: 'dir', root: root.value, path: acc })
  }
  return items
})

function setTableRef(el) {
  tableRef.value = el
}

function clearSelection() {
  selectedFile.value = null
  selectedFiles.value = []
  tableRef.value?.clearSelection?.()
  tableRef.value?.setCurrentRow?.()
}

function onSelectionChange(rows) {
  selectedFiles.value = (rows || []).filter(r => r && !r.isDir && r.selectable)
}

function onShowAllModel(checked) {
  showAll.value = checked
  if (!isDownload.value) {
    localStorage.setItem(SHOW_ALL_KEY, checked ? '1' : '0')
  }
  loadDir()
}

async function loadDir() {
  clearSelection()
  if (atHome.value) {
    entries.value = [
      { name: '上传文件', isDir: true, selectable: false, home: 'upload', size: null },
      { name: '本地日志', isDir: true, selectable: false, home: 'logs', size: null }
    ]
    absPath.value = ''
    return
  }
  const res = await browseTelemetryFiles({ root: root.value, path: relPath.value, showAll: showAll.value })
  const data = res.data || {}
  entries.value = data.entries || []
  absPath.value = data.absPath || ''
  relPath.value = data.path || ''
}

async function highlightRow(row) {
  selectedFile.value = row
  await nextTick()
  if (props.multiple) {
    tableRef.value?.clearSelection?.()
    if (row) tableRef.value?.toggleRowSelection?.(row, true)
  } else {
    tableRef.value?.setCurrentRow?.(row)
  }
}

async function tryLocate() {
  const raw = String(props.currentPath || '').trim()
  if (!raw) return false
  try {
    const res = await locateTelemetryFile({ path: raw })
    const loc = res.data || {}
    if (!loc.found || !loc.root) return false
    atHome.value = false
    root.value = loc.root
    relPath.value = loc.path || ''
    await loadDir()
    if (loc.name) {
      const row = entries.value.find(e => e.name === loc.name && !e.isDir && e.selectable)
      if (row) await highlightRow(row)
    }
    return true
  } catch {
    return false
  }
}

function goHome() {
  atHome.value = true
  root.value = ''
  relPath.value = ''
  loadDir()
}

function goCrumb(item) {
  if (!item || item.kind === 'home') {
    goHome()
    return
  }
  atHome.value = false
  root.value = item.root
  relPath.value = item.path || ''
  loadDir()
}

function onRowClick(row) {
  if (row && !row.isDir && row.selectable) {
    if (props.multiple) {
      tableRef.value?.toggleRowSelection?.(row)
      return
    }
    selectedFile.value = row
    return
  }
  if (!props.multiple) {
    selectedFile.value = null
    tableRef.value?.setCurrentRow?.()
  }
}

function onRowDblClick(row) {
  if (!row) return
  // 首页虚拟项：只切 root，path 必须为空，绝不能把「本地日志/上传文件」写进相对路径
  if (row.home) {
    root.value = row.home
    relPath.value = ''
    atHome.value = false
    loadDir()
    return
  }
  if (atHome.value) return
  if (row.isDir) {
    relPath.value = relPath.value ? `${relPath.value}/${row.name}` : row.name
    loadDir()
  }
}

function zipNameForSingle(fileName) {
  const base = String(fileName || 'download')
  const i = base.lastIndexOf('.')
  const stem = i > 0 ? base.slice(0, i) : base
  return `${stem || 'download'}.zip`
}

function zipNameForMulti() {
  const d = new Date()
  const p = n => String(n).padStart(2, '0')
  const ms = String(d.getMilliseconds()).padStart(3, '0')
  return `logs_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}${ms}.zip`
}

async function downloadNames(names, saveName) {
  if (!names.length) {
    ElMessage.warning('请选择文件')
    return
  }
  if (!root.value) {
    ElMessage.warning('请先进入目录')
    return
  }
  downloading.value = true
  try {
    const data = await downloadTelemetryFilesZip({
      root: root.value,
      path: relPath.value || '',
      names
    })
    if (!blobValidate(data)) {
      const text = await data.text()
      let msg = '下载失败'
      try {
        msg = JSON.parse(text)?.msg || msg
      } catch {
        /* ignore */
      }
      ElMessage.error(msg)
      return
    }
    saveAs(new Blob([data], { type: 'application/zip' }), saveName)
    ElMessage.success('下载完成')
  } catch (e) {
    ElMessage.error(e?.message || '下载失败')
  } finally {
    downloading.value = false
  }
}

/** 点文件名：始终单文件下载 */
function onDownloadNameClick(row) {
  if (!row || row.isDir || !row.selectable) return
  downloadNames([row.name], zipNameForSingle(row.name))
}

/** 下载按钮：多选打包 / 单选一个 */
function downloadByButton() {
  if (props.multiple) {
    const files = selectedFiles.value.filter(r => r && !r.isDir && r.selectable)
    if (!files.length) {
      ElMessage.warning('请选择文件')
      return
    }
    const names = files.map(f => f.name)
    const saveName = names.length === 1 ? zipNameForSingle(names[0]) : zipNameForMulti()
    downloadNames(names, saveName)
    return
  }
  const file = selectedFile.value
  if (!file || file.isDir || !file.selectable) {
    ElMessage.warning('请选择文件')
    return
  }
  downloadNames([file.name], zipNameForSingle(file.name))
}

function onConfirm() {
  if (!selectedFile.value) {
    ElMessage.warning('请选择文件')
    return
  }
  const full = absPath.value
    ? `${absPath.value.replace(/[\\/]+$/, '')}/${selectedFile.value.name}`
    : selectedFile.value.name
  emit('select', full.replace(/\\/g, '/'))
  onClose()
}

function onPrimary() {
  if (isDownload.value) {
    downloadByButton()
    return
  }
  onConfirm()
}

function onClose() {
  if (props.embedded) return
  emit('update:modelValue', false)
}

function onRefresh() {
  loadDir()
}

function sizeK(bytes) {
  const k = (Number(bytes) || 0) / 1024
  if (k >= 100) return String(Math.round(k))
  const text = k.toFixed(1)
  return text.endsWith('.0') ? text.slice(0, -2) : text
}

function onPickUpload() {
  fileInput.value?.click()
}

async function confirmOverwrite(file) {
  const res = await statTelemetryUpload({ filename: file.name })
  const info = res.data || {}
  if (!info.exists) return true
  try {
    await ElMessageBox.confirm(
      `已存在同名文件，大小${sizeK(info.size)}K\n是否继续上传？`,
      '提示',
      { confirmButtonText: '覆盖', cancelButtonText: '取消', type: 'warning' }
    )
    return true
  } catch {
    return false
  }
}

async function openUploadDirAndSelect(fileName) {
  atHome.value = false
  root.value = 'upload'
  relPath.value = ''
  await loadDir()
  const name = baseNameAny(fileName)
  const row = entries.value.find(e => e.name === name && !e.isDir && e.selectable)
  if (row) await highlightRow(row)
}

async function onFileChosen(ev) {
  const file = ev.target.files && ev.target.files[0]
  ev.target.value = ''
  if (!file) return
  if (!(await confirmOverwrite(file))) return
  uploadOpen.value = true
  uploadPct.value = 0
  uploadStatus.value = ''
  uploadName.value = file.name
  abortCtl = new AbortController()
  const total = Math.max(1, Math.ceil(file.size / CHUNK))
  try {
    let lastPath = ''
    for (let i = 0; i < total; i++) {
      const blob = file.slice(i * CHUNK, (i + 1) * CHUNK)
      const form = new FormData()
      form.append('file', blob, file.name)
      const res = await uploadTelemetryFileChunk(form, {
        signal: abortCtl.signal,
        params: { filename: file.name, chunkIndex: i, totalChunks: total },
        onUploadProgress: e => {
          if (!e.total) return
          const part = e.loaded / e.total
          uploadPct.value = Math.min(99, Math.round(((i + part) / total) * 100))
        }
      })
      lastPath = res.data?.path || lastPath
      uploadPct.value = Math.round(((i + 1) / total) * 100)
    }
    uploadStatus.value = 'success'
    emit('select', lastPath)
    ElMessage.success('上传完成')
    uploadOpen.value = false
    await openUploadDirAndSelect(file.name)
  } catch (e) {
    if (e?.code === 'ERR_CANCELED' || e?.name === 'CanceledError') {
      ElMessage.info('已停止传输')
    } else {
      ElMessage.error(e?.message || '上传失败')
    }
    uploadStatus.value = 'exception'
  }
}

async function onUploadDialogClose() {
  if (abortCtl && uploadPct.value < 100 && uploadStatus.value !== 'success') {
    try {
      await ElMessageBox.confirm('关闭将停止传输，是否继续？', '提示', { type: 'warning' })
      abortCtl.abort()
    } catch {
      uploadOpen.value = true
      return
    }
  }
  uploadOpen.value = false
}

async function bootstrap() {
  atHome.value = true
  root.value = ''
  relPath.value = ''
  clearSelection()
  if (isDownload.value) {
    showAll.value = true
  }
  const located = await tryLocate()
  if (!located) await loadDir()
}

watch(
  () => props.modelValue,
  async open => {
    if (props.embedded) return
    if (!open) return
    await bootstrap()
  }
)

onMounted(() => {
  if (props.embedded) bootstrap()
})
</script>

<style scoped>
.hidden-file {
  display: none;
}
.upload-name {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  word-break: break-all;
}
.recv-file-browser-embed {
  width: 100%;
}
.browser-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.browser-footer-left {
  display: flex;
  align-items: center;
  gap: 20px;
}
</style>
