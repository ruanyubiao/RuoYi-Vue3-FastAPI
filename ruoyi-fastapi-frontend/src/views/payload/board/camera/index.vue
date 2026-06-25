<template>
  <div class="app-container camera-page">
    <el-form :inline="true" class="mb8">
      <el-form-item label="串口">
        <el-select v-model="port" filterable style="width: 140px">
          <el-option v-for="p in serialPorts" :key="p.port" :label="p.port" :value="p.port" />
        </el-select>
        <el-button link @click="refreshPorts">刷新</el-button>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="connect">连接</el-button>
        <el-button @click="disconnect">断开</el-button>
      </el-form-item>
      <el-form-item label="分辨率">
        <el-select v-model="resolution" style="width: 120px">
          <el-option v-for="r in resolutions" :key="r" :label="r" :value="r" />
        </el-select>
      </el-form-item>
      <el-form-item label="图像序号">
        <el-input-number v-model="imageNo" :min="1" :max="64" />
      </el-form-item>
      <el-form-item>
        <el-button type="success" @click="startRefresh">开始刷新</el-button>
        <el-button type="danger" @click="stopRefresh">停止刷新</el-button>
      </el-form-item>
    </el-form>
    <div class="status-bar">{{ statusText }}</div>
    <div class="image-wrap">
      <img v-if="imageSrc" :src="imageSrc" alt="camera" class="camera-img" />
      <el-empty v-else description="暂无图像" />
    </div>
  </div>
</template>

<script setup name="Camera">
import { listSerialPorts, openSerialPort, closeSerialPort } from '@/api/payload/device'
import { startCamera, stopCamera, getCameraImage, getCameraStatus } from '@/api/payload/camera'

const serialPorts = ref([])
const port = ref('')
const resolution = ref('256×256')
const resolutions = ['400×400', '256×256', '128×128', '64×64']
const imageNo = ref(1)
const imageSrc = ref('')
const statusText = ref('就绪')
let imageTimer = null

async function refreshPorts() {
  const res = await listSerialPorts()
  serialPorts.value = res.data || []
  if (!port.value && serialPorts.value.length) port.value = serialPorts.value[0].port
}

async function connect() {
  if (!port.value) return
  await openSerialPort({ port: port.value, mode: 'camera' })
  statusText.value = `已连接 ${port.value}`
}

async function disconnect() {
  stopRefresh()
  if (port.value) await closeSerialPort(port.value)
  statusText.value = '已断开'
}

async function startRefresh() {
  if (!port.value) return
  await startCamera({ port: port.value, resolution: resolution.value, imageNo: imageNo.value })
  statusText.value = '采集中...'
  fetchImage()
  imageTimer = setInterval(fetchImage, 1500)
}

async function stopRefresh() {
  if (imageTimer) clearInterval(imageTimer)
  imageTimer = null
  if (port.value) await stopCamera(port.value)
  statusText.value = '已停止刷新'
}

async function fetchImage() {
  if (!port.value) return
  try {
    const st = await getCameraStatus(port.value)
    if (st.data?.message) statusText.value = st.data.message
    const res = await getCameraImage(port.value)
    if (res.data?.data) {
      const fmt = res.data.format || 'png'
      imageSrc.value = `data:image/${fmt};base64,${res.data.data}`
    }
  } catch (e) {
    statusText.value = '拉取图像失败'
  }
}

onMounted(refreshPorts)
onUnmounted(stopRefresh)
</script>

<style scoped>
.status-bar { margin-bottom: 8px; color: var(--el-text-color-secondary); }
.image-wrap { border: 1px solid var(--el-border-color); min-height: 400px; display: flex; align-items: center; justify-content: center; }
.camera-img { max-width: 100%; max-height: calc(100vh - 220px); image-rendering: pixelated; }
</style>
