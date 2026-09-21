const { apiBase } = require('./config')

const TOKEN_KEY = 'access_token'
const METHOD_KEY = 'auth_method'
const OPTED_OUT_KEY = 'auth_opted_out'

function detailMessage(data, fallback) {
  if (!data) return fallback
  const detail = data.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail[0]) return detail[0].msg || fallback
  return fallback
}

App({
  globalData: {
    apiBase,
    token: wx.getStorageSync(TOKEN_KEY) || '',
    user: null,
  },

  onLaunch() {
    this.loginPromise = this.bootstrapAuth()
  },

  isLoggedIn() {
    return Boolean(this.globalData.token)
  },

  setSession(token, method) {
    this.globalData.token = token
    wx.setStorageSync(TOKEN_KEY, token)
    if (method) wx.setStorageSync(METHOD_KEY, method)
    wx.removeStorageSync(OPTED_OUT_KEY)
  },

  clearSession(options = {}) {
    this.globalData.token = ''
    this.globalData.user = null
    wx.removeStorageSync(TOKEN_KEY)
    if (options.logout) wx.setStorageSync(OPTED_OUT_KEY, true)
  },

  waitAuth() {
    const pending = this.loginPromise
    if (!pending) return Promise.resolve(this.globalData.token)
    return Promise.resolve(pending).then(() => this.globalData.token).catch(() => this.globalData.token)
  },

  bootstrapAuth() {
    if (this.globalData.token) return Promise.resolve(this.globalData.token)
    if (wx.getStorageSync(OPTED_OUT_KEY)) return Promise.resolve('')
    const method = wx.getStorageSync(METHOD_KEY) || 'wechat'
    if (method !== 'wechat') return Promise.resolve('')
    return this.wechatLogin().catch(() => '')
  },

  ensureLogin() {
    if (this.globalData.token) return Promise.resolve(this.globalData.token)
    const pending = this.loginPromise || this.bootstrapAuth()
    this.loginPromise = pending
    return pending.then((token) => {
      this.loginPromise = null
      if (token) return token
      return Promise.reject(new Error('请先登录'))
    }).catch((error) => {
      this.loginPromise = null
      return Promise.reject(error)
    })
  },

  wechatLogin() {
    return new Promise((resolve, reject) => {
      wx.login({
        success: ({ code }) => {
          const header = { 'Content-Type': 'application/json' }
          if (this.globalData.token) header.Authorization = `Bearer ${this.globalData.token}`
          wx.request({
            url: `${this.globalData.apiBase}/auth/wechat`,
            method: 'POST',
            data: { code },
            header,
            success: ({ statusCode, data }) => {
              if (statusCode >= 200 && statusCode < 300) {
                this.setSession(data.access_token, 'wechat')
                resolve(data.access_token)
              } else reject(new Error(detailMessage(data, '微信登录失败')))
            },
            fail: reject,
          })
        },
        fail: reject,
      })
    })
  },

  accountAuth(path, payload) {
    return new Promise((resolve, reject) => {
      wx.request({
        url: `${this.globalData.apiBase}${path}`,
        method: 'POST',
        data: payload,
        header: { 'Content-Type': 'application/json' },
        success: ({ statusCode, data }) => {
          if (statusCode >= 200 && statusCode < 300) {
            this.setSession(data.access_token, 'password')
            resolve(data.access_token)
          } else reject(new Error(detailMessage(data, '登录失败')))
        },
        fail: reject,
      })
    })
  },

  logout() {
    this.clearSession({ logout: true })
  },
})
