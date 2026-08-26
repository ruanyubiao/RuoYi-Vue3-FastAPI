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
      <el-button @click="onClose">取消</el-button>
      <el-button type="primary" :disabled="!selectedFile" @click="onConfirm">确认</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
/** 选回放文件：首页分「上传文件 / 本地日志」两根，只显示文件夹与 ``_recv`` 文件。 */
import { ElMessage } from 'element-plus'
import { browseTelemetryFiles, locateTelemetryFile } from '@/api/payload/telemetry'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** 路径输入框当前值；打开时若文件在白名单内则定位到所在目录 */
  currentPath: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue', 'select'])

const tableRef = ref(null)
const atHome = ref(true)
const root = ref('')
const relPath = ref('')
const absPath = ref('')
const entries = ref([])
const selectedFile = ref(null)

const crumb = computed(() => {
  if (atHome.value) return '首页'
  const label = root.value === 'upload' ? '上传文件' : '本地日志'
  return relPath.value ? `${label} / ${relPath.value}` : label
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
      { name: '上传文件', isDir: true, selectable: false, home: 'upload', size: null },
      { name: '本地日志', isDir: true, selectable: false, home: 'logs', size: null }
    ]
    absPath.value = ''
    return
  }
  const res = await browseTelemetryFiles({ root: root.value, path: relPath.value })
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
    ElMessage.warning('请选择文件名包含 _recv 的文件')
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
