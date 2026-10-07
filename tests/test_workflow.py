import hashlib
import io
import json
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest
from PIL import Image
from starlette.requests import Request

from app import database, main, processing
from app.rate_limit import reset_rate_limits
from app.security import hash_password, hash_token, utc_now


def jpeg_bytes(color=(240, 240, 240)):
    output = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(output, format="JPEG")
    return output.getvalue()


def prepare_database(tmp_path, monkeypatch):
    data = tmp_path / "data"
    uploads = data / "uploads"
    monkeypatch.setattr(database, "DATA_DIR", data)
    monkeypatch.setattr(database, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(database, "DB_PATH", data / "atestados.db")
    monkeypatch.setattr(main, "UPLOAD_DIR", uploads)
    database.initialize_database()
    with database.connect() as connection:
        user_id = connection.execute(
            "INSERT INTO usuarios(usuario,nome,senha_hash,totp_secret_encrypted,perfil,operador_public_id) VALUES(?,?,?,?,?,?)",
            ("admin", "Administrador", "hash-teste", "totp-teste", "admin", database.new_operator_public_id()),
        ).lastrowid
    return user_id, uploads


def test_operator_public_id_is_stable_unique_and_survives_deactivation(tmp_path, monkeypatch):
    user_id, _uploads = prepare_database(tmp_path, monkeypatch)
    with database.connect() as connection:
        original = connection.execute(
            "SELECT operador_public_id FROM usuarios WHERE id=?", (user_id,)
        ).fetchone()[0]
        connection.execute("UPDATE usuarios SET ativo=0 WHERE id=?", (user_id,))
    database.initialize_database()
    with database.connect() as connection:
        after = connection.execute(
            "SELECT operador_public_id FROM usuarios WHERE id=?", (user_id,)
        ).fetchone()[0]
    assert after == original
    assert re.fullmatch(r"opr_[0-9a-f]{32}", original)
    assert database.new_operator_public_id() != original


def test_analyst_cannot_call_sensitive_admin_routes(tmp_path, monkeypatch):
    _admin_id, _uploads = prepare_database(tmp_path, monkeypatch)
    raw_session = "sessao-analista-rbac"
    csrf = "csrf-analista-rbac"
    with database.connect() as connection:
        analyst_id = connection.execute(
            "INSERT INTO usuarios(usuario,nome,senha_hash,totp_secret_encrypted,perfil) VALUES(?,?,?,?,?)",
            ("analista", "Pessoa Analista", "hash-teste", "totp-teste", "analista"),
        ).lastrowid
        record_id = connection.execute(
            "INSERT INTO atestados(arquivo_original,arquivo_salvo,status) VALUES(?,?,?)",
            ("atestado.pdf", "atestado.pdf", "pendente"),
        ).lastrowid
        connection.execute(
            "INSERT INTO sessoes(usuario_id,token_hash,csrf_token,user_agent_hash,expira_em) VALUES(?,?,?,?,?)",
            (
                analyst_id, hash_token(raw_session), csrf, hash_token("ua:testclient"),
                (utc_now() + timedelta(hours=1)).isoformat(),
            ),
        )

    client = TestClient(main.app, base_url="http://127.0.0.1")
    client.cookies.set("rh_session", raw_session)

    review = client.get(f"/atestados/{record_id}")
    assert review.status_code == 200
    assert "Aprovar e salvar" in review.text
    assert "Excluir atestado" not in review.text
    assert 'href="/relatorios"' not in review.text

    assert client.get("/relatorios").status_code == 403
    assert client.get("/exportar.xlsx").status_code == 403
    assert client.post(
        f"/atestados/{record_id}/excluir", data={"csrf_token": csrf}
    ).status_code == 403
    assert client.post(
        "/fila/999/reprocessar", data={"csrf_token": csrf}
    ).status_code == 403


def test_dashboard_renders_server_side_ui_with_records(tmp_path, monkeypatch):
    user_id, _ = prepare_database(tmp_path, monkeypatch)
    raw_session = "sessao-dashboard"
    csrf = "csrf-dashboard"
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO atestados(
                arquivo_original,arquivo_salvo,status,nome,tipo_documento,
                data_atestado,dias_afastamento,confianca
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                "atestado.pdf", "atestado.pdf", "confirmado", "Pessoa Teste",
                "atestado_medico", "2026-08-21", 2, 0.98,
            ),
        )
        connection.execute(
            "INSERT INTO sessoes(usuario_id,token_hash,csrf_token,user_agent_hash,expira_em) VALUES(?,?,?,?,?)",
            (
                user_id, hash_token(raw_session), csrf, hash_token("ua:testclient"),
                (utc_now() + timedelta(hours=1)).isoformat(),
            ),
        )

    client = TestClient(main.app, base_url="http://127.0.0.1")
    client.cookies.set("rh_session", raw_session)
    response = client.get("/")

    assert response.status_code == 200
    assert "Pessoa Teste" in response.text
    assert "21/08/2026" in response.text
    assert "Confirmado" in response.text
    assert "UI." not in response.text


