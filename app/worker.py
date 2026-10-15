"""Entrypoints pequenos do worker. Não duplica lógica de negócio."""

from .bronze import process_bronze_check
from .processing import process_queue_item


def process_queue_job(queue_id: int):
    try:
        return process_queue_item(queue_id)
    except Exception:
        # A máquina de estados do banco decide se/quando há nova tentativa; o RQ
        # apenas agenda a próxima execução e não mantém uma política concorrente.
        from datetime import datetime, timezone
        from .database import connect
        from .queueing import enqueue_queue_item
        with connect() as connection:
            item = connection.execute(
                "SELECT status,disponivel_em FROM fila_processamento WHERE id=?", (queue_id,)
            ).fetchone()
        if item and item["status"] in {"aguardando_retentativa", "pausado_quota"}:
            delay = 1
            try:
                available = datetime.fromisoformat(item["disponivel_em"])
                delay = max(1, int((available - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError):
                pass
            enqueue_queue_item(queue_id, delay)
        raise


def process_bronze_job(check_id: int):
    return process_bronze_check(check_id)


def reconciliation_loop(stop_event, interval_seconds: int) -> None:
    """Repara periodicamente despachos perdidos sem executar o trabalho pesado."""
    from .queueing import reconcile_pending_jobs
    while not stop_event.is_set():
        try:
            reconcile_pending_jobs()
        except Exception:
            # O próximo ciclo tenta novamente; o estado permanece no PostgreSQL.
            pass
        stop_event.wait(interval_seconds)


def main() -> None:
    import os
    import threading
    from redis import Redis
    from rq import Queue, Worker
    from .database import initialize_database
    from .queueing import reconcile_pending_jobs, validate_queue_configuration

    validate_queue_configuration()
    initialize_database()
    connection = Redis.from_url(os.environ["REDIS_URL"])
    reconcile_pending_jobs()
    stop_event = threading.Event()
    reconciler = threading.Thread(
        target=reconciliation_loop,
        args=(stop_event, max(30, int(os.getenv("QUEUE_RECONCILE_INTERVAL_SECONDS", "60")))),
        daemon=True,
        name="queue-reconciler",
    )
    reconciler.start()
    try:
        Worker([Queue(os.getenv("QUEUE_NAME", "atestados"), connection=connection)], connection=connection).work(with_scheduler=True)
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
