<template>
  <div class="app-container">
    <el-empty :description="`遥测表[${tableType}] · 功能建设中（计划阶段 P2）`" />
  </div>
</template>

<script setup name="PayloadTelemetryTable">
const route = useRoute();

// 7 个遥测表共用本组件，通过路由 query.type 区分数据类型(FF/FD/FB/F9/F7/FE/FC)
const tableType = computed(() => route.query.type || route.meta?.query?.type || "FF");
</script>
