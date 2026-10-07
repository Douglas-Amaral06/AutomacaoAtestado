"""Validação e ingresso de arquivos na fila, independente do provedor de identidade."""
import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from .config import positive_env_int
from .database import UPLOAD_DIR, connect
from .databricks_delivery import SAO_PAULO

ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_MULTIPART_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024


def detected_mime(path: Path) -> str | None:
    with path.open("rb") as source:
        head = source.read(16)
    if head.startswith(b"%PDF-"): return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"): return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP": return "image/webp"
    return None


def validate_document_structure(path: Path, mime_type: str) -> None:
    if path.stat().st_size == 0:
        raise HTTPException(400, "O arquivo está vazio.")
    if mime_type == "application/pdf":
        try:
            with path.open("rb") as source:
                reader = PdfReader(source, strict=True)
                if reader.is_encrypted or not reader.pages:
                    raise ValueError("PDF protegido ou sem páginas")
                for page in reader.pages:
                    page.get_contents()
        except Exception:
            raise HTTPException(400, "O PDF está protegido, incompleto ou corrompido.") from None
        return
    try:
        with Image.open(path) as image:
            image.verify()
            if image.width <= 0 or image.height <= 0 or image.width * image.height > 40_000_000:
                raise ValueError("dimensões inválidas")
        with Image.open(path) as image:
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(400, "A imagem está corrompida ou incompleta.") from error


def ingest_document(file: UploadFile, operator_id: int) -> int:
    stored_path = None
    queue_id = None
    received_at = datetime.now(SAO_PAULO).isoformat()
    try:
        if file.content_type not in ALLOWED_TYPES:
            raise HTTPException(400, "Envie um arquivo PDF, JPG ou PNG.")
        extensions = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
        stored_name = f"{uuid.uuid4().hex}{extensions[file.content_type]}"
        stored_path = UPLOAD_DIR / stored_name
        written = 0
        digest_builder = hashlib.sha256()
        with stored_path.open("xb") as output:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Arquivo acima de 15 MB.")
                digest_builder.update(chunk)
                output.write(chunk)
        gemini_input_limit = positive_env_int("GEMINI_MAX_DOCUMENT_MB", 8) * 1024 * 1024
        if written > gemini_input_limit:
            raise HTTPException(
                413,
                f"Documento acima do limite configurado para leitura ({gemini_input_limit // (1024 * 1024)} MB).",
            )
        if written == 0:
            raise HTTPException(400, "O arquivo está vazio.")
        actual_mime = detected_mime(stored_path)
        if actual_mime != file.content_type:
            raise HTTPException(400, "Conteúdo do arquivo não corresponde ao tipo informado.")
        validate_document_structure(stored_path, actual_mime)
        digest = digest_builder.hexdigest()
        with connect() as connection:
            queue_id = connection.execute("""INSERT INTO fila_processamento(
                arquivo_hash,arquivo_original,arquivo_salvo,mime_type,status,
                data_recebimento,unidade,polo,origem,operador_id
            ) VALUES(?,?,?,?,'aguardando_retentativa',?,?,?,'painel',?)""", (
                digest, Path((file.filename or "documento").replace("\\", "/")).name[:255],
                stored_name, actual_mime, received_at,
                os.getenv("DELIVERY_UNIT", "AUREA").strip().upper(),
                os.getenv("DELIVERY_POLO", "SP").strip().upper(), operator_id,
            )).lastrowid
        return queue_id
    except Exception:
        if queue_id is None and stored_path:
            stored_path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()


class UploadBodyLimit:
    """Limita bytes efetivos antes do spool multipart, mesmo com tamanho declarado falso."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or scope.get("path") != "/atestados/upload":
            return await self.app(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_MULTIPART_BYTES:
                    raise HTTPException(413, "Requisição de upload acima do limite permitido.")
            return message

        return await self.app(scope, bounded_receive, send)
