<template>
  <div class="app-container xl-board-page">
    <div class="main-grid">
      <div class="col-left">
        <BoardConnectBar
          kind="serial"
          source="cpazx"
          :prefs-key="prefsKey"
          :serial-fallback="FALLBACK_SERIAL"
          :fallback-parsers="FALLBACK_PARSERS_XL_CPAZX"
          v-model:connected="linkConnected"
          v-model:device-id="deviceId"
        />
        <BoardTelecontrolPanel
          ref="tcRef"
          class="panel-tc"
          board="cpazx"
          :connected="linkConnected"
          :device-id="deviceId"
          connect-kind="serial"
          :prefs-key="prefsKey"
        />
        <div class="panel panel-xfer">
          <PayloadTransferInfo
            v-model="xferDeviceId"
            title="传输信息"
            :devices="xferDevices"
          />
        </div>
      </div>

      <div class="col-right">
        <div class="joystick-area">
          <CpazxJoystick
            v-model:travel="joyTravel"
            v-model:az="joyAz"
            v-model:el="joyEl"
            v-model:locked="joyLocked"
            @update:engaging="onJoyEngaging"
            @change="onJoyChange"
          />
        </div>
        <div class="panel panel-tm">
          <PayloadTelemetryTable level="t3" :types="tmTypes" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup name="PayloadBoardCpazx">
/**
 * CPA 指向：连接 / 遥控 / 传输 / 摇杆 / 遥测 由子面板拼装。
 * 摇杆改动会写回 CP06 输入框；改 CP06 不影响摇杆位置。20Hz 走 sendOrderById。
 */
import { ElMessage } from 'element-plus'
import PayloadTransferInfo from '@/components/Payload/PayloadTransferInfo.vue'
import PayloadTelemetryTable from '@/components/Payload/PayloadTelemetryTable.vue'
import CpazxJoystick from '@/components/Payload/CpazxJoystick.vue'
import BoardConnectBar from '../components/BoardConnectBar.vue'
import BoardTelecontrolPanel from '../components/BoardTelecontrolPanel.vue'
import {
  ASSEMBLER_PASSTHROUGH,
  PARSER_TM_XL_CPAZX,
  FALLBACK_PARSERS_XL_CPAZX
} from '@/utils/pipelineIds'
import { JOYSTICK_INTERVAL_MS, JOYSTICK_TRAVEL_SQUARE, normalizeTravel } from '@/utils/virtualJoystick'
import cache from '@/plugins/cache'

const SPEED_ORDER_ID = 'CP06'
const prefsKey = 'payload:board:cpazx:prefs'
const tmTypes = ['CPAZX']

const FALLBACK_SERIAL = {
  baudrate: 921600,
  baudChoices: [921600],
  dataBits: 8,
  stopBits: 1,
  parity: 'N',
  flowControl: 'NONE',
  assemblerId: ASSEMBLER_PASSTHROUGH,
  parserId: PARSER_TM_XL_CPAZX
}

const linkConnected = ref(false)
const deviceId = ref('')
const xferDeviceId = ref('')
const xferSourceId = 'source:cpazx'
const xferDevices = computed(() => {
  if (linkConnected.value) {
    return [{ id: xferSourceId, label: 'CPA指向' }]
  }
  return []
})

watch(linkConnected, (on) => {
  xferDeviceId.value = on ? xferSourceId : ''
  syncJoyTimer()
})

const tcRef = ref(null)
const joyAz = ref(0)
const joyEl = ref(0)
const joyLocked = ref(false)
const joyTravel = ref(JOYSTICK_TRAVEL_SQUARE)
const joyEngaging = ref(false)
let joyTimer = null
let joySending = false
let joyDirty = false
let cp06PreviewTimer = null
let lastJoyFailAt = 0

function speedFieldIndexes(ord) {
  const comps = ord?.component || []
  const nums = []
  comps.forEach((comp, i) => {
    if (String(comp?.componentType || '').toLowerCase() === 'number') nums.push(i)
  })
  if (nums.length < 2) return null
  return { az: nums[0], el: nums[1] }
}

