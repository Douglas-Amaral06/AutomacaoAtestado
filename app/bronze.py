"""Confirmação somente-leitura da ingestão na Bronze via Statement Execution API."""

import json
import os
import re
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .database import connect
from .safe_errors import format_safe_error
from .security import utc_now

_TABLE = "renapsi_prd.bronze_atestados.atestado_whatsapp"
_DELAYS = (30, 120, 300, 900)


def bronze_enabled() -> bool:
    return os.getenv("BRONZE_CHECK_ENABLED", "false").strip().lower() == "true"


def schedule_bronze_check(atestado_id: int, id_documento: str) -> int | None:
    if not bronze_enabled():
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", id_documento or ""):
        raise ValueError("id_documento inválido para consulta Bronze")
    now = utc_now().isoformat()
    with connect() as connection:
        existing = connection.execute(
            "SELECT id FROM bronze_checks WHERE atestado_id=?", (atestado_id,)
        ).fetchone()
        if existing:
            check_id = existing["id"]
        else:
            check_id = connection.execute(
                """INSERT INTO bronze_checks(atestado_id,id_documento,status,disponivel_em,atualizado_em)
                   VALUES(?,?,'aguardando',?,?)""", (atestado_id, id_documento, now, now)
            ).lastrowid
        connection.execute(
            "UPDATE atestados SET status_bronze='aguardando' WHERE id=? AND status_entrega='entregue_volume'",
            (atestado_id,),
        )
    from .queueing import enqueue_bronze_check
    enqueue_bronze_check(check_id)
    return check_id


def _statement_found(id_documento: str) -> bool:
    host = os.getenv("DATABRICKS_HOST", "").strip().rstrip("/")
    token = os.getenv("DATABRICKS_TOKEN", "").strip()
    warehouse = os.getenv("DATABRICKS_SQL_WAREHOUSE_ID", "").strip()
    if not host or not token or not warehouse:
        raise RuntimeError("Configuração do checkout Bronze incompleta.")
    payload = json.dumps({
        "warehouse_id": warehouse,
        "statement": f"SELECT 1 FROM {_TABLE} WHERE id_documento = :id_documento LIMIT 1",
        "parameters": [{"name": "id_documento", "value": id_documento, "type": "STRING"}],
        "wait_timeout": "10s",
        "on_wait_timeout": "CANCEL",
        "disposition": "INLINE",
        "format": "JSON_ARRAY",
    }).encode()
    request = Request(
        host + "/api/2.0/sql/statements", data=payload, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=int(os.getenv("DATABRICKS_TIMEOUT_SECONDS", "60"))) as response:
        body = json.loads(response.read())
    state = body.get("status", {}).get("state")
    if state != "SUCCEEDED":
        raise RuntimeError("Consulta Bronze não foi concluída.")
    return bool(body.get("result", {}).get("data_array"))


def process_bronze_check(check_id: int) -> dict:
    with connect() as connection:
        check = connection.execute("SELECT * FROM bronze_checks WHERE id=?", (check_id,)).fetchone()
    if not check or check["status"] in {"confirmado", "nao_encontrado"}:
        return {"status": check["status"] if check else "ausente"}
    attempt = int(check["tentativas"]) + 1
    now = utc_now()
    try:
        found = _statement_found(check["id_documento"])
    except (HTTPError, URLError, TimeoutError, RuntimeError, ValueError) as error:
        safe_message, _ = format_safe_error(error)
        status = "erro_consulta"
        next_delay = _DELAYS[attempt - 1] if attempt <= len(_DELAYS) else 0
        next_at = now + timedelta(seconds=next_delay) if next_delay else None
        with connect() as connection:
            connection.execute(
                """UPDATE bronze_checks SET status=?,tentativas=?,ultimo_erro=?,disponivel_em=?,atualizado_em=?
                   WHERE id=?""", (status, attempt, safe_message, next_at.isoformat() if next_at else None, now.isoformat(), check_id)
            )
            connection.execute("UPDATE atestados SET status_bronze=? WHERE id=?", (status, check["atestado_id"]))
        try:
            from .processing import add_log
            add_log("erro", "bronze_consulta_falhou", safe_message, {
                "atestado_id": check["atestado_id"], "component": "bronze",
            })
        except Exception:
            pass
        if next_delay:
            from .queueing import enqueue_bronze_check
            enqueue_bronze_check(check_id, next_delay)
        return {"status": status}
    status = "confirmado" if found else ("nao_encontrado" if attempt > len(_DELAYS) else "aguardando")
    verified = now.isoformat() if status in {"confirmado", "nao_encontrado"} else None
    next_delay = _DELAYS[attempt - 1] if status == "aguardando" else 0
    with connect() as connection:
        connection.execute(
            """UPDATE bronze_checks SET status=?,tentativas=?,ultimo_erro=NULL,disponivel_em=?,atualizado_em=?
               WHERE id=?""", (status, attempt, (now + timedelta(seconds=next_delay)).isoformat() if next_delay else None, now.isoformat(), check_id)
        )
        connection.execute(
            "UPDATE atestados SET status_bronze=?,bronze_verificado_em=? WHERE id=? AND status_entrega='entregue_volume'",
            (status, verified, check["atestado_id"]),
        )
    if status == "aguardando":
        from .queueing import enqueue_bronze_check
        enqueue_bronze_check(check_id, next_delay)
    return {"status": status}
