import uuid

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Asset, GenerationTask, SystemSetting
from app.services.providers import clipcat


def test_login_and_me(client, auth):
    response = client.get("/v1/me", headers=auth)
    assert response.status_code == 200
    assert response.json()["balance"] == 0
    assert response.json()["wechat_bound"] is True
    assert response.json()["has_password"] is False


def test_register_login_and_wechat_bind(client):
    register_ip = {"X-Real-IP": f"test-{uuid.uuid4().hex}"}
    registered = client.post("/v1/auth/register", headers=register_ip, json={
        "username": "Alice_01", "password": "secret12", "nickname": "爱丽丝",
    })
    assert registered.status_code == 200, registered.text
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", **register_ip}
    me = client.get("/v1/me", headers=headers).json()
    assert me["username"] == "alice_01"
    assert me["nickname"] == "爱丽丝"
    assert me["has_password"] is True
    assert me["wechat_bound"] is False

    duplicate = client.post("/v1/auth/register", headers={"X-Real-IP": f"test-{uuid.uuid4().hex}"}, json={
        "username": "Alice_01", "password": "secret12",
    })
    assert duplicate.status_code == 409

    login = client.post("/v1/auth/login", headers={"X-Real-IP": f"test-{uuid.uuid4().hex}"}, json={
        "username": "Alice_01", "password": "secret12",
    })
    assert login.status_code == 200
    wrong = client.post("/v1/auth/login", headers={"X-Real-IP": f"test-{uuid.uuid4().hex}"}, json={
        "username": "Alice_01", "password": "wrong-password",
    })
    assert wrong.status_code == 401

    patched = client.patch("/v1/me", headers=headers, json={"nickname": "新昵称"})
    assert patched.status_code == 200
    assert patched.json()["nickname"] == "新昵称"

    bound = client.post("/v1/auth/wechat", headers=headers, json={"code": "bind-alice"})
    assert bound.status_code == 200
    me2 = client.get("/v1/me", headers={"Authorization": f"Bearer {bound.json()['access_token']}", **register_ip}).json()
    assert me2["id"] == me["id"]
    assert me2["wechat_bound"] is True

    conflict = client.post("/v1/auth/wechat", headers=headers, json={"code": "another-wechat"})
    assert conflict.status_code == 409


def test_yoga_hot_products_endpoint_returns_cached_snapshot(client):
    payload = {
        "data_date": "2026-09-19",
        "products": [{"rank": index, "name": f"瑜伽裤 {index}"} for index in range(1, 11)],
    }
    with SessionLocal() as db:
        row = db.get(SystemSetting, "hot_products:yoga_pants:US")
        if row:
            row.value = payload
        else:
            db.add(SystemSetting(key="hot_products:yoga_pants:US", value=payload))
        db.commit()

    response = client.get("/v1/hot-products/yoga-pants")

    assert response.status_code == 200
    assert response.json()["data_date"] == "2026-09-19"
    assert len(response.json()["products"]) == 10


