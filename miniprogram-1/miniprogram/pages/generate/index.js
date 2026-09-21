const {request}=require('../../utils/api')
const {takeSeed}=require('./seed')

const TITLE={
  queued:'正在生成',
  processing:'正在生成',
  pending_review:'生成完成',
  succeeded:'生成完成',
  failed:'生成失败',
  rejected:'生成失败'
}
const RUNNING=new Set(['queued','processing'])
const TIPS=[
  '生成完成后会自动展示，无需反复刷新',
  '图片一般需要 1-3 分钟，视频会更久一些',
  '生成失败时积分会自动退还',
  '等待时可以先去作品页看看历史创作'
]

function pad(n){return String(n).padStart(2,'0')}
function ratioBox(ratio){
  const [a,b]=(ratio||'1:1').split(':').map(Number)
  const w=a||1,h=b||1
  if(w>=h) return {width:'100%',paddingBottom:`${Math.round(100*h/w)}%`}
  return {width:`${Math.round(100*w/h)}%`,paddingBottom:'100%'}
}
function stepsOf(status){
  const labels=['提交任务','AI 生成','完成交付']
  const active=RUNNING.has(status)?1:2
  return labels.map((name,i)=>{
    if(status==='failed'||status==='rejected') return {name,state:i===2?'fail':'done'}
    if(status==='succeeded'||status==='pending_review') return {name,state:'done'}
    if(i<active) return {name,state:'done'}
    if(i===active) return {name,state:'active'}
    return {name,state:'wait'}
  })
}

Page({
  data:{
    loading:true,error:'',task:null,phase:'running',title:'正在生成',subtitle:'',
    kind:'图片',image:'',video:'',ratio:'1:1',
    hint:TIPS[0],steps:[],boxStyle:'',createdText:''
  },
  onLoad(query){
    this.taskId=query.id||''
    this.tipIndex=0
    const seeded=takeSeed(this.taskId)
    if(seeded) this.applyTask(seeded)
    if(!this.taskId){
      this.setData({loading:false,error:'未找到生成任务'})
      return
    }
    this.poll()
  },
  onUnload(){this.stop()},
  stop(){
    if(this.timer){clearTimeout(this.timer);this.timer=null}
    if(this.tipTimer){clearInterval(this.tipTimer);this.tipTimer=null}
  },
  applyTask(task){
    const phase=RUNNING.has(task.status)?'running':task.status==='succeeded'||task.status==='pending_review'?'success':'fail'
    const kind=task.feature_type==='video'?'视频':'图片'
    const image=task.feature_type==='image'&&task.assets&&task.assets[0]?task.assets[0].url:''
    const video=task.feature_type==='video'&&task.assets&&task.assets[0]?task.assets[0].url:''
    const ratio=(task.params&&task.params.aspect_ratio)||'1:1'
    const box=ratioBox(ratio)
    const created=task.created_at?new Date(task.created_at.endsWith('Z')?task.created_at:task.created_at+'Z'):null
    const subtitle=phase==='running'
      ?`AI 正在创作你的${kind}，请稍候`
      :phase==='success'?`你的${kind}已经准备好了`
      :(task.error_message||'可以返回后重新试一次')
    this.setData({
      loading:false,error:'',task,phase,kind,image,video,ratio,subtitle,
      title:TITLE[task.status]||'生成中',
      steps:stepsOf(task.status),
      boxStyle:`width:${box.width};padding-bottom:${box.paddingBottom};`,
      createdText:created?`${pad(created.getHours())}:${pad(created.getMinutes())} 提交` :''
    })
    wx.setNavigationBarTitle({title:TITLE[task.status]||'生成中'})
    if(phase==='running'){
      if(!this.tipTimer){
        this.tipTimer=setInterval(()=>{
          this.tipIndex=(this.tipIndex+1)%TIPS.length
          this.setData({hint:TIPS[this.tipIndex]})
        },4000)
      }
    }else if(this.tipTimer){
      clearInterval(this.tipTimer)
      this.tipTimer=null
    }
  },
  async poll(){
    try{
      const task=await request(`/generations/${this.taskId}`)
      this.applyTask(task)
      if(RUNNING.has(task.status)){
        if(this.timer) clearTimeout(this.timer)
        this.timer=setTimeout(()=>this.poll(),2500)
      }
    }catch(e){
      if(!this.data.task) this.setData({loading:false,error:e.message||'读取任务失败'})
    }
  },
  preview(){
    if(this.data.image) wx.previewImage({urls:[this.data.image]})
  },
  createAgain(){
    const url=this.data.task&&this.data.task.feature_type==='video'?'/pages/video/index':'/pages/image/index'
    wx.redirectTo({url})
  },
  toWorks(){wx.switchTab({url:'/pages/works/index'})}
})
