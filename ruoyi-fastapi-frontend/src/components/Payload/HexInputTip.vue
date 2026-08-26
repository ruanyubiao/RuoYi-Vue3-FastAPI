<template>
  <el-tooltip
    placement="top"
    :show-after="200"
    effect="light"
    popper-class="hex-input-rule-tooltip"
  >
    <template #content>
      <div class="hex-rule">
        <div class="hex-rule-title">Hex 文本规则</div>
        <ul class="hex-rule-list">
          <li v-for="(line, i) in HEX_INPUT_RULE_LINES" :key="i">{{ line }}</li>
        </ul>
        <table class="hex-rule-table">
          <thead>
            <tr>
              <th>输入</th>
              <th>结果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="[src, dst] in HEX_INPUT_RULE_EXAMPLES" :key="src">
              <td><code>{{ src }}</code></td>
              <td><code>{{ dst }}</code></td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <el-icon class="hex-rule-icon" @click.stop><QuestionFilled /></el-icon>
  </el-tooltip>
</template>

<script setup>
/**
 * Hex 输入规则提示：悬停问号展示分段规则与示例。
 * 规则：只允许 0-9/A-F 与空白；空白分段；每段 2 字符 1 字节；奇数段在末字符前补 0。
 * 文案与示例来自 @/utils/payloadRawData。
 */
import { QuestionFilled } from '@element-plus/icons-vue'
import { HEX_INPUT_RULE_EXAMPLES, HEX_INPUT_RULE_LINES } from '@/utils/payloadRawData'
</script>

<style scoped>
.hex-rule-icon {
  margin-left: 4px;
  vertical-align: middle;
  cursor: help;
  color: var(--el-text-color-secondary);
}
</style>

<style>
.hex-input-rule-tooltip {
  max-width: 420px;
}
.hex-input-rule-tooltip .hex-rule-title {
  font-weight: 600;
  margin-bottom: 6px;
}
.hex-input-rule-tooltip .hex-rule-list {
  margin: 0 0 8px;
  padding-left: 18px;
  line-height: 1.55;
}
.hex-input-rule-tooltip .hex-rule-table {
  width: 100%;
  border-collapse: collapse;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
}
.hex-input-rule-tooltip .hex-rule-table th,
.hex-input-rule-tooltip .hex-rule-table td {
  text-align: left;
  padding: 2px 8px 2px 0;
  vertical-align: top;
}
.hex-input-rule-tooltip .hex-rule-table th {
  color: var(--el-text-color-secondary);
  font-weight: 500;
  font-family: inherit;
}
.hex-input-rule-tooltip .hex-rule-table code {
  font-family: inherit;
}
</style>