def test_dashboard_paginates_large_result_sets(tmp_path, monkeypatch):
    user_id, _uploads = prepare_database(tmp_path, monkeypatch)
    raw_session, csrf = "sessao-paginacao", "csrf-paginacao"
    with database.connect() as connection:
        connection.executemany(
            "INSERT INTO atestados(arquivo_original,arquivo_salvo,status,nome) VALUES(?,?,?,?)",
            [(f"{index}.pdf", f"{index}.pdf", "pendente", f"Pessoa {index:03d}") for index in range(1, 61)],
        )
        connection.execute(
            "INSERT INTO sessoes(usuario_id,token_hash,csrf_token,user_agent_hash,expira_em) VALUES(?,?,?,?,?)",
            (user_id, hash_token(raw_session), csrf, hash_token("ua:testclient"), (utc_now() + timedelta(hours=1)).isoformat()),
        )
    client = TestClient(main.app, base_url="http://127.0.0.1")
    client.cookies.set("rh_session", raw_session)

    first = client.get("/?page=1&per_page=50")
    second = client.get("/?page=2&per_page=50")
    assert "Pessoa 060" in first.text
    assert "Pessoa 001" not in first.text
    assert "Pessoa 001" in second.text
    assert "Página 1 de 2" in first.text


def test_dashboard_searches_by_databricks_document_id(tmp_path, monkeypatch):
    user_id, _uploads = prepare_database(tmp_path, monkeypatch)
    raw_session = "sessao-busca-databricks"
    document_id = "UNI001_20260828T091116_304b38fa"
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO atestados(
                   arquivo_original,arquivo_salvo,status,nome,id_documento,status_entrega,operador_envio_id
               ) VALUES(?,?,?,?,?,?,?)""",
            ("teste.pdf", "teste.pdf", "pendente", "Pessoa Encontrada", document_id, "entregue_volume", user_id),
        )
        connection.execute(
            "INSERT INTO atestados(arquivo_original,arquivo_salvo,status,nome) VALUES(?,?,?,?)",
            ("outro.pdf", "outro.pdf", "pendente", "Pessoa Oculta"),
        )
        connection.execute(
            "INSERT INTO sessoes(usuario_id,token_hash,csrf_token,user_agent_hash,expira_em) VALUES(?,?,?,?,?)",
            (user_id, hash_token(raw_session), "csrf", hash_token("ua:testclient"), (utc_now()+timedelta(hours=1)).isoformat()),
        )
    client = TestClient(main.app, base_url="http://127.0.0.1")
    client.cookies.set("rh_session", raw_session)

    response = client.get("/?q=20260828T091116")

    assert response.status_code == 200
    assert "Pessoa Encontrada" in response.text
    assert "Pessoa Oculta" not in response.text
    assert document_id in response.text
    assert "No Volume" in response.text
    assert "Administrador" in response.text


def test_processing_failure_stores_only_correlation_data(tmp_path, monkeypatch):
    _user_id, uploads = prepare_database(tmp_path, monkeypatch)
    monkeypatch.setattr(processing, "UPLOAD_DIR", uploads)
    saved = uploads / "falha.pdf"
    saved.write_bytes(b"%PDF-ficticio")
    secret = "dapi12345678901234567890"
    monkeypatch.setattr(
        processing,
        "extract_document",
        lambda _path: (_ for _ in ()).throw(
            RuntimeError(f"jdbc:databricks://usuario:senha@host?token={secret} CPF 12345678909")
        ),
    )
    with database.connect() as connection:
        queue_id = connection.execute(
            """INSERT INTO fila_processamento(arquivo_hash,arquivo_original,arquivo_salvo,mime_type,status)
               VALUES(?,?,?,?,?)""",
            ("e" * 64, "falha.pdf", saved.name, "application/pdf", "aguardando_retentativa"),
        ).lastrowid

    with pytest.raises(RuntimeError):
        processing.process_queue_item(queue_id)

    with database.connect() as connection:
        queue = connection.execute(
            "SELECT ultimo_erro,erro_amigavel FROM fila_processamento WHERE id=?", (queue_id,)
        ).fetchone()
        log = connection.execute(
            "SELECT mensagem,detalhes FROM logs WHERE evento='processamento_falhou' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    persisted = " ".join((queue["ultimo_erro"], queue["erro_amigavel"], log["mensagem"], log["detalhes"]))
    assert secret not in persisted
    assert "usuario:senha" not in persisted
    assert "12345678909" not in persisted
    assert "Referência:" in persisted
    assert '"error_type": "RuntimeError"' in log["detalhes"]


def test_fastapi_unhandled_error_response_contains_only_correlation_id(tmp_path, monkeypatch):
    prepare_database(tmp_path, monkeypatch)
    secret = "dapi12345678901234567890"
    response = asyncio.run(
        main.unexpected_exception_handler(
            None,
            RuntimeError(f"https://usuario:senha@host?token={secret} CPF 12345678909"),
        )
    )
    body = response.body.decode()

    assert response.status_code == 500
    assert '"codigo":"internal_error"' in body
    assert "Referência" in body
    assert secret not in body
    assert "usuario:senha" not in body
    assert "12345678909" not in body


def test_queue_item_can_only_be_claimed_by_one_server_instance(tmp_path, monkeypatch):
    _user_id, uploads = prepare_database(tmp_path, monkeypatch)
    monkeypatch.setattr(processing, "UPLOAD_DIR", uploads)
    with database.connect() as connection:
        queue_id = connection.execute(
            """INSERT INTO fila_processamento(arquivo_hash,arquivo_original,arquivo_salvo,mime_type,status)
               VALUES(?,?,?,?,?)""",
            ("b" * 64, "falha.pdf", "falha.pdf", "application/pdf", "aguardando_retentativa"),
        ).lastrowid
    item, token = processing._claim_queue_item(queue_id)
    assert item["lock_token"] == token
    try:
        processing._claim_queue_item(queue_id)
        assert False, "a segunda instância não deveria assumir o item"
    except processing.QueueItemBusyError:
        pass


def test_worker_recovers_abandoned_processing_item(tmp_path, monkeypatch):
    prepare_database(tmp_path, monkeypatch)
    with database.connect() as connection:
        queue_id = connection.execute(
            """INSERT INTO fila_processamento(
                   arquivo_hash,arquivo_original,arquivo_salvo,mime_type,status,lock_token,lock_expires_em
               ) VALUES(?,?,?,?,?,?,?)""",
            ("f" * 64, "abandonado.pdf", "abandonado.pdf", "application/pdf", "processando", None, None),
        ).lastrowid
    recovered = []
    monkeypatch.setattr(processing, "process_queue_item", lambda item_id: recovered.append(item_id))

    assert processing.resume_pending_once() == 1
    assert recovered == [queue_id]


def test_lost_queue_lease_cannot_be_renewed(tmp_path, monkeypatch):
    prepare_database(tmp_path, monkeypatch)
    with database.connect() as connection:
        queue_id = connection.execute(
            """INSERT INTO fila_processamento(
                   arquivo_hash,arquivo_original,arquivo_salvo,mime_type,status,lock_token
               ) VALUES(?,?,?,?,?,?)""",
            ("1" * 64, "lease.pdf", "lease.pdf", "application/pdf", "processando", "owner-real"),
        ).lastrowid

    with pytest.raises(processing.QueueItemBusyError):
        processing.renew_queue_lease(queue_id, "owner-incorreto")


def test_failed_extraction_can_be_reprocessed_from_dashboard(tmp_path, monkeypatch):
    user_id, _uploads = prepare_database(tmp_path, monkeypatch)
    raw_session, csrf = "sessao-reprocessar", "csrf-reprocessar"
    with database.connect() as connection:
        queue_id = connection.execute(
            """INSERT INTO fila_processamento(
                arquivo_hash,arquivo_original,arquivo_salvo,mime_type,status,tentativas,ultimo_erro
            ) VALUES(?,?,?,?,?,?,?)""",
            ("c" * 64, "falha.pdf", "falha.pdf", "application/pdf", "falhou", 3, "timeout"),
        ).lastrowid
        connection.execute(
            "INSERT INTO sessoes(usuario_id,token_hash,csrf_token,user_agent_hash,expira_em) VALUES(?,?,?,?,?)",
            (user_id, hash_token(raw_session), csrf, hash_token("ua:testclient"), (utc_now() + timedelta(hours=1)).isoformat()),
        )
    processed = []
    monkeypatch.setattr(main, "process_queue_item", lambda item_id: processed.append(item_id) or {"status": "pendente"})
    client = TestClient(main.app, base_url="http://127.0.0.1")
    client.cookies.set("rh_session", raw_session)
    response = client.post(f"/fila/{queue_id}/reprocessar", data={"csrf_token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert processed == [queue_id]
    with database.connect() as connection:
        item = connection.execute("SELECT status,tentativas,ultimo_erro FROM fila_processamento WHERE id=?", (queue_id,)).fetchone()
    assert dict(item) == {"status": "aguardando_retentativa", "tentativas": 0, "ultimo_erro": None}


def test_admin_login_requires_only_valid_user_and_password(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "chave-de-teste-com-mais-de-trinta-e-dois-caracteres")
    user_id, _ = prepare_database(tmp_path, monkeypatch)
    with database.connect() as connection:
        connection.execute(
            "UPDATE usuarios SET senha_hash=? WHERE id=?",
            (hash_password("Senha-Admin-Forte-123!"), user_id),
        )
    client = TestClient(main.app, base_url="http://127.0.0.1")
    accepted = client.post(
        "/login", data={"usuario": "admin", "senha": "Senha-Admin-Forte-123!"},
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/"
    assert "httponly" in accepted.headers["set-cookie"].lower()
    rejected = TestClient(main.app, base_url="http://127.0.0.1").post(
        "/login", data={"usuario": "admin", "senha": "senha-incorreta"},
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    assert "Credenciais+invalidas" in rejected.headers["location"]


def test_delete_removes_record_file_and_duplicate_marker(tmp_path, monkeypatch):
    user_id, uploads = prepare_database(tmp_path, monkeypatch)
    saved = uploads / "teste.jpg"
    saved.write_bytes(b"\xff\xd8\xff")
    raw_session, csrf, digest = "sessao-exclusao", "csrf-exclusao", "hash-arquivo"
    with database.connect() as connection:
        record_id = connection.execute(
            "INSERT INTO atestados(arquivo_original,arquivo_salvo,arquivo_hash,status) VALUES(?,?,?,?)",
            ("teste.jpg", saved.name, digest, "confirmado"),
        ).lastrowid
        connection.execute(
            "INSERT INTO fila_processamento(arquivo_hash,arquivo_original,arquivo_salvo,mime_type,status,atestado_id) VALUES(?,?,?,?,?,?)",
            (digest, "teste.jpg", saved.name, "image/jpeg", "concluido", record_id),
        )
        connection.execute(
            "INSERT INTO sessoes(usuario_id,token_hash,csrf_token,user_agent_hash,expira_em) VALUES(?,?,?,?,?)",
            (user_id, hash_token(raw_session), csrf, hash_token("ua:testclient"), (utc_now() + timedelta(hours=1)).isoformat()),
        )
    client = TestClient(main.app, base_url="http://127.0.0.1")
    client.cookies.set("rh_session", raw_session)
    response = client.post(
        f"/atestados/{record_id}/excluir", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert not saved.exists()
    with database.connect() as connection:
        assert connection.execute("SELECT 1 FROM atestados WHERE id=?", (record_id,)).fetchone() is None
        assert connection.execute("SELECT 1 FROM fila_processamento WHERE arquivo_hash=?", (digest,)).fetchone() is None


def test_export_is_streamed_without_creating_sensitive_xlsx(tmp_path, monkeypatch):
    user_id, _ = prepare_database(tmp_path, monkeypatch)
    raw_session, csrf = "sessao-exportacao", "csrf-exportacao"
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO atestados(arquivo_original,arquivo_salvo,status,nome,observacoes,dias_afastamento) VALUES(?,?,?,?,?,?)",
            ("teste.pdf", "teste.pdf", "confirmado", "=HYPERLINK(\"https://example.test\")", "  +cmd", 2),
        )
        connection.execute(
            "INSERT INTO sessoes(usuario_id,token_hash,csrf_token,user_agent_hash,expira_em) VALUES(?,?,?,?,?)",
            (user_id, hash_token(raw_session), csrf, hash_token("ua:testclient"), (utc_now() + timedelta(hours=1)).isoformat()),
        )
    client = TestClient(main.app, base_url="http://127.0.0.1")
    client.cookies.set("rh_session", raw_session)
    response = client.get("/exportar.xlsx")
    assert response.status_code == 200
    assert response.content.startswith(b"PK")
    assert not (database.DATA_DIR / "atestados_exportados.xlsx").exists()
    workbook = load_workbook(io.BytesIO(response.content), data_only=False)
    sheet = workbook["Atestados"]
    assert sheet["B2"].value == "'=HYPERLINK(\"https://example.test\")"
    assert sheet["Q2"].value == "'  +cmd"
    assert sheet["M2"].value == 2
    assert sheet["B2"].data_type == "s"
    workbook.close()
