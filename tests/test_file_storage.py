import hashlib

import pytest

from app.file_storage import LocalFileStorage, SupabaseFileStorage
from app.queueing import validate_queue_configuration


def test_local_storage_round_trip_and_delete(tmp_path):
    storage = LocalFileStorage(tmp_path)
    key = "pending/opaque/document.pdf"
    content = b"documento-sintetico"
    storage.store(key, content)
    assert storage.exists(key)
    assert storage.read(key) == content
    assert hashlib.sha256(storage.read(key)).hexdigest() == hashlib.sha256(content).hexdigest()
    storage.delete(key)
    assert not storage.exists(key)


def test_supabase_storage_never_uses_public_url(monkeypatch):
    calls = []

    class Response:
        status_code = 200
        is_error = False
        content = b"ok"

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response()

    monkeypatch.setattr("app.file_storage.httpx.request", request)
    storage = SupabaseFileStorage("https://project.supabase.co", "secret", "private-bucket")
    storage.store("pending/a/file.pdf", b"x")
    assert calls[0][1].endswith("/storage/v1/object/private-bucket/pending/a/file.pdf")
    assert "/public/" not in calls[0][1]
    assert calls[0][2]["headers"]["Authorization"] == "Bearer secret"


def test_redis_requires_supabase_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("QUEUE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://example")
    monkeypatch.setenv("FILE_STORAGE_BACKEND", "local")
    with pytest.raises(RuntimeError, match="supabase"):
        validate_queue_configuration()
