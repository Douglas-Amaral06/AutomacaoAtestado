"""Integração opt-in: use apenas os serviços descartáveis do docker-compose."""

import os
import uuid

import pytest

from app import database, queueing


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


@pytest.mark.skipif(not os.getenv("TEST_REDIS_URL"), reason="TEST_REDIS_URL não configurada")
def test_redis_real_is_reachable(monkeypatch):
    monkeypatch.setenv("QUEUE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", os.environ["TEST_REDIS_URL"])
    assert queueing.redis_health() is True
