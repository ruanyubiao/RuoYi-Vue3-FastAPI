import { beforeEach } from 'vitest'

/** 每个用例前清空浏览器 Storage，避免用例互相污染 */
beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})