function applyJoyToCp06() {
  const tc = tcRef.value
  if (!tc) return
  const ord = tc.getOrder(SPEED_ORDER_ID)
  const idx = speedFieldIndexes(ord)
  if (!idx) return
  tc.setCompValues(SPEED_ORDER_ID, { [idx.az]: joyAz.value, [idx.el]: joyEl.value })
}

function scheduleCp06Preview() {
  clearTimeout(cp06PreviewTimer)
  cp06PreviewTimer = setTimeout(() => {
    tcRef.value?.previewOrderById(SPEED_ORDER_ID, { showLoading: false })
  }, 250)
}

function onJoyEngaging(on) {
  joyEngaging.value = !!on
  syncJoyTimer()
}

function onJoyChange() {
  applyJoyToCp06()
  scheduleCp06Preview()
  syncJoyTimer()
}

function joyNeedSend() {
  if (joyEngaging.value) return true
  return joyLocked.value && (joyAz.value !== 0 || joyEl.value !== 0)
}

function stopJoyTimer() {
  if (joyTimer) {
    clearInterval(joyTimer)
    joyTimer = null
  }
}

function syncJoyTimer() {
  if (!linkConnected.value || !joyNeedSend()) {
    const wasOn = !!joyTimer
    stopJoyTimer()
    if (wasOn) sendJoyTick()
    return
  }
  if (!joyTimer) {
    sendJoyTick()
    joyTimer = setInterval(sendJoyTick, JOYSTICK_INTERVAL_MS)
  }
}

async function sendJoyTick() {
  if (!linkConnected.value || !deviceId.value) return
  if (joySending) {
    joyDirty = true
    return
  }
  const tc = tcRef.value
  if (!tc?.getOrder(SPEED_ORDER_ID)) return
  applyJoyToCp06()
  joySending = true
  try {
    await tc.sendOrderById(SPEED_ORDER_ID, {
      wait: false,
      t: Date.now(),
      silent: true
    })
  } catch (e) {
    const now = Date.now()
    if (now - lastJoyFailAt > 2000) {
      lastJoyFailAt = now
      ElMessage.error(e?.message || '速度指令发送失败')
    }
  } finally {
    joySending = false
    if (joyDirty) {
      joyDirty = false
      sendJoyTick()
    }
  }
}

watch(joyLocked, syncJoyTimer)

function mergePrefs(patch) {
  const cur = cache.local.getJSON(prefsKey, {}) || {}
  cache.local.setJSON(prefsKey, { ...cur, ...patch })
}

function loadJoyTravelPref() {
  const p = cache.local.getJSON(prefsKey, {}) || {}
  if (p.joyTravel) joyTravel.value = normalizeTravel(p.joyTravel)
}

loadJoyTravelPref()
watch(joyTravel, (v) => {
  mergePrefs({ joyTravel: normalizeTravel(v) })
})

onDeactivated(() => {
  if (!joyLocked.value) {
    joyEngaging.value = false
    joyAz.value = 0
    joyEl.value = 0
    applyJoyToCp06()
  }
  syncJoyTimer()
})

onUnmounted(() => {
  stopJoyTimer()
  clearTimeout(cp06PreviewTimer)
})
</script>

<style scoped>
.xl-board-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-height: 100%;
  min-height: 480px;
  overflow: hidden;
  box-sizing: border-box;
}
.main-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(320px, 1fr) 2fr;
  gap: 10px;
}
.col-left,
.col-right {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}
.col-left .panel-tc {
  flex: 1.4;
  min-height: 0;
}
.col-left .panel-xfer {
  flex: 0.8;
  min-height: 0;
}
.col-right .panel-tm {
  flex: 1;
  min-height: 0;
  padding: 4px 8px;
  box-sizing: border-box;
}
.joystick-area {
  height: 400px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: visible;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-bg-color);
  box-sizing: border-box;
}
.panel-tm :deep(.payload-tm-table) {
  height: 100%;
}
.panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  overflow: hidden;
  background: var(--el-bg-color);
}
</style>
