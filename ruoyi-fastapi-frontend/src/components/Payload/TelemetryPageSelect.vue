<template>
  <el-select
    :model-value="modelValue"
    filterable
    :filter-method="onFilter"
    :size="size"
    :disabled="disabled"
    :clearable="clearable"
    :placeholder="placeholder"
    @visible-change="onVisible"
    @update:model-value="onUpdate"
    @change="onChange"
  >
    <el-option-group v-for="g in groups" :key="g.label" :label="g.label">
      <el-option
        v-for="p in g.options"
        :key="optionValue(p)"
        :label="optionLabel(p)"
        :value="optionValue(p)"
      />
    </el-option-group>
  </el-select>
</template>

<script setup>
/**
 * 遥测表下拉：XL / BIU 分组 + 可搜索模糊筛选。
 * Element Plus 自带 filter 是整段连续匹配，且自定义 filter-method 后必须自己过滤 v-for。
 * keepKey=当前选中项，避免筛掉后输入框只剩 raw value。
 */
import { loadTelemetryPagesCached } from '@/utils/telemetryPagesCache'
import { telemetryOptionLabel, groupTelemetryPages } from '@/utils/telemetryOptionLabel'

const props = defineProps({
  modelValue: { type: String, default: '' },
  /** 父组件已拉好的 page 列表；null 且 autoLoad 时本组件自己拉配置 */
  pages: { type: Array, default: null },
  /** 为 true 时 onMounted 拉遥测表列表（走进程内缓存，切换下拉不再请求） */
  autoLoad: { type: Boolean, default: false },
  /** 加载后若尚未选中则选第一项（文件/CAN 历史顶栏） */
  autoSelectFirst: { type: Boolean, default: false },
  size: { type: String, default: 'default' },
  disabled: { type: Boolean, default: false },
  clearable: { type: Boolean, default: false },
  placeholder: { type: String, default: '请选择遥测表' }
})

const emit = defineEmits(['update:modelValue', 'change', 'loaded'])

const filterQuery = ref('') // el-select 输入框内容；关掉下拉时清空
const loadedPages = ref([])

const pageList = computed(() => (props.pages != null ? props.pages : loadedPages.value))
const groups = computed(() =>
  groupTelemetryPages(pageList.value, filterQuery.value, props.modelValue)
)

function optionValue(p) {
  // 配置页用 key（BIU:FF）；表格 types 用 id
  return p?.key || p?.id || ''
}

function optionLabel(p) {
  return p?.label || telemetryOptionLabel(p)
}

function onFilter(q) {
  filterQuery.value = q || ''
}

function onVisible(open) {
  if (!open) filterQuery.value = ''
}

function onUpdate(v) {
  emit('update:modelValue', v)
}

function onChange(v) {
  emit('change', v)
}

async function loadPages() {
  if (!props.autoLoad) return
  loadedPages.value = await loadTelemetryPagesCached()
  emit('loaded', loadedPages.value)
  if (props.autoSelectFirst && !props.modelValue && loadedPages.value.length) {
    emit('update:modelValue', loadedPages.value[0].key)
  }
}

onMounted(loadPages)
</script>
