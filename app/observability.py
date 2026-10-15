"""Métricas operacionais agregadas, sem conteúdo pessoal ou médico."""

from datetime import timedelta

from .database import connect
from .security import utc_now


def operational_metrics(days: int = 1) -> dict:
    days = days if days in {1, 7, 30} else 1
    cutoff = (utc_now() - timedelta(days=days)).isoformat()
    with connect() as connection:
        received = connection.execute(
            "SELECT COUNT(*) FROM fila_processamento WHERE criado_em>=?", (cutoff,)
        ).fetchone()[0]
        extracted = connection.execute(
            "SELECT COUNT(*) FROM atestados WHERE processamento_finalizado_em>=? OR (processamento_finalizado_em IS NULL AND criado_em>=?)",
            (cutoff, cutoff),
        ).fetchone()[0]
        approved = connection.execute(
            "SELECT COUNT(*) FROM atestados WHERE status='confirmado' AND revisado_em>=?", (cutoff,)
        ).fetchone()[0]
        rejected = connection.execute(
            "SELECT COUNT(*) FROM atestados WHERE status='rejeitado' AND revisado_em>=?", (cutoff,)
        ).fetchone()[0]
        gemini_failures = connection.execute(
            "SELECT COUNT(*) FROM logs WHERE detalhes LIKE ? AND criado_em>=?",
            ('%\"component\": \"gemini\"%', cutoff),
        ).fetchone()[0]
        databricks_failures = connection.execute(
            "SELECT COUNT(*) FROM logs WHERE detalhes LIKE ? AND criado_em>=?",
            ('%\"component\": \"databricks\"%', cutoff),
        ).fetchone()[0]
        queue_failures = connection.execute(
            "SELECT COUNT(*) FROM logs WHERE detalhes LIKE ? AND criado_em>=?",
            ('%\"component\": \"queue\"%', cutoff),
        ).fetchone()[0]
        bronze_failures = connection.execute(
            "SELECT COUNT(*) FROM logs WHERE detalhes LIKE ? AND criado_em>=?",
            ('%\"component\": \"bronze\"%', cutoff),
        ).fetchone()[0]
        delivered = connection.execute(
            "SELECT COUNT(*) FROM atestados WHERE status_entrega='entregue_volume' AND entrega_finalizada_em>=?",
            (cutoff,),
        ).fetchone()[0]
        bronze_confirmed = connection.execute(
            "SELECT COUNT(*) FROM atestados WHERE status_bronze='confirmado' AND bronze_verificado_em>=?",
            (cutoff,),
        ).fetchone()[0]
        bronze_waiting = connection.execute(
            "SELECT COUNT(*) FROM atestados WHERE status_entrega='entregue_volume' AND status_bronze='aguardando'"
        ).fetchone()[0]
        bronze_errors = connection.execute(
            "SELECT COUNT(*) FROM atestados WHERE status_entrega='entregue_volume' AND status_bronze='erro_consulta'"
        ).fetchone()[0]
        times = connection.execute(
            "SELECT processamento_iniciado_em,processamento_finalizado_em FROM atestados WHERE processamento_finalizado_em>=?",
            (cutoff,),
        ).fetchall()
    durations = []
    for row in times:
        try:
            start = __import__("datetime").datetime.fromisoformat(row["processamento_iniciado_em"])
            end = __import__("datetime").datetime.fromisoformat(row["processamento_finalizado_em"])
            durations.append((end - start).total_seconds())
        except (TypeError, ValueError):
            pass
    technical_total = extracted + gemini_failures + delivered + databricks_failures
    technical_success = extracted + delivered
    return {
        "days": days, "received": received, "extracted": extracted,
        "approved": approved, "rejected": rejected, "gemini_failures": gemini_failures,
        "databricks_failures": databricks_failures, "queue_failures": queue_failures,
        "bronze_failures": bronze_failures,
        "average_extraction_seconds": round(sum(durations) / len(durations), 1) if durations else 0,
        "success_rate": round(100 * technical_success / technical_total, 1) if technical_total else 100.0,
        "delivered": delivered, "bronze_confirmed": bronze_confirmed,
        "bronze_waiting": bronze_waiting, "bronze_errors": bronze_errors,
    }
