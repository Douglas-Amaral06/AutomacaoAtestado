"""Fluxo público do piloto: sessão, arquivo, fila, revisão e contrato de entrega."""
import hashlib
import io
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import database, main, processing, uploads, security
from app.databricks_delivery import DeliveryService, synthetic_pdf_bytes
from app.gemini_service import QuotaExceededError
from app.storage_client import LocalFakeStorageClient


EXTRACTED = {"is_atestado": True, "tipo_documento": "atestado_medico",
             "nome": "Pessoa Fictícia", "cpf": "52998224725", "cid": "N39.0",
             "dias_afastamento": 2, "data_atestado": "2026-08-18", "crm": "00123",
             "crm_uf": "SP", "assinado": True, "carimbado": False, "confianca": "alta"}


def image_bytes(kind="JPEG"):
    result = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(result, kind)
    return result.getvalue()


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "atestados.db")
    monkeypatch.setattr(database, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    for module in (main, processing, uploads):
        monkeypatch.setattr(module, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setenv("APP_SECRET_KEY", "a" * 48)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("GEMINI_MAX_DOCUMENT_MB", "8")
    monkeypatch.setenv("UPLOAD_RATE_LIMIT_PER_HOUR", "30")
    monkeypatch.setenv("UPLOAD_DAILY_QUOTA_MB", "300")
    database.initialize_database()
    monkeypatch.setattr(processing, "extract_document", lambda _path: dict(EXTRACTED))
    client = TestClient(main.app, base_url="http://127.0.0.1")
    with database.connect() as connection:
        operator = connection.execute(
            """INSERT INTO usuarios(usuario,nome,senha_hash,totp_secret_encrypted,perfil,operador_public_id)
               VALUES('analista','Analista Teste','hash','','analista',?)""", ("opr_" + "a" * 32,),
        ).lastrowid
        connection.execute(
            """INSERT INTO sessoes(usuario_id,token_hash,csrf_token,user_agent_hash,expira_em)
               VALUES(?,?,?,?,?)""", (operator, security.hash_token("session"), "csrf",
               security.hash_token("ua:testclient"), (security.utc_now()+timedelta(hours=1)).isoformat()),
        )
    client.cookies.set("rh_session", "session")
    return client, operator


def send(client, content=None, mime="image/jpeg", **fields):
    return client.post("/atestados/upload", files={"file": ("documento.bin", image_bytes() if content is None else content, mime)},
                       data={"csrf_token": "csrf", **fields}, follow_redirects=False)


def record():
    with database.connect() as connection:
        return connection.execute("SELECT * FROM atestados ORDER BY id DESC LIMIT 1").fetchone()


def approve(client, item, **fields):
    data = {key: str(value).lower() if isinstance(value, bool) else value for key, value in EXTRACTED.items()}
    data.update({"csrf_token": "csrf", "acao": "aprovar", "versao_registro": item["revisado_em"] or item["criado_em"], **fields})
    return client.post(f"/atestados/{item['id']}/revisar", data=data, follow_redirects=False)


def real_delivery_to_test_storage(tmp_path, monkeypatch):
    storage = LocalFakeStorageClient(tmp_path / "volume")
    monkeypatch.setenv("DELIVERY_MODE", "databricks")
    monkeypatch.setattr(main, "configured_delivery_service", lambda: DeliveryService(storage))
    return storage


@pytest.mark.parametrize("role", ["admin", "analista"])
@pytest.mark.parametrize("mime,content", [
    ("image/jpeg", image_bytes()), ("image/png", image_bytes("PNG")),
    ("application/pdf", synthetic_pdf_bytes("FICTICIO", "2026-08-18")),
])
def test_authenticated_upload_validates_and_records_server_metadata(panel, mime, content, role):
    client, operator = panel
    with database.connect() as connection:
        connection.execute("UPDATE usuarios SET perfil=?", (role,))
    assert client.get("/atestados/novo").status_code == 200
    response = send(client, content, mime, operador_id="999", origem="outra", unidade="OUTRA", polo="RJ", data_recebimento="1900-01-01")
    assert response.status_code == 303
    with database.connect() as connection:
        queued = connection.execute("SELECT * FROM fila_processamento").fetchone()
    assert queued["operador_id"] == operator
    assert queued["origem"] == "painel"
    assert (queued["unidade"], queued["polo"]) == ("AUREA", "SP")
    assert datetime.fromisoformat(queued["data_recebimento"]).utcoffset() == timedelta(hours=-3)
    assert queued["arquivo_hash"] == hashlib.sha256(content).hexdigest()
    assert (uploads.UPLOAD_DIR / queued["arquivo_salvo"]).read_bytes() == content
    assert re.fullmatch(r"[a-f0-9]{32}\.(jpg|png|pdf)", queued["arquivo_salvo"])
    assert record()["operador_envio_id"] == operator
    assert record()["status_entrega"] == "aguardando_aprovacao"
    assert "Extração concluída" in client.get(response.headers["location"]).text


def test_upload_requires_session_and_csrf_and_permission(panel, monkeypatch):
    client, _ = panel
    assert send(client, csrf_token="wrong").status_code == 403
    monkeypatch.setitem(security.ROLE_PERMISSIONS, "analista", frozenset({"review"}))
    assert send(client).status_code == 403
    client.cookies.clear()
    assert send(client).status_code == 401
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM fila_processamento").fetchone()[0] == 0


@pytest.mark.parametrize("content,mime", [
    (b"", "image/jpeg"), (image_bytes(), "application/pdf"), (b"text", "text/plain"),
    (b"\xff\xd8\xffbad", "image/jpeg"), (b"\x89PNG\r\n\x1a\nbad", "image/png"),
    (b"%PDF-1.4\n%%EOF", "application/pdf"), (b"%PDF-unfinished", "application/pdf"),
])
def test_invalid_files_never_enter_queue(panel, content, mime):
    client, _ = panel
    response = send(client, content, mime)
    assert response.status_code == 400
    assert "Enviar atestado" in response.text
    assert not list(uploads.UPLOAD_DIR.iterdir())
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM fila_processamento").fetchone()[0] == 0


@pytest.mark.parametrize("size,reading_limit", [(16 * 1024 * 1024, "20"), (2 * 1024 * 1024, "1")])
def test_size_limits_leave_no_files(panel, monkeypatch, size, reading_limit):
    monkeypatch.setenv("GEMINI_MAX_DOCUMENT_MB", reading_limit)
    assert send(panel[0], b"x" * size).status_code == 413
    assert not list(uploads.UPLOAD_DIR.iterdir())


def test_rate_limit_is_per_authenticated_user(panel, monkeypatch):
    monkeypatch.setenv("UPLOAD_RATE_LIMIT_PER_HOUR", "1")
    assert send(panel[0]).status_code == 303
    response = send(panel[0])
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_daily_quota_is_enforced(panel, monkeypatch):
    monkeypatch.setenv("UPLOAD_DAILY_QUOTA_MB", "1")
    assert send(panel[0], b"x" * (2 * 1024 * 1024)).status_code == 413


def test_duplicate_hash_is_warning_and_each_upload_is_kept(panel):
    client, _ = panel
    first = send(client)
    second = send(client)
    assert first.status_code == second.status_code == 303
    assert "Possível documento repetido" in client.get(second.headers["location"]).text
    assert "Possível documento repetido" in client.get(f"/atestados/{record()['id']}").text
    with database.connect() as connection:
        rows = connection.execute("SELECT arquivo_hash,arquivo_salvo FROM fila_processamento").fetchall()
    assert len(rows) == 2 and rows[0]["arquivo_hash"] == rows[1]["arquivo_hash"]
    assert rows[0]["arquivo_salvo"] != rows[1]["arquivo_salvo"]


def test_non_document_is_ignored(panel, monkeypatch):
    monkeypatch.setattr(processing, "extract_document", lambda _: {"is_atestado": False})
    response = send(panel[0])
    assert "Documento não reconhecido" in panel[0].get(response.headers["location"]).text
    assert record() is None
    assert not list(uploads.UPLOAD_DIR.iterdir())


@pytest.mark.parametrize("error,expected", [(QuotaExceededError("quota", 120), "pausado_quota"), (TimeoutError(), "aguardando_retentativa")])
def test_temporary_errors_preserve_queue_and_original(panel, monkeypatch, error, expected):
    def fail(_):
        raise error
    monkeypatch.setattr(processing, "extract_document", fail)
    response = send(panel[0])
    assert response.status_code == 303
    with database.connect() as connection:
        queued = connection.execute("SELECT * FROM fila_processamento").fetchone()
    assert queued["status"] == expected
    assert queued["lock_token"] is None and queued["disponivel_em"]
    assert (uploads.UPLOAD_DIR / queued["arquivo_salvo"]).exists()
    assert record() is None


def test_approval_delivers_pair_and_only_then_confirms(panel, tmp_path, monkeypatch):
    client, operator = panel
    storage = real_delivery_to_test_storage(tmp_path, monkeypatch)
    send(client)
    assert not list(storage.root.rglob("*.json"))
    item = record()
    with database.connect() as connection:
        connection.execute("UPDATE atestados SET matricula='M123',empresa='Empresa preservada' WHERE id=?", (item["id"],))
    events = []
    binary, read, metadata = storage.write_binary, storage.read_binary, storage.write_json
    def write(path, content):
        assert record()["status"] == "pendente"
        assert record()["status_entrega"] == "entregando"
        events.append("documento")
        binary(path, content)
    def verify(path):
        events.append("sha")
        return read(path)
    def write_json(path, payload):
        events.append("json")
        assert record()["status"] != "confirmado"
        metadata(path, payload)
    monkeypatch.setattr(storage, "write_binary", write)
    monkeypatch.setattr(storage, "read_binary", verify)
    monkeypatch.setattr(storage, "write_json", write_json)
    assert approve(client, item, nome="Nome corrigido").status_code == 303
    assert events == ["documento", "sha", "json"]
    saved = record()
    assert saved["status"] == "confirmado" and saved["status_entrega"] == "entregue_volume"
    assert saved["revisado_por"] == operator
    assert saved["matricula"] == "M123" and saved["empresa"] == "Empresa preservada"
    payload = json.loads(next(storage.root.rglob("*.json")).read_text(encoding="utf-8"))
    assert payload["id_documento"] == saved["id_documento"]
    assert payload["origem"]["canal"] == "painel"
    assert payload["origem"]["operador_id"] == "opr_" + "a" * 32
    assert payload["origem"]["unidade"] == "AUREA" and payload["origem"]["polo"] == "SP"
    assert payload["origem"]["teste"] is False
    for field in ("id_mensagem", "id_conversa", "whatsapp_remetente", "whatsapp_destinatario"):
        assert payload["origem"][field] is None
    assert payload["arquivo"]["sha256"] == hashlib.sha256(image_bytes()).hexdigest()
    assert payload["documento"]["nome_paciente"] == "Nome corrigido"
    (uploads.UPLOAD_DIR / saved["arquivo_salvo"]).unlink()
    assert approve(client, saved).status_code == 409
    assert client.get(f"/atestados/{saved['id']}/arquivo").status_code == 404
    assert len(events) == 3


def test_rejection_never_calls_storage(panel, monkeypatch):
    send(panel[0])
    monkeypatch.setattr(main, "configured_delivery_service", lambda: pytest.fail("Rejeição não pode acessar storage"))
    assert approve(panel[0], record(), acao="rejeitar", motivo_rejeicao="Inválido").status_code == 303
    assert record()["status"] == record()["status_entrega"] == "rejeitado"


@pytest.mark.parametrize("failure_stage", ["document", "hash", "json", "disabled"])
def test_delivery_failure_keeps_corrections_and_allows_retry(panel, tmp_path, monkeypatch, failure_stage):
    client, _ = panel
    storage = real_delivery_to_test_storage(tmp_path, monkeypatch)
    send(client)
    def fail(*_):
        raise RuntimeError("password=segredo-nao-exibir host=interno")
    with monkeypatch.context() as patch:
        if failure_stage == "disabled":
            patch.setattr(main, "configured_delivery_service", lambda: None)
        elif failure_stage == "hash":
            patch.setattr(storage, "read_binary", lambda _: b"corrompido")
        else:
            patch.setattr(storage, "write_binary" if failure_stage == "document" else "write_json", fail)
        response = approve(client, record(), nome="Correção preservada")
    assert response.status_code == 503
    assert "Suas correções foram salvas" in response.text
    assert "segredo-nao-exibir" not in response.text
    assert record()["nome"] == "Correção preservada"
    assert record()["status"] == "pendente" and record()["status_entrega"] == "falha_entrega"
    assert not list(storage.root.rglob("*.json"))
    assert approve(client, record(), nome="Correção preservada").status_code == 303
    assert record()["status"] == "confirmado"


def test_review_reservation_blocks_concurrent_second_request(panel, tmp_path, monkeypatch):
    client, _ = panel
    storage = real_delivery_to_test_storage(tmp_path, monkeypatch)
    send(client)
    entered, release = threading.Event(), threading.Event()
    binary = storage.write_binary
    def wait_write(path, content):
        entered.set()
        assert release.wait(10)
        binary(path, content)
    monkeypatch.setattr(storage, "write_binary", wait_write)
    item = record()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(approve, client, item)
        try:
            assert entered.wait(10)
            # Reabrir a tela revela a nova versão, mas não deve roubar a reserva.
            second = approve(client, record())
            assert second.status_code == 409
        finally:
            release.set()
        assert first.result().status_code == 303


def test_health_and_removed_routes(panel):
    client, _ = panel
    client.cookies.clear()
    assert client.get("/healthz").json() == {"status": "ok"}
    for method, path in [("get", "/extensao"), ("post", "/api/parear"), ("post", "/api/atestados"),
                         ("post", "/api/logs"), ("get", "/api/extensao/status"),
                         ("post", "/extensao/gerar-codigo"), ("post", "/extensao/tokens/1/revogar")]:
        assert getattr(client, method)(path).status_code == 404
    paths = [getattr(route, "path", "") for route in main.app.routes]
    assert paths.count("/fila/{queue_id}/excluir") == 1
    assert not any("extensao" in path or "parear" in path for path in paths)


def test_contract_collision_does_not_overwrite_previous_delivery(panel, tmp_path, monkeypatch):
    client, _ = panel
    storage = real_delivery_to_test_storage(tmp_path, monkeypatch)
    send(client)
    first = record()
    send(client)
    second = record()
    with database.connect() as connection:
        connection.execute("UPDATE fila_processamento SET data_recebimento='2026-10-01T12:00:00-03:00'")
    assert approve(client, first).status_code == 303
    before = next(storage.root.rglob("*.json")).read_bytes()
    response = approve(client, second, nome="Outra correção")
    assert response.status_code == 503
    assert "Envie novamente o documento" in response.text
    assert next(storage.root.rglob("*.json")).read_bytes() == before
    assert record()["status"] == "pendente"


def test_actual_body_limit_rejects_forged_content_length(panel, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_MULTIPART_BYTES", 1024)
    response = panel[0].post("/atestados/upload", headers={"content-length": "100"},
                           files={"file": ("x.jpg", b"x" * 2000, "image/jpeg")},
                           data={"csrf_token": "csrf"})
    assert response.status_code == 413
    assert not list(uploads.UPLOAD_DIR.iterdir())


def test_missing_content_length_is_rejected_before_parser(panel):
    import asyncio
    from starlette.requests import Request
    request = Request({"type": "http", "method": "POST", "path": "/atestados/upload",
                       "headers": [(b"cookie", b"rh_session=session"), (b"user-agent", b"testclient")],
                       "client": ("127.0.0.1", 1000), "server": ("127.0.0.1", 8000),
                       "scheme": "http", "query_string": b""})
    async def forbidden(_):
        pytest.fail("Parser chamado antes de conferir Content-Length")
    assert asyncio.run(main.upload_limits(request, forbidden)).status_code == 411
