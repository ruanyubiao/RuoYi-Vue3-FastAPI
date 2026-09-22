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
    <el-form-item>
      <el-button @click="browserOpen = true">选择文件</el-button>
    </el-form-item>
    <el-form-item>
      <el-input :model-value="displayFsPath(filePath)" readonly placeholder="上传或选择文件" style="width: 500px" />
    </el-form-item>
    <el-form-item>
      <el-button type="primary" :loading="parsing" :disabled="!filePath || !tmSelect" @click="emit('parse')">
        解析
      </el-button>
      <el-button @click="sessionsOpen = true">解析进程</el-button>
      <slot />
    </el-form-item>
    <RecvFileBrowserDialog
      v-model="browserOpen"
      :current-path="filePath"
      @select="p => emit('update:filePath', p)"
    />
    <FilePlaySessionsDialog v-model="sessionsOpen" :channel="channel" />
  </el-form>
</template>

<script setup>
/** 历史文件顶栏：遥测表、路径、解析、选择回放文件。 */
import RecvFileBrowserDialog from '@/components/Payload/RecvFileBrowserDialog.vue'
import FilePlaySessionsDialog from '@/components/Payload/FilePlaySessionsDialog.vue'
import TelemetryPageSelect from '@/components/Payload/TelemetryPageSelect.vue'
import { displayFsPath } from '@/utils/fsPath'
import { loadTelemetryPagesCached } from '@/utils/telemetryPages'

const props = defineProps({
  filePath: { type: String, default: '' },
  tmType: { type: String, default: '' },
  parsing: { type: Boolean, default: false },
  channel: { type: String, default: 'history' }
})
const emit = defineEmits(['update:filePath', 'update:tmType', 'parse', 'type-change'])

const tmSelect = computed({
  get: () => props.tmType,
  set: v => emit('update:tmType', v)
})
/** 与实时表/曲线页相同：只拉一次配置，切换下拉不再请求 /telemetry/config */
const tmPages = ref([])
const browserOpen = ref(false)
const sessionsOpen = ref(false)

function onTypeChange(v) {
  emit('update:tmType', v)
  emit('type-change', v)
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
</style>
