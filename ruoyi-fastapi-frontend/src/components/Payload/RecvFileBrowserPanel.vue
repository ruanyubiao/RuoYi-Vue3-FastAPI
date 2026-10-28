<template>
  <div class="browser">
    <div class="browser-nav">
      <nav class="crumb-trail" aria-label="目录路径">
        <template v-for="(item, idx) in crumbItems" :key="item.key">
          <span v-if="idx > 0" class="crumb-sep">/</span>
          <button
            type="button"
            class="crumb-btn"
            :class="{
              'is-home': item.kind === 'home',
              'is-tail': idx === crumbItems.length - 1
            }"
            :title="item.kind === 'home' ? '首页' : undefined"
            @click="$emit('go-crumb', item)"
          >
            <span v-if="item.kind === 'home'" class="home-glyph" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="18" height="18" focusable="false">
                <path fill="#E85D4C" d="M3 11.5 12 3l9 8.5V11l-9-8.5L3 11v.5z" />
                <path fill="#C9483A" d="M12 3 21 11.5V13l-9-8.5L3 13v-1.5L12 3z" />
                <path fill="#F2EDE6" d="M6.2 11.2h11.6V21H6.2z" />
                <path fill="#5B9BD5" d="M9.2 13.4h2.4V16H9.2zm3.2 0h2.4V16h-2.4z" />
                <path fill="#8B5A2B" d="M10.7 17.2h2.6V21h-2.6z" />
              </svg>
            </span>
            <span>{{ item.label }}</span>
          </button>
        </template>
      </nav>
      <el-button v-if="!isDownload" class="nav-upload" @click="$emit('pick-upload')">上传</el-button>
    </div>
    <el-table
      :ref="el => $emit('set-table-ref', el)"
      :data="entries"
      :height="tableHeight"
      :highlight-current-row="!multiple"
      row-key="name"
      @row-click="row => $emit('row-click', row)"
      @row-dblclick="row => $emit('row-dblclick', row)"
      @selection-change="rows => $emit('selection-change', rows)"
    >
      <el-table-column
        v-if="multiple"
        type="selection"
        width="48"
        :selectable="rowSelectable"
      />
      <el-table-column label="名称" min-width="380">
        <template #default="{ row }">
          <span
            v-if="isDownload && row && !row.isDir && row.selectable"
            class="file-name-link"
            @click.stop="$emit('download-name', row)"
          >
            📄 {{ row.name }}
          </span>
          <span v-else>{{ row.isDir ? '📁' : '📄' }} {{ row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          {{ row.isDir ? '文件夹' : '文件' }}
        </template>
      </el-table-column>
      <el-table-column label="大小" width="110" align="right">
        <template #default="{ row }">
          {{ sizeText(row) }}
        </template>
      </el-table-column>
    </el-table>
    <div v-if="includeFooter" class="browser-footer">
      <div class="browser-footer-left">
        <el-button circle icon="Refresh" title="刷新" @click="$emit('refresh')" />
        <el-checkbox
          :model-value="showAll"
          @update:model-value="v => $emit('update:show-all', v)"
        >
          显示所有文件
        </el-checkbox>
      </div>
      <div>
        <el-button v-if="showCancel" @click="$emit('cancel')">取消</el-button>
        <el-button
          type="primary"
          :disabled="!hasSelection"
          :loading="downloading"
          @click="$emit('primary')"
        >
          {{ isDownload ? '下载' : '确认' }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  entries: { type: Array, default: () => [] },
  crumbItems: { type: Array, default: () => [] },
  showAll: { type: Boolean, default: false },
  isDownload: { type: Boolean, default: false },
  /** 是否已选中可操作的文件（单选或多选） */
  hasSelection: { type: Boolean, default: false },
  downloading: { type: Boolean, default: false },
  tableHeight: { type: [Number, String], default: 360 },
  showCancel: { type: Boolean, default: true },
  includeFooter: { type: Boolean, default: true },
  /** 文件多选；目录不可勾选 */
  multiple: { type: Boolean, default: false }
})

defineEmits([
  'go-crumb',
  'pick-upload',
  'row-click',
  'row-dblclick',
  'download-name',
  'refresh',
  'update:show-all',
  'primary',
  'cancel',
  'set-table-ref',
  'selection-change'
])

function rowSelectable(row) {
  return !!(row && !row.isDir && row.selectable)
}

function trimSizeText(text) {
  if (!text.includes('.')) return text
  return text.replace(/0+$/, '').replace(/\.$/, '')
}

function sizeText(row) {
  if (!row || row.isDir || row.size == null || row.size === '') return ''
  const bytes = Number(row.size)
  if (!Number.isFinite(bytes) || bytes < 0) return ''
  if (bytes === 0) return '0 B'
  // 换算仍按 1024；升单位阈值用 1000，避免出现 1013.11 KB 这类显示
  const KB = 1024
  const MB = 1024 * KB
  const GB = 1024 * MB
  let value
  let unit
  if (bytes >= 1000 * MB) {
    value = bytes / GB
    unit = 'GB'
  } else if (bytes >= 1000 * KB) {
    value = bytes / MB
    unit = 'MB'
  } else if (bytes >= 1000) {
    value = bytes / KB
    unit = 'KB'
  } else {
    return `${bytes} B`
  }
  return `${trimSizeText(value.toFixed(2))} ${unit}`
}
</script>

<style scoped>
.browser-nav {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  min-width: 0;
}
.crumb-trail {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.crumb-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin: 0;
  padding: 2px 8px;
  border: none;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
  border-radius: 6px;
  transition: background-color 0.15s ease, color 0.15s ease;
}
.crumb-btn.is-home {
  padding-left: 6px;
}
.crumb-btn:hover {
  background: var(--el-fill-color-dark);
  color: var(--el-text-color-primary);
}
.crumb-btn.is-home:hover .home-glyph {
  transform: scale(1.12);
}
.home-glyph {
  display: inline-flex;
  transition: transform 0.15s ease;
}
.crumb-sep {
  color: var(--el-text-color-secondary);
  padding: 0 2px;
  user-select: none;
}
.crumb-btn.is-tail {
  color: var(--el-text-color-primary);
  font-weight: 500;
}
.nav-upload {
  margin-left: auto;
  flex-shrink: 0;
}
.browser-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  margin-top: 12px;
}
.browser-footer-left {
  display: flex;
  align-items: center;
  gap: 20px;
}
.file-name-link {
  color: var(--el-color-primary);
  cursor: pointer;
}
.file-name-link:hover {
  text-decoration: underline;
}
.browser :deep(.el-table) {
  --el-table-current-row-bg-color: rgba(64, 158, 255, 0.18);
}
.browser :deep(.el-table__body tr.current-row > td.el-table__cell) {
  background-color: rgba(64, 158, 255, 0.18) !important;
}
.browser :deep(.el-table__body tr.current-row:hover > td.el-table__cell) {
  background-color: rgba(64, 158, 255, 0.34) !important;
}
</style>
