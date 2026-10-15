from datetime import timedelta

import pytest

from app import bronze, database, main, observability, queueing, worker
from app.security import utc_now


def isolated_database(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "infra.db")
    database.initialize_database()


def test_production_requires_postgres(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    try:
        database.validate_database_configuration()
        assert False
    except RuntimeError as error:
        assert "DATABASE_URL" in str(error)


def test_production_rejects_redis_while_upload_storage_is_local(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("QUEUE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://internal:6379/0")
    monkeypatch.setenv("FILE_STORAGE_BACKEND", "local")
    with pytest.raises(
        RuntimeError,
        match="FILE_STORAGE_BACKEND=supabase é obrigatório com Redis em pilot/production\\.",
    ):
        queueing.validate_queue_configuration()


def test_redis_dispatch_failure_does_not_remove_durable_queue(tmp_path, monkeypatch):
    isolated_database(tmp_path, monkeypatch)
    with database.connect() as connection:
        queue_id = connection.execute(
            """INSERT INTO fila_processamento(arquivo_hash,arquivo_original,arquivo_salvo,mime_type,status)
               VALUES('hash','sintetico.pdf','sintetico.pdf','application/pdf','aguardando_retentativa')"""
        ).lastrowid
    monkeypatch.setenv("QUEUE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    try:
        queueing.enqueue_queue_item(queue_id)
    except Exception:
        pass
    with database.connect() as connection:
        assert connection.execute("SELECT status FROM fila_processamento WHERE id=?", (queue_id,)).fetchone()[0] == "aguardando_retentativa"


def test_bronze_failure_never_changes_volume_delivery(tmp_path, monkeypatch):
    isolated_database(tmp_path, monkeypatch)
    monkeypatch.setenv("BRONZE_CHECK_ENABLED", "true")
    monkeypatch.setenv("QUEUE_BACKEND", "local")
    with database.connect() as connection:
        atestado_id = connection.execute(
            """INSERT INTO atestados(arquivo_original,arquivo_salvo,status,status_entrega,id_documento)
               VALUES('a.pdf','a.pdf','confirmado','entregue_volume','DOC_12345678')"""
        ).lastrowid
    check_id = bronze.schedule_bronze_check(atestado_id, "DOC_12345678")
    monkeypatch.setattr(bronze, "_statement_found", lambda _value: (_ for _ in ()).throw(RuntimeError()))
    bronze.process_bronze_check(check_id)
    with database.connect() as connection:
        row = connection.execute("SELECT status_entrega,status_bronze FROM atestados WHERE id=?", (atestado_id,)).fetchone()
    assert row["status_entrega"] == "entregue_volume"
    assert row["status_bronze"] == "erro_consulta"


def test_bronze_scheduling_failure_does_not_invalidate_delivery(tmp_path, monkeypatch):
    isolated_database(tmp_path, monkeypatch)
    with database.connect() as connection:
        atestado_id = connection.execute(
            """INSERT INTO atestados(arquivo_original,arquivo_salvo,status,status_entrega,id_documento)
               VALUES('a.pdf','a.pdf','confirmado','entregue_volume','DOC_12345678')"""
        ).lastrowid
    monkeypatch.setattr(main, "schedule_bronze_check", lambda *_args: (_ for _ in ()).throw(RuntimeError()))
    main.schedule_bronze_observability(atestado_id, "DOC_12345678")
    with database.connect() as connection:
        row = connection.execute("SELECT status,status_entrega,status_bronze FROM atestados WHERE id=?", (atestado_id,)).fetchone()
    assert row["status"] == "confirmado"
    assert row["status_entrega"] == "entregue_volume"
    assert row["status_bronze"] == "erro_consulta"


def test_bronze_uses_all_backoff_delays_before_last_check(tmp_path, monkeypatch):
    isolated_database(tmp_path, monkeypatch)
    monkeypatch.setenv("BRONZE_CHECK_ENABLED", "true")
    monkeypatch.setenv("QUEUE_BACKEND", "local")
    with database.connect() as connection:
        atestado_id = connection.execute(
            """INSERT INTO atestados(arquivo_original,arquivo_salvo,status,status_entrega,id_documento)
               VALUES('a.pdf','a.pdf','confirmado','entregue_volume','DOC_12345678')"""
        ).lastrowid
    check_id = bronze.schedule_bronze_check(atestado_id, "DOC_12345678")
    delays = []
    monkeypatch.setattr(bronze, "_statement_found", lambda _value: False)
    monkeypatch.setattr(queueing, "enqueue_bronze_check", lambda _id, delay=0: delays.append(delay) or True)
    for _ in range(5):
        result = bronze.process_bronze_check(check_id)
    assert delays == [30, 120, 300, 900]
    assert result["status"] == "nao_encontrado"


def test_reconciler_recovers_due_job_and_periodically_retries(tmp_path, monkeypatch):
    isolated_database(tmp_path, monkeypatch)
    monkeypatch.setenv("QUEUE_BACKEND", "redis")
    with database.connect() as connection:
        queue_id = connection.execute(
            """INSERT INTO fila_processamento(arquivo_hash,arquivo_original,arquivo_salvo,mime_type,status)
               VALUES('h','a.pdf','a.pdf','application/pdf','aguardando_retentativa')"""
        ).lastrowid
    dispatched = []
    monkeypatch.setattr(queueing, "enqueue_queue_item", lambda item_id: dispatched.append(item_id) or True)
    monkeypatch.setattr(queueing, "enqueue_bronze_check", lambda _item_id: False)
    assert queueing.reconcile_pending_jobs()["processamento"] == 1
    assert dispatched == [queue_id]

    class StopAfterTwo:
        calls = 0
        def is_set(self): return self.calls >= 2
        def wait(self, _seconds): self.calls += 1
    cycles = []
    monkeypatch.setattr(queueing, "reconcile_pending_jobs", lambda: cycles.append(1))
    worker.reconciliation_loop(StopAfterTwo(), 30)
    assert len(cycles) == 2


def test_operational_metrics_exclude_human_rejection_from_failures(tmp_path, monkeypatch):
    isolated_database(tmp_path, monkeypatch)
    now = utc_now().isoformat()
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO fila_processamento(arquivo_hash,arquivo_original,arquivo_salvo,mime_type,status,criado_em)
               VALUES('h','a.pdf','a.pdf','application/pdf','concluido',?)""", (now,)
        )
        connection.execute(
            """INSERT INTO atestados(arquivo_original,arquivo_salvo,status,status_entrega,criado_em,revisado_em,
               processamento_iniciado_em,processamento_finalizado_em)
               VALUES('a.pdf','a.pdf','rejeitado','rejeitado',?,?,?,?)""",
            (now, now, (utc_now() - timedelta(seconds=4)).isoformat(), now),
        )
        for component in ("gemini", "databricks", "queue", "bronze"):
            connection.execute(
                "INSERT INTO logs(nivel,evento,mensagem,detalhes,criado_em) VALUES('erro','falha','sintética',?,?)",
                ('{\"component\": \"' + component + '\"}', now),
            )
    metrics = observability.operational_metrics(1)
    assert metrics["received"] == 1
    assert metrics["extracted"] == 1
    assert metrics["rejected"] == 1
    assert metrics["gemini_failures"] == 1
    assert metrics["databricks_failures"] == 1
    assert metrics["queue_failures"] == 1
    assert metrics["bronze_failures"] == 1
    assert metrics["success_rate"] == 33.3
