<template>
  <div class="app-container">
    <el-row :gutter="10" class="mb8">
      <el-col :span="1.5">
        <el-tooltip
          content="从磁盘重新读取全部遥控/遥测配置，刷新系统内存缓存（无需重启服务）"
          placement="right"
        >
          <el-button type="primary" plain icon="Refresh" :loading="reloading" @click="reloadConfigs">
            重新载入配置
          </el-button>
        </el-tooltip>
      </el-col>
      <right-toolbar :search="false" @queryTable="loadList" />
    </el-row>

    <el-table v-loading="loading" :data="rows">
      <el-table-column prop="index" label="序号" width="80" align="center" />
      <el-table-column prop="name" label="文件名" min-width="260" :show-overflow-tooltip="true" />
      <el-table-column prop="datetime" label="生成时间" width="180" align="center" />
      <el-table-column prop="mtime" label="修改时间" width="180" align="center" />
      <el-table-column label="操作" width="360" align="left" header-align="left" class-name="small-padding fixed-width">
        <template #default="{ row }">
          <el-button link type="primary" @click="downloadFile(row)">下载</el-button>
          <el-button link type="primary" @click="openPreview(row)">预览</el-button>
          <el-button link type="primary" v-hasPermi="['payload:configfile:edit']" @click="openEdit(row)">
            编辑
          </el-button>
          <el-tooltip :content="`仅重载「${row.name}」到内存缓存`" placement="top">
            <el-button
              link
              type="primary"
              :loading="reloadingName === row.name"
              @click="reloadOne(row)"
            >
              重载配置
            </el-button>
          </el-tooltip>
          <el-button
            v-if="isTelecontrolCfg(row.name)"
            link
            type="primary"
            :loading="exportingName === row.name"
            @click="exportOrders(row)"
          >
            导出指令
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dlg.visible"
      :title="dlg.mode === 'edit' ? `编辑 · ${dlg.name}` : `预览 · ${dlg.name}`"
      width="80%"
      top="5vh"
      destroy-on-close
      class="cfg-dialog"
      @opened="fitEditorHeight"
    >
      <el-scrollbar max-height="65vh" class="cfg-scroll">
        <textarea
          ref="editorRef"
          v-model="dlg.content"
          class="cfg-textarea"
          :readonly="dlg.mode === 'preview'"
          spellcheck="false"
          @input="fitEditorHeight"
        />
      </el-scrollbar>
      <template #footer>
        <el-button
          v-if="dlg.mode === 'edit'"
          type="primary"
          :loading="dlg.saving"
          @click="saveEdit"
        >
          保存
        </el-button>
        <el-button v-if="dlg.mode === 'preview'" type="primary" plain @click="downloadDlgContent">
          下载
        </el-button>
        <el-button @click="dlg.visible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="PayloadDebugConfigFiles">
import { ElMessage } from 'element-plus'
import { saveAs } from 'file-saver'
import {
  exportPayloadConfigOrders,
  getPayloadConfigFileContent,
  listPayloadConfigFiles,
  reloadPayloadConfigFiles,
  savePayloadConfigFileContent
} from '@/api/payload/configFile'

const loading = ref(false)
const reloading = ref(false)
const reloadingName = ref('')
const exportingName = ref('')
const rows = ref([])
const editorRef = ref(null)
const dlg = reactive({
  visible: false,
  mode: 'preview',
  name: '',
  content: '',
  saving: false
})

function isTelecontrolCfg(name) {
  return String(name || '').endsWith('-TeleControlCfg.json')
}

