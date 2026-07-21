<template>
  <div class="app-container">
    <el-form :model="queryParams" ref="queryRef" :inline="true" v-show="showSearch">
      <el-form-item label="序列名称" prop="seqName">
        <el-input
          v-model="queryParams.seqName"
          placeholder="请输入序列名称"
          clearable
          style="width: 200px"
          @keyup.enter="handleQuery"
        />
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-select v-model="queryParams.status" placeholder="序列状态" clearable style="width: 200px">
          <el-option
            v-for="dict in sys_normal_disable"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" icon="Search" @click="handleQuery">搜索</el-button>
        <el-button icon="Refresh" @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-row :gutter="10" class="mb8">
      <el-col :span="1.5">
        <el-button
          type="primary"
          plain
          icon="Plus"
          @click="handleAdd"
          v-hasPermi="['payload:sequence:add']"
        >新增</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="success"
          plain
          icon="Edit"
          :disabled="single"
          @click="handleUpdate"
          v-hasPermi="['payload:sequence:edit']"
        >修改</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="danger"
          plain
          icon="Delete"
          :disabled="multiple"
          @click="handleDelete"
          v-hasPermi="['payload:sequence:remove']"
        >删除</el-button>
      </el-col>
      <right-toolbar v-model:showSearch="showSearch" @queryTable="getList"></right-toolbar>
    </el-row>

    <el-table v-loading="loading" :data="sequenceList" @selection-change="handleSelectionChange">
      <el-table-column type="selection" width="55" align="center" />
      <el-table-column label="序列编号" align="center" prop="seqId" width="90" />
      <el-table-column label="序列名称" align="center" prop="seqName" :show-overflow-tooltip="true" />
      <el-table-column label="指令条数" align="center" width="100">
        <template #default="scope">
          <el-tag type="info">{{ commandCount(scope.row.commands) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" align="center" prop="status" width="90">
        <template #default="scope">
          <dict-tag :options="sys_normal_disable" :value="scope.row.status" />
        </template>
      </el-table-column>
      <el-table-column label="备注" align="center" prop="remark" :show-overflow-tooltip="true" />
      <el-table-column label="创建时间" align="center" prop="createTime" width="180">
        <template #default="scope">
          <span>{{ parseTime(scope.row.createTime) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="460" align="center" class-name="small-padding fixed-width">
        <template #default="scope">
          <el-button link type="primary" icon="Edit" @click="handleUpdate(scope.row)" v-hasPermi="['payload:sequence:edit']">修改</el-button>
          <el-button link type="primary" icon="CopyDocument" @click="handleCopy(scope.row)" v-hasPermi="['payload:sequence:add']">复制</el-button>
          <el-button link type="primary" icon="Download" @click="handleExport(scope.row)" v-hasPermi="['payload:sequence:query']">导出</el-button>
          <el-button link type="success" icon="VideoPlay" @click="handleRun(scope.row)" v-hasPermi="['payload:sequence:edit']">执行</el-button>
          <el-button link type="warning" icon="Document" @click="openRunHistory(scope.row)" v-hasPermi="['payload:sequence:query']">日志</el-button>
          <el-button link type="primary" icon="Delete" @click="handleDelete(scope.row)" v-hasPermi="['payload:sequence:remove']">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <pagination
      v-show="total > 0"
      :total="total"
      v-model:page="queryParams.pageNum"
      v-model:limit="queryParams.pageSize"
      @pagination="getList"
    />

    <!-- 执行指令序列对话框 -->
    <el-dialog
      :title="runProgress.status === 'running' ? '执行中…' : '执行指令序列'"
      v-model="runOpen"
      width="560px"
      append-to-body
      :close-on-click-modal="!runLoading"
      @closed="onRunDialogClosed"
    >
      <el-form label-width="100px">
        <el-form-item label="序列名称">
          <span>{{ runForm.seqName }}</span>
        </el-form-item>
        <el-form-item label="指令条数">
          <el-tag type="info">{{ runForm.commandCount }}</el-tag>
        </el-form-item>
        <el-form-item label="目标设备">
          <el-select
            v-model="runForm.deviceId"
            filterable
            placeholder="请选择 CAN 通道"
            class="run-device-select"
            :disabled="runLoading"
          >
            <el-option v-for="d in deviceOptions" :key="d" :label="d" :value="d" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="runProgress.runId" label="执行进度">
          <div class="run-progress">
            <el-progress
              :percentage="runPercent"
              :status="runProgressStatus"
              :stroke-width="14"
            />
            <div class="run-progress-meta">
              {{ runProgress.current || 0 }}/{{ runProgress.total || runForm.commandCount }}
              （成功 {{ runProgress.ok || 0 }} / 失败 {{ runProgress.fail || 0 }}）
            </div>
            <div v-if="runProgress.message" class="run-progress-msg">{{ runProgress.message }}</div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="runOpen = false">{{ runLoading ? '后台继续' : '关 闭' }}</el-button>
        <el-button type="primary" :loading="runLoading" :disabled="runLoading" @click="confirmRun">开始执行</el-button>
      </template>
    </el-dialog>

    <!-- 执行历史 -->
    <el-dialog title="执行日志" v-model="historyOpen" width="780px" append-to-body>
      <div class="history-head">序列：{{ historySeqName }}</div>
      <el-table v-loading="historyLoading" :data="historyList" height="360">
        <el-table-column label="序号" width="60" align="center">
          <template #default="scope">{{ scope.$index + 1 }}</template>
        </el-table-column>
        <el-table-column label="开始时间" min-width="180">
          <template #default="scope">
            {{ formatRunTime(scope.row.startTime) }}
          </template>
        </el-table-column>
        <el-table-column label="结束时间" min-width="180">
          <template #default="scope">
            {{ formatRunTime(scope.row.endTime) || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="进度" width="110" align="center">
          <template #default="scope">
            {{ scope.row.ok || 0 }}/{{ scope.row.total || 0 }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="scope">
            <el-icon v-if="scope.row.status === 'success'" color="#67C23A" :size="18"><CircleCheckFilled /></el-icon>
            <el-icon v-else-if="scope.row.status === 'failed'" color="#F56C6C" :size="18"><CircleCloseFilled /></el-icon>
            <el-tag v-else type="warning" size="small">执行中</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="scope">
            <el-button link type="primary" @click="openRunDetail(scope.row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 单次执行详情 -->
    <el-dialog title="执行详情" v-model="detailOpen" width="780px" append-to-body class="seq-run-detail-dialog">
      <div class="history-head">
        {{ detailRun.seqName }} · {{ formatRunTime(detailRun.startTime) }}
        <el-tag class="ml8" :type="detailRun.status === 'success' ? 'success' : detailRun.status === 'failed' ? 'danger' : 'warning'" size="small">
          {{ detailStatusText(detailRun.status) }}
        </el-tag>
      </div>
      <el-table
        class="detail-run-table"
        :data="detailRun.items || []"
        height="420"
        table-layout="fixed"
      >
        <el-table-column label="#" width="40" align="center">
          <template #default="scope">{{ (scope.row.index ?? scope.$index) + 1 }}</template>
        </el-table-column>
        <el-table-column label="发送时间" width="192" align="center">
          <template #default="scope">
            <span class="time-cell">{{ formatRunTime(scope.row.time) || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="指令" width="88" align="center">
          <template #default="scope">
            <el-tooltip
              :content="scope.row.orderId || scope.row.name || ''"
              placement="top"
              :disabled="!((scope.row.orderId || scope.row.name || '').length > 8)"
              popper-class="theme-aware-tooltip"
            >
              <span class="msg-cell">{{ scope.row.orderId || scope.row.name || '-' }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="HEX" min-width="160">
          <template #default="scope">
            <el-tooltip
              :content="scope.row.hex || ''"
              placement="top"
              :disabled="!(scope.row.hex && String(scope.row.hex).length > 18)"
              popper-class="theme-aware-tooltip"
            >
              <span class="hex-cell">{{ scope.row.hex || '-' }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="56" align="center">
          <template #default="scope">
            <el-icon v-if="scope.row.status === 'success'" color="#67C23A" :size="18"><CircleCheckFilled /></el-icon>
            <el-icon v-else-if="scope.row.status === 'failed'" color="#F56C6C" :size="18"><CircleCloseFilled /></el-icon>
            <el-tag v-else-if="scope.row.status === 'skipped'" type="info" size="small">跳过</el-tag>
            <el-tag v-else type="warning" size="small">{{ scope.row.status || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="说明" width="100">
          <template #default="scope">
            <el-tooltip
              :content="scope.row.message || ''"
              placement="top"
              :disabled="!(scope.row.message && String(scope.row.message).length > 8)"
              popper-class="theme-aware-tooltip"
            >
              <span class="msg-cell">{{ scope.row.message || '-' }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup name="Sequence">
import { CircleCheckFilled, CircleCloseFilled } from '@element-plus/icons-vue'
import { listSequence, delSequence, runSequence, getSequenceRun, listSequenceRuns } from '@/api/payload/sequence'
import { listCanChannels } from '@/api/payload/device'

const ACTIVE_KEY = 'payload:activeDeviceId'

const { proxy } = getCurrentInstance()
const { sys_normal_disable } = proxy.useDict('sys_normal_disable')
const router = useRouter()

const sequenceList = ref([])
const loading = ref(true)
const showSearch = ref(true)
const ids = ref([])
const single = ref(true)
const multiple = ref(true)
const total = ref(0)
const runOpen = ref(false)
const runLoading = ref(false)
const deviceOptions = ref([])
const runForm = reactive({
  seqId: undefined,
  seqName: '',
  commandCount: 0,
  deviceId: localStorage.getItem(ACTIVE_KEY) || ''
})
const runProgress = reactive({
  runId: '',
  status: '',
  total: 0,
  current: 0,
  ok: 0,
  fail: 0,
  message: ''
})
let pollTimer = null

const historyOpen = ref(false)
const historyLoading = ref(false)
const historyList = ref([])
const historySeqId = ref(null)
const historySeqName = ref('')
const detailOpen = ref(false)
const detailRun = ref({})

const data = reactive({
  queryParams: {
    pageNum: 1,
    pageSize: 10,
    seqName: undefined,
    status: undefined
  }
})

const { queryParams } = toRefs(data)

const runPercent = computed(() => {
  const totalN = Number(runProgress.total || runForm.commandCount || 0)
  if (!totalN) return 0
  const cur = Number(runProgress.current || 0)
  return Math.min(100, Math.round((cur / totalN) * 100))
})

const runProgressStatus = computed(() => {
  if (runProgress.status === 'success') return 'success'
  if (runProgress.status === 'failed') return 'exception'
  return undefined
})

/** 兼容旧版数组与 { defaultInterval, items } */
function parseCommands(commands) {
  if (!commands) return []
  if (Array.isArray(commands)) return commands
  try {
    const data = JSON.parse(commands)
    if (Array.isArray(data)) return data
    if (data && typeof data === 'object') {
      const items = data.items || data.commands || []
      return Array.isArray(items) ? items : []
    }
    return []
  } catch (e) {
    return []
  }
}

function commandCount(commands) {
  return parseCommands(commands).length
}

function csvEscape(value) {
  const text = String(value ?? '')
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

function handleExport(row) {
  const items = parseCommands(row.commands)
  if (!items.length) {
    proxy.$modal.msgWarning('该序列没有可导出的指令')
    return
  }
  const lines = ['order,value']
  for (const item of items) {
    const order = item.name || item.orderId || item.order_id || ''
    const value = item.hex || ''
    lines.push(`${csvEscape(order)},${csvEscape(value)}`)
  }
  const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${row.seqName || 'sequence'}_${row.seqId || ''}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function getList() {
  loading.value = true
  listSequence(queryParams.value).then(response => {
    sequenceList.value = response.rows
    total.value = response.total
    loading.value = false
  })
}

function handleQuery() {
  queryParams.value.pageNum = 1
  getList()
}

function resetQuery() {
  proxy.resetForm('queryRef')
  handleQuery()
}

function handleSelectionChange(selection) {
  ids.value = selection.map(item => item.seqId)
  single.value = selection.length != 1
  multiple.value = !selection.length
}

function goEdit(query = {}) {
  router.push({ path: '/payload/sequence-edit/index', query })
}

function handleAdd() {
  goEdit()
}

function handleUpdate(row) {
  const seqId = row?.seqId || ids.value[0]
  if (!seqId) return
  goEdit({ seqId })
}

function handleCopy(row) {
  goEdit({ copyFrom: row.seqId })
}

function loadDeviceOptions() {
  listCanChannels().then(res => {
    const list = (res.data || []).map(item => item.deviceId).filter(Boolean)
    deviceOptions.value = list.length ? list : ['can:0:0:0']
    if (!runForm.deviceId && deviceOptions.value.length) {
      runForm.deviceId = deviceOptions.value[0]
    }
  })
}

function resetRunProgress() {
  runProgress.runId = ''
  runProgress.status = ''
  runProgress.total = 0
  runProgress.current = 0
  runProgress.ok = 0
  runProgress.fail = 0
  runProgress.message = ''
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function applyRunState(data) {
  runProgress.runId = data.runId || runProgress.runId
  runProgress.status = data.status || ''
  runProgress.total = data.total || 0
  runProgress.current = data.current || 0
  runProgress.ok = data.ok || 0
  runProgress.fail = data.fail || 0
  runProgress.message = data.message || ''
}

function startPoll(runId) {
  stopPoll()
  const tick = () => {
    getSequenceRun(runId)
      .then(res => {
        const data = res.data || {}
        applyRunState(data)
        if (data.status && data.status !== 'running') {
          stopPoll()
          runLoading.value = false
          if (data.status === 'success') {
            proxy.$modal.msgSuccess(`序列执行成功：${data.ok || 0}/${data.total || 0}`)
          } else {
            proxy.$modal.msgWarning(data.message || `序列执行结束：成功 ${data.ok || 0}，失败 ${data.fail || 0}`)
          }
        }
      })
      .catch(() => {})
  }
  tick()
  pollTimer = setInterval(tick, 500)
}

function handleRun(row) {
  stopPoll()
  resetRunProgress()
  runForm.seqId = row.seqId
  runForm.seqName = row.seqName
  runForm.commandCount = commandCount(row.commands)
  runForm.deviceId = localStorage.getItem(ACTIVE_KEY) || deviceOptions.value[0] || ''
  loadDeviceOptions()
  runOpen.value = true
}

function onRunDialogClosed() {
  if (!runLoading.value) {
    stopPoll()
    resetRunProgress()
  }
}

function confirmRun() {
  if (!runForm.deviceId) {
    proxy.$modal.msgWarning('请选择目标设备，请先在首页打开 CAN 通道')
    return
  }
  if (runLoading.value) return
  runLoading.value = true
  resetRunProgress()
  runSequence(runForm.seqId, { deviceId: runForm.deviceId })
    .then(res => {
      const data = res.data || {}
      localStorage.setItem(ACTIVE_KEY, runForm.deviceId)
      applyRunState({
        runId: data.runId,
        status: data.status || 'running',
        total: data.total || runForm.commandCount,
        current: 0,
        ok: 0,
        fail: 0
      })
      if (!data.runId) {
        runLoading.value = false
        proxy.$modal.msgError('未返回执行任务 ID')
        return
      }
      startPoll(data.runId)
    })
    .catch(() => {
      runLoading.value = false
    })
}

function formatRunTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 23)
}

function detailStatusText(status) {
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  if (status === 'running') return '执行中'
  return status || '-'
}

function openRunHistory(row) {
  historySeqId.value = row.seqId
  historySeqName.value = row.seqName || ''
  historyOpen.value = true
  historyLoading.value = true
  listSequenceRuns(row.seqId, 50)
    .then(res => {
      historyList.value = res.data || []
    })
    .finally(() => {
      historyLoading.value = false
    })
}

function openRunDetail(row) {
  if (!row?.runId) return
  getSequenceRun(row.runId).then(res => {
    detailRun.value = res.data || row
    detailOpen.value = true
  })
}

function handleDelete(row) {
  const seqIds = row.seqId || ids.value
  proxy.$modal.confirm('是否确认删除指令序列编号为"' + seqIds + '"的数据项？').then(function () {
    return delSequence(seqIds)
  }).then(() => {
    getList()
    proxy.$modal.msgSuccess('删除成功')
  }).catch(() => {})
}

onUnmounted(() => {
  stopPoll()
})

onActivated(() => {
  if (sessionStorage.getItem('payload:sequence:needRefresh') === '1') {
    sessionStorage.removeItem('payload:sequence:needRefresh')
    getList()
  }
})

getList()
loadDeviceOptions()
</script>

<style scoped>
.run-device-select {
  width: 280px;
  max-width: 100%;
}
.run-progress {
  width: 100%;
}
.run-progress-meta {
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.run-progress-msg {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-color-danger);
}
.history-head {
  margin-bottom: 10px;
  font-weight: 600;
}
.ml8 {
  margin-left: 8px;
}
.hex-cell,
.msg-cell {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.hex-cell {
  font-family: monospace;
  font-size: 12px;
}
/* 内容区保底 168px（列宽 192 ≈ 168 + 单元格左右 padding） */
.time-cell {
  display: inline-block;
  min-width: 168px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  font-size: 12px;
}
.detail-run-table :deep(.el-scrollbar__bar.is-horizontal) {
  display: none;
}
.detail-run-table :deep(.el-table__body-wrapper) {
  overflow-x: hidden !important;
}
</style>

<style>
/* teleported tooltip：跟随主题，避免 dark 下白底 */
.theme-aware-tooltip.el-popper {
  background: var(--el-bg-color-overlay) !important;
  color: var(--el-text-color-primary) !important;
  border: 1px solid var(--el-border-color) !important;
  box-shadow: var(--el-box-shadow-light);
  max-width: 480px;
  word-break: break-all;
}
.theme-aware-tooltip.el-popper .el-popper__arrow::before {
  background: var(--el-bg-color-overlay) !important;
  border: 1px solid var(--el-border-color) !important;
}
</style>
