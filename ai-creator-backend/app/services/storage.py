import hashlib
import mimetypes
import os
import tempfile
import time
from urllib.parse import quote

import httpx
import oss2

from app.core.config import settings


ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/webp", "video/mp4", "video/quicktime"
}


class StorageService:
    def configured(self) -> bool:
        return bool(settings.oss_endpoint and settings.oss_bucket and settings.oss_access_key_id
                    and settings.oss_access_key_secret)

    def _bucket(self):
        auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
        return oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket)

    def _normalize_content_type(self, content_type: str, filename: str = "") -> str:
        value = (content_type or "").split(";")[0].strip().lower()
        if value == "image/jpg":
            value = "image/jpeg"
        if not value or value == "application/octet-stream":
            guessed, _ = mimetypes.guess_type(filename)
            value = (guessed or "image/jpeg").lower()
        if value not in ALLOWED_CONTENT_TYPES:
            raise ValueError("不支持的文件类型")
        return value

    def _new_key(self, user_id: str, filename: str, content_type: str) -> str:
        suffix = mimetypes.guess_extension(content_type) or ""
        if suffix == ".jpe":
            suffix = ".jpg"
        digest = hashlib.sha256(f"{user_id}:{filename}:{time.time_ns()}".encode()).hexdigest()[:24]
        return f"uploads/{user_id}/{digest}{suffix}"

    def _root(self) -> str:
        return os.path.abspath(settings.upload_dir or "data")

    def local_path(self, key: str) -> str:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ValueError("无效的文件路径")
        root = self._root()
        path = os.path.abspath(os.path.join(root, key))
        if os.path.commonpath([root, path]) != root:
            raise ValueError("无效的文件路径")
        return path

    def local_path_for(self, url: str) -> str | None:
        if not str(url or "").startswith("local://"):
            return None
        path = self.local_path(str(url)[len("local://"):])
        if not os.path.isfile(path):
            raise RuntimeError("上传的图片已失效，请重新上传")
        return path

    def presign_put(self, user_id: str, filename: str, content_type: str) -> dict:
        content_type = self._normalize_content_type(content_type, filename)
        key = self._new_key(user_id, filename, content_type)
        if not self.configured():
            return {"key": key, "upload_url": "", "asset_url": f"mock://{key}", "headers": {"Content-Type": content_type}, "mock": True}
        url = self._bucket().sign_url("PUT", key, 900, headers={"Content-Type": content_type})
        return {"key": key, "upload_url": url, "asset_url": self._bucket().sign_url("GET", key, 86400),
                "headers": {"Content-Type": content_type}, "mock": False}

    def save_upload(self, user_id: str, filename: str, content_type: str, data: bytes) -> dict:
        content_type = self._normalize_content_type(content_type, filename)
        key = self._new_key(user_id, filename, content_type)
        path = self.local_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        if self.configured():
            self._bucket().put_object(key, data, headers={"Content-Type": content_type})
        return {"key": key, "asset_url": f"local://{key}"}

    def signed_get(self, key: str) -> str:
        if settings.oss_public_base_url:
            return f"{settings.oss_public_base_url.rstrip('/')}/{quote(key)}"
        if not self.configured():
            return ""
        return self._bucket().sign_url("GET", key, 3600)

    def delete(self, key: str) -> None:
        if self.configured():
            self._bucket().delete_object(key)

    def import_remote(self, user_id: str, task_id: str, url: str, media_type: str) -> tuple[str | None, str | None]:
        """Copy a provider result to private OSS. Falls back to the URL only in mock/local mode."""
        if not self.configured():
            return None, url
        extension = ".png" if media_type == "image" else ".mp4"
        key = f"results/{user_id}/{task_id}/{hashlib.sha256(url.encode()).hexdigest()[:20]}{extension}"
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temp:
                temp_path = temp.name
                with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
                    response.raise_for_status()
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > 200 * 1024 * 1024:
                            raise ValueError("供应商产物超过 200MB 限制")
                        temp.write(chunk)
            self._bucket().put_object_from_file(key, temp_path)
            return key, None
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)


storage = StorageService()
