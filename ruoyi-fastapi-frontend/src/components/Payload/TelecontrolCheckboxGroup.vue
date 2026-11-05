<template>
  <div class="cg">
    <div v-for="(item, i) in items" :key="i" class="cg-item">
      <div class="cg-head">
        <span v-if="item.name" class="cg-name">{{ item.name }}</span>
        <el-checkbox
          :model-value="isOn(i)"
          @change="(val) => toggle(i, val)"
        />
      </div>
      <div class="cg-body">
        <template v-for="(child, j) in item.component || []" :key="j">
          <div v-if="childType(child) === 'checkboxgroup'" class="cg-nested">不支持嵌套复选框组</div>
          <div v-else-if="childType(child) !== 'fixed'" class="cg-field">
            <span class="cg-label">{{ child.title || child.name || `参数${j + 1}` }}</span>
            <el-input-number
              v-if="childType(child) === 'number'"
              :model-value="cell(i, j)"
              class="cg-control"
              :disabled="!isOn(i)"
              :min="numBound(child.minVal)"
              :max="numBound(child.maxVal)"
              :precision="numberPrecision(child)"
              :step="numberStep(child)"
              :step-strictly="isIntegerDataType(child)"
              @update:model-value="(val) => setCell(i, j, val)"
            />
            <el-select
              v-else-if="childType(child) === 'select'"
              :model-value="cell(i, j)"
              class="cg-control"
              :disabled="!isOn(i)"
              @update:model-value="(val) => setCell(i, j, val)"
            >
              <el-option
                v-for="(label, key) in child.options || {}"
                :key="key"
                :label="label"
                :value="key"
              />
            </el-select>
            <el-input
              v-else
              :model-value="cell(i, j)"
              class="cg-control"
              :disabled="!isOn(i)"
              @update:model-value="(val) => setCell(i, j, val)"
            />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import {
  checkboxMaskBits,
  formatCheckboxMask,
  isIntegerDataType,
  numberPrecision,
  numberStep,
  numBound,
  parseCheckboxMask,
  resolveComponentValue
} from '@/utils/telecontrolComponent'

const props = defineProps({
  comp: { type: Object, required: true },
  modelValue: { type: Object, default: null }
})

const emit = defineEmits(['update:modelValue', 'change'])

const items = computed(() => (Array.isArray(props.comp?.group) ? props.comp.group : []))

function childType(child) {
  return String(child?.componentType || 'fixed').toLowerCase()
}

function baseValue() {
  const rows = items.value.map((item) => {
    const children = Array.isArray(item?.component) ? item.component : []
    return children.map((child) => resolveComponentValue(child))
  })
  const bits = checkboxMaskBits(props.comp)
  const saved = props.modelValue
  const mask = formatCheckboxMask(
    parseCheckboxMask(saved && typeof saved === 'object' ? saved.mask : 0, bits),
    bits
  )
  const savedRows = saved && Array.isArray(saved.values) ? saved.values : []
  return {
    mask,
    values: rows.map((row, i) => row.map((fallback, j) => {
      const got = savedRows[i]?.[j]
      return got === undefined || got === null ? fallback : got
    }))
  }
}

function isOn(index) {
  const mask = parseCheckboxMask(baseValue().mask, checkboxMaskBits(props.comp))
  return (mask & (1n << BigInt(index))) !== 0n
}

function cell(i, j) {
  return baseValue().values[i]?.[j]
}

function commit(next) {
  emit('update:modelValue', next)
  emit('change', next)
}

function toggle(index, on) {
  const next = baseValue()
  const bits = checkboxMaskBits(props.comp)
  let mask = parseCheckboxMask(next.mask, bits)
  const bit = 1n << BigInt(index)
  mask = on ? (mask | bit) : (mask & ~bit)
  next.mask = formatCheckboxMask(mask, bits)
  commit(next)
}

function setCell(i, j, val) {
  const next = baseValue()
  next.values[i][j] = val
  commit(next)
}
</script>

<style scoped>
.cg {
  width: 100%;
}
.cg-item + .cg-item {
  margin-top: 8px;
}
.cg-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 24px;
}
.cg-name {
  line-height: 1.4;
}
.cg-body {
  margin-top: 4px;
}
.cg-field {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.cg-label {
  flex: 0 0 120px;
  line-height: 1.4;
  color: var(--el-text-color-regular);
}
.cg-control {
  width: 180px;
  max-width: 100%;
}
.cg-nested {
  margin-top: 4px;
  color: var(--el-color-danger);
}
</style>
