<template>
  <div class="payload-tm-table" :class="levelClass">
    <div class="tm-header">
      <div v-if="!hideTitle" class="tm-head-left">
        <TelemetryPageSelect
          v-if="isMultiType"
          :model-value="normalizedType"
          :pages="typeList"
          :size="preset.controlSize"
          class="tm-key-select"
          @update:model-value="onTypeSelect"
        />
        <span v-else class="tm-title">{{ currentLabel }}</span>
      </div>
      <el-tag :size="preset.controlSize" :type="dataSource ? 'success' : 'info'">
        {{ dataSource || '无数据' }}
      </el-tag>
      <span class="tm-ts">刷新时间: {{ refreshTs || '-' }}</span>
      <span class="tm-ts">数据时间: {{ dataTs || '-' }}</span>
    </div>
    <div class="tm-table-wrap">
      <el-table
        :data="rows"
        v-loading="initialLoading"
        row-key="id"
        border
        stripe
        height="100%"
        :size="preset.tableSize"
        empty-text="暂无数据"
      >
        <el-table-column label="编号" :width="preset.idWidth">
          <template #default="{ row }">
            <el-tooltip
              v-if="defById[row.id]"
              placement="right"
              :show-after="200"
              effect="light"
              popper-class="tm-cfg-tooltip"
            >
              <template #content>
                <pre class="tm-cfg-json">{{ cfgJson(row.id) }}</pre>
              </template>
              <span class="id-cell">{{ row.id }}</span>
            </el-tooltip>
            <span v-else>{{ row.id }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="name"
          label="参数名称"
          :width="preset.nameWidth"
          :min-width="preset.nameMinWidth"
          show-overflow-tooltip
        />
        <el-table-column label="当前值" :width="preset.valueWidth">
          <template #default="{ row }">
            <span
              :class="cellClass(row.id)"
              class="value-cell"
              :title="enableCurveNav ? '双击查看曲线' : undefined"
              @dblclick="onValueDblClick(row)"
            >{{ row.show ?? row.value }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" :width="preset.unitWidth" />
        <el-table-column
          prop="hex"
          label="HEX"
          :min-width="preset.hexMinWidth"
          show-overflow-tooltip
        />
      </el-table>
    </div>
  </div>
</template>

<script>
// 模块级常量，可以在 defineProps 的 validator 中安全引用
const SOURCE_KINDS = ['live', 'db', 'file'];
</script>


<script setup>
/**
 * 遥测表展示组件。
 *
 * 数据来源由 sourceKind 决定：
 * - live：轮询 POST /payload/telemetry/table/batch，读 Redis 热层 payload:tm:*
 * - db / file：不请求热层；只渲染父组件注入的 externalSnap（解析/取帧之后）
 *
 * 历史页（历史 CAN、历史文件）下拉只改当前表类型，点「解析」才出数。
 */
import { useRouter } from 'vue-router'
import { getTelemetryTableBatch } from '@/api/payload/telemetry'
import { takeTelemetryCfg, saveTelemetryCfg, tmTypeCfgScope, isTelemetryCfgStale } from '@/utils/telemetryCfgCache'
import { telemetryOptionLabel } from '@/utils/telemetryOptionLabel'
import TelemetryPageSelect from '@/components/Payload/TelemetryPageSelect.vue'

/** 头部/表格尺寸档位：t1 整页 → t3 小区域 */
const LEVEL_PRESETS = {
  t1: {
    controlSize: 'default',
    tableSize: 'default',
    idWidth: 80,
    nameWidth: 320,
    nameMinWidth: undefined,
    valueWidth: 180,
    unitWidth: 80,
    hexMinWidth: 120
  },
  t2: {
    controlSize: 'small',
    tableSize: 'small',
    idWidth: 88,
    nameWidth: undefined,
    nameMinWidth: 180,
    valueWidth: 140,
    unitWidth: 72,
    hexMinWidth: 100
  },
  t3: {
    controlSize: 'small',
    tableSize: 'small',
    idWidth: 88,
    nameWidth: undefined,
    nameMinWidth: 140,
    valueWidth: 120,
    unitWidth: 64,
    hexMinWidth: 90
  }
}

const props = defineProps({
  /**
   * 遥测表类型列表，统一用数组传入：
   * - 1 项 → 头部显示标题
   * - 多项 → 头部显示下拉
   * 元素可为 'FF' 或 { id: 'D8', name: '慢遥测(全窗)' }
   */
  types: { type: Array, required: true },
  /**
   * 当前选中的表 key（如 BIU:FD）。
   * 多项时配合 v-model:type；未传或非法时回落到 types 第一项。
   */
  type: { type: String, default: '' },
  /**
   * 布局档位：t1 整页大表 / t2 中等 / t3 看板小区域。
   * 只改字号、列宽、控件 size，不影响取数。
   */
  level: {
    type: String,
    default: 't1',
    validator: v => ['t1', 't2', 't3'].includes(v)
  },
  /**
   * 实时轮询间隔（毫秒）。
   * <=0 时不轮询。历史页应设 0；即使误设正数，sourceKind 非 live 也不会发 batch。
   */
  pollMs: { type: Number, default: 1000 },
  /**
   * 数据来源：
   * - live：请求 table/batch，读 Redis 实时热层（默认，实时数据/相机/看板）
   * - db：历史库（CAN 归档），值只来自 externalSnap，选表不请求热层
   * - file：历史文件，同上
   * 请求 batch 时会原样带到 items[].source；后端非 live 也不回 Redis 行。
   */
  sourceKind: {
    type: String,
    default: 'live',
    validator: v => SOURCE_KINDS.includes(v)
  },
  /**
   * 是否允许双击「当前值」跳转到实时曲线页。
   * 历史回放页应关掉，避免跳到实时曲线。
   */
  enableCurveNav: { type: Boolean, default: true },
  /**
   * 多表时：若某表热层出现更新、更「有效」的数据，自动把 type 切过去。
   * 默认关；相机页开（D8/D9 跟最新帧走）。历史页不应开启。
   */
  autoSwitchType: { type: Boolean, default: false },
  /**
   * 隐藏左侧标题/表下拉（数据源标签与时间仍显示）。
   * 历史页的表下拉在工具栏，表格本身 hideTitle。
   */
  hideTitle: { type: Boolean, default: false },
  /**
   * 父组件注入的一帧快照（历史解析/取帧）。
   * 结构：{ type, rows, ts, dataSource, name, dataId? }
   * 有值时写入 snap 并重绘当前表；live 页一般不传。
   */
  externalSnap: { type: Object, default: null }
})

/** update:type：下拉/自动切表；data-change：当前表展示变了；snaps-change：多表缓存变了 */
const emit = defineEmits(['update:type', 'data-change', 'snaps-change'])

/** 双击当前值跳转实时曲线用 */
const router = useRouter()

/** 把 types 项收成 { id, name, family, label }；id 大写，label 给下拉显示 */
function normalizeOption(o) {
  const id = String((typeof o === 'string' ? o : o?.id || o?.key) || '')
    .trim()
    .toUpperCase()
  const name = typeof o === 'string' ? '' : o?.name || ''
  const localKey =
    typeof o === 'string' ? '' : String(o?.localKey || o?.local_key || '').trim()
  const customLabel = typeof o === 'string' ? '' : String(o?.label || '').trim()
  const family = typeof o === 'string' ? '' : String(o?.family || '').trim().toLowerCase()
  const displayId = localKey || id
  return {
    id,
    name,
    family,
    label: customLabel || telemetryOptionLabel({ family, localKey: displayId, name })
  }
}

/** 规范化后的可选表列表：[{ id, name, family, label }] */
const typeList = computed(() => (props.types || []).map(normalizeOption).filter(o => o.id))
/** 是否多项：头部用下拉而不是标题 */
const isMultiType = computed(() => typeList.value.length > 1)
/** 当前 types 的 id 列表；变化会触发重新拉 cfg（仅 live） */
const typeIds = computed(() => typeList.value.map(o => o.id))
/** 是否读 Redis 热层；db/file 只吃 externalSnap */
const isLiveSource = computed(() => props.sourceKind === 'live')

/** 实际展示的表 key：合法的 props.type，否则 types[0] */
const normalizedType = computed(() => {
  const explicit = String(props.type || '').trim().toUpperCase()
  if (explicit && typeList.value.some(o => o.id === explicit)) return explicit
  return typeList.value[0]?.id || explicit
})

/** 当前 level 对应的列宽/字号 */
const preset = computed(() => LEVEL_PRESETS[props.level] || LEVEL_PRESETS.t1)
/** 根节点 class，如 level-t1 */
const levelClass = computed(() => `level-${props.level}`)

/**
 * 多表内存缓存：type → snap。
 * snap 字段：type, rows, ts, dataId, name, dataSource, cfg, cfgDatetime, cfgMtime
 * 切表不丢，live 轮询按表叠值；历史页由 applyExternalSnap 写入。
 */
const snapByType = reactive({})
/** autoSwitchType 上次切到的有效类型；相同则不重复 emit，避免下拉抖动 */
const lastEffectiveType = ref('')

/** 当前展示表名（优先 cfg.name，否则 types 项 name/id） */
const tableName = ref('')
/** 当前表配置骨架行（有 id/name/unit，值为空）；有 cfg 时行序以此为准 */
const defRows = ref([])
/** 当前表字段定义：id → cfg 行对象（编号列 tooltip 用） */
const defById = ref({})
/** 当前下拉对应表的展示行（叠了值的骨架或 Redis/回放行） */
const rows = ref([])
/** 上一轮各 id 的展示值，用于变红高亮 */
const prevValues = ref({})
/** 相对上一轮发生变化的字段 id 集合 */
const changedIds = ref(new Set())
/** 首次拉 batch 或 types 变更时的表格 loading */
const initialLoading = ref(false)
/** 头部「数据源」标签：串口/网口参数，或 mysql/文件回放标记 */
const dataSource = ref('')
/** 该帧自身时间（热层 ts 或回放帧时间） */
const dataTs = ref('')
/** 本组件最近一次成功 batch 的本地时钟（历史页不走 batch 则可能为空） */
const refreshTs = ref('')
/** 热层 dataId；相同则后端不下发行，减少带宽 */
const dataId = ref('')
/** setInterval 句柄；pollMs<=0 或非 live 时为 null */
let pollTimer = null
/** 防止 refreshBatch 重入 */
let refreshing = false
/** 各表是否已拿到过 cfg（live 轮询时避免每轮都带 needCfg） */
const cfgLoaded = reactive({})

/** 头部标题：优先当前表 cfg 名，否则 types 项 name/id */
const currentLabel = computed(() => {
  if (tableName.value) return tableName.value
  const hit = typeList.value.find(o => o.id === normalizedType.value)
  return hit?.name || hit?.id || normalizedType.value
})

/** localStorage 配置缓存的 scope key（按表类型隔离） */
function cfgScope(type = normalizedType.value) {
  return tmTypeCfgScope(type)
}

/** 头部下拉改选：同步到父组件 v-model:type */
function onTypeSelect(v) {
  const next = String(v || '').toUpperCase()
  if (next && next !== normalizedType.value) {
    emit('update:type', next)
  }
}

/** 本地「刷新时间」显示用，精确到毫秒 */
function formatNow() {
  const d = new Date()
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

/** 空值：未定义 / null / 纯空白，不算「有遥测」 */
function isEmptyVal(v) {
  return v === undefined || v === null || String(v).trim() === ''
}

/** 当前值单元格 class：相对上一轮变了则变红 */
function cellClass(id) {
  return changedIds.value.has(id) ? 'cell-changed' : ''
}

/** 编号列 tooltip：该字段完整 cfg JSON */
function cfgJson(id) {
  const cfg = defById.value[id]
  return cfg ? JSON.stringify(cfg, null, 2) : ''
}

/** 由表定义生成空值行（id/name/unit 保留，value/show/hex 为空） */
function skeletonFromDef(data) {
  return (data?.row || [])
    .filter(r => r.id)
    .map(r => ({
      id: r.id || '',
      name: r.name || '',
      value: '',
      show: '',
      unit: r.unit || '',
      hex: ''
    }))
}

/** 是否至少有一行带非空展示值 */
function rowsHaveValues(rowList) {
  return (rowList || []).some(r => {
    const s = r?.show ?? r?.value
    return s !== '' && s != null && String(s).trim() !== ''
  })
}

/** 把数据时间字符串解析成毫秒时间戳；失败为 0（autoSwitch 比新旧用） */
function parseDataTsMs(ts) {
  if (!ts) return 0
  const t = Date.parse(String(ts).trim().replace(/-/g, '/'))
  return Number.isFinite(t) ? t : 0
}

/** 取或创建某 type 的 snap 槽（切表后仍保留各表最新数据） */
function ensureSnap(type) {
  const key = String(type || '').toUpperCase()
  if (!key) return null
  if (!snapByType[key]) {
    snapByType[key] = {
      type: key,
      rows: [],
      ts: '',
      dataId: '',
      name: '',
      dataSource: '',
      cfg: null,
      cfgDatetime: '',
      cfgMtime: ''
    }
  }
  return snapByType[key]
}

/** 写入该 type 的 cfg 到 snap；若是当前展示表则立刻套到表格 */
function applyCfgToType(type, cfg, meta = {}) {
  if (!cfg) return
  const snap = ensureSnap(type)
  snap.cfg = cfg
  if (cfg.name) snap.name = cfg.name
  if (meta.cfgDatetime != null) snap.cfgDatetime = meta.cfgDatetime
  if (meta.cfgMtime != null) snap.cfgMtime = meta.cfgMtime
  if (cfg.row?.length) {
    saveTelemetryCfg(cfgScope(type), {
      name: cfg.name || snap.name,
      tableKey: type,
      cfgRows: cfg.row,
      cfgName: cfg.name || '',
      cfgDatetime: meta.cfgDatetime || snap.cfgDatetime || '',
      cfgMtime: meta.cfgMtime || snap.cfgMtime || ''
    })
  }
  if (type === normalizedType.value) {
    applyCfgLocal(cfg)
  }
}

/** 把 cfg 套到当前表格的 defById / defRows / tableName（不改已有遥测值） */
function applyCfgLocal(cfg) {
  if (!cfg) return
  if (cfg.name) tableName.value = cfg.name
  const map = {}
  for (const r of cfg.row || []) {
    if (r.id) map[r.id] = r
  }
  defById.value = map
  defRows.value = skeletonFromDef(cfg)
}

/** 从 localStorage 恢复某表 cfg；无缓存返回 false */
function applyCachedCfgForType(type) {
  const cached = takeTelemetryCfg(cfgScope(type))
  if (!cached?.cfgRows?.length) return false
  const cfg = { name: cached.cfgName || cached.name || '', row: cached.cfgRows }
  applyCfgToType(type, cfg)
  const snap = ensureSnap(type)
  if (!snap.rows.length) {
    snap.rows = skeletonFromDef(cfg)
  }
  return true
}

/** 行序/名称/单位以 cfg 骨架为准，值按 id 从 next 叠上；无骨架则直接用 next */
function mergeRowsForDisplay(next, skeleton) {
  // 有配置骨架时：行序/名称/单位以 cfg 为准，值按 id 从 Redis 行叠上（避免旧解析字段盖住新配置）
  if (skeleton?.length) {
    const byId = new Map((next || []).map(r => [String(r?.id || ''), r]))
    return skeleton.map(s => {
      const v = byId.get(String(s.id || ''))
      return {
        id: s.id || '',
        name: s.name || '',
        unit: s.unit || '',
        value: v?.value ?? '',
        show: v?.show ?? v?.value ?? '',
        hex: v?.hex ?? ''
      }
    })
  }
  return next?.length ? next : []
}

/** 叠值到当前表格行，并标出相对上一轮变化的 id */
function applyRowsLocal(next) {
  const display = mergeRowsForDisplay(next, defRows.value)
  const changed = new Set()
  display.forEach(r => {
    const key = r.id
    const val = String(r.show ?? r.value ?? '')
    const prev = prevValues.value[key]
    if (prev !== undefined && !isEmptyVal(prev) && prev !== val) {
      changed.add(key)
    }
    prevValues.value[key] = val
  })
  changedIds.value = changed
  if (rows.value.length === display.length && rows.value.length) {
    const byId = new Map(display.map(r => [r.id, r]))
    let sameOrder = true
    for (let i = 0; i < rows.value.length; i++) {
      const id = rows.value[i].id
      const n = byId.get(id)
      if (!n || display[i]?.id !== id) {
        sameOrder = false
        break
      }
      rows.value[i].name = n.name
      rows.value[i].value = n.value
      rows.value[i].show = n.show
      rows.value[i].unit = n.unit
      rows.value[i].hex = n.hex
    }
    if (!sameOrder) rows.value = display
  } else {
    rows.value = display
  }
}

/** 用当前 type 的 snap 刷新表格展示（切表/轮询后；不重新请求） */
function paintActiveFromSnap() {
  const type = normalizedType.value
  const snap = ensureSnap(type)
  if (snap.cfg) applyCfgLocal(snap.cfg)
  else applyCachedCfgForType(type)
  tableName.value = snap.name || tableName.value
  dataTs.value = snap.ts || ''
  dataId.value = snap.dataId ?? ''
  dataSource.value = snap.dataSource || ''
  applyRowsLocal(snap.rows || [])
}

/** 通知父组件：当前表展示行/时间变了 */
function emitDataChange() {
  emit('data-change', {
    type: normalizedType.value,
    rows: rows.value,
    ts: dataTs.value,
    dataId: dataId.value,
    dataSource: dataSource.value,
    name: tableName.value,
    snaps: getAllSnaps()
  })
}

/** 通知父组件：多表 snap 缓存变了（相机看板跟这个） */
function emitSnapsChange() {
  emit('snaps-change', getAllSnaps())
}

/** 将 batch 单项写入对应表 snap（cfg / rows / ts / dataId） */
function ingestItem(item, { needCfgHint = false } = {}) {
  const type = String(item?.type || '').toUpperCase()
  if (!type) return
  const snap = ensureSnap(type)
  if (item.cfgDatetime != null) snap.cfgDatetime = item.cfgDatetime
  if (item.cfgMtime != null) snap.cfgMtime = item.cfgMtime
  if (item.cfg) {
    applyCfgToType(type, item.cfg, {
      cfgDatetime: item.cfgDatetime || snap.cfgDatetime || '',
      cfgMtime: item.cfgMtime || snap.cfgMtime || ''
    })
    cfgLoaded[type] = true
  } else if (
    isTelemetryCfgStale(cfgScope(type), {
      cfgDatetime: item.cfgDatetime,
      cfgMtime: item.cfgMtime
    })
  ) {
    cfgLoaded[type] = false
  }
  if (item.name) snap.name = item.name
  if (item.ts) snap.ts = String(item.ts)
  if (item.dataId != null && item.dataId !== '') snap.dataId = item.dataId
  if (item.dataSource != null || item.srcParam != null) {
    snap.dataSource = item.dataSource || item.srcParam || ''
  }
  if (item.changed !== false && Array.isArray(item.rows)) {
    snap.rows = item.rows
  } else if (!snap.rows.length && item.cfg) {
    snap.rows = skeletonFromDef(item.cfg)
  } else if (!snap.rows.length && needCfgHint) {
    applyCachedCfgForType(type)
  }
}

/** snap 是否有真实遥测（有 ts/dataId 且行有值） */
function snapHasValidData(type) {
  const snap = snapByType[String(type || '').toUpperCase()]
  if (!snap) return false
  const hasReal = !!(snap.ts || (snap.dataId != null && snap.dataId !== '' && Number(snap.dataId) !== 0))
  return hasReal && rowsHaveValues(snap.rows)
}

/**
 * 有效数据类型：多表都有值时取数据时间最新的；无有效数据返回空。
 * 与 getActiveType（当前下拉选中）不同，可与下拉不一致。
 */
function computeEffectiveType() {
  const ids = typeIds.value
  const ok = ids.filter(id => snapHasValidData(id))
  if (!ok.length) return ''
  if (ok.length === 1) return ok[0]
  let best = ok[0]
  let bestTs = parseDataTsMs(snapByType[best]?.ts)
  for (let i = 1; i < ok.length; i++) {
    const id = ok[i]
    const ts = parseDataTsMs(snapByType[id]?.ts)
    if (ts >= bestTs) {
      best = id
      bestTs = ts
    }
  }
  return best
}

/** 有效类型变化时才切下拉（autoSwitchType）；同一有效类型不重复 emit */
function maybeAutoSwitch() {
  if (!props.autoSwitchType) return
  const next = computeEffectiveType()
  if (!next) return
  // 有效类型未变（例如仍是 D8）→ 不切下拉
  if (next === lastEffectiveType.value) return
  lastEffectiveType.value = next
  if (normalizedType.value !== next) {
    emit('update:type', next)
  }
}

/**
 * 向后端拉一批表的最新热层。
 * 非 live 直接 return。items[].source 带到 /table/batch，后端 db/file 也不回 Redis 行。
 */
async function refreshBatch({ showLoading = false, needCfg = false } = {}) {
  const ids = typeIds.value
  // 历史页选表不应打热层；解析后的帧走 externalSnap
  if (!isLiveSource.value || refreshing || !ids.length) return
  refreshing = true
  if (showLoading) initialLoading.value = true
  try {
    const items = ids.map(type => {
      const snap = ensureSnap(type)
      const stale = isTelemetryCfgStale(cfgScope(type), {
        cfgDatetime: snap.cfgDatetime,
        cfgMtime: snap.cfgMtime
      })
      const wantCfg = needCfg || !cfgLoaded[type] || stale
      const did = snap.dataId != null && snap.dataId !== '' ? String(snap.dataId) : undefined
      return {
        type,
        dataId: did || undefined,
        needCfg: wantCfg,
        source: props.sourceKind
      }
    })
    const res = await getTelemetryTableBatch(items)
    refreshTs.value = formatNow()
    const rowsUpdatedTypes = new Set()
    const cfgUpdatedTypes = new Set()
    let needCfgAgain = false
    for (const item of res.data?.items || []) {
      const t = String(item?.type || '').toUpperCase()
      const rowsUpdated = item?.changed !== false && Array.isArray(item.rows)
      ingestItem(item, { needCfgHint: needCfg })
      if (t && rowsUpdated) rowsUpdatedTypes.add(t)
      if (t && item.cfg) cfgUpdatedTypes.add(t)
      if (t && (needCfg || item.cfg)) cfgLoaded[t] = true
      // 仅带回时间戳、配置已过期且本轮未带 cfg → 再拉一轮
      if (
        t &&
        !item.cfg &&
        isTelemetryCfgStale(cfgScope(t), {
          cfgDatetime: item.cfgDatetime,
          cfgMtime: item.cfgMtime
        })
      ) {
        cfgLoaded[t] = false
        needCfgAgain = true
      }
    }
    const activeBefore = normalizedType.value
    maybeAutoSwitch()
    // 无新数据（dataId/时间未变）不重绘表格，保留变红高亮；有新行或切表/拉 cfg 再刷
    const activeAfter = normalizedType.value
    if (
      needCfg ||
      showLoading ||
      activeAfter !== activeBefore ||
      rowsUpdatedTypes.has(activeAfter) ||
      cfgUpdatedTypes.has(activeAfter)
    ) {
      paintActiveFromSnap()
    }
    emitDataChange()
    emitSnapsChange()
    if (needCfgAgain && !needCfg) {
      refreshing = false
      await refreshBatch({ showLoading: false, needCfg: true })
      return
    }
  } catch {
    for (const id of ids) applyCachedCfgForType(id)
    paintActiveFromSnap()
    emitDataChange()
    emitSnapsChange()
  } finally {
    refreshing = false
    if (showLoading) initialLoading.value = false
  }
}

/** 父组件注入的一帧（历史解析/取帧）写入 snap 并重绘；live 一般不走这里 */
function applyExternalSnap(snap) {
  if (!snap) return
  const type = String(snap.type || normalizedType.value || '').toUpperCase()
  if (!type) return
  const s = ensureSnap(type)
  if (Array.isArray(snap.rows)) s.rows = snap.rows
  if (snap.ts != null) s.ts = snap.ts
  if (snap.dataSource != null) s.dataSource = snap.dataSource
  if (snap.name) s.name = snap.name
  if (snap.dataId != null) s.dataId = snap.dataId
  refreshTs.value = formatNow()
  paintActiveFromSnap()
  emitDataChange()
}

watch(
  () => {
    const snap = props.externalSnap
    if (!snap) return ''
    return [snap.dataId, snap.ts, snap.type, Array.isArray(snap.rows) ? snap.rows.length : 0].join('|')
  },
  () => {
    if (props.externalSnap) applyExternalSnap(props.externalSnap)
  }
)

/** live 且 pollMs>0 时按间隔 refreshBatch；历史页直接 return */
function startPoll() {
  stopPoll()
  if (!isLiveSource.value) return
  const ms = Number(props.pollMs)
  if (!ms || ms <= 0) return
  pollTimer = setInterval(() => refreshBatch({ showLoading: false, needCfg: false }), Math.max(200, ms))
}

/** 清掉轮询定时器（切页 keep-alive / 卸载时必须停，否则多页同时 batch） */
function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

/** 切表：清空变红高亮，从该表 snap 重绘（不重新请求） */
function switchActiveTypeView() {
  prevValues.value = {}
  changedIds.value = new Set()
  paintActiveFromSnap()
  emitDataChange()
}

/** 双击当前值：仅 live 且 enableCurveNav 时跳实时曲线 */
function onValueDblClick(row) {
  if (!props.enableCurveNav || !row?.id) return
  router.push({
    path: '/telemetry/curve',
    query: {
      type: normalizedType.value,
      field: row.id,
      from: 'table'
    }
  })
}

/** —— 对外读缓存 API —— */
/** 拷贝当前 types 下各表 snap（给父组件/相机看板）。不含 cfg 原文。 */
function getAllSnaps() {
  const out = {}
  for (const id of typeIds.value) {
    const s = snapByType[id]
    if (!s) continue
    out[id] = {
      type: id,
      rows: Array.isArray(s.rows) ? s.rows.map(r => ({ ...r })) : [],
      ts: s.ts || '',
      dataId: s.dataId ?? '',
      name: s.name || '',
      dataSource: s.dataSource || ''
    }
  }
  return out
}

/** 读某一张表的 snap 拷贝；type 空则用当前选中表 */
function getTable(type) {
  const key = String(type || normalizedType.value || '').toUpperCase()
  const s = snapByType[key]
  if (!s) return null
  return {
    type: key,
    rows: Array.isArray(s.rows) ? s.rows.map(r => ({ ...r })) : [],
    ts: s.ts || '',
    dataId: s.dataId ?? '',
    name: s.name || '',
    dataSource: s.dataSource || ''
  }
}

/** 读某表某字段行拷贝；没有则 null */
function getField(type, fieldId) {
  const table = getTable(type)
  if (!table || !fieldId) return null
  const id = String(fieldId).toUpperCase()
  const row = (table.rows || []).find(r => String(r?.id || '').toUpperCase() === id)
  return row ? { ...row } : null
}

/** 按 id 列表批量取字段行（缺的丢掉） */
function getFields(type, fieldIds) {
  const ids = (fieldIds || []).map(x => String(x).toUpperCase())
  const table = getTable(type)
  if (!table) return []
  const byId = new Map((table.rows || []).map(r => [String(r?.id || '').toUpperCase(), r]))
  return ids.map(id => (byId.has(id) ? { ...byId.get(id) } : null)).filter(Boolean)
}

/** 当前下拉选中的表类型（用户选择或 autoSwitch 写入） */
function getActiveType() {
  return normalizedType.value || ''
}

/** 缓存中数据最新且有有效值的表类型（可与下拉不一致；相机统计区/分辨率跟这个） */
function getEffectiveType() {
  return computeEffectiveType()
}

watch(
  () => normalizedType.value,
  (t, old) => {
    if (!t || t === old) return
    switchActiveTypeView()
  }
)

watch(
  () => props.pollMs,
  () => {
    if (pollTimer) startPoll()
  }
)

watch(
  typeIds,
  (ids, oldIds) => {
    const a = (ids || []).join('|')
    const b = (oldIds || []).join('|')
    if (a === b) return
    lastEffectiveType.value = ''
    if (!isLiveSource.value) {
      for (const snap of Object.values(snapByType)) {
        snap.rows = []
        snap.ts = ''
        snap.dataId = ''
        snap.dataSource = ''
      }
      switchActiveTypeView()
      return
    }
    refreshBatch({ showLoading: true, needCfg: true })
  }
)

onMounted(async () => {
  for (const id of typeIds.value) applyCachedCfgForType(id)
  paintActiveFromSnap()
  if (!isLiveSource.value || Number(props.pollMs) <= 0) {
    if (props.externalSnap) applyExternalSnap(props.externalSnap)
    return
  }
  initialLoading.value = true
  try {
    await refreshBatch({ showLoading: false, needCfg: true })
  } finally {
    initialLoading.value = false
  }
  startPoll()
})

/** keep-alive 切走不会 unmount，必须在 deactivated 停轮询，否则多页同时 batch */
onActivated(() => {
  startPoll()
})

onDeactivated(() => {
  stopPoll()
})

onUnmounted(stopPoll)

/** 给父组件/ref 用：refresh 只 live 有效；历史页用 applyExternalSnap */
defineExpose({
  refresh: () => refreshBatch({ showLoading: false, needCfg: false }),
  refreshBatch,
  getAllSnaps,
  getTable,
  getField,
  getFields,
  getActiveType,
  getEffectiveType,
  applyExternalSnap
})
</script>

<style scoped>
.payload-tm-table {
  height: 100%;
  max-height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}
.tm-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.tm-head-left {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}
.tm-title {
  margin: 0;
  font-weight: 600;
  line-height: 1.3;
}
.tm-table-wrap {
  flex: 1;
  min-height: 0;
}
.tm-ts {
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}
.value-cell {
  user-select: none;
}
.value-cell[title] {
  cursor: pointer;
}
.id-cell {
  cursor: help;
}
.cell-changed {
  color: #f56c6c;
}

.level-t1 .tm-header {
  margin-bottom: 12px;
  padding: 4px 0;
}
.level-t1 .tm-title {
  font-size: 16px;
}
.level-t1 .tm-ts {
  margin-left: 8px;
  font-size: 13px;
}
.level-t1 .tm-key-select {
  width: 280px;
}

.level-t2 .tm-header {
  margin-bottom: 8px;
  padding: 2px 0;
  gap: 8px;
}
.level-t2 .tm-title {
  font-size: 14px;
}
.level-t2 .tm-ts {
  font-size: 12px;
}
.level-t2 .tm-key-select {
  width: 180px;
}

.level-t3 .tm-header {
  margin-bottom: 4px;
  padding: 0;
  gap: 6px;
}
.level-t3 .tm-title {
  font-size: 13px;
}
.level-t3 .tm-ts {
  font-size: 12px;
}
.level-t3 .tm-key-select {
  width: 168px;
}
</style>

<style>
.tm-cfg-tooltip .tm-cfg-json {
  margin: 0;
  padding: 0;
  max-height: 60vh;
  overflow: auto;
  white-space: pre;
  color: inherit;
  font-family: var(--el-font-family-mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace);
  font-size: 12px;
  line-height: 1.45;
}
</style>
