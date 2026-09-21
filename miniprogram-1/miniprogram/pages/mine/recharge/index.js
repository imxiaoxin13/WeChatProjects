const {request, uuid, promptLogin} = require('../../../utils/api')

const RATE = 10
const MIN_YUAN = 5
const MAX_YUAN = 5000
const PRESETS = [
  {yuan: 10, tag: ''},
  {yuan: 50, tag: '热门'},
  {yuan: 100, tag: '超值'},
  {yuan: 200, tag: ''},
]

Page({
  data: {
    rate: RATE,
    minYuan: MIN_YUAN,
    presets: PRESETS,
    selected: 10,
    customYuan: '',
    usingCustom: false,
    payYuan: 10,
    payPoints: 100,
    canPay: true,
    paying: false,
    balance: 0,
    loggedIn: false,
  },

  onShow() {
    this.refresh()
  },

  async refresh() {
    await getApp().waitAuth()
    const loggedIn = getApp().isLoggedIn()
    this.setData({loggedIn})
    if (!loggedIn) {
      this.setData({balance: 0})
      return
    }
    try {
      const user = await request('/me')
      this.setData({balance: user.balance || 0})
    } catch (error) {
      wx.showToast({title: error.message, icon: 'none'})
    }
  },

  pickPreset(e) {
    const yuan = Number(e.currentTarget.dataset.yuan)
    this.setData({selected: yuan, usingCustom: false})
    this.syncPay(yuan)
  },

  pickCustom() {
    this.setData({selected: 'custom', usingCustom: true})
    this.syncPay(this.parseCustom())
  },

  onCustomInput(e) {
    const digits = String(e.detail.value || '').replace(/[^\d]/g, '')
    const customYuan = digits.replace(/^0+(?=\d)/, '')
    this.setData({selected: 'custom', usingCustom: true, customYuan})
    this.syncPay(customYuan ? Number(customYuan) : 0)
  },

  parseCustom() {
    const value = Number(this.data.customYuan)
    return Number.isInteger(value) ? value : 0
  },

  syncPay(yuan) {
    const valid = Number.isInteger(yuan) && yuan >= MIN_YUAN && yuan <= MAX_YUAN
    this.setData({
      payYuan: valid ? yuan : 0,
      payPoints: valid ? yuan * RATE : 0,
      canPay: valid,
    })
  },

  async pay() {
    if (!getApp().isLoggedIn()) return promptLogin('登录后即可充值积分')
    if (this.data.paying) return
    const yuan = this.data.usingCustom ? this.parseCustom() : Number(this.data.selected)
    if (!Number.isInteger(yuan) || yuan < MIN_YUAN) {
      return wx.showToast({title: `请输入不低于 ${MIN_YUAN} 元的整数金额`, icon: 'none'})
    }
    if (yuan > MAX_YUAN) {
      return wx.showToast({title: `单笔最多 ${MAX_YUAN} 元`, icon: 'none'})
    }
    const points = yuan * RATE
    wx.showModal({
      title: '确认充值',
      content: `支付 ¥${yuan}，立即到账 ${points} 积分。充值后不支持退款。`,
      confirmText: '立即支付',
      success: async (res) => {
        if (!res.confirm) return
        this.setData({paying: true})
        wx.showLoading({title: '正在支付'})
        try {
          // TODO: 接入微信支付后改为 wx.requestPayment
          const order = await request('/recharge-orders', {
            method: 'POST',
            data: {amount_yuan: yuan, idempotency_key: uuid()},
          })
          wx.hideLoading()
          this.setData({balance: this.data.balance + (order.points || points), paying: false})
          wx.showToast({title: '充值成功，积分已到账', icon: 'success'})
        } catch (error) {
          wx.hideLoading()
          this.setData({paying: false})
          wx.showToast({title: error.message, icon: 'none'})
        }
      },
    })
  },
})
