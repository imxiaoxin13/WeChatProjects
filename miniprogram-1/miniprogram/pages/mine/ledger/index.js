const {request} = require('../../../utils/api')
const {decorateLedger} = require('../../../utils/wallet')

Page({
  data: {ledger: []},

  onShow() {
    this.load()
  },

  async load() {
    try {
      const ledger = decorateLedger(await request('/wallet/ledger'))
      this.setData({ledger})
    } catch (error) {
      wx.showToast({title: error.message, icon: 'none'})
    }
  },
})
