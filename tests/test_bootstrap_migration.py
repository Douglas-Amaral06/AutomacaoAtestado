import asyncio
import json
import sqlite3
from datetime import timedelta

import pytest

from app import database, bootstrap, main
from app.security import verify_password


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "b" * 48)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    monkeypatch.setattr(database, "UPLOAD_DIR", tmp_path / "uploads")
    return tmp_path


def config(monkeypatch, **values):
    user = {"usuario": "analista", "nome": "Analista", "perfil": "analista", "senha": "senha-forte-para-teste", **values}
    monkeypatch.setenv("BOOTSTRAP_USERS_JSON", json.dumps([user]))
    return user


def test_bootstrap_hashes_once_and_recovers_same_identity_after_redeploy(isolated, monkeypatch):
    user = config(monkeypatch)
    database.initialize_database()
    assert bootstrap.bootstrap_users() == 1
    with database.connect() as connection:
        before = dict(connection.execute("SELECT * FROM usuarios").fetchone())
    assert verify_password(before["senha_hash"], user["senha"])
    assert user["senha"].encode() not in database.DB_PATH.read_bytes()
    config(monkeypatch, senha="outra-senha-de-teste", perfil="admin")
    assert bootstrap.bootstrap_users() == 0
    with database.connect() as connection:
        assert dict(connection.execute("SELECT * FROM usuarios").fetchone()) == before
    monkeypatch.setattr(database, "DB_PATH", isolated / "redeploy.db")
    database.initialize_database()
    assert bootstrap.bootstrap_users() == 1
    with database.connect() as connection:
        after = connection.execute("SELECT * FROM usuarios").fetchone()
    assert after["operador_public_id"] == before["operador_public_id"]


def test_explicit_operator_id_is_supported(isolated, monkeypatch):
    config(monkeypatch, operador_public_id="opr_" + "c" * 32)
    database.initialize_database()
    bootstrap.bootstrap_users()
    with database.connect() as connection:
        assert connection.execute("SELECT operador_public_id FROM usuarios").fetchone()[0] == "opr_" + "c" * 32


@pytest.mark.parametrize("raw", ['{"senha":"SEGREDO-NAO-LOGAR",', '{}', '[{"usuario":"admin","senha":"SEGREDO-NAO-LOGAR"}]'])
def test_invalid_bootstrap_never_exposes_secret(isolated, monkeypatch, raw):
    database.initialize_database()
    monkeypatch.setenv("BOOTSTRAP_USERS_JSON", raw)
    with pytest.raises(RuntimeError) as error:
        bootstrap.bootstrap_users()
    assert "SEGREDO-NAO-LOGAR" not in str(error.value)
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0


def test_legacy_queue_migration_keeps_ids_owners_locks_and_records(isolated):
    database.initialize_database()
    with database.connect() as connection:
        connection.execute("INSERT INTO usuarios(id,usuario,nome,senha_hash,totp_secret_encrypted,perfil) VALUES(7,'antigo','Nome','hash','','analista')")
        connection.execute("INSERT INTO atestados(id,arquivo_original,arquivo_salvo,matricula) VALUES(4,'doc.pdf','uuid.pdf','123')")
        connection.execute("DROP TABLE fila_processamento")
        connection.execute("""CREATE TABLE fila_processamento (
            id INTEGER PRIMARY KEY, arquivo_hash TEXT NOT NULL UNIQUE, arquivo_original TEXT NOT NULL,
            arquivo_salvo TEXT NOT NULL, mime_type TEXT NOT NULL, status TEXT NOT NULL,
            tentativas INTEGER, atestado_id INTEGER, criado_em TEXT, atualizado_em TEXT,
            id_mensagem TEXT, id_conversa TEXT, whatsapp_remetente TEXT, token_servico_id INTEGER,
            operador_id INTEGER, data_recebimento TEXT, unidade TEXT,
            lock_token TEXT, lock_expires_em TEXT, erro_amigavel TEXT)""")
        connection.execute("CREATE TABLE tokens_servico(id INTEGER PRIMARY KEY,criado_por INTEGER)")
        connection.execute("INSERT INTO tokens_servico VALUES(9,7)")
        connection.execute("CREATE TABLE codigos_pareamento(id INTEGER PRIMARY KEY)")
        connection.execute("""INSERT INTO fila_processamento VALUES(
            8,'sha','doc.pdf','uuid.pdf','application/pdf','processando',2,4,
            '2026-10-01','2026-10-02','msg','chat','sender',9,NULL,
            '2026-10-01T12:00:00-03:00','AUREA','lease','2026-10-02T12:00:00Z','mensagem útil')""")
    database.initialize_database()
    database.initialize_database()
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM fila_processamento").fetchone()
        assert row["id"] == 8 and row["atestado_id"] == 4 and row["operador_id"] == 7
        assert row["tentativas"] == 2 and row["lock_token"] == "lease"
        assert row["lock_expires_em"] == "2026-10-02T12:00:00Z"
        assert row["erro_amigavel"] == "mensagem útil"
        assert row["origem"] == "painel" and row["data_recebimento"].endswith("-03:00")
        assert not {"id_mensagem", "id_conversa", "whatsapp_remetente", "token_servico_id"} & set(row.keys())
        assert connection.execute("SELECT matricula FROM atestados WHERE id=4").fetchone()[0] == "123"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.execute("INSERT INTO fila_processamento(arquivo_hash,arquivo_original,arquivo_salvo,mime_type) VALUES('sha','doc.pdf','outro.pdf','application/pdf')")
        assert connection.execute("SELECT COUNT(*) FROM fila_processamento").fetchone()[0] == 2
        assert not connection.execute("SELECT name FROM sqlite_master WHERE name IN ('tokens_servico','codigos_pareamento')").fetchall()


def test_backup_worker_is_not_started_when_disabled(isolated, monkeypatch):
    started = []
    class Thread:
        def __init__(self, *, target, daemon, name):
            self.name = name
        def start(self):
            started.append(self.name)
    monkeypatch.setattr(main.threading, "Thread", Thread)
    monkeypatch.setenv("LOCAL_BACKUP_ENABLED", "false")
    async def lifecycle():
        async with main.lifespan(main.app):
            pass
    asyncio.run(lifecycle())
    assert started == ["fila-atestados"]
