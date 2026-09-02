<template>
  <span class="tc-comp-label">
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
</script>

<style scoped>
.tc-comp-label {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
}
.tc-comp-label-text {
  overflow: hidden;
  text-overflow: ellipsis;
}
.tc-comp-label-tip {
  margin-left: 4px;
  flex-shrink: 0;
  font-size: 14px;
  color: var(--el-text-color-secondary);
  cursor: help;
  vertical-align: middle;
}
</style>
