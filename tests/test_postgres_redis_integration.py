"""Integração opt-in: use apenas os serviços descartáveis do docker-compose."""

import io
import json
import logging
import os
import re
import uuid

import pytest
from PIL import Image

from app import database, processing, queueing, uploads
from app.safe_errors import format_safe_error


def test_hybrid_row_factory_accepts_command_without_result_set():
    class CommandCursor:
        description = None

    assert dict(database._hybrid_row_factory(CommandCursor())(())) == {}


def test_hybrid_row_factory_keeps_select_key_and_index_access():
    class Column:
        def __init__(self, name):
            self.name = name

    class SelectCursor:
        description = (Column("id"), Column("usuario"))

    row = database._hybrid_row_factory(SelectCursor())((7, "douglas"))
    assert row[0] == 7 and row["usuario"] == "douglas"


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL não configurada")
def test_postgres_real_schema_users_queue_logs_and_atestados(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("APP_ENV", "test")
    database.initialize_database()
    marker = uuid.uuid4().hex
    with database.connect() as connection:
        user_id = connection.execute(
            """INSERT INTO usuarios(usuario,nome,senha_hash,totp_secret_encrypted,perfil,operador_public_id)
               VALUES(?,?,?,?,?,?)""",
            ("test_" + marker, "Usuário sintético", "hash-sintetico", "", "analista", "opr_" + marker),
        ).lastrowid
        assert connection.execute(
            "SELECT id FROM usuarios WHERE LOWER(usuario)=LOWER(?)", ("TEST_" + marker.upper(),)
        ).fetchone()[0] == user_id
        queue_id = connection.execute(
            """INSERT INTO fila_processamento(arquivo_hash,arquivo_original,arquivo_salvo,mime_type,status,operador_id)
               VALUES(?,?,?,?,?,?)""", (marker, "teste.pdf", "teste.pdf", "application/pdf", "aguardando_retentativa", user_id)
        ).lastrowid
        assert connection.execute("SELECT id FROM fila_processamento WHERE id=?", (queue_id,)).fetchone()[0] == queue_id
        connection.execute("DELETE FROM fila_processamento WHERE id=?", (queue_id,))
    with pytest.raises(Exception):
        with database.connect() as connection:
            connection.execute(
                """INSERT INTO usuarios(usuario,nome,senha_hash,totp_secret_encrypted,perfil,operador_public_id)
                   VALUES(?,?,?,?,?,?)""",
                ("TEST_" + marker.upper(), "Duplicado", "hash", "", "analista", "opr_" + uuid.uuid4().hex),
            )
    with database.connect() as connection:
        connection.execute("DELETE FROM usuarios WHERE id=?", (user_id,))


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL não configurada")
def test_postgres_real_processes_valid_gemini_result_until_review(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("FILE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("GEMINI_MAX_DOCUMENT_MB", "8")
    monkeypatch.setattr(database, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(processing, "UPLOAD_DIR", tmp_path / "uploads")
    database.initialize_database()

    marker = uuid.uuid4().hex
    image = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(image, "JPEG")
    content = image.getvalue()
    extracted = {
        "is_atestado": True,
        "tipo_documento": "atestado_medico",
        "motivo_classificacao": "documento sintético de integração",
        "nome": "Pessoa Sintética",
        "cpf": "52998224725",
        "crm": "00123",
        "crm_uf": "SP",
        "cid": "N39.0",
        "dias_afastamento": 2,
        "data_atestado": "2026-10-15",
        "assinado": True,
        "carimbado": False,
        "observacoes": None,
        "confianca": "alta",
    }
    monkeypatch.setattr(processing, "extract_document", lambda _path: dict(extracted))

    user_id = queue_id = record_id = None
    try:
        with database.connect() as connection:
            user_id = connection.execute(
                """INSERT INTO usuarios(usuario,nome,senha_hash,totp_secret_encrypted,perfil,operador_public_id)
                   VALUES(?,?,?,?,?,?)""",
                ("process_" + marker, "Usuário sintético", "hash-sintetico", "", "analista", "opr_" + marker),
            ).lastrowid

        upload = type("Upload", (), {
            "content_type": "image/jpeg",
            "filename": "documento-sintetico.jpg",
            "file": io.BytesIO(content),
        })()
        queue_id = uploads.ingest_document(upload, user_id)
        result = processing.process_queue_item(queue_id)
        record_id = result["id"]

        with database.connect() as connection:
            queue = connection.execute(
                "SELECT status,atestado_id,lock_token FROM fila_processamento WHERE id=?", (queue_id,)
            ).fetchone()
            record = connection.execute(
                """SELECT status,status_entrega,assinado,carimbado,processamento_finalizado_em
                   FROM atestados WHERE id=?""",
                (record_id,),
            ).fetchone()

        assert result["status"] == "pendente"
        assert queue["status"] == "concluido"
        assert queue["atestado_id"] == record_id and queue["lock_token"] is None
        assert record["status"] == "pendente"
        assert record["status_entrega"] == "aguardando_aprovacao"
        assert (record["assinado"], record["carimbado"]) == (1, 0)
        assert record["processamento_finalizado_em"]
    finally:
        with database.connect() as connection:
            if queue_id is not None:
                connection.execute("DELETE FROM logs WHERE detalhes LIKE ?", (f'%\"fila_id\": {queue_id}%',))
                connection.execute("DELETE FROM fila_processamento WHERE id=?", (queue_id,))
            if record_id is not None:
                connection.execute("DELETE FROM atestados WHERE id=?", (record_id,))
            if user_id is not None:
                connection.execute("DELETE FROM usuarios WHERE id=?", (user_id,))


def test_postgres_error_log_has_correlation_without_sensitive_message(caplog):
    from psycopg.errors import DatatypeMismatch

    secret = "CPF 52998224725 token=segredo-postgres"
    with caplog.at_level(logging.ERROR, logger="sistema_interno"):
        try:
            raise DatatypeMismatch(secret)
        except DatatypeMismatch as error:
            safe_message, details = format_safe_error(error)

    assert details["error_type"] == "DatatypeMismatch"
    assert re.fullmatch(r"[0-9a-f]{16}", details["correlation_id"])
    assert details["correlation_id"] in safe_message
    assert details["correlation_id"] in caplog.text
    assert secret not in safe_message
    assert secret not in json.dumps(details)
    assert secret not in caplog.text


@pytest.mark.skipif(not os.getenv("TEST_REDIS_URL"), reason="TEST_REDIS_URL não configurada")
def test_redis_real_is_reachable(monkeypatch):
    monkeypatch.setenv("QUEUE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", os.environ["TEST_REDIS_URL"])
    assert queueing.redis_health() is True
