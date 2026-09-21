const {request} = require('../../../utils/api')
const {decorateOrders} = require('../../../utils/wallet')

Page({
  data: {orders: []},

  onShow() {
    this.load()
  },

  async load() {
    try {
      const orders = decorateOrders(await request('/recharge-orders'))
      this.setData({orders})
    } catch (error) {
      wx.showToast({title: error.message, icon: 'none'})
    }
  },
})
