// 简化版 user store - 无登录功能
const useUserStore = defineStore(
  'user',
  {
    state: () => ({
      token: '',
      id: '',
      name: '访客',
      nickName: '访客',
      avatar: '',
      roles: [],
      permissions: []
    }),
    actions: {
      // 无需登录，直接设置默认信息
      initUserInfo() {
        this.name = '访客'
        this.nickName = '访客'
        this.roles = ['ROLE_DEFAULT']
        this.permissions = []
      }
    }
  })

export default useUserStore
