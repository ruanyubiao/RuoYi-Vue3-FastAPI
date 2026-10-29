<template>
  <span class="tc-comp-label" :class="sizeClass" :title="displayLabel">
    <span class="tc-comp-label-text">{{ displayLabel }}</span>
    <el-tooltip
      v-if="displayTip"
      :content="displayTip"
      placement="top"
      :show-after="200"
    >
      <el-icon class="tc-comp-label-tip"><question-filled /></el-icon>
    </el-tooltip>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import { componentLabel, componentTip } from '@/utils/telecontrolComponent'

const props = defineProps({
  comp: { type: Object, default: null },
  index: { type: Number, default: 0 },
  label: { type: String, default: '' }
})

const displayLabel = computed(() => props.label || componentLabel(props.comp, props.index))
const displayTip = computed(() => componentTip(props.comp))

/** 超长标题缩小字号，减少折行、减轻右对齐参差感 */
const sizeClass = computed(() => {
  const n = Array.from(String(displayLabel.value || '')).length
  if (n >= 30) return 'tc-comp-label--xs'
  if (n >= 15) return 'tc-comp-label--sm'
  return ''
})
</script>

<style scoped>
.tc-comp-label {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  gap: 2px;
}
.tc-comp-label-text {
  white-space: normal;
  word-break: break-word;
  line-height: 1.35;
  text-align: inherit;
}
.tc-comp-label--sm .tc-comp-label-text {
  font-size: 12px;
}
.tc-comp-label--xs .tc-comp-label-text {
  font-size: 11px;
  line-height: 1.3;
}
.tc-comp-label-tip {
  flex-shrink: 0;
  font-size: 14px;
  color: var(--el-text-color-secondary);
  cursor: help;
  vertical-align: middle;
}
</style>
