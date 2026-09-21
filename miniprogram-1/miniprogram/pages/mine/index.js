const {request, promptLogin} = require('../../utils/api')

Page({
  data: {
    loggedIn: false,
    loading: false,
    user: {balance: 0, frozen: 0, nickname: '', username: '', wechat_bound: false, has_password: false, avatar_url: ''},
    displayName: '未登录',
    avatarText: '我',
    menus: [
      {name: '充值积分', tip: '微信支付，即时到账', url: '/pages/mine/recharge/index', auth: false},
      {name: '充值订单', tip: '查看充值记录', url: '/pages/mine/orders/index', auth: true},
      {name: '积分明细', tip: '查看积分变动记录', url: '/pages/mine/ledger/index', auth: true},
    ],
  },

  onShow() {
    this.refresh()
  },

  async refresh() {
    const app = getApp()
    await app.waitAuth()
    if (!app.isLoggedIn()) {
      this.setData({
        loggedIn: false,
        user: {balance: 0, frozen: 0},
        displayName: '未登录',
        avatarText: '我',
      })
      return
    }
    this.setData({loggedIn: true, loading: true})
    try {
      await this.loadProfile()
    } catch (error) {
      if (error.statusCode === 401 || error.message === '请先登录') {
        this.setData({loggedIn: false})
      } else {
        wx.showToast({title: error.message, icon: 'none'})
      }
    } finally {
      this.setData({loading: false})
    }
  },

  async loadProfile() {
    const user = await request('/me')
    getApp().globalData.user = user
    this.setData({
      loggedIn: true,
      user,
      displayName: user.nickname || user.username || '微信用户',
      avatarText: (user.nickname || user.username || '我').slice(0, 1).toUpperCase(),
    })
  },

  openAuth() {
    wx.navigateTo({url: '/pages/mine/auth/index'})
  },

  async wechatLogin() {
    wx.showLoading({title: '正在登录'})
    try {
      await getApp().wechatLogin()
      await this.loadProfile()
      wx.showToast({title: '登录成功', icon: 'success'})
    } catch (error) {
      wx.showToast({title: error.message || '微信登录失败', icon: 'none'})
    } finally {
      wx.hideLoading()
    }
  },

  async bindWechat() {
    wx.showLoading({title: '正在绑定'})
    try {
      await getApp().wechatLogin()
      await this.loadProfile()
      wx.showToast({title: '微信已绑定', icon: 'success'})
    } catch (error) {
      wx.showToast({title: error.message, icon: 'none'})
    } finally {
      wx.hideLoading()
    }
  },

  editNickname() {
    wx.showModal({
      title: '修改昵称',
      editable: true,
      placeholderText: '请输入新昵称',
      content: this.data.displayName,
      success: async (res) => {
        if (!res.confirm) return
        const nickname = (res.content || '').trim()
        if (!nickname) return wx.showToast({title: '昵称不能为空', icon: 'none'})
        try {
          const user = await request('/me', {method: 'PATCH', data: {nickname}})
          this.setData({
            user,
            displayName: user.nickname || user.username || '微信用户',
            avatarText: (user.nickname || user.username || '我').slice(0, 1).toUpperCase(),
          })
          wx.showToast({title: '已更新', icon: 'success'})
        } catch (error) {
          wx.showToast({title: error.message, icon: 'none'})
        }
      },
    })
  },

  openMenu(e) {
    const {url, auth} = e.currentTarget.dataset
    const needAuth = auth === true || auth === 'true'
    if (needAuth && !getApp().isLoggedIn()) return promptLogin()
    wx.navigateTo({url})
  },

  logout() {
    wx.showModal({
      title: '退出登录',
      content: '退出后不会自动登录，需要重新使用微信或账号登录。',
      confirmText: '退出',
      confirmColor: '#de5959',
      success: (res) => {
        if (!res.confirm) return
        getApp().logout()
        this.setData({
          loggedIn: false,
          user: {balance: 0, frozen: 0},
          displayName: '未登录',
          avatarText: '我',
        })
        wx.showToast({title: '已退出登录', icon: 'none'})
      },
    })
  },
})
