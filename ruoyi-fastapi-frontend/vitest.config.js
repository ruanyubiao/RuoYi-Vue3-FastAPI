import path from 'path'
import vue from '@vitejs/plugin-vue'
import autoImport from 'unplugin-auto-import/vite'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  // 组件测试需要编译 .vue，并与 vite/plugins/auto-import.js 一样自动导入 ref/computed 等
  plugins: [
    vue(),
    autoImport({ imports: ['vue', 'vue-router', 'pinia'], dts: false })
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '~': path.resolve(__dirname, './')
    }
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    include: ['tests/**/*.test.js'],
    setupFiles: ['./tests/setup.js'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{js,vue}'],
      reporter: ['text-summary', 'json-summary']
    }
  }
})
