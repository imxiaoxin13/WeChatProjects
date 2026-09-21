const app = getApp()

function uuid() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
}

function detailMessage(data) {
  if (!data) return '请求失败'
  const detail = data.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail[0]) return detail[0].msg || '请求失败'
  return '请求失败'
}

function promptLogin(message) {
  wx.showModal({
    title: '请先登录',
    content: message || '登录后即可使用创作、对话和作品功能',
    confirmText: '去登录',
    success: (res) => {
      if (res.confirm) wx.navigateTo({ url: '/pages/mine/auth/index' })
    },
  })
}

async function request(path, options = {}) {
  const needAuth = options.auth !== false
  let token = app.globalData.token || ''
  if (needAuth) token = await app.ensureLogin()
  return new Promise((resolve, reject) => {
    const header = {
      'Content-Type': 'application/json',
      ...(options.header || {}),
    }
    if (token) header.Authorization = `Bearer ${token}`
    wx.request({
      url: `${app.globalData.apiBase}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header,
      success: ({ statusCode, data }) => {
        if (statusCode >= 200 && statusCode < 300) resolve(data)
        else {
          if (statusCode === 401) app.clearSession()
          const error = new Error(detailMessage(data))
          error.statusCode = statusCode
          reject(error)
        }
      },
      fail: reject,
    })
  })
}

async function upload(path) {
  const token = await app.ensureLogin()
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${app.globalData.apiBase}/uploads`,
      filePath: path,
      name: 'file',
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: ({ statusCode, data }) => {
        let parsed = data
        try { parsed = typeof data === 'string' ? JSON.parse(data) : data } catch (e) { parsed = {} }
        if (statusCode >= 200 && statusCode < 300 && parsed.asset_url) resolve(parsed.asset_url)
        else {
          if (statusCode === 401) app.clearSession()
          reject(new Error(detailMessage(parsed)))
        }
      },
      fail: reject,
    })
  })
}

module.exports = { request, uuid, upload, promptLogin }
