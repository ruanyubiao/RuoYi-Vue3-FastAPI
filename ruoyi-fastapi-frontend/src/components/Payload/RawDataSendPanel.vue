<template>
  <div class="raw-send-panel">
    <div v-if="title" class="send-title">{{ title }}</div>
    <slot name="before" />
    <el-form-item :label="dataLabel">
      <el-input
        :model-value="modelValue.text"
        :disabled="disabled"
        :placeholder="placeholder"
        class="send-input"
        @update:model-value="onTextInput"
        @blur="onTextBlur"
      />
    </el-form-item>
    <el-form-item class="hex-form-item">
      <div class="hex-inline">
        <el-checkbox
          :model-value="modelValue.isHex"
          :disabled="disabled"
          class="hex-checkbox"
          @click.prevent="toggleHex"
        >HEX</el-checkbox>
        <el-checkbox
          :model-value="modelValue.parseEscape"
          :disabled="disabled || modelValue.isHex"
          class="hex-checkbox"
          @update:model-value="onParseEscapeChange"
        >解析转义符</el-checkbox>
        <el-select
          :model-value="modelValue.lineEnding"
          :disabled="disabled"
          class="line-ending-select"
          @update:model-value="onLineEndingChange"
        >
          <el-option v-for="o in LINE_ENDING_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
      </div>
    </el-form-item>
    <el-form-item label=" ">
      <el-button type="success" :disabled="disabled || sending" :loading="sending" @click="onSend">发送</el-button>
    </el-form-item>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import {
  HEX_INPUT_WARN,
  LINE_ENDING_OPTIONS,
  buildRawSendHex,
  hexToPrintableText,
  isHexText,
  normalizeHexDisplay,
  textToHex
} from '@/utils/payloadRawData'

const props = defineProps({
  modelValue: {
    type: Object,
    required: true
  },
  disabled: { type: Boolean, default: false },
  sending: { type: Boolean, default: false },
  title: { type: String, default: '' },
  dataLabel: { type: String, default: '数据' },
  placeholder: { type: String, default: '输入数据' }
})

const emit = defineEmits(['update:modelValue', 'send'])

function patch(partial) {
  emit('update:modelValue', { ...props.modelValue, ...partial })
}

function onTextInput(next) {
  if (props.modelValue.isHex && !isHexText(next, { input: true })) {
    ElMessage.warning(HEX_INPUT_WARN)
    return
  }
  patch({ text: next })
}

function onTextBlur() {
  if (!props.modelValue.isHex) return
  const raw = String(props.modelValue.text || '')
  if (!raw.trim()) return
  if (!isHexText(raw, { input: true })) {
    ElMessage.warning(HEX_INPUT_WARN)
    return
  }
  const norm = normalizeHexDisplay(raw)
  if (norm) patch({ text: norm })
}

function onParseEscapeChange(val) {
  patch({ parseEscape: !!val })
}

function onLineEndingChange(val) {
  patch({ lineEnding: val || 'none' })
}

function toggleHex() {
  if (props.disabled) return
  // 完全受控：转换失败时不改 isHex，避免 el-checkbox 内部状态与 model 不同步
  if (!props.modelValue.isHex) {
    // 普通文本 → HEX：按字符编码转换，保留前后空格（不 trim）；与解析转义符无关
    const raw = String(props.modelValue.text ?? '')
    const text = raw.length ? textToHex(raw) : ''
    patch({ isHex: true, text })
    return
  }
  const savedHex = String(props.modelValue.text || '')
  if (!savedHex.trim()) {
    patch({ isHex: false, text: '' })
    return
  }
  const result = hexToPrintableText(savedHex)
  if (!result.ok) {
    ElMessage.warning('包含非打印字符，无法转换!')
    return
  }
  patch({ isHex: false, text: result.text })
}

function onSend() {
  const built = buildRawSendHex(props.modelValue)
  if (!built.ok) {
    ElMessage.warning(built.warn)
    return
  }
  if (!built.hex) {
    ElMessage.warning('请输入数据')
    return
  }
  emit('send', built.hex)
}
</script>

<style scoped>
.send-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--el-text-color-primary);
}
.send-input {
  width: 100%;
  max-width: 320px;
}
.hex-form-item :deep(.el-form-item__content) {
  line-height: 32px;
}
.hex-inline {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.hex-checkbox {
  height: 32px;
  display: inline-flex;
  align-items: center;
}
.line-ending-select {
  width: 82px;
  margin-left: 12px;
}
.line-ending-select :deep(.el-select__wrapper) {
  padding-left: 4px;
  padding-right: 16px;
}
</style>
