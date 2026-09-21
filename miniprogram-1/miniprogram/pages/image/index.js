const {request,uuid,upload,promptLogin}=require('../../utils/api')
const {seedTask}=require('../generate/seed')

const RATIO_LABELS={'1:1':'方图','16:9':'横版','9:16':'竖版'}
const CLIPCAT_RATIOS=['1:1','16:9','9:16']

function formatRatios(values){
  return (values&&values.length?values:CLIPCAT_RATIOS).map(value=>{
    const parts=String(value).split(':').map(Number)
    const a=parts[0]||1,b=parts[1]||1
    let w=56,h=56
    if(a>=b){w=72;h=Math.max(28,Math.round(72*b/a))}
    else{h=72;w=Math.max(28,Math.round(72*a/b))}
    return {value,label:RATIO_LABELS[value]||value,w,h}
  })
}

Page({
  data:{prompt:'',ratios:formatRatios(CLIPCAT_RATIOS),ratio:'1:1',localImages:[],submitting:false},
  onLoad(){this.loadOptions()},
  async loadOptions(){
    try{
      const products=await request('/ai-products?feature_type=image',{auth:false})
      const product=products[0]||{}
      const ratios=formatRatios(product.config&&product.config.aspect_ratios)
      const next={ratios}
      if(!ratios.some(item=>item.value===this.data.ratio)) next.ratio=ratios[0]?ratios[0].value:'1:1'
      this.setData(next)
    }catch(e){wx.showToast({title:e.message,icon:'none'})}
  },
  onPrompt(e){this.setData({prompt:e.detail.value})},
  pickRatio(e){this.setData({ratio:e.currentTarget.dataset.value})},
  choose(){
    wx.chooseMedia({
      count:5-this.data.localImages.length,
      mediaType:['image'],
      success:r=>this.setData({localImages:[...this.data.localImages,...r.tempFiles.map(x=>x.tempFilePath)]})
    })
  },
  remove(e){
    const i=e.currentTarget.dataset.index
    this.setData({localImages:this.data.localImages.filter((_,n)=>n!==i)})
  },
  async submit(){
    if(!getApp().isLoggedIn()) return promptLogin()
    if(!this.data.prompt.trim()) return wx.showToast({title:'请填写画面描述',icon:'none'})
    this.setData({submitting:true})
    wx.showLoading({title:'正在提交'})
    try{
      const urls=[]
      for(const path of this.data.localImages) urls.push(await upload(path))
      const task=await request('/generations/images',{
        method:'POST',
        data:{
          prompt:this.data.prompt,
          params:{aspect_ratio:this.data.ratio,image_urls:urls},
          idempotency_key:uuid()
        }
      })
      seedTask(task)
      wx.redirectTo({url:`/pages/generate/index?id=${task.id}`})
    }catch(e){wx.showToast({title:e.message,icon:'none'})}
    finally{wx.hideLoading();this.setData({submitting:false})}
  }
})
