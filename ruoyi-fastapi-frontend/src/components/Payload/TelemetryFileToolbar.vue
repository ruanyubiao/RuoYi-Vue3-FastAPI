<template>
  <el-form :inline="true" label-width="70px" class="file-toolbar" @submit.prevent>
    <el-form-item label="遥测表">
      <TelemetryPageSelect
        v-model="tmSelect"
        :pages="tmPages"
        auto-select-first
        style="width: 280px"
        @change="onTypeChange"
      />
    </el-form-item>
    <el-form-item label="路径">
      <el-input :model-value="filePath" readonly placeholder="上传或选择文件" style="width: 360px" />
    </el-form-item>
    <el-form-item>
      <el-button type="primary" :loading="parsing" :disabled="!filePath || !tmSelect" @click="emit('parse')">
        解析
      </el-button>
      <el-button @click="onPickUpload">上传</el-button>
      <el-button @click="browserOpen = true">选择文件</el-button>
      <slot />
    </el-form-item>
    <input ref="fileInput" type="file" class="hidden-file" @change="onFileChosen" />
    <RecvFileBrowserDialog
      v-model="browserOpen"
      :current-path="filePath"
      @select="p => emit('update:filePath', p)"
    />
    <el-dialog v-model="uploadOpen" title="上传文件" width="420px" append-to-body :close-on-click-modal="false" @close="onUploadDialogClose">
      <el-progress :percentage="uploadPct" :status="uploadStatus" />
      <p class="upload-name">{{ uploadName }}</p>
      <template #footer>
        <el-button @click="onUploadDialogClose">关闭</el-button>
      </template>
    </el-dialog>
  </el-form>
</template>

<script setup>
/** 历史文件顶栏：遥测表、路径、解析、分片上传、浏览 ``_recv`` 文件。>100MB 走分片到 log_data。 */
import { ElMessage, ElMessageBox } from 'element-plus'
import RecvFileBrowserDialog from '@/components/Payload/RecvFileBrowserDialog.vue'
import TelemetryPageSelect from '@/components/Payload/TelemetryPageSelect.vue'
import { uploadTelemetryFileChunk } from '@/api/payload/telemetry'
import { loadTelemetryPagesCached } from '@/utils/telemetryPages'

const CHUNK = 2 * 1024 * 1024 // 与后端分片大小一致

const props = defineProps({
  filePath: { type: String, default: '' },
  tmType: { type: String, default: '' },
  parsing: { type: Boolean, default: false }
})
const emit = defineEmits(['update:filePath', 'update:tmType', 'parse', 'type-change'])

const tmSelect = computed({
  get: () => props.tmType,
  set: v => emit('update:tmType', v)
})
/** 与实时表/曲线页相同：只拉一次配置，切换下拉不再请求 /telemetry/config */
const tmPages = ref([])
const fileInput = ref(null)
const browserOpen = ref(false)
const uploadOpen = ref(false)
const uploadPct = ref(0)
const uploadStatus = ref('')
const uploadName = ref('')
let abortCtl = null

function onTypeChange(v) {
  emit('update:tmType', v)
  emit('type-change', v)
}

function onPickUpload() {
  fileInput.value?.click()
}

async function onFileChosen(ev) {
  const file = ev.target.files && ev.target.files[0]
  ev.target.value = ''
  if (!file) return
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
    emit('update:filePath', lastPath)
    ElMessage.success('上传完成')
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

onMounted(async () => {
  tmPages.value = await loadTelemetryPagesCached()
  if (!props.tmType && tmPages.value.length) {
    emit('update:tmType', tmPages.value[0].key)
  }
})
</script>

<style scoped>
.file-toolbar {
  flex-shrink: 0;
  margin-bottom: 0;
}
.file-toolbar :deep(.el-form-item) {
  margin-bottom: 8px;
  margin-right: 20px;
}
.hidden-file {
  display: none;
}
.upload-name {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  word-break: break-all;
}
</style>
