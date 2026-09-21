import asyncio
import hashlib
import json

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, get_db
from app.core.security import create_token, get_current_user, get_optional_user, hash_password, verify_password
from app.models import (
    AIProduct, Asset, ChatMessage, Conversation, GenerationTask, PointAccount,
    PointLedger, RechargeOrder, RechargePackage, RiskEvent, SystemSetting, TaskStatus, User, new_id, utcnow,
)
from app.schemas import (
    AccountLoginIn, AccountRegisterIn, ChatIn, ConversationIn, GenerationIn,
    ProfilePatchIn, RechargeOrderIn, WechatLoginIn,
)
from app.services.content_safety import ContentRejected, content_safety
from app.services.providers import IMAGE_ASPECT_RATIOS, clipcat, deepseek, is_social_reference_url, normalize_reference_video_url
from app.services.storage import storage
from app.services.wallet import capture, credit, release, reserve
from app.workers.tasks import process_generation


router = APIRouter()
YOGA_PRODUCTS_SETTING_KEY = "hot_products:yoga_pants:US"
ACCOUNT_OPENID_PREFIX = "acct_"


def wechat_bound(user: User) -> bool:
    return bool(user.openid) and not user.openid.startswith(ACCOUNT_OPENID_PREFIX)


def account_openid(username: str) -> str:
    return f"{ACCOUNT_OPENID_PREFIX}{username}"


def issue_token(user: User) -> dict:
    return {"access_token": create_token(user.id, "user"), "token_type": "bearer"}


def create_user(db: Session, **kwargs) -> User:
    user = User(**kwargs)
    db.add(user)
    db.flush()
    db.add(PointAccount(user_id=user.id, balance=0, frozen=0))
    return user


def user_payload(user: User, account: PointAccount | None) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "avatar_url": user.avatar_url,
        "status": user.status,
        "has_password": bool(user.password_hash),
        "wechat_bound": wechat_bound(user),
        "balance": account.balance if account else 0,
        "frozen": account.frozen if account else 0,
    }


async def resolve_wechat_openid(code: str) -> str:
    if settings.mock_external_services or not settings.wechat_configured:
        return "mock_" + hashlib.sha256(code.encode()).hexdigest()[:24]
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get("https://api.weixin.qq.com/sns/jscode2session", params={
            "appid": settings.wechat_app_id,
            "secret": settings.wechat_app_secret,
            "js_code": code,
            "grant_type": "authorization_code",
        })
        response.raise_for_status()
    data = response.json()
    openid = data.get("openid")
    if not openid:
        raise HTTPException(status_code=401, detail=data.get("errmsg", "微信登录失败"))
    return openid


