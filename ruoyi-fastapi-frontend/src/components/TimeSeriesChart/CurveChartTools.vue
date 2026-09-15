<template>
  <div class="icon-tool-group">
    <el-tooltip :content="cropMode ? '再次点击取消截取' : cropTip" placement="top">
      <span class="icon-tool-wrap">
        <el-button
          class="icon-tool-btn"
          :type="cropMode ? 'primary' : 'default'"
          :disabled="disabled"
          @click="$emit('crop')"
        >
          <el-icon><Crop /></el-icon>
        </el-button>
      </span>
    </el-tooltip>
    <el-tooltip :content="exportTip" placement="top">
      <span class="icon-tool-wrap">
        <el-button class="icon-tool-btn" :disabled="disabled" @click="$emit('export')">
          <el-icon><Download /></el-icon>
        </el-button>
      </span>
    </el-tooltip>
  </div>
</template>

<script setup>
import { Crop, Download } from '@element-plus/icons-vue'

defineProps({
  cropMode: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  cropTip: { type: String, default: '截取时间片段（拖选）' },
  exportTip: { type: String, default: '导出当前时间窗口数据为 CSV' }
})

defineEmits(['crop', 'export'])
</script>

<style scoped>
.icon-tool-group {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-top: 6px;
  flex-shrink: 0;
}
.icon-tool-wrap {
  display: inline-flex;
  line-height: 0;
}
.icon-tool-btn {
  width: 20px !important;
  height: 20px !important;
  min-width: 20px !important;
  margin: 0 !important;
  padding: 0 !important;
}
.icon-tool-btn :deep(.el-icon) {
  font-size: 12px;
}
</style>
