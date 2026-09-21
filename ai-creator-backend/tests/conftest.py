import os
import tempfile
import uuid

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["MOCK_EXTERNAL_SERVICES"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["JWT_SECRET"] = "test-secret-at-least-thirty-two-characters"

import pytest
from fastapi.testclient import TestClient

from app.core.db import Base, engine
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    with TestClient(app) as value:
        yield value


@pytest.fixture()
def auth(client):
    client_ip = f"test-{uuid.uuid4().hex}"
    token = client.post("/v1/auth/wechat", headers={"X-Real-IP": client_ip},
                        json={"code": "test-user"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Real-IP": client_ip}