function fitEditorHeight() {
  nextTick(() => {
    const el = editorRef.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.max(el.scrollHeight, 360)}px`
  })
}

async function loadList() {
  loading.value = true
  try {
    const res = await listPayloadConfigFiles()
    rows.value = res.data || []
  } catch (e) {
    ElMessage.error(e?.message || '加载配置列表失败')
  } finally {
    loading.value = false
  }
}

async function reloadConfigs() {
  reloading.value = true
  try {
    const res = await reloadPayloadConfigFiles()
    ElMessage.success(res.msg || '配置已重新载入')
    await loadList()
  } catch (e) {
    ElMessage.error(e?.message || '重新载入失败')
  } finally {
    reloading.value = false
  }
}

async function reloadOne(row) {
  reloadingName.value = row.name
  try {
    const res = await reloadPayloadConfigFiles(row.name)
    ElMessage.success(res.msg || `已重载 ${row.name}`)
    await loadList()
  } catch (e) {
    ElMessage.error(e?.message || '重载配置失败')
  } finally {
    reloadingName.value = ''
  }
}

async function exportOrders(row) {
  exportingName.value = row.name
  try {
    const res = await exportPayloadConfigOrders(row.name)
    const list = res.data || []
    const blob = new Blob([JSON.stringify(list, null, 2) + '\n'], {
      type: 'application/json;charset=utf-8'
    })
    const outName = String(row.name).replace(/\.json$/i, '') + '-orders.json'
    saveAs(blob, outName)
    ElMessage.success(`已导出 ${list.length} 条指令`)
  } catch (e) {
    ElMessage.error(e?.message || '导出指令失败')
  } finally {
    exportingName.value = ''
  }
}

async function fetchContent(name) {
  const res = await getPayloadConfigFileContent(name)
  return res.data || {}
}

async function openPreview(row) {
  try {
    const data = await fetchContent(row.name)
    dlg.mode = 'preview'
    dlg.name = data.name || row.name
    dlg.content = data.content || ''
    dlg.visible = true
  } catch (e) {
    ElMessage.error(e?.message || '读取失败')
  }
}

async function openEdit(row) {
  try {
    const data = await fetchContent(row.name)
    dlg.mode = 'edit'
    dlg.name = data.name || row.name
    dlg.content = data.content || ''
    dlg.visible = true
  } catch (e) {
    ElMessage.error(e?.message || '读取失败')
  }
}

function validateJson(text) {
  try {
    const parsed = JSON.parse(text)
    if (parsed === null || (typeof parsed !== 'object' && !Array.isArray(parsed))) {
      return 'JSON 根节点须为对象或数组'
    }
    return ''
  } catch (e) {
    return `JSON 格式错误: ${e.message || e}`
  }
}

async function saveEdit() {
  const err = validateJson(dlg.content)
  if (err) {
    ElMessage.error(err)
    return
  }
  dlg.saving = true
  try {
    const res = await savePayloadConfigFileContent(dlg.name, dlg.content)
    dlg.content = res.data?.content ?? dlg.content
    ElMessage.success(res.msg || '保存成功')
    dlg.visible = false
    await loadList()
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    dlg.saving = false
  }
}

async function downloadFile(row) {
  try {
    const data = await fetchContent(row.name)
    const blob = new Blob([data.content || ''], { type: 'application/json;charset=utf-8' })
    saveAs(blob, data.name || row.name)
  } catch (e) {
    ElMessage.error(e?.message || '下载失败')
  }
}

function downloadDlgContent() {
  const blob = new Blob([dlg.content || ''], { type: 'application/json;charset=utf-8' })
  saveAs(blob, dlg.name || 'config.json')
}

onMounted(loadList)
</script>

<style scoped>
.cfg-scroll {
  width: 100%;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-fill-color-blank);
}
.cfg-scroll :deep(.el-scrollbar__wrap) {
  overflow-x: hidden !important;
}
.cfg-scroll :deep(.el-scrollbar__bar.is-vertical) {
  right: 2px;
}
.cfg-textarea {
  display: block;
  box-sizing: border-box;
  width: 100%;
  min-height: 360px;
  margin: 0;
  padding: 12px 14px;
  border: none;
  outline: none;
  resize: none;
  overflow: hidden;
  background: transparent;
  color: var(--el-text-color-regular);
  font-family: Consolas, 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.45;
  white-space: pre;
  tab-size: 2;
}
.cfg-textarea[readonly] {
  cursor: default;
  color: var(--el-text-color-primary);
}
</style>
