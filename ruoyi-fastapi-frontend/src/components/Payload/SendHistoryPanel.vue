<template>
  <el-drawer
    v-if="drawer"
    v-model="opened"
    direction="ltr"
    size="460px"
    append-to-body
    class="send-history-drawer"
  >
    <template #header>
      <div class="hist-head">
        <span class="hist-title">遥控历史</span>
        <div v-if="sourceOptions.length > 1" class="hist-sources">
          <button
            v-for="s in sourceOptions"
            :key="s.id"
            type="button"
            class="hist-source-btn"
            :class="{ 'is-active': s.id === activeId }"
            @click="selectSource(s.id)"
          >{{ s.label }}</button>
        </div>
        <el-button class="hist-clear" link type="danger" @click="clearCurrent">清空</el-button>
      </div>
    </template>
    <el-scrollbar class="hist-scroll">
      <div v-if="items.length" class="history-list">
        <div v-for="(h, i) in items" :key="i" class="history-item">
          <div class="history-summary">
            <el-tag :type="h.success ? 'success' : 'danger'" size="small" class="history-tag">{{ activeLabel || h.message }}</el-tag>
            <span class="history-time">{{ h.ts }}</span>
            <span class="history-name">{{ h.name }}</span>
          </div>
          <div class="history-hex">{{ h.hex }}</div>
        </div>
      </div>
      <el-empty v-else class="history-empty" description="暂无发送记录" :image-size="64" />
    </el-scrollbar>
  </el-drawer>
  <section v-else class="send-history-embed">
    <div class="hist-head">
      <span class="hist-title">遥控历史</span>
      <div v-if="sourceOptions.length > 1" class="hist-sources">
        <button
          v-for="s in sourceOptions"
          :key="s.id"
          type="button"
          class="hist-source-btn"
          :class="{ 'is-active': s.id === activeId }"
          @click="selectSource(s.id)"
        >{{ s.label }}</button>
      </div>
      <el-button class="hist-clear" link type="danger" @click="clearCurrent">清空</el-button>
    </div>
    <el-scrollbar class="hist-scroll">
      <div v-if="items.length" class="history-list">
        <div v-for="(h, i) in items" :key="i" class="history-item">
          <div class="history-summary">
            <el-tag :type="h.success ? 'success' : 'danger'" size="small" class="history-tag">{{ activeLabel || h.message }}</el-tag>
            <span class="history-time">{{ h.ts }}</span>
            <span class="history-name">{{ h.name }}</span>
          </div>
          <div class="history-hex">{{ h.hex }}</div>
        </div>
      </div>
      <el-empty v-else class="history-empty" description="暂无发送记录" :image-size="64" />
    </el-scrollbar>
  </section>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { clearTelecontrolHistory, getTelecontrolHistory } from '@/api/payload/telecontrol'

const props = defineProps({
  /** { id, label }[]，一个来源时也传数组 */
  sources: { type: Array, default: () => [] },
  /** 单板用抽屉；遥控指令页固定嵌入 */
  drawer: { type: Boolean, default: false }
})

const opened = defineModel({ type: Boolean, default: false })

const POLL_MS = 3000
const activeId = ref('')
const items = ref([])
let timer = null
let loadGen = 0

const sourceOptions = computed(() =>
  (props.sources || []).filter(s => s && s.id).map(s => ({
    id: String(s.id),
    label: String(s.label || s.id)
  }))
)

const activeLabel = computed(() =>
  sourceOptions.value.find(s => s.id === activeId.value)?.label || ''
)

const polling = computed(() => (props.drawer ? opened.value : true) && !!activeId.value)

function selectSource(id) {
  if (!id || id === activeId.value) return
  activeId.value = id
}

async function load() {
  const source = activeId.value
  if (!source || (props.drawer && !opened.value)) return
  const gen = ++loadGen
  try {
    const res = await getTelecontrolHistory(source, 50)
    if (gen !== loadGen || source !== activeId.value) return
    items.value = Array.isArray(res.data) ? res.data : []
  } catch {
    if (gen === loadGen) items.value = []
  }
}

function refresh() {
  if (!polling.value) return
  return load()
}

async function clearCurrent() {
  const source = activeId.value
  if (!source) return
  try {
    await clearTelecontrolHistory(source)
  } catch {
    ElMessage.error('清空失败')
    return
  }
  items.value = []
  ElMessage.success('发送历史已清空')
}

function startPoll() {
  stopPoll()
  if (!polling.value) return
  load()
  timer = setInterval(load, POLL_MS)
}

function stopPoll() {
  if (timer) clearInterval(timer)
  timer = null
}

watch(sourceOptions, (list) => {
  if (!list.some(s => s.id === activeId.value)) {
    activeId.value = list[0]?.id || ''
  }
}, { immediate: true })

watch(activeId, (id, prev) => {
  if (!prev || id === prev) return
  items.value = []
  if (polling.value) startPoll()
})

watch(polling, (on) => {
  if (on) startPoll()
  else stopPoll()
}, { immediate: true })

onActivated(() => {
  if (polling.value) startPoll()
})
onDeactivated(stopPoll)
onUnmounted(stopPoll)

defineExpose({ refresh })
</script>

<style scoped>
.send-history-embed {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.hist-head {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.send-history-embed .hist-head {
  flex: 0 0 auto;
  margin-bottom: 8px;
}
.hist-title {
  font-weight: 600;
  font-size: 13px;
  line-height: 1.4;
}
.hist-sources {
  display: inline-flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 10px;
  min-width: 0;
}
.hist-source-btn {
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  line-height: 1.4;
  color: var(--el-text-color-secondary);
  font-family: inherit;
}
.hist-source-btn:hover {
  color: var(--el-color-primary);
}
.hist-source-btn.is-active {
  color: var(--el-color-primary);
  font-weight: 500;
  cursor: default;
}
.hist-clear {
  margin-left: auto;
  padding-bottom: 0;
  height: auto;
  line-height: 1.4;
}
.hist-scroll {
  flex: 1;
  min-height: 0;
  height: 100%;
}
.history-list {
  padding-right: 4px;
}
.history-empty {
  padding: 24px 0;
}
.history-item {
  border-bottom: 1px dashed var(--el-border-color);
  padding: 8px 0;
  font-size: 12px;
}
.history-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.history-tag {
  flex-shrink: 0;
}
.history-time {
  flex-shrink: 0;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.history-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-hex {
  font-family: monospace;
  word-break: break-all;
  margin-top: 4px;
}
</style>

<style>
.send-history-drawer .el-drawer__body {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding-top: 0;
}
</style>
