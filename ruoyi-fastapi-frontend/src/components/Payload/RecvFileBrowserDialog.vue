<template>
  <el-dialog
    :model-value="modelValue"
    title="选择文件"
    width="960px"
    append-to-body
    destroy-on-close
    @close="onClose"
  >
    <div class="browser">
      <div class="browser-nav">
        <el-button :disabled="atHome" @click="goUp">上级</el-button>
        <span class="crumb">{{ crumb }}</span>
        <el-button class="nav-upload" @click="onPickUpload">上传</el-button>
      </div>
      <el-table
        ref="tableRef"
        :data="entries"
        height="360"
        highlight-current-row
        row-key="name"
        @row-click="onRowClick"
        @row-dblclick="onRowDblClick"
      >
        <el-table-column label="名称" min-width="380">
          <template #default="{ row }">
            <span>{{ row.isDir ? '📁' : '📄' }} {{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            {{ row.isDir ? '文件夹' : '文件' }}
          </template>
        </el-table-column>
        <el-table-column label="大小(M)" width="110" align="right">
          <template #default="{ row }">
            {{ sizeText(row) }}
          </template>
        </el-table-column>
      </el-table>
    </div>
    <template #footer>
      <div class="browser-footer">
        <div class="browser-footer-left">
          <el-button circle icon="Refresh" title="刷新" @click="onRefresh" />
          <el-checkbox v-model="showAll" @change="onShowAllChange">显示所有文件</el-checkbox>
        </div>
        <div>
          <el-button @click="onClose">取消</el-button>
          <el-button type="primary" :disabled="!selectedFile" @click="onConfirm">确认</el-button>
        </div>
      </div>
    </template>
    <input ref="fileInput" type="file" class="hidden-file" accept=".bin" @change="onFileChosen" />
    <el-dialog
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
</template>

<script setup>
/** 选回放文件。默认只列 .bin；「显示所有文件」记在 localStorage，换目录时一并请求。 */
import { ElMessage, ElMessageBox } from 'element-plus'
import { browseTelemetryFiles, locateTelemetryFile, statTelemetryUpload, uploadTelemetryFileChunk } from '@/api/payload/telemetry'

const CHUNK = 2 * 1024 * 1024
const SHOW_ALL_KEY = 'payload:fileBrowser:showAll'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** 路径输入框当前值；打开时若文件在白名单内则定位到所在目录 */
  currentPath: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue', 'select'])

const tableRef = ref(null)
const fileInput = ref(null)
const atHome = ref(true)
const root = ref('')
const relPath = ref('')
const absPath = ref('')
const entries = ref([])
const selectedFile = ref(null)
const uploadOpen = ref(false)
const uploadPct = ref(0)
const uploadStatus = ref('')
const uploadName = ref('')
const showAll = ref(localStorage.getItem(SHOW_ALL_KEY) === '1')
let abortCtl = null

const crumb = computed(() => {
  if (atHome.value) return '首页'
  const label = root.value === 'upload' ? '/上传文件' : '/本地日志'
  return relPath.value ? `${label}/${relPath.value}` : label
})

function sizeText(row) {
  if (!row || row.isDir || row.size == null || row.size === '') return ''
  const mb = Number(row.size) / (1024 * 1024)
  if (!Number.isFinite(mb)) return ''
  if (mb > 0 && mb < 0.01) return mb.toFixed(3)
  return mb.toFixed(2)
}

async function loadDir() {
  selectedFile.value = null
  if (atHome.value) {
    entries.value = [
      { name: '/上传文件', isDir: true, selectable: false, home: 'upload', size: null },
      { name: '/本地日志', isDir: true, selectable: false, home: 'logs', size: null }
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
  tableRef.value?.setCurrentRow?.(row)
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

function onRowClick(row) {
  if (row && !row.isDir && row.selectable) {
    selectedFile.value = row
    return
  }
  selectedFile.value = null
  tableRef.value?.setCurrentRow?.()
}

function onRowDblClick(row) {
  if (!row) return
  if (atHome.value && row.home) {
    root.value = row.home
    relPath.value = ''
    atHome.value = false
    loadDir()
    return
  }
  if (row.isDir) {
    relPath.value = relPath.value ? `${relPath.value}/${row.name}` : row.name
    loadDir()
  }
}

function goUp() {
  if (atHome.value) return
  if (!relPath.value) {
    atHome.value = true
    root.value = ''
    loadDir()
    return
  }
  const parts = relPath.value.split('/').filter(Boolean)
  parts.pop()
  relPath.value = parts.join('/')
  loadDir()
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

function onClose() {
  emit('update:modelValue', false)
}

function onRefresh() {
  loadDir()
}

function onShowAllChange(checked) {
  localStorage.setItem(SHOW_ALL_KEY, checked ? '1' : '0')
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
    if (!atHome.value && root.value === 'upload' && !relPath.value) await loadDir()
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

watch(
  () => props.modelValue,
  async open => {
    if (!open) return
    atHome.value = true
    root.value = ''
    relPath.value = ''
    selectedFile.value = null
    const located = await tryLocate()
    if (!located) await loadDir()
  }
)
</script>

<style scoped>
.browser-nav {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.nav-upload {
  margin-left: auto;
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
.hidden-file {
  display: none;
}
.upload-name {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  word-break: break-all;
}
.crumb {
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.browser :deep(.el-table) {
  --el-table-current-row-bg-color: rgba(64, 158, 255, 0.18);
}
.browser :deep(.el-table__body tr.current-row > td.el-table__cell) {
  background-color: rgba(64, 158, 255, 0.18) !important;
}
.browser :deep(.el-table__body tr.current-row:hover > td.el-table__cell) {
  background-color: rgba(64, 158, 255, 0.34) !important;
}
</style>
