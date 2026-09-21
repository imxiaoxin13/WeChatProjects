# AI Creator Backend

微信 AI 创作小程序的独立 FastAPI 后台项目，包含用户、积分、充值审核、ClipCat 生图/视频生成/参考视频复刻、OSS 和管理端 API。

图片和视频创建接口允许省略 `product_id`。后台会自动选择对应功能下已启用的 ClipCat 配置，客户端无需暴露供应商或模型选择。视频产品接口以 ClipCat 实时 `models --raw` 目录为准，返回完整的视频秒数、分辨率、比例和有效组合；客户端提交的组合会再次校验。视频生成通过 `params.generation_mode = "generate"` 提交，并由 Worker 调用 ClipCat `generate` 通道。

## 本地开发

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload
```

默认使用 SQLite、同步 Celery 和 mock 外部服务，不会调用或消耗真实供应商额度。接口文档位于 `http://127.0.0.1:8000/docs`。

```bash
.venv/bin/pytest -q
```

## 本地 Docker 基础服务 + 源码启动

先准备本地配置并启动 MySQL、Redis：

```bash
cp .env.docker-local.example .env
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d mysql redis
.venv/bin/alembic upgrade head
```

API、Celery Worker 和定时任务分别在三个终端运行：

```bash
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
.venv/bin/celery -A app.workers.celery_app:celery_app worker --loglevel=INFO
# macOS 会自动使用 threads 池；若仍手动指定 prefork，任务会入队后立刻失败。
.venv/bin/celery -A app.workers.celery_app:celery_app beat --loglevel=INFO
```

停止基础服务：

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml down
```

## 阿里云生产部署

生产环境中 Docker Compose 只运行 MySQL、Redis 两项基础服务。API、Celery Worker 和 Celery Beat 直接从源码运行，由 systemd 负责开机自启与异常重启。

以下命令假设代码位于 `/opt/ai-creator-backend`，系统为支持 systemd 的 Alibaba Cloud Linux、Rocky Linux 或 Ubuntu：

```bash
cd /opt/ai-creator-backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 首次运行会创建 ai-creator 系统用户和配置文件，然后退出
sudo bash deploy/systemd/install.sh
sudo editor /etc/ai-creator/ai-creator.env

# Docker 中只会启动 mysql、redis，并与源码服务共用同一配置
docker compose --env-file /etc/ai-creator/ai-creator.env up -d

# Clipcat 必须安装到实际执行 Worker 的系统用户下
sudo -u ai-creator -H bash -c 'curl -fsSL https://clipcat.ai/cli -o /tmp/install-clipcat.sh && sh /tmp/install-clipcat.sh && rm /tmp/install-clipcat.sh'

# 配置完成后再次运行，安装并启动三个宿主机服务
sudo bash deploy/systemd/install.sh
```

如代码目录或服务用户不同，可分别作为参数传入：

```bash
sudo bash deploy/systemd/install.sh /srv/ai-creator appuser
```

服务管理与日志：

```bash
sudo systemctl status ai-creator-api ai-creator-worker ai-creator-beat
sudo journalctl -u ai-creator-worker -u ai-creator-beat -f
sudo systemctl restart ai-creator-api ai-creator-worker ai-creator-beat
```

`ai-creator-beat` 在整套部署中只能运行一个实例；`ai-creator-worker` 可以按吞吐量扩容。每天 00:00 的 TikTok 选品任务由 Beat 发布、Worker 执行。修改代码或配置后需重启对应的 systemd 服务。

宿主机安装 Nginx 后，可使用 `deploy/nginx/default.conf`；该配置将 `/v1/` 和 `/health` 转发到源码运行的 `127.0.0.1:8000`。替换其中域名并安装证书后再启用。

生产环境建议进一步将本机 MySQL 和 Redis 替换为阿里云 RDS 与 ApsaraDB Redis，并通过 VPC 内网访问。

已在任何消息或日志中暴露过的 API Key 都必须先吊销，再将新 Key 写入服务器 Secret；不要写入代码或提交 `.env`。