def test_admin_recharge_and_generation(client, auth):
    login = client.post("/v1/admin/auth/login", json={"username": "admin", "password": "change-me-before-deploy"})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    admin_headers = {"X-CSRF-Token": csrf}

    user = client.get("/v1/me", headers=auth).json()
    adjust = client.post(
        f"/v1/admin/users/{user['id']}/points",
        headers=admin_headers,
        json={"amount": 200, "note": "测试积分", "idempotency_key": uuid.uuid4().hex},
    )
    assert adjust.status_code == 200

    product = next(item for item in client.get("/v1/ai-products?feature_type=image").json())
    generated = client.post(
        "/v1/generations/images", headers=auth,
        json={"product_id": product["id"], "prompt": "一只橙色小猫", "params": {},
              "idempotency_key": uuid.uuid4().hex},
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["status"] == "succeeded"
    assert client.get("/v1/me", headers=auth).json()["balance"] == 190


def test_delete_work_is_soft_deleted(client, auth):
    login = client.post("/v1/admin/auth/login", json={"username": "admin", "password": "change-me-before-deploy"})
    csrf = login.json()["csrf_token"]
    user = client.get("/v1/me", headers=auth).json()
    client.post(f"/v1/admin/users/{user['id']}/points", headers={"X-CSRF-Token": csrf}, json={
        "amount": 100, "note": "删除作品测试积分", "idempotency_key": uuid.uuid4().hex,
    })
    product = client.get("/v1/ai-products?feature_type=image").json()[0]
    generated = client.post("/v1/generations/images", headers=auth, json={
        "product_id": product["id"], "prompt": "待删除的小猫", "params": {},
        "idempotency_key": uuid.uuid4().hex,
    }).json()
    asset_id = generated["assets"][0]["id"]
    assert client.delete(f"/v1/assets/{asset_id}", headers=auth).status_code == 200
    leftover = [item["id"] for item in client.get("/v1/generations", headers=auth).json()]
    assert generated["id"] not in leftover
    assert client.get(f"/v1/generations/{generated['id']}", headers=auth).status_code == 404
    assert client.delete(f"/v1/assets/{asset_id}", headers=auth).status_code == 404
    with SessionLocal() as db:
        asset = db.get(Asset, asset_id)
        task = db.get(GenerationTask, generated["id"])
        assert asset is not None and asset.deleted_at is not None
        assert task is not None and task.deleted_at is not None


def test_generation_idempotency(client, auth):
    login = client.post("/v1/admin/auth/login", json={"username": "admin", "password": "change-me-before-deploy"})
    csrf = login.json()["csrf_token"]
    user = client.get("/v1/me", headers=auth).json()
    client.post(f"/v1/admin/users/{user['id']}/points", headers={"X-CSRF-Token": csrf},
                json={"amount": 100, "note": "补充测试积分", "idempotency_key": uuid.uuid4().hex})
    product = client.get("/v1/ai-products?feature_type=image").json()[0]
    key = uuid.uuid4().hex
    body = {"product_id": product["id"], "prompt": "幂等测试", "params": {}, "idempotency_key": key}
    first = client.post("/v1/generations/images", headers=auth, json=body)
    second = client.post("/v1/generations/images", headers=auth, json=body)
    assert first.json()["id"] == second.json()["id"]


def test_image_generation_uses_backend_default_clipcat_product(client, auth):
    login = client.post("/v1/admin/auth/login", json={"username": "admin", "password": "change-me-before-deploy"})
    csrf = login.json()["csrf_token"]
    user = client.get("/v1/me", headers=auth).json()
    client.post(f"/v1/admin/users/{user['id']}/points", headers={"X-CSRF-Token": csrf}, json={
        "amount": 100, "note": "生图测试积分", "idempotency_key": uuid.uuid4().hex,
    })

    response = client.post("/v1/generations/images", headers=auth, json={
        "prompt": "一只宇航员小猫", "params": {"aspect_ratio": "1:1"},
        "idempotency_key": uuid.uuid4().hex,
    })

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"
    assert response.json()["params"]["model"] == "default"
    assert response.json()["params"]["aspect_ratio"] == "1:1"


def test_image_products_expose_clipcat_aspect_ratios(client):
    product = client.get("/v1/ai-products?feature_type=image").json()[0]
    assert "model" not in product
    assert product["config"]["aspect_ratios"] == ["1:1", "16:9", "9:16"]


def test_image_generation_rejects_unsupported_aspect_ratio(client, auth):
    login = client.post("/v1/admin/auth/login", json={"username": "admin", "password": "change-me-before-deploy"})
    csrf = login.json()["csrf_token"]
    user = client.get("/v1/me", headers=auth).json()
    client.post(f"/v1/admin/users/{user['id']}/points", headers={"X-CSRF-Token": csrf}, json={
        "amount": 100, "note": "比例测试积分", "idempotency_key": uuid.uuid4().hex,
    })
    response = client.post("/v1/generations/images", headers=auth, json={
        "prompt": "一只宇航员小猫", "params": {"aspect_ratio": "21:9"},
        "idempotency_key": uuid.uuid4().hex,
    })
    assert response.status_code == 400
    assert "画面比例" in response.text


def test_video_generation_uses_raw_mode(client, auth):
    login = client.post("/v1/admin/auth/login", json={"username": "admin", "password": "change-me-before-deploy"})
    csrf = login.json()["csrf_token"]
    user = client.get("/v1/me", headers=auth).json()
    client.post(f"/v1/admin/users/{user['id']}/points", headers={"X-CSRF-Token": csrf}, json={
        "amount": 200, "note": "视频测试积分", "idempotency_key": uuid.uuid4().hex,
    })

    response = client.post("/v1/generations/videos", headers=auth, json={
        "prompt": "宇航员小猫在太空看地球，电影感推进镜头",
        "params": {"generation_mode": "generate", "image_urls": [], "max_supplier_credits": 9999},
        "idempotency_key": uuid.uuid4().hex,
    })

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"
    assert response.json()["params"]["generation_mode"] == "generate"
    assert response.json()["params"]["provider_task_type"] == "raw"
    assert response.json()["params"]["max_supplier_credits"] == 80


def test_video_products_expose_selectable_generation_parameters(client):
    product = client.get("/v1/ai-products?feature_type=video").json()[0]
    assert product["config"]["durations"]
    assert product["config"]["resolutions"]
    assert product["config"]["aspect_ratios"]
    assert product["config"]["combinations"]
    assert product["config"]["combinations"][0]["points_cost"] == product["points_cost"]


def test_video_generation_rejects_unsupported_parameters(client, auth):
    response = client.post("/v1/generations/videos", headers=auth, json={
        "prompt": "宇航员小猫在太空看地球",
        "params": {
            "generation_mode": "generate",
            "duration": 99,
            "resolution": "8k",
            "aspect_ratio": "1:1",
        },
        "idempotency_key": uuid.uuid4().hex,
    })
    assert response.status_code == 400
    assert "视频秒数与分辨率组合" in response.text


def test_product_video_mode_is_removed(client, auth):
    response = client.post("/v1/generations/videos", headers=auth, json={
        "prompt": "旧版商品视频请求",
        "params": {"generation_mode": "product", "image_urls": ["https://example.com/a.jpg"]},
        "idempotency_key": uuid.uuid4().hex,
    })
    assert response.status_code == 400
    assert "视频生成方式" in response.text


def test_upload_stores_local_asset_for_replicate(client, auth, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    uploaded = client.post("/v1/uploads", headers=auth, files={
        "file": ("product.jpg", b"\xff\xd8\xff\xd9", "image/jpeg"),
    })
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["asset_url"].startswith("local://")

    rejected = client.post("/v1/generations/videos", headers=auth, json={
        "prompt": "用我的商品复刻这条视频",
        "params": {
            "generation_mode": "replicate",
            "image_urls": ["mock://uploads/x.jpg"],
            "reference_video_url": "https://www.tiktok.com/@u/video/1",
        },
        "idempotency_key": uuid.uuid4().hex,
    })
    assert rejected.status_code == 400
    assert "图片未上传成功" in rejected.text


def test_replicate_rejects_douyin_search_page(client, auth):
    response = client.post("/v1/generations/videos", headers=auth, json={
        "prompt": "替换人物，衣服变黑色",
        "params": {
            "generation_mode": "replicate",
            "image_urls": ["https://example.com/a.jpg"],
            "reference_video_url": "https://www.douyin.com/search/%E5%B0%8Flin%E8%AF%B4",
        },
        "idempotency_key": uuid.uuid4().hex,
    })
    assert response.status_code == 400
    assert "分享链接" in response.text


def test_video_generation_uses_selected_live_combination_cost(client, auth, monkeypatch):
    login = client.post("/v1/admin/auth/login", json={
        "username": "admin", "password": "change-me-before-deploy",
    })
    csrf = login.json()["csrf_token"]
    user = client.get("/v1/me", headers=auth).json()
    client.post(f"/v1/admin/users/{user['id']}/points", headers={"X-CSRF-Token": csrf}, json={
        "amount": 200, "note": "动态视频积分", "idempotency_key": uuid.uuid4().hex,
    })
    monkeypatch.setattr(clipcat, "video_options", lambda model, config: {
        "duration": 10,
        "resolution": "480p",
        "aspect_ratio": "9:16",
        "durations": [10, 15],
        "resolutions": ["480p", "720p"],
        "aspect_ratios": ["9:16", "16:9"],
        "combinations": [
            {"duration": 10, "resolution": "480p", "supplier_credits": 60},
            {"duration": 15, "resolution": "720p", "supplier_credits": 160},
        ],
    })

    response = client.post("/v1/generations/videos", headers=auth, json={
        "prompt": "城市夜景延时摄影",
        "params": {
            "generation_mode": "generate",
            "duration": 15,
            "resolution": "720p",
            "aspect_ratio": "16:9",
        },
        "idempotency_key": uuid.uuid4().hex,
    })

    assert response.status_code == 200, response.text
    assert response.json()["points"] == 160
    assert response.json()["params"]["max_supplier_credits"] == 160


def test_content_rejection_does_not_charge(client, auth):
    before = client.get("/v1/me", headers=auth).json()["balance"]
    product = client.get("/v1/ai-products?feature_type=image").json()[0]
    response = client.post("/v1/generations/images", headers=auth, json={
        "product_id": product["id"], "prompt": "__reject__", "params": {},
        "idempotency_key": uuid.uuid4().hex,
    })
    assert response.status_code == 422
    assert client.get("/v1/me", headers=auth).json()["balance"] == before


def test_recharge_credits_immediately_and_is_idempotent(client, auth):
    before = client.get("/v1/me", headers=auth).json()["balance"]
    key = uuid.uuid4().hex
    first = client.post("/v1/recharge-orders", headers=auth, json={"amount_yuan": 10, "idempotency_key": key})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "paid"
    assert first.json()["points"] == 100
    second = client.post("/v1/recharge-orders", headers=auth, json={"amount_yuan": 10, "idempotency_key": key})
    assert first.json()["id"] == second.json()["id"]
    after = client.get("/v1/me", headers=auth).json()["balance"]
    assert after - before == 100
    too_small = client.post("/v1/recharge-orders", headers=auth, json={
        "amount_yuan": 4, "idempotency_key": uuid.uuid4().hex,
    })
    assert too_small.status_code == 422


def test_conversation_history_and_delete(client, auth):
    first = client.post("/v1/conversations", headers=auth, json={"title": "会话一"}).json()
    second = client.post("/v1/conversations", headers=auth, json={"title": "会话二"}).json()
    listed = client.get("/v1/conversations", headers=auth).json()
    ids = [item["id"] for item in listed]
    assert first["id"] in ids
    assert second["id"] in ids
    assert listed[0]["id"] == second["id"]
    assert listed[0]["title"] == "会话二"
    assert listed[0]["preview"] == ""
    assert client.get(f"/v1/conversations/{first['id']}/messages", headers=auth).json() == []
    assert client.delete(f"/v1/conversations/{first['id']}", headers=auth).status_code == 200
    leftover = [item["id"] for item in client.get("/v1/conversations", headers=auth).json()]
    assert first["id"] not in leftover
    assert client.get(f"/v1/conversations/{first['id']}/messages", headers=auth).status_code == 404
    assert client.delete(f"/v1/conversations/{first['id']}", headers=auth).status_code == 404


def test_streaming_chat_charges_once(client, auth):
    conversation = client.post("/v1/conversations", headers=auth, json={"title": "测试"}).json()
    before = client.get("/v1/me", headers=auth).json()["balance"]
    with client.stream("POST", f"/v1/conversations/{conversation['id']}/messages", headers=auth,
                       json={"content": "你好", "idempotency_key": uuid.uuid4().hex}) as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert '"type": "done"' in body
    assert client.get("/v1/me", headers=auth).json()["balance"] == before - 1
