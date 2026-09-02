<template>
  <CameraBoard camera-protocol="v17" />
</template>

<!-- 组件名须与路由 name 一致：path camera_v17 → capitalize → Camera_v17，否则 keep-alive 不缓存 -->
<script setup name="Camera_v17">
import CameraBoard from '../camera/index.vue'
</script>
