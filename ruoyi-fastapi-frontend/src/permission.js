import router from './router'
import NProgress from 'nprogress'
import 'nprogress/nprogress.css'

NProgress.configure({ showSpinner: false })

// 移除所有权限检查，直接进入页面
router.beforeEach((to, from, next) => {
  NProgress.start()
  // 直接放行，不做任何权限验证
  next()
})

router.afterEach(() => {
  NProgress.done()
})
