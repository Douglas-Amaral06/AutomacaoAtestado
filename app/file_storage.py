"""Armazenamento temporário de originais, independente do filesystem do processo."""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import httpx

from .config import DATA_DIR


class FileStorageError(RuntimeError):
    """Falha segura ao conversar com o armazenamento temporário."""


class LocalFileStorage:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or DATA_DIR / "uploads")

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise FileStorageError("Chave de armazenamento inválida.")
        return path

    def store(self, key: str, content: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(content)

    def read(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            raise

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class SupabaseFileStorage:
    """Cliente server-side para bucket privado, sem URLs públicas ou assinadas."""

    def __init__(self, url: str, secret_key: str, bucket: str, timeout: int = 30):
        self.url = url.rstrip("/")
        self.secret_key = secret_key
        self.bucket = bucket
        self.timeout = timeout

    def _url(self, key: str) -> str:
        return f"{self.url}/storage/v1/object/{quote(self.bucket, safe='')}/{quote(key, safe='/')}"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.secret_key}", "apikey": self.secret_key}

    def _request(self, method: str, key: str, **kwargs) -> httpx.Response:
        headers = {**self._headers, **kwargs.pop("headers", {})}
        try:
            response = httpx.request(method, self._url(key), headers=headers, timeout=self.timeout, **kwargs)
        except httpx.HTTPError as error:
            raise FileStorageError("Armazenamento temporário indisponível.") from error
        if response.status_code == 404:
            raise FileNotFoundError(key)
        if response.is_error:
            raise FileStorageError("Falha no armazenamento temporário.")
        return response

    def store(self, key: str, content: bytes) -> None:
        self._request("POST", key, content=content, headers={**self._headers, "x-upsert": "false"})

    def read(self, key: str) -> bytes:
        return self._request("GET", key).content

    def exists(self, key: str) -> bool:
        try:
            self._request("HEAD", key)
            return True
        except FileNotFoundError:
            return False

    def delete(self, key: str) -> None:
        # API de remoção aceita uma lista de nomes; nenhum dado sensível é enviado.
        endpoint = f"{self.url}/storage/v1/object/{quote(self.bucket, safe='')}"
        try:
            response = httpx.request("DELETE", endpoint, headers=self._headers, json={"prefixes": [key]}, timeout=self.timeout)
        except httpx.HTTPError as error:
            raise FileStorageError("Falha ao limpar armazenamento temporário.") from error
        if response.is_error:
            raise FileStorageError("Falha ao limpar armazenamento temporário.")


def file_storage(local_root: Path | None = None):
    backend = os.getenv("FILE_STORAGE_BACKEND", "local").strip().lower()
    if backend == "local":
        return LocalFileStorage(local_root)
    if backend != "supabase":
        raise RuntimeError("FILE_STORAGE_BACKEND deve ser 'local' ou 'supabase'.")
    url = os.getenv("SUPABASE_URL", "").strip()
    secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "atestados-temp").strip()
    if not url or not secret or not bucket:
        raise RuntimeError("SUPABASE_URL, SUPABASE_SECRET_KEY e SUPABASE_STORAGE_BUCKET são obrigatórias.")
    return SupabaseFileStorage(url, secret, bucket)


def storage_key(filename: str) -> str:
    """Chave opaca sem atributos pessoais, com o formato legado como nome interno."""
    import uuid
    if os.getenv("FILE_STORAGE_BACKEND", "local").strip().lower() == "local":
        return Path(filename).name
    return f"pending/{uuid.uuid4().hex}/{Path(filename).name}"


@contextmanager
def local_copy(storage, key: str, suffix: str = ""):
    """Materializa uma cópia de trabalho efêmera para bibliotecas que exigem Path."""
    handle = tempfile.NamedTemporaryFile(prefix="atestado-", suffix=suffix, delete=False)
    path = Path(handle.name)
    try:
        handle.write(storage.read(key))
        handle.close()
        yield path
    finally:
        handle.close()
        path.unlink(missing_ok=True)
