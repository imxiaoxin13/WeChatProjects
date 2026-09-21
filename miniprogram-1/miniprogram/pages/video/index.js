const {request,uuid,upload,promptLogin}=require('../../utils/api')
const {seedTask}=require('../generate/seed')

function unique(values){return [...new Set(values)]}

Page({
  data:{
    products:[],mode:'generate',prompt:'',images:[],referenceVideoUrl:'',
    durations:[],resolutions:[],aspectRatios:[],combinations:[],
    duration:null,durationIndex:0,durationSliderMax:0,resolution:'',aspectRatio:'',submitting:false
  },
  onLoad(){this.loadProducts()},
  async loadProducts(){
    try{
      const products=await request('/ai-products?feature_type=video',{auth:false})
      this.setData({products})
      this.applyProduct(products[0]||{})
    }catch(e){wx.showToast({title:e.message,icon:'none'})}
  },
  applyProduct(product){
    const config=product.config||{}
    const combinations=config.combinations||[]
    const durations=config.durations||[config.duration||10]
    const duration=durations.includes(config.duration)?config.duration:durations[0]
    const validResolutions=combinations.length
      ?unique(combinations.filter(item=>item.duration===duration).map(item=>item.resolution))
      :(config.resolutions||[config.resolution||'480p'])
    const resolution=validResolutions.includes(config.resolution)?config.resolution:validResolutions[0]
    const aspectRatios=config.aspect_ratios||[config.aspect_ratio||'9:16']
    const aspectRatio=aspectRatios.includes(config.aspect_ratio)?config.aspect_ratio:aspectRatios[0]
    const durationIndex=Math.max(0,durations.indexOf(duration))
    this.setData({
      combinations,durations,resolutions:validResolutions,aspectRatios,duration,
      durationIndex,durationSliderMax:Math.max(0,durations.length-1),resolution,aspectRatio
    })
  },
  setMode(e){this.setData({mode:e.currentTarget.dataset.mode})},
  onPrompt(e){this.setData({prompt:e.detail.value})},
  onReference(e){this.setData({referenceVideoUrl:e.detail.value})},
  pickDurationSlider(e){
    const durationIndex=Math.max(0,Math.min(Number(e.detail.value),this.data.durations.length-1))
    const duration=this.data.durations[durationIndex]
    const resolutions=this.data.combinations.length
      ?unique(this.data.combinations.filter(item=>item.duration===duration).map(item=>item.resolution))
      :this.data.resolutions
    const resolution=resolutions.includes(this.data.resolution)?this.data.resolution:resolutions[0]
    this.setData({durationIndex,duration,resolutions,resolution})
  },
  pickResolution(e){
    const resolution=e.currentTarget.dataset.value
    this.setData({resolution})
  },
  pickAspectRatio(e){this.setData({aspectRatio:e.currentTarget.dataset.value})},
  choose(){
    wx.chooseMedia({
      count:5-this.data.images.length,
      mediaType:['image'],
      success:r=>this.setData({images:[...this.data.images,...r.tempFiles.map(x=>x.tempFilePath)]})
    })
  },
  remove(e){
    const index=Number(e.currentTarget.dataset.index)
    this.setData({images:this.data.images.filter((_,i)=>i!==index)})
  },
  async submit(){
    if(!getApp().isLoggedIn()) return promptLogin()
    const product=this.data.products[0]
    if(!this.data.prompt.trim()) return wx.showToast({title:'请填写创作要求',icon:'none'})
    if(this.data.mode==='replicate'&&!this.data.images.length) return wx.showToast({title:'请添加替换素材图片',icon:'none'})
    if(this.data.mode==='replicate'&&!this.data.referenceVideoUrl.trim()) return wx.showToast({title:'请填写参考视频链接',icon:'none'})
    if(this.data.mode==='replicate'){
      const url=this.data.referenceVideoUrl.trim()
      if(/douyin\.com\/search|tiktok\.com\/search/i.test(url)&&!/[?&](modal_id|video_id)=\d+/.test(url)){
        return wx.showToast({title:'请粘贴视频分享链接，不要用搜索页',icon:'none'})
      }
    }
    this.setData({submitting:true})
    wx.showLoading({title:this.data.mode==='replicate'?'上传并提交':'正在提交'})
    try{
      const urls=[]
      if(this.data.mode==='replicate'){
        for(const path of this.data.images) urls.push(await upload(path))
      }
      const data={
        prompt:this.data.prompt,
        params:{
          generation_mode:this.data.mode,
          image_urls:urls,
          reference_video_url:this.data.mode==='replicate'?this.data.referenceVideoUrl.trim():'',
          duration:this.data.duration,
          resolution:this.data.resolution,
          aspect_ratio:this.data.aspectRatio
        },
        idempotency_key:uuid()
      }
      if(product) data.product_id=product.id
      const task=await request('/generations/videos',{method:'POST',data})
      seedTask(task)
      wx.redirectTo({url:`/pages/generate/index?id=${task.id}`})
    }catch(e){wx.showToast({title:e.message,icon:'none'})}
    finally{wx.hideLoading();this.setData({submitting:false})}
  }
})
