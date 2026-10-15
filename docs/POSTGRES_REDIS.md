# PostgreSQL e Redis

## Arquitetura futura, ainda bloqueada em produção

```text
Browser → FastAPI → PostgreSQL → Redis/RQ → Worker → Gemini / Databricks
```

PostgreSQL é a fonte durável do estado. Redis apenas despacha IDs. O worker chama a
mesma função `process_queue_item(queue_id)` já usada localmente, e o lease atômico no
banco impede duas execuções simultâneas. Na inicialização, o worker reconcilia itens
aguardando e leases expirados; a indisponibilidade do Redis não apaga a fila persistida.

SQLite permanece disponível com `APP_ENV=development|test` e sem `DATABASE_URL`.
Em `pilot|production`, PostgreSQL é obrigatório. Redis é bloqueado enquanto os uploads
usarem filesystem local, porque Web e Worker do Render não compartilham `/tmp`. A
inicialização falha com mensagem segura caso alguém tente ativar essa combinação.

Quando um armazenamento compartilhado for autorizado e implementado, o worker já possui
reconciliação periódica (padrão 60 segundos) para recuperar despachos perdidos.

## Migração manual

```powershell
python scripts/migrate_sqlite_to_postgres.py --source data/atestados.db --destination "$env:DATABASE_URL"
```

O destino deve estar vazio. O script usa uma transação, preserva IDs, valida contagens,
ajusta sequences e aborta em conflito. Ele não roda no startup nem imprime registros ou
credenciais.

## Desenvolvimento

`docker compose up -d` inicia PostgreSQL e Redis sintéticos. Configure localmente:

```text
DATABASE_URL=postgresql://atestados:local_test_only@localhost:5432/atestados_test
REDIS_URL=redis://localhost:6379/0
QUEUE_BACKEND=redis
```

O backup ZIP interno continua exclusivo do SQLite. Em PostgreSQL, use os backups do
provedor. Uploads locais pendentes não são tornados persistentes por esta mudança.

## Storage compartilhado para worker Redis

Quando `QUEUE_BACKEND=redis` em `pilot` ou `production`, defina obrigatoriamente
`FILE_STORAGE_BACKEND=supabase` e mantenha o bucket `SUPABASE_STORAGE_BUCKET` privado. O PostgreSQL
armazena apenas `storage_key`, nunca URL assinada ou credenciais. O worker lê o objeto por essa referência,
portanto pode rodar em outro container. Supabase é temporário e não substitui o Databricks.

