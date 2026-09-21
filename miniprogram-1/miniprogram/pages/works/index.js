const {request}=require('../../utils/api')
const {seedTask}=require('../generate/seed')
const STATUS_TEXT={queued:'排队中',processing:'生成中',pending_review:'已完成',succeeded:'已完成',failed:'生成失败',rejected:'生成失败'}
Page({
  data:{tasks:[],filter:'all',filters:[{v:'all',n:'全部'},{v:'image',n:'图片'},{v:'video',n:'视频'}],loading:false,guest:false},
  async onShow(){
    await getApp().waitAuth()
    if(!getApp().isLoggedIn()){
      this.setData({guest:true,tasks:[],loading:false})
      return
    }
    this.setData({guest:false})
    this.load()
  },
  goLogin(){wx.navigateTo({url:'/pages/mine/auth/index'})},
  setFilter(e){this.setData({filter:e.currentTarget.dataset.value});this.load()},
  async load(){
    if(!getApp().isLoggedIn()) return
    this.setData({loading:true})
    try{
      const suffix=this.data.filter==='all'?'':`?feature_type=${this.data.filter}`
      const tasks=(await request(`/generations${suffix}`)).map(item=>({
        ...item,
        statusText:STATUS_TEXT[item.status]||item.status,
        pendingText:item.status==='failed'||item.status==='rejected'?(STATUS_TEXT[item.status]||'生成失败'):'AI 正在创作…'
      }))
      this.setData({tasks})
    }catch(e){wx.showToast({title:e.message,icon:'none'})}
    finally{this.setData({loading:false})}
  },
  openTask(e){
    const id=e.currentTarget.dataset.id
    if(!id) return
    const task=this.data.tasks.find((item)=>item.id===id)
    if(task) seedTask(task)
    wx.navigateTo({url:`/pages/generate/index?id=${id}`})
  },
  async remove(e){
    const id=e.currentTarget.dataset.id
    const confirmed=await new Promise((resolve)=>{
      wx.showModal({
        title:'删除作品',
        content:'删除后将从作品列表中移除，确认删除吗？',
        confirmText:'删除',
        confirmColor:'#e35151',
        success:(res)=>resolve(!!res.confirm),
        fail:()=>resolve(false),
      })
    })
    if(!confirmed) return
    try{
      await request(`/assets/${id}`,{method:'DELETE'})
      wx.showToast({title:'已删除'})
      this.load()
    }catch(err){wx.showToast({title:err.message,icon:'none'})}
  }
})