def task_json(task: GenerationTask) -> dict:
    return {
        "id": task.id,
        "feature_type": task.feature_type,
        "status": task.status,
        "prompt": task.prompt,
        "params": task.request_params,
        "points": task.frozen_points,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "assets": [
            {
                "id": item.id,
                "media_type": item.media_type,
                "url": storage.signed_get(item.oss_key) if item.oss_key else item.external_url,
                "review_status": item.review_status,
            }
            for item in task.assets if not item.deleted_at
        ],
        "created_at": task.created_at.isoformat(),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.post("/auth/wechat")
async def wechat_login(payload: WechatLoginIn, db: Session = Depends(get_db),
                      current: User | None = Depends(get_optional_user)):
    openid = await resolve_wechat_openid(payload.code)
    existing = db.scalar(select(User).where(User.openid == openid))
    if current:
        if wechat_bound(current) and current.openid != openid:
            raise HTTPException(status_code=409, detail="该账号已绑定其他微信")
        if existing and existing.id != current.id:
            raise HTTPException(status_code=409, detail="该微信已绑定其他账号")
        current.openid = openid
        if not current.nickname:
            current.nickname = "微信用户"
        db.commit()
        return issue_token(current)
    if not existing:
        existing = create_user(db, openid=openid, nickname="微信用户")
        db.commit()
    return issue_token(existing)


@router.post("/auth/register")
def register(payload: AccountRegisterIn, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=409, detail="该账号已被注册")
    nickname = (payload.nickname or "").strip() or username
    user = create_user(
        db,
        openid=account_openid(username),
        username=username,
        password_hash=hash_password(payload.password),
        nickname=nickname,
    )
    db.commit()
    return issue_token(user)


@router.post("/auth/login")
def login(payload: AccountLoginIn, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return issue_token(user)


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_payload(user, db.get(PointAccount, user.id))


@router.patch("/me")
def update_me(payload: ProfilePatchIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.nickname is None and payload.avatar_url is None:
        raise HTTPException(status_code=400, detail="请提供要更新的资料")
    if payload.nickname is not None:
        user.nickname = payload.nickname.strip()
    if payload.avatar_url is not None:
        user.avatar_url = payload.avatar_url.strip() or None
    db.commit()
    return user_payload(user, db.get(PointAccount, user.id))


@router.get("/hot-products/yoga-pants")
def yoga_pants_hot_products(db: Session = Depends(get_db)):
    row = db.get(SystemSetting, YOGA_PRODUCTS_SETTING_KEY)
    if not row or not row.value.get("products"):
        raise HTTPException(status_code=503, detail="瑜伽裤爆品榜单正在初始化")
    return row.value


@router.get("/wallet/ledger")
def wallet_ledger(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(PointLedger).where(PointLedger.user_id == user.id)
                      .order_by(PointLedger.created_at.desc()).limit(100)).all()
    return [{"id": row.id, "kind": row.kind, "amount": row.amount,
             "balance_after": row.balance_after, "note": row.note,
             "created_at": row.created_at.isoformat()} for row in rows]


@router.get("/ai-products")
def products(feature_type: str | None = None, db: Session = Depends(get_db)):
    query = select(AIProduct).where(AIProduct.is_active.is_(True))
    if feature_type:
        query = query.where(AIProduct.feature_type == feature_type)
    rows = db.scalars(query.order_by(AIProduct.points_cost)).all()
    public_keys = {
        "aspect_ratios", "duration", "resolution", "aspect_ratio",
        "durations", "resolutions", "combinations",
    }
    payload = []
    for item in rows:
        config = {key: value for key, value in (item.config or {}).items() if key in public_keys}
        if item.feature_type == "image":
            config["aspect_ratios"] = list(IMAGE_ASPECT_RATIOS)
        elif item.feature_type == "video" and item.provider == "clipcat":
            try:
                options = clipcat.video_options(item.model, item.config or {})
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail="视频参数同步暂不可用") from exc
            options["combinations"] = [
                {
                    "duration": combination["duration"],
                    "resolution": combination["resolution"],
                    "points_cost": max(item.points_cost, int(combination.get("supplier_credits") or 0)),
                }
                for combination in options["combinations"]
            ]
            config.update(options)
        payload.append({"id": item.id, "name": item.name, "feature_type": item.feature_type,
                        "points_cost": item.points_cost, "config": config})
    return payload


def usable_image_url(value) -> bool:
    text = str(value or "").strip()
    return text.startswith(("https://", "http://", "local://"))


@router.post("/uploads/presign")
def presign_upload(payload: dict, user: User = Depends(get_current_user)):
    filename = str(payload.get("filename", "upload"))[:200]
    content_type = str(payload.get("content_type", ""))
    size_bytes = int(payload.get("size_bytes", 0))
    if size_bytes <= 0 or size_bytes > settings.upload_max_bytes:
        raise HTTPException(status_code=400, detail=f"文件大小必须在 1 到 {settings.upload_max_bytes // 1024 // 1024}MB 之间")
    try:
        return storage.presign_put(user.id, filename, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/uploads")
async def upload_media(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    data = await file.read()
    if not data or len(data) > settings.upload_max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小必须在 1 到 {settings.upload_max_bytes // 1024 // 1024}MB 之间",
        )
    try:
        return storage.save_upload(user.id, file.filename or "upload", file.content_type or "", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _create_generation(feature_type: str, payload: GenerationIn, user: User, db: Session):
    existing = db.scalar(select(GenerationTask).where(
        GenerationTask.user_id == user.id,
        GenerationTask.idempotency_key == payload.idempotency_key,
    ))
    if existing:
        return task_json(existing)
    product = db.get(AIProduct, payload.product_id) if payload.product_id else db.scalar(
        select(AIProduct).where(
            AIProduct.feature_type == feature_type,
            AIProduct.provider == "clipcat",
            AIProduct.is_active.is_(True),
        ).order_by(AIProduct.points_cost, AIProduct.created_at)
    )
    if (not product or not product.is_active or product.feature_type != feature_type
            or product.provider != "clipcat"):
        raise HTTPException(status_code=503, detail="生成服务暂不可用")
    try:
        await content_safety.check_text(user.openid, payload.prompt)
    except ContentRejected as exc:
        db.add(RiskEvent(user_id=user.id, target_type=feature_type,
                         target_id=payload.idempotency_key, result="rejected",
                         detail={"reason": str(exc)}))
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    task_points = product.points_cost
    request_params = {**product.config, **payload.params, "model": product.model}
    if "max_supplier_credits" in (product.config or {}):
        request_params["max_supplier_credits"] = product.config["max_supplier_credits"]
    if feature_type == "image":
        ratio = str(request_params.get("aspect_ratio") or "1:1")
        if ratio not in IMAGE_ASPECT_RATIOS:
            raise HTTPException(status_code=400, detail="不支持的画面比例")
        request_params["aspect_ratio"] = ratio
        request_params["aspect_ratios"] = list(IMAGE_ASPECT_RATIOS)
    if feature_type == "video":
        mode = request_params.get("generation_mode")
        if not mode:
            mode = "replicate" if request_params.get("reference_video_url") else "generate"
        if mode == "text":
            mode = "generate"
        if mode not in {"generate", "replicate"}:
            raise HTTPException(status_code=400, detail="不支持的视频生成方式")
        try:
            options = clipcat.video_options(product.model, product.config or {})
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="视频参数同步暂不可用") from exc
        try:
            duration = int(request_params.get("duration") or options["duration"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="不支持的视频秒数") from None
        resolution = str(request_params.get("resolution") or options["resolution"])
        aspect_ratio = str(request_params.get("aspect_ratio") or options["aspect_ratio"])
        combination = next((item for item in options["combinations"] if (
            item["duration"] == duration and item["resolution"] == resolution
        )), None)
        if not combination:
            raise HTTPException(status_code=400, detail="不支持的视频秒数与分辨率组合")
        if aspect_ratio not in options["aspect_ratios"]:
            raise HTTPException(status_code=400, detail="不支持的视频比例")
        request_params.update({
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
        })
        supplier_credits = int(combination.get("supplier_credits") or product.config.get(
            "max_supplier_credits", product.points_cost
        ))
        image_urls = request_params.get("image_urls") or []
        if mode == "generate":
            request_params["image_urls"] = []
            request_params["reference_video_url"] = ""
            request_params["provider_task_type"] = "raw"
        else:
            if not isinstance(image_urls, list) or not image_urls or len(image_urls) > 5:
                raise HTTPException(status_code=400, detail="参考视频复刻需要上传 1 到 5 张替换素材图片")
            if any(str(item).startswith("mock://") for item in image_urls):
                raise HTTPException(status_code=400, detail="图片未上传成功，请重新添加替换素材后再试")
            if any(not usable_image_url(item) for item in image_urls):
                raise HTTPException(status_code=400, detail="替换素材图片地址无效，请重新上传后再试")
            if not request_params.get("reference_video_url"):
                raise HTTPException(status_code=400, detail="参考视频复刻需要视频链接")
            try:
                request_params["reference_video_url"] = normalize_reference_video_url(
                    request_params["reference_video_url"]
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if is_social_reference_url(request_params["reference_video_url"]):
                supplier_credits += 10
            request_params["provider_task_type"] = "replicate"
        request_params["max_supplier_credits"] = supplier_credits
        request_params["generation_mode"] = mode
        task_points = max(product.points_cost, supplier_credits)
    task = GenerationTask(
        user_id=user.id, product_id=product.id, feature_type=feature_type,
        provider=product.provider, status=TaskStatus.QUEUED.value,
        prompt=payload.prompt, request_params=request_params,
        frozen_points=task_points, idempotency_key=payload.idempotency_key,
    )
    db.add(task)
    db.flush()
    reserve(db, user.id, task_points, "generation", task.id, payload.idempotency_key)
    db.commit()
    process_generation.delay(task.id)
    db.refresh(task)
    return task_json(task)


@router.post("/generations/images")
async def create_image(payload: GenerationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _create_generation("image", payload, user, db)


@router.post("/generations/videos")
async def create_video(payload: GenerationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _create_generation("video", payload, user, db)


@router.get("/generations")
def generations(feature_type: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(GenerationTask).where(GenerationTask.user_id == user.id, GenerationTask.deleted_at.is_(None))
    if feature_type:
        query = query.where(GenerationTask.feature_type == feature_type)
    rows = db.scalars(query.order_by(GenerationTask.created_at.desc()).limit(100)).unique().all()
    return [task_json(item) for item in rows]


@router.get("/generations/{task_id}")
def generation(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(GenerationTask, task_id)
    if not task or task.user_id != user.id or task.deleted_at:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task_json(task)


def conversation_json(row: Conversation, preview: str = "") -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "preview": preview,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def conversation_previews(db: Session, conversation_ids: list[str]) -> dict[str, str]:
    if not conversation_ids:
        return {}
    latest = (
        select(
            ChatMessage.conversation_id,
            func.max(ChatMessage.created_at).label("max_created"),
        )
        .where(ChatMessage.conversation_id.in_(conversation_ids))
        .group_by(ChatMessage.conversation_id)
        .subquery()
    )
    rows = db.execute(
        select(ChatMessage.conversation_id, ChatMessage.content).join(
            latest,
            (ChatMessage.conversation_id == latest.c.conversation_id)
            & (ChatMessage.created_at == latest.c.max_created),
        )
    ).all()
    return {conversation_id: (content or "").replace("\n", " ")[:40] for conversation_id, content in rows}


@router.post("/conversations")
def create_conversation(payload: ConversationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = Conversation(user_id=user.id, title=payload.title)
    db.add(row)
    db.commit()
    return conversation_json(row)


@router.get("/conversations")
def conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Conversation).where(Conversation.user_id == user.id)
                      .order_by(Conversation.updated_at.desc()).limit(100)).all()
    previews = conversation_previews(db, [row.id for row in rows])
    return [conversation_json(row, previews.get(row.id, "")) for row in rows]


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id))
    db.delete(conversation)
    db.commit()
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    rows = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
                      .order_by(ChatMessage.created_at)).all()
    return [{"id": row.id, "role": row.role, "content": row.content,
             "status": row.status, "created_at": row.created_at.isoformat()} for row in rows]


@router.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, payload: ChatIn, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    duplicate = db.scalar(select(ChatMessage).where(
        ChatMessage.conversation_id == conversation_id,
        ChatMessage.idempotency_key == payload.idempotency_key,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="该消息已提交")
    product = db.scalar(select(AIProduct).where(
        AIProduct.feature_type == "chat", AIProduct.is_active.is_(True)).order_by(AIProduct.points_cost))
    if not product:
        raise HTTPException(status_code=503, detail="聊天服务未开放")
    try:
        await content_safety.check_text(user.openid, payload.content, scene=2)
    except ContentRejected as exc:
        db.add(RiskEvent(user_id=user.id, target_type="chat",
                         target_id=payload.idempotency_key, result="rejected",
                         detail={"reason": str(exc)}))
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    message = ChatMessage(
        conversation_id=conversation_id, user_id=user.id, role="user", content=payload.content,
        status="completed", points_cost=product.points_cost, idempotency_key=payload.idempotency_key,
    )
    db.add(message)
    db.flush()
    reserve(db, user.id, product.points_cost, "chat", message.id, payload.idempotency_key)
    if conversation.title == "新对话":
        conversation.title = payload.content[:30]
    conversation.updated_at = utcnow()
    db.commit()
    chat_setting = db.get(SystemSetting, "chat")
    chat_config = chat_setting.value if chat_setting else {}
    context_rounds = max(1, min(int(chat_config.get("max_context_rounds", settings.max_context_rounds)), 100))
    system_prompt = str(chat_config.get("system_prompt", settings.system_prompt))[:10000]
    user_id, message_id, model = user.id, message.id, product.model

    async def event_stream():
        answer = ""
        try:
            with SessionLocal() as stream_db:
                history = stream_db.scalars(select(ChatMessage).where(
                    ChatMessage.conversation_id == conversation_id,
                    ChatMessage.status == "completed",
                ).order_by(ChatMessage.created_at.desc()).limit(context_rounds * 2)).all()
                context = [{"role": "system", "content": system_prompt}]
                context.extend({"role": item.role, "content": item.content} for item in reversed(history))
            async for chunk in deepseek.stream(context, model):
                answer += chunk
                yield json.dumps({"type": "delta", "content": chunk}, ensure_ascii=False) + "\n"
            with SessionLocal() as stream_db:
                stream_db.add(ChatMessage(
                    conversation_id=conversation_id, user_id=user_id, role="assistant",
                    content=answer, status="completed", points_cost=0,
                ))
                conv = stream_db.get(Conversation, conversation_id)
                if conv:
                    conv.updated_at = utcnow()
                capture(stream_db, user_id, product.points_cost, "chat", message_id)
                stream_db.commit()
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
        except asyncio.CancelledError:
            with SessionLocal() as stream_db:
                failed = stream_db.get(ChatMessage, message_id)
                failed.status = "failed"
                release(stream_db, user_id, product.points_cost, "chat", message_id, "客户端断开连接")
                stream_db.commit()
            raise
        except Exception as exc:
            with SessionLocal() as stream_db:
                failed = stream_db.get(ChatMessage, message_id)
                failed.status = "failed"
                release(stream_db, user_id, product.points_cost, "chat", message_id, str(exc))
                stream_db.commit()
            yield json.dumps({"type": "error", "message": "AI 回复失败，积分已退还"}, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no"
    })


POINTS_PER_YUAN = 10


@router.get("/recharge-packages")
def recharge_packages(db: Session = Depends(get_db)):
    rows = db.scalars(select(RechargePackage).where(RechargePackage.is_active.is_(True))
                      .order_by(RechargePackage.sort_order, RechargePackage.amount_cents)).all()
    return [{"id": row.id, "name": row.name, "amount_cents": row.amount_cents,
             "points": row.points, "bonus_points": row.bonus_points} for row in rows]


@router.post("/recharge-orders")
def create_recharge_order(payload: RechargeOrderIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    existing = db.scalar(select(RechargeOrder).where(
        RechargeOrder.user_id == user.id, RechargeOrder.idempotency_key == payload.idempotency_key))
    if existing:
        return {"id": existing.id, "order_no": existing.order_no, "status": existing.status,
                "amount_cents": existing.amount_cents, "points": existing.points}
    points = payload.amount_yuan * POINTS_PER_YUAN
    order = RechargeOrder(
        order_no=f"R{utcnow():%Y%m%d%H%M%S}{new_id()[:8]}",
        user_id=user.id,
        package_id=None,
        amount_cents=payload.amount_yuan * 100,
        points=points,
        idempotency_key=payload.idempotency_key,
        status="paid",
    )
    db.add(order)
    db.flush()
    # TODO: 接入微信支付后改为 unpaid，支付成功回调再 credit。
    credit(db, user.id, points, "recharge", order.id, f"recharge:{order.id}", "充值到账，不可退款")
    db.commit()
    return {"id": order.id, "order_no": order.order_no, "status": order.status,
            "amount_cents": order.amount_cents, "points": order.points}


@router.get("/recharge-orders")
def recharge_orders(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(RechargeOrder).where(RechargeOrder.user_id == user.id)
                      .order_by(RechargeOrder.created_at.desc()).limit(100)).all()
    return [{"id": row.id, "order_no": row.order_no, "amount_cents": row.amount_cents,
             "points": row.points, "status": row.status, "created_at": row.created_at.isoformat()} for row in rows]


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if not asset or asset.user_id != user.id or asset.deleted_at:
        raise HTTPException(status_code=404, detail="作品不存在")
    now = utcnow()
    asset.deleted_at = now
    task = db.get(GenerationTask, asset.task_id) if asset.task_id else None
    if task and task.user_id == user.id:
        task.deleted_at = now
        for item in task.assets:
            if not item.deleted_at:
                item.deleted_at = now
    db.commit()
    return {"ok": True}
