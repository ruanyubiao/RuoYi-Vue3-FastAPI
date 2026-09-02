<template>
  <span class="tc-order-title">
    <span>{{ lineText }}</span>
    <el-tooltip
      v-if="tip"
      :content="tip"
      placement="top"
      :show-after="200"
    >
      <el-icon class="tc-order-title-tip"><question-filled /></el-icon>
    </el-tooltip>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import { orderTip } from '@/utils/telecontrolComponent'

const props = defineProps({
  order: { type: Object, default: null },
  byteLen: { type: [Number, String], default: '-' },
  showBytes: { type: Boolean, default: true }
})

const tip = computed(() => orderTip(props.order))

const lineText = computed(() => {
  const id = props.order?.id || ''
  const name = props.order?.name || ''
  if (!props.showBytes) return `${id} ${name}`.trim()
  const n = props.byteLen
  const len = n === '' || n === null || n === undefined ? '-' : n
  return `${id} - ${name} - ${len} 字节`
})
</script>

<style scoped>
.tc-order-title {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
}
.tc-order-title-tip {
  margin-left: 4px;
  flex-shrink: 0;
  font-size: 14px;
  color: var(--el-text-color-secondary);
  cursor: help;
  vertical-align: middle;
}
</style>
