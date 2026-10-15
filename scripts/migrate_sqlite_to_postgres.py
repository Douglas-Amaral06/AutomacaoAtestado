"""Migração manual, transacional e conservadora de SQLite para PostgreSQL."""

import argparse
import sqlite3

import psycopg
from psycopg import sql

TABLES = (
    "usuarios", "atestados", "sessoes", "tentativas_login", "gemini_consumo",
    "fila_processamento", "logs", "bronze_checks",
)


def migrate(source_path: str, destination_url: str) -> dict[str, int]:
    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    try:
        with psycopg.connect(destination_url) as destination:
            for table in TABLES:
                exists = source.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                if not exists:
                    continue
                source_rows = source.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
                target_count = destination.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()[0]
                if target_count:
                    raise RuntimeError(f"Destino não vazio para a tabela {table}; migração abortada.")
                if source_rows:
                    columns = source_rows[0].keys()
                    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        sql.Identifier(table),
                        sql.SQL(",").join(map(sql.Identifier, columns)),
                        sql.SQL(",").join(sql.Placeholder() for _ in columns),
                    )
                    destination.executemany(query, [tuple(row) for row in source_rows])
                copied = destination.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()[0]
                if copied != len(source_rows):
                    raise RuntimeError(f"Contagem divergente na tabela {table}; migração abortada.")
                counts[table] = copied
                if source_rows and "id" in source_rows[0].keys():
                    destination.execute(
                        sql.SQL("SELECT setval(pg_get_serial_sequence(%s,'id'), COALESCE(MAX(id),1), MAX(id) IS NOT NULL) FROM {}")
                        .format(sql.Identifier(table)), (table,),
                    )
        return counts
    finally:
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra um SQLite explicitamente informado para um PostgreSQL vazio.")
    parser.add_argument("--source", required=True, help="Caminho do arquivo SQLite")
    parser.add_argument("--destination", required=True, help="DATABASE_URL PostgreSQL (não será exibida)")
    args = parser.parse_args()
    counts = migrate(args.source, args.destination)
    print("Migração concluída; contagens por tabela:")
    for table, count in counts.items():
        print(f"- {table}: {count}")


if __name__ == "__main__":
    main()
