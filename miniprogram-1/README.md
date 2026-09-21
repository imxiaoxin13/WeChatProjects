# AI 创作微信小程序

这是微信开发者平台通过当前 AppID 创建的原生小程序前端项目。`project.config.json`、`project.private.config.json` 和微信开发者工具项目结构均保留在本目录。

功能包括 ClipCat AI 生图、视频生成、参考视频复刻、DeepSeek 流式聊天、作品中心和个人中心。个人中心支持微信自动登录、账号注册登录、退出登录、积分查看与充值。视频页会展示后台从 ClipCat 实时目录取得的视频秒数、分辨率与比例选项。

## 关联项目

- 后台：`/Users/Admin/WeChatProjects/ai-creator-backend`
- 管理员端：`/Users/Admin/WeChatProjects/ai-creator-admin`

## 使用

1. 使用微信开发者工具直接打开本目录。
2. 本地联调时，`miniprogram/config.js` 默认请求 `http://127.0.0.1:8000/v1`，需在开发者工具中关闭合法域名校验。
3. 正式发布前，将 `apiBase` 改为后台的正式 HTTPS 地址，并在微信公众平台配置 request、uploadFile 和 downloadFile 合法域名。
4. API Key 只允许配置在后台服务器，不得写入本项目。
