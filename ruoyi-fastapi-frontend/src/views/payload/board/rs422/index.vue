<template>
  <BoardPage
    family="yj216"
    board="rs422"
    title="RS422测试"
    :tables="RS422_TABLES"
  />
</template>

<script setup name="Yj216Rs422">
import BoardPage from '../BoardPage.vue'

const RS422_TABLES = ['LCWP20', 'LCWP30', 'LCWP40', 'LCWP50', 'LCWP60', 'LCOS', 'UPHI']
</script>
