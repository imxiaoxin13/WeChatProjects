const {request}=require('../../utils/api')

const HOT_PRODUCTS=[
  {rank:1,productId:'1729596073113195136',brand:'Shapellx',name:'AirSlim 塑形高腰瑜伽裤',category:'塑形款',gmv:'$14.62万',sales:'1768件',price:'$98.79',rating:'4.7★'},
  {rank:2,productId:'1732548484494758886',brand:'TikTok 热销',name:'三条装高腰加绒保暖瑜伽裤',category:'加绒款',gmv:'$2.70万',sales:'829件',price:'$38.99',rating:'4.9★'},
  {rank:3,productId:'1732067339613409435',brand:'CHRLEISURE',name:'六条装高腰口袋运动瑜伽裤',category:'组合装',gmv:'$2.86万',sales:'667件',price:'$49.83',rating:'4.6★'},
  {rank:4,productId:'1729560841401111015',brand:'TikTok 热销',name:'纯色高腰微喇修身瑜伽裤',category:'微喇款',gmv:'$1.69万',sales:'511件',price:'$33.16',rating:'3.5★'},
  {rank:5,productId:'1729485663226008830',brand:'SHOWITTY',name:'交叉腰微喇口袋瑜伽裤',category:'口袋款',gmv:'$8744',sales:'434件',price:'$20.58',rating:'4.3★'},
  {rank:6,productId:'1729410017419366654',brand:'SHOWITTY',name:'高腰加绒口袋保暖瑜伽裤',category:'加绒款',gmv:'$1.35万',sales:'433件',price:'$36.35',rating:'4.5★'},
  {rank:7,productId:'1732475372811424355',brand:'TikTok 热销',name:'三条装高腰收腹微喇瑜伽裤',category:'收腹款',gmv:'$1.09万',sales:'420件',price:'$41.10',rating:'3.7★'},
  {rank:8,productId:'1732617607618859907',brand:'ComfrtCore',name:'2.0 V 型腰线柔软高腰瑜伽裤',category:'V腰款',gmv:'$2.41万',sales:'410件',price:'$95.55',rating:'4.5★'},
  {rank:9,productId:'1732010666714174414',brand:'HIJESSE',name:'天鹅绒加厚高腰口袋瑜伽裤',category:'保暖款',gmv:'$1.15万',sales:'389件',price:'$40.29',rating:'4.3★'},
  {rank:10,productId:'1731963384215474327',brand:'TikTok 热销',name:'多尺码加厚加绒高腰瑜伽裤',category:'多尺码',gmv:'$8330',sales:'233件',price:'$35.72',rating:'4.5★'}
]

function formatUsd(value){
  const amount=Number(value)||0
  return amount>=10000?`$${(amount/10000).toFixed(2)}万`:`$${Math.round(amount)}`
}

function formatProducts(selection){
  if(!selection||!Array.isArray(selection.products)||selection.products.length!==10)return HOT_PRODUCTS
  return selection.products.map((item,index)=>({
    rank:index+1,
    productId:item.product_id,
    brand:item.brand||'TikTok 热销',
    name:item.name||item.original_name||'高腰瑜伽裤',
    category:item.category||'高腰款',
    gmv:formatUsd(item.gmv_30d),
    sales:`${Number(item.sales_30d)||0}件`,
    price:`$${(Number(item.price)||0).toFixed(2)}`,
    rating:`${(Number(item.rating)||0).toFixed(1)}★`
  }))
}

Page({
  data:{
    loggedIn:false,
    user:{balance:0,frozen:0},
    hotProducts:HOT_PRODUCTS,
    productUpdatedAt:'2026-09-19'
  },
  onShow(){this.load()},
  async load(){
    try{
      await getApp().waitAuth()
      const selectionPromise=request('/hot-products/yoga-pants',{auth:false}).catch(()=>null)
      let loggedIn=Boolean(getApp().isLoggedIn())
      let user={balance:0,frozen:0}
      if(loggedIn){
        try{user=await request('/me')}catch{loggedIn=false}
      }
      const selection=await selectionPromise
      this.setData({
        loggedIn,
        user,
        hotProducts:formatProducts(selection),
        productUpdatedAt:selection&&selection.data_date?selection.data_date:this.data.productUpdatedAt
      })
    }catch(e){
      wx.showToast({title:e.message,icon:'none'})
    }
  },
  copyProduct(e){
    const {brand,name}=e.currentTarget.dataset
    wx.setClipboardData({data:`${brand} ${name}`})
  },
  open(e){
    const url=e.currentTarget.dataset.url
    if(['/pages/chat/index','/pages/works/index','/pages/mine/index'].includes(url))wx.switchTab({url})
    else wx.navigateTo({url})
  }
})
