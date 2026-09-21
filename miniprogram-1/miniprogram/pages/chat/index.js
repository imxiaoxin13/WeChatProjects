const {request, uuid, promptLogin} = require('../../utils/api')
const app = getApp()
const CONV_KEY = 'current_conversation_id'

function pad(value) {
  return String(value).padStart(2, '0')
}

function formatTime(iso) {
  if (!iso) return ''
  const raw = String(iso).trim()
  const date = new Date(/Z$|[+-]\d\d:\d\d$/.test(raw) ? raw : raw.replace(' ', 'T') + 'Z')
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  if (date.toDateString() === now.toDateString()) {
    return `${pad(date.getHours())}:${pad(date.getMinutes())}`
  }
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1}月${date.getDate()}日`
  }
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`
}

function decorate(list, conversationId) {
  return (list || []).map((item) => ({
    ...item,
    timeText: formatTime(item.updated_at),
    active: item.id === conversationId,
  }))
}

Page({
  data: {
    conversationId: '',
    conversationTitle: '米鹊助手',
    conversations: [],
    historyOpen: false,
    messages: [],
    input: '',
    sending: false,
    scrollId: '',
    guest: false,
  },

  preventMove() {},

  goLogin() {
    wx.navigateTo({url: '/pages/mine/auth/index'})
  },

  async onShow() {
    await getApp().waitAuth()
    if (this.data.guest && getApp().isLoggedIn()) {
      this.setData({guest: false})
      try { await this.bootstrap() } catch (e) { wx.showToast({title: e.message, icon: 'none'}) }
    }
  },

  async onLoad() {
    await getApp().waitAuth()
    if (!getApp().isLoggedIn()) {
      this.setData({guest: true})
      return
    }
    try {
      await this.bootstrap()
    } catch (e) {
      wx.showToast({title: e.message, icon: 'none'})
    }
  },

  async bootstrap() {
    const conversations = await this.loadConversations()
    const savedId = wx.getStorageSync(CONV_KEY)
    let current = conversations.find((item) => item.id === savedId) || conversations[0]
    if (!current) {
      current = await request('/conversations', {method: 'POST', data: {title: '新对话'}})
    }
    await this.openConversation(current.id, current.title)
  },

  async loadConversations() {
    const rows = await request('/conversations')
    const conversations = decorate(rows, this.data.conversationId)
    this.setData({conversations})
    return conversations
  },

  remember(id) {
    wx.setStorageSync(CONV_KEY, id)
  },

  async openConversation(id, title) {
    this.remember(id)
    this.setData({
      conversationId: id,
      conversationTitle: title || '米鹊助手',
      input: '',
      historyOpen: false,
      conversations: decorate(this.data.conversations, id),
    })
    await this.loadMessages()
  },

  async loadMessages() {
    const messages = await request(`/conversations/${this.data.conversationId}/messages`)
    this.setData({
      messages,
      scrollId: messages.length ? `m-${messages.length - 1}` : '',
    })
  },

  onInput(e) {
    this.setData({input: e.detail.value})
  },

  useHint(e) {
    this.setData({input: e.currentTarget.dataset.text})
  },

  openHistory() {
    if (this.data.guest) return this.goLogin()
    this.setData({historyOpen: true})
    this.loadConversations().catch(() => {})
  },

  closeHistory() {
    this.setData({historyOpen: false})
  },

  async newChat() {
    if (this.data.guest) return this.goLogin()
    if (this.data.sending) {
      wx.showToast({title: '请等待回复完成', icon: 'none'})
      return
    }
    if (!this.data.messages.length && this.data.conversationTitle === '新对话') {
      this.closeHistory()
      return
    }
    try {
      const row = await request('/conversations', {method: 'POST', data: {title: '新对话'}})
      const conversations = decorate([row, ...this.data.conversations], row.id)
      this.setData({conversations, messages: [], input: '', historyOpen: false})
      await this.openConversation(row.id, row.title)
    } catch (e) {
      wx.showToast({title: e.message, icon: 'none'})
    }
  },

  async switchChat(e) {
    const id = e.currentTarget.dataset.id
    if (id === this.data.conversationId) {
      this.closeHistory()
      return
    }
    if (this.data.sending) {
      wx.showToast({title: '请等待回复完成', icon: 'none'})
      return
    }
    const item = this.data.conversations.find((row) => row.id === id)
    try {
      await this.openConversation(id, item && item.title)
    } catch (err) {
      wx.showToast({title: err.message, icon: 'none'})
    }
  },

  async deleteChat(e) {
    const id = e.currentTarget.dataset.id
    const confirmed = await new Promise((resolve) => {
      wx.showModal({
        title: '删除会话',
        content: '删除后无法恢复这条对话记录',
        success: (res) => resolve(res.confirm),
      })
    })
    if (!confirmed) return
    try {
      await request(`/conversations/${id}`, {method: 'DELETE'})
      let conversations = this.data.conversations.filter((item) => item.id !== id)
      this.setData({conversations})
      if (id !== this.data.conversationId) return
      if (conversations.length) {
        await this.openConversation(conversations[0].id, conversations[0].title)
      } else {
        const row = await request('/conversations', {method: 'POST', data: {title: '新对话'}})
        this.setData({conversations: decorate([row], row.id), messages: [], input: ''})
        await this.openConversation(row.id, row.title)
      }
    } catch (err) {
      wx.showToast({title: err.message, icon: 'none'})
    }
  },

  async send() {
    if (this.data.guest || !getApp().isLoggedIn()) return promptLogin()
    const content = this.data.input.trim()
    if (!content || this.data.sending) return
    const messages = [...this.data.messages, {role: 'user', content}, {role: 'assistant', content: '', streaming: true}]
    const assistantIndex = messages.length - 1
    const patch = {
      messages,
      input: '',
      sending: true,
      scrollId: `m-${assistantIndex}`,
    }
    if (this.data.conversationTitle === '新对话') {
      patch.conversationTitle = content.slice(0, 30)
    }
    this.setData(patch)
    const token = await app.ensureLogin()
    let buffer = ''
    const decoder = typeof TextDecoder !== 'undefined' ? new TextDecoder('utf-8') : null
    const consume = (text) => {
      buffer += text
      const lines = buffer.split('\n')
      buffer = lines.pop()
      lines.forEach((line) => {
        if (!line) return
        try {
          const event = JSON.parse(line)
          if (event.type === 'delta') {
            const key = `messages[${assistantIndex}].content`
            this.setData({
              [key]: this.data.messages[assistantIndex].content + event.content,
              scrollId: `m-${assistantIndex}`,
            })
          } else if (event.type === 'error') {
            wx.showToast({title: event.message, icon: 'none'})
          } else if (event.type === 'done') {
            this.loadConversations().catch(() => {})
          }
        } catch (e) {}
      })
    }
    const task = wx.request({
      url: `${app.globalData.apiBase}/conversations/${this.data.conversationId}/messages`,
      method: 'POST',
      enableChunked: true,
      data: {content, idempotency_key: uuid()},
      header: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
      success: (r) => {
        if (r.statusCode >= 400) wx.showToast({title: r.data.detail || '发送失败', icon: 'none'})
        this.setData({sending: false})
      },
      fail: () => {
        wx.showToast({title: '网络连接失败', icon: 'none'})
        this.setData({sending: false})
      },
    })
    task.onChunkReceived(({data}) => {
      try {
        consume(decoder ? decoder.decode(data, {stream: true}) : decodeURIComponent(escape(String.fromCharCode(...new Uint8Array(data)))))
      } catch (e) {}
    })
  },
})
