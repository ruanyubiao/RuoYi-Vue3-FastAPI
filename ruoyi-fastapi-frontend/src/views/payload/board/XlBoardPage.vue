<template>
  <div class="app-container xl-board-page">
    <div class="main-grid">
      <div class="col-left">
        <BoardConnectBar
          :kind="connectKind"
          :source="sourceTag"
          :prefs-key="prefsKey"
          :udp-prefs-key="udpPrefsKey"
          :serial-fallback="FALLBACK_SERIAL"
          :udp-fallback="FALLBACK_UDP"
          :fallback-parsers="FALLBACK_PARSERS_XL_BOARD"
          v-model:connected="linkConnected"
          v-model:device-id="deviceId"
        />
        <BoardTelecontrolPanel
          class="panel-tc"
          :board="boardId"
          :connected="linkConnected"
          :device-id="deviceId"
          :connect-kind="connectKind"
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
        <div class="panel panel-tm">
          <PayloadTelemetryTable level="t3" :types="tmTypes" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * XL 单板遥控/遥测页（热控 / CPA-ZK / 地检）。
 * connectKind=serial：热控/CPA-ZK，按钮绑定 cfg key=board。
 * connectKind=udp：地检板，按钮绑定 connectSource（xl_udp_dj）。
 */
import PayloadTransferInfo from '@/components/Payload/PayloadTransferInfo.vue'
import PayloadTelemetryTable from '@/components/Payload/PayloadTelemetryTable.vue'
import BoardConnectBar from './components/BoardConnectBar.vue'
import BoardTelecontrolPanel from './components/BoardTelecontrolPanel.vue'
import {
  ASSEMBLER_PASSTHROUGH,
  ASSEMBLER_ENG_TM_SUBPKT,
  PARSER_TM_XL_BOARD,
  FALLBACK_PARSERS_XL_BOARD
} from '@/utils/pipelineIds'

const props = defineProps({
  /** rkdj | zk | dj */
  board: { type: String, required: true },
  /** 页面标题（菜单名） */
  title: { type: String, default: '' },
  /** serial=热控/CPA-ZK；udp=地检板网口 */
  connectKind: { type: String, default: 'serial' },
  /** 会话 source / cfg_device_connect key；空则用 board */
  connectSource: { type: String, default: '' }
})

const boardId = computed(() => String(props.board || '').toLowerCase())
const tableKey = computed(() => {
  if (boardId.value === 'dj') return 'DJ'
  if (boardId.value === 'zk') return 'ZK'
  return 'RKDJ'
})
const tmTypes = computed(() => [tableKey.value])
const sourceTag = computed(() => String(props.connectSource || boardId.value).trim())
const prefsKey = computed(() => `payload:board:${boardId.value}:prefs`)
const udpPrefsKey = computed(() => `payload:board:${boardId.value}:udpPrefs`)

const FALLBACK_SERIAL = {
  baudrate: 115200,
  baudChoices: [115200],
  dataBits: 8,
  stopBits: 1,
  parity: 'N',
  flowControl: 'NONE',
  assemblerId: ASSEMBLER_PASSTHROUGH,
  parserId: PARSER_TM_XL_BOARD
}
const FALLBACK_UDP = {
  localHost: '127.0.0.1',
  localPort: 66,
  remoteHost: '127.0.0.1',
  remotePort: 99,
  assemblerId: ASSEMBLER_ENG_TM_SUBPKT,
  parserId: PARSER_TM_XL_BOARD,
  fullDuplex: true
}

const linkConnected = ref(false)
const deviceId = ref('')
const xferDeviceId = ref('')
const xferSourceId = computed(() => `source:${sourceTag.value}`)
const xferDevices = computed(() => {
  if (linkConnected.value) {
    return [{ id: xferSourceId.value, label: props.title || boardId.value || '本页连接' }]
  }
  return []
})

watch(
  linkConnected,
  (on) => {
    xferDeviceId.value = on ? xferSourceId.value : ''
  }
)
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
