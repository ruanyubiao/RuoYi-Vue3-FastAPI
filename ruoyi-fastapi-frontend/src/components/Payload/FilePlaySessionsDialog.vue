<template>
  <el-dialog
    :model-value="modelValue"
    title="解析进程"
    width="1200px"
    append-to-body
    class="fileplay-sessions-dialog"
    @close="onClose"
  >
    <template #header>
      <span class="el-dialog__title">解析进程</span>
      <button
        type="button"
        class="sessions-refresh"
        aria-label="刷新"
        :disabled="loading"
        @click="loadList"
      >
        <el-icon :size="20" :class="{ 'is-loading': loading }"><Refresh /></el-icon>
      </button>
    </template>
    <el-table v-loading="loading" :data="items" height="360" table-layout="fixed">
      <el-table-column label="序号" width="50" align="center">
        <template #default="scope">{{ scope.$index + 1 }}</template>
      </el-table-column>
      <el-table-column label="hash" width="150" align="center" show-overflow-tooltip>
        <template #default="scope">{{ scope.row.pathHash || '-' }}</template>
      </el-table-column>
      <el-table-column label="路径" min-width="240">
        <template #default="scope">
          <span class="path-cell">{{ scope.row.path || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="开始时间" width="100" align="center">
        <template #default="scope">{{ formatTs(scope.row.startedAt) }}</template>
      </el-table-column>
      <el-table-column label="访问时间" width="100" align="center">
        <template #default="scope">{{ formatTs(scope.row.lastAccess) }}</template>
      </el-table-column>
      <el-table-column label="文件状态" width="80" align="center">
        <template #default="scope">{{ scope.row.fileStatus || '-' }}</template>
      </el-table-column>
      <el-table-column label="解析进程" width="80" align="center">
        <template #default="scope">{{ scope.row.procStatus || '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="80" align="center">
        <template #default="scope">
          <div class="op-cell">
            <el-button link type="danger" :disabled="!scope.row.hasCache" @click="onClear(scope.row)">
              清除缓存
            </el-button>
          </div>
          <div class="op-cell">
            <el-button link type="warning" :disabled="!scope.row.workerAlive" @click="onCloseProc(scope.row)">
              关闭进程
            </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>
</template>

<script setup>
/** 历史文件解析会话：缓存 ∪ 进程一行；清缓存不杀进程，关进程不删缓存。 */
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import {
  clearTelemetryFileSession,
  closeTelemetryFileSession,
  listTelemetryFileSessions
} from '@/api/payload/telemetry'
import { parseTime } from '@/utils/ruoyi'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  channel: { type: String, default: 'history' }
})
const emit = defineEmits(['update:modelValue'])

const loading = ref(false)
const items = ref([])

function formatTs(ts) {
  const n = Number(ts) || 0
  return n ? parseTime(n) || '-' : '-'
}

async function loadList() {
  loading.value = true
  try {
    const res = await listTelemetryFileSessions({ channel: props.channel })
    items.value = res.data?.items || []
  } catch (e) {
    items.value = []
    ElMessage.error(e?.message || '加载解析进程失败')
  } finally {
    loading.value = false
  }
}

function onClose() {
  emit('update:modelValue', false)
}

async function onClear(row) {
  if (!row?.pathHash) return
  try {
    await clearTelemetryFileSession({ pathHash: row.pathHash, channel: props.channel })
    ElMessage.success('已清除缓存')
    await loadList()
  } catch (e) {
    ElMessage.error(e?.message || '清除缓存失败')
  }
}

async function onCloseProc(row) {
  if (!row?.pathHash) return
  try {
    await closeTelemetryFileSession({ pathHash: row.pathHash, channel: props.channel })
    ElMessage.success('已关闭进程')
    await loadList()
  } catch (e) {
    ElMessage.error(e?.message || '关闭进程失败')
  }
}

watch(
  () => props.modelValue,
  open => {
    if (open) loadList()
  }
)
</script>

<style scoped>
.path-cell {
  white-space: normal;
  word-break: break-all;
  line-height: 1.4;
}
.op-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
  line-height: 1.4;
}
</style>

<style>
.fileplay-sessions-dialog.el-dialog .el-dialog__header {
  position: relative;
  padding: 16px 20px 8px;
  margin-right: 0;
}
.fileplay-sessions-dialog.el-dialog .el-dialog__headerbtn {
  top: 50%;
  right: 16px;
  width: 40px;
  height: 40px;
  transform: translateY(-50%);
  font-size: 20px;
}
.fileplay-sessions-dialog .sessions-refresh {
  position: absolute;
  top: 50%;
  right: 56px;
  width: 40px;
  height: 40px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--el-color-info);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transform: translateY(-50%);
  font-size: 20px;
  line-height: 1;
}
.fileplay-sessions-dialog .sessions-refresh:hover {
  color: var(--el-color-primary);
}
.fileplay-sessions-dialog .sessions-refresh:disabled {
  cursor: default;
  opacity: 0.65;
}
</style>
