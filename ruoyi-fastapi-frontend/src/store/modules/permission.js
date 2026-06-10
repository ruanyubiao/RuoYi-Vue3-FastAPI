import router, { constantRoutes } from '@/router'

// 匹配 views 里面所有的.vue文件
const modules = import.meta.glob('./../../views/**/*.vue')

const usePermissionStore = defineStore(
  'permission',
  {
    state: () => ({
      routes: [],
      addRoutes: [],
      defaultRoutes: [],
      topbarRouters: [],
      sidebarRouters: []
    }),
    actions: {
      setRoutes(routes) {
        this.addRoutes = routes
        this.routes = constantRoutes.concat(routes)
      },
      setDefaultRoutes(routes) {
        this.defaultRoutes = constantRoutes.concat(routes)
      },
      setTopbarRoutes(routes) {
        this.topbarRouters = routes
      },
      setSidebarRouters(routes) {
        this.sidebarRouters = routes
      },
      generateRoutes(roles) {
        return new Promise(resolve => {
          // 轻量化版本：直接使用常量路由，不请求后端
          const sidebarRoutes = constantRoutes
          const rewriteRoutes = constantRoutes
          const defaultRoutes = constantRoutes
          this.setRoutes(rewriteRoutes)
          this.setSidebarRouters(constantRoutes)
          this.setDefaultRoutes(constantRoutes)
          this.setTopbarRoutes(constantRoutes)
          resolve(rewriteRoutes)
        })
      }
    }
  })

export default usePermissionStore
