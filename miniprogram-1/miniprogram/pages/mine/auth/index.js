Page({
  data: {
    mode: 'login',
    username: '',
    password: '',
    nickname: '',
  },

  onLoad(query) {
    const mode = query.mode === 'register' ? 'register' : 'login'
    this.setModeTitle(mode)
    this.setData({mode})
  },

  onShow() {
    if (getApp().isLoggedIn()) this.leave()
  },

  setMode(e) {
    const mode = e.currentTarget.dataset.mode
    if (mode === this.data.mode) return
    this.setModeTitle(mode)
    this.setData({mode})
  },

  setModeTitle(mode) {
    wx.setNavigationBarTitle({title: mode === 'register' ? '注册账号' : '账号登录'})
  },

  onUsername(e) { this.setData({username: (e.detail.value || '').trim()}) },
  onPassword(e) { this.setData({password: e.detail.value || ''}) },
  onNickname(e) { this.setData({nickname: e.detail.value || ''}) },

  async submit() {
    const {mode, username, password, nickname} = this.data
    if (!username) return wx.showToast({title: '请输入账号', icon: 'none'})
    if (password.length < 6) return wx.showToast({title: '密码至少 6 位', icon: 'none'})
    wx.showLoading({title: mode === 'register' ? '正在注册' : '正在登录'})
    try {
      const path = mode === 'register' ? '/auth/register' : '/auth/login'
      const payload = {username, password}
      if (mode === 'register' && nickname.trim()) payload.nickname = nickname.trim()
      await getApp().accountAuth(path, payload)
      wx.showToast({title: mode === 'register' ? '注册成功' : '登录成功', icon: 'success'})
      this.leave()
    } catch (error) {
      wx.showToast({title: error.message, icon: 'none'})
    } finally {
      wx.hideLoading()
    }
  },

  async wechatLogin() {
    wx.showLoading({title: '正在登录'})
    try {
      await getApp().wechatLogin()
      wx.showToast({title: '登录成功', icon: 'success'})
      this.leave()
    } catch (error) {
      wx.showToast({title: error.message || '微信登录失败', icon: 'none'})
    } finally {
      wx.hideLoading()
    }
  },

  leave() {
    wx.switchTab({url: '/pages/mine/index'})
  },
})
