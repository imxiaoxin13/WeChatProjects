# AI Creator Admin

微信 AI 创作平台的独立 Vue 3 + TypeScript + Element Plus 管理端项目。

## 本地开发

后台 API 默认代理到 `http://127.0.0.1:8000`：

```bash
npm install
npm run dev
```

生产构建检查：

```bash
npm run build
```

## 独立部署

1. 将 `.env.example` 复制为 `.env`，把 `VITE_API_BASE` 设置为 FastAPI 后台的正式 HTTPS 地址，例如 `https://api.example.com/v1`。
2. 替换 `deploy/nginx/default.conf` 中的管理端域名，并将证书放入 `deploy/certs/`。
3. 执行 `docker compose up -d --build`。

管理员会话由后台通过 HttpOnly Cookie 管理，因此后台 `ALLOWED_ORIGINS` 必须包含管理端完整 HTTPS 域名，并保持 `withCredentials` 开启。

