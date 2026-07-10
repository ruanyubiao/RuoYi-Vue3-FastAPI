<template>
  <div class="app-container">
    <el-card shadow="never">
      <template #header>
        <span>CAN 遥测数据</span>
      </template>
      <el-form label-width="100px" class="dev-form">
        <el-form-item label="设备ID">
          <el-select v-model="deviceId" filterable allow-create default-first-option style="width: 280px">
            <el-option v-for="d in deviceOptions" :key="d" :label="d" :value="d" />
          </el-select>
          <el-button link type="primary" style="margin-left: 8px" @click="refreshDevices">刷新</el-button>
        </el-form-item>
        <el-form-item label="CAN遥测数据">
          <el-input
            v-model="hexText"
            type="textarea"
            :rows="8"
            placeholder="输入CAN遥测数据（完整复合帧 HEX，空格可选）"
            class="hex-input"
          />
        </el-form-item>
        <el-form-item label=" ">
          <el-button type="primary" :loading="sending" @click="handleSend" v-hasPermi="['payload:devtest:view']">
            发送
          </el-button>
          <el-button @click="fillSample">填入样例</el-button>
          <el-button @click="hexText = ''">清空</el-button>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="lastResult"
        :title="`已写入 Redis · 类型 0x${lastResult.dataType} · ${lastResult.name || ''} · 字段 ${lastResult.fieldCount} · ${lastResult.ts}`"
        type="success"
        show-icon
        :closable="false"
        class="result-alert"
      />
      <div class="hint">
        说明：此处模拟 CAN 库多帧组包后的完整遥测应答。发送后经校验/解析写入 Redis，可在「遥测」菜单对应表页查看。
      </div>
    </el-card>
  </div>
</template>

<script setup name="DevTest">
import { ElMessage } from 'element-plus'
import { listCanChannels } from '@/api/payload/device'
import { injectCanYcTest } from '@/api/payload/telemetry'

const ACTIVE_KEY = 'payload:activeDeviceId'
const SAMPLE_HEX =
  '00 BF 3A FF 33 00 00 00 00 00 00 00 00 00 45 00 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2 05 97 00 81 00 00 00 02 11 01 C8 0C B1 42 70 00 00 3F 2D 74 BE 44 C3 61 9A 41 6E BF 80 00 00 6D C3 80 26 00 00 55 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 02 00 21 1F AA AA AA AA 00 00 00 00 00 00 30 FF 0C 00 FC 00 00 10 00 00 00 00 00 00 03 00 CC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 4C'

const deviceId = ref(localStorage.getItem(ACTIVE_KEY) || 'can:0:0:0')
const deviceOptions = ref([deviceId.value])
const hexText = ref('')
const sending = ref(false)
const lastResult = ref(null)

async function refreshDevices() {
  try {
    const res = await listCanChannels()
    const list = (res.data || []).map(d => d.deviceId || d).filter(Boolean)
    const active = localStorage.getItem(ACTIVE_KEY)
    const opts = [...new Set([active, deviceId.value, ...list].filter(Boolean))]
    deviceOptions.value = opts.length ? opts : ['can:0:0:0']
    if (!opts.includes(deviceId.value)) {
      deviceId.value = deviceOptions.value[0]
    }
  } catch {
    deviceOptions.value = [deviceId.value || 'can:0:0:0']
  }
}

function fillSample() {
  hexText.value = SAMPLE_HEX
}

async function handleSend() {
  if (!hexText.value.trim()) {
    ElMessage.warning('请输入 CAN 遥测数据')
    return
  }
  if (!deviceId.value) {
    ElMessage.warning('请选择设备ID')
    return
  }
  sending.value = true
  lastResult.value = null
  try {
    const res = await injectCanYcTest({ deviceId: deviceId.value, hex: hexText.value })
    lastResult.value = res.data || {}
    localStorage.setItem(ACTIVE_KEY, deviceId.value)
    ElMessage.success(res.msg || '注入成功')
  } finally {
    sending.value = false
  }
}

onMounted(refreshDevices)
</script>

<style scoped>
.dev-form {
  max-width: 960px;
}
.hex-input :deep(textarea) {
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
  line-height: 1.5;
}
.result-alert {
  margin-top: 8px;
  max-width: 960px;
}
.hint {
  margin-top: 16px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}
</style>
