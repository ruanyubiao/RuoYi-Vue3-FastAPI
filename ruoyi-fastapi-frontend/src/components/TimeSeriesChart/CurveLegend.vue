<template>
  <div v-if="curves.length" class="curve-legend">
    <div v-for="c in curves" :key="c.key" class="legend-item">
      <span class="legend-dot" :style="{ background: c.color }" />
      <span class="legend-label">{{ c.field }} {{ c.name }}{{ c.unit ? ` (${c.unit})` : '' }}</span>
      <el-button class="legend-remove" circle size="small" @click="$emit('remove', c.key)">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { Close } from '@element-plus/icons-vue'

defineProps({
  curves: { type: Array, default: () => [] }
})

defineEmits(['remove'])
</script>

<style scoped>
.curve-legend {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  padding: 6px 0 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.legend-label {
  line-height: 1.3;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.legend-remove {
  width: 20px !important;
  height: 20px !important;
  min-height: 20px;
  padding: 0 !important;
  border: none;
  color: var(--el-text-color-secondary);
}
.legend-remove :deep(.el-icon) {
  font-size: 10px;
}
</style>
