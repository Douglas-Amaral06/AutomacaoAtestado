"""Despacho RQ; o estado durável permanece no banco de dados."""

import os
from datetime import datetime, timezone

from .database import connect


def queue_backend() -> str:
    return os.getenv("QUEUE_BACKEND", "local").strip().lower()


def validate_queue_configuration() -> None:
    env = os.getenv("APP_ENV", "development").strip().lower()
    backend = queue_backend()
    if env in {"pilot", "production"} and backend == "redis" and os.getenv("FILE_STORAGE_BACKEND", "local").strip().lower() != "supabase":
        raise RuntimeError(
            "FILE_STORAGE_BACKEND=supabase é obrigatório com Redis em pilot/production."
        )
    if backend == "redis" and not os.getenv("REDIS_URL", "").strip():
        raise RuntimeError("REDIS_URL é obrigatória quando QUEUE_BACKEND=redis.")


def _queue():
    from redis import Redis
    from rq import Queue
    return Queue(
        os.getenv("QUEUE_NAME", "atestados"),
        connection=Redis.from_url(os.environ["REDIS_URL"]),
        default_timeout=int(os.getenv("QUEUE_JOB_TIMEOUT_SECONDS", "900")),
    )


def enqueue_queue_item(queue_id: int, delay_seconds: int = 0) -> bool:
    if queue_backend() != "redis":
        return False
    queue = _queue()
    suffix = f"-{int(datetime.now(timezone.utc).timestamp())}" if delay_seconds else ""
    job_id = f"processamento-{queue_id}{suffix}"
    existing = queue.fetch_job(job_id)
    if existing and existing.get_status(refresh=True) in {"queued", "started", "scheduled", "deferred"}:
        return False
    if delay_seconds:
        from datetime import timedelta
        queue.enqueue_in(timedelta(seconds=delay_seconds), "app.worker.process_queue_job", queue_id,
                         job_id=job_id, result_ttl=3600, failure_ttl=86400)
    else:
        queue.enqueue("app.worker.process_queue_job", queue_id, job_id=job_id, result_ttl=3600, failure_ttl=86400)
    return True


def enqueue_bronze_check(check_id: int, delay_seconds: int = 0) -> bool:
    if queue_backend() != "redis":
        return False
    queue = _queue()
    job_id = f"bronze-{check_id}-{int(datetime.now(timezone.utc).timestamp())}"
    if delay_seconds:
        queue.enqueue_in(
            __import__("datetime").timedelta(seconds=delay_seconds),
            "app.worker.process_bronze_job", check_id, job_id=job_id,
        )
    else:
        queue.enqueue("app.worker.process_bronze_job", check_id, job_id=job_id)
    return True


def reconcile_pending_jobs(limit: int = 200) -> dict:
    if queue_backend() != "redis":
        return {"processamento": 0, "bronze": 0}
    now = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        processing = connection.execute(
            """SELECT id FROM fila_processamento WHERE atestado_id IS NULL AND (
                 (status IN ('aguardando_retentativa','pausado_quota') AND
                  (disponivel_em IS NULL OR disponivel_em<=?)) OR
                 (status='processando' AND (lock_expires_em IS NULL OR lock_expires_em<=?)))
               ORDER BY id LIMIT ?""", (now, now, limit),
        ).fetchall()
        bronze = connection.execute(
            """SELECT id FROM bronze_checks WHERE status IN ('aguardando','erro_consulta')
               AND (disponivel_em IS NULL OR disponivel_em<=?) ORDER BY id LIMIT ?""",
            (now, limit),
        ).fetchall()
    return {
        "processamento": sum(enqueue_queue_item(row["id"]) for row in processing),
        "bronze": sum(enqueue_bronze_check(row["id"]) for row in bronze),
    }


def redis_health() -> bool:
    if queue_backend() != "redis":
        return False
    return bool(_queue().connection.ping())


def worker_health() -> bool:
    if queue_backend() != "redis":
        return False
    from rq import Worker
    queue = _queue()
    return any(worker.get_state(refresh=True) in {"idle", "busy"}
               for worker in Worker.all(connection=queue.connection))
