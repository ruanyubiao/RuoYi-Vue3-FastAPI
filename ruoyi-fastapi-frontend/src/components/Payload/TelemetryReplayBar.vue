<template>
  <div class="replay-bar">
    <div class="replay-slider">
      <span class="slider-edge">{{ displayIndex }}</span>
      <el-slider
        class="slider-body"
        :model-value="frameIndex"
        :min="1"
        :max="sliderMax"
        :disabled="!frameCount"
        @update:model-value="onSlider"
      />
      <span class="slider-edge">{{ displayMax }}</span>
    </div>
    <div class="replay-pager">
      <el-button :disabled="frameIndex <= 1" @click="go(frameIndex - 1)">上一页</el-button>
      <el-input-number
        :model-value="frameIndex"
        :min="1"
        :max="sliderMax"
        :disabled="!frameCount"
        :controls="false"
        @change="onInput"
      />
      <el-button :disabled="frameIndex >= sliderMax" @click="go(frameIndex + 1)">下一页</el-button>
    </div>
    <div class="replay-play">
      <el-checkbox :model-value="playing" @change="v => emit('update:playing', v)">自动播放</el-checkbox>
      <el-tooltip content="自动播放时每帧停留的毫秒数" placement="top">
        <el-input-number
          class="replay-interval"
          :model-value="Number(intervalMs) || 1000"
          :min="100"
          :step="1"
          :precision="0"
          :controls="false"
          placeholder="间隔(ms)"
          @change="onInterval"
          @blur="onIntervalBlur"
          @keydown.enter="onIntervalEnter"
        />
      </el-tooltip>
    </div>
  </div>
</template>

<script setup>
/**
 * 历史回放条：滑块 / 页码 / 自动播放。
 * 滑块头尾按 5 位宽对齐帧号。自动播放是否停在最后一帧由父页 watch(playing) 决定。
 * 数字框去掉步进箭头（:controls=false）。
 */
const props = defineProps({
  frameIndex: { type: Number, default: 1 }, // 当前帧，1-based
  frameCount: { type: Number, default: 0 }, // 0 表示尚未解析
  playing: { type: Boolean, default: false },
  intervalMs: { type: Number, default: 1000 } // 每帧停留，最小 100
})
const emit = defineEmits(['update:frameIndex', 'update:playing', 'update:intervalMs', 'change'])

const sliderMax = computed(() => Math.max(1, Number(props.frameCount) || 1)) // el-slider max 不能为 0
const displayIndex = computed(() => (props.frameCount ? props.frameIndex : 0))
const displayMax = computed(() => Number(props.frameCount) || 0)

function go(n) {
  const max = Number(props.frameCount) || 0
  if (!max) return
  const next = Math.min(max, Math.max(1, Number(n) || 1))
  emit('update:frameIndex', next)
  emit('change', next) // 父页拉该帧
}

function onSlider(v) {
  go(v)
}

function onInput(v) {
  go(v)
}

function onInterval(v) {
  const n = Math.max(100, Math.round(Number(v) || 1000))
  emit('update:intervalMs', n)
}

/** 焦点离开：把输入框里的值夹到 ≥100 并写回（自动播放时父页会重开定时器） */
function onIntervalBlur(e) {
  const raw = e?.target?.value
  onInterval(raw === '' || raw == null ? props.intervalMs : raw)
}

function onIntervalEnter(e) {
  const raw = e?.target?.value
  if (raw === '' || raw == null) return
  onInterval(raw)
}
</script>

<style scoped>
.replay-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  min-height: 40px;
}
.replay-slider {
  flex: 1 1 50%;
  min-width: 0;
  padding: 0 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.slider-body {
  flex: 1;
  min-width: 0;
}
.slider-edge {
  flex-shrink: 0;
  min-width: 5ch;
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.slider-edge:last-child {
  text-align: left;
}
.replay-pager {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.replay-pager :deep(.el-input-number) {
  width: 80px;
}
.replay-play {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-left: auto;
}
.replay-interval {
  width: 100px;
}
</style>
