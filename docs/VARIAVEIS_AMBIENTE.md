# Inventário de variáveis de ambiente

## Render — necessárias para o piloto

| Grupo | Variáveis |
|---|---|
| Aplicação | `PYTHON_VERSION`, `APP_ENV`, `APP_SECRET_KEY`, `DATA_DIR`, `ALLOWED_HOSTS` |
| Usuários | `BOOTSTRAP_USERS_JSON` |
| Sessão e proxy | `COOKIE_SECURE`, `TRUST_CLOUDFLARE` |
| Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL`, `PROCESSOR_CONTRACT_APPROVED`, `PROCESSOR_REGION`, `GEMINI_TIMEOUT_SECONDS`, `GEMINI_MAX_ATTEMPTS`, `GEMINI_MAX_OUTPUT_TOKENS`, `GEMINI_MAX_DOCUMENT_MB`, `GEMINI_DAILY_REQUEST_LIMIT`, `GEMINI_DAILY_OUTPUT_TOKEN_BUDGET` |
| Upload | `UPLOAD_RATE_LIMIT_PER_HOUR`, `UPLOAD_DAILY_QUOTA_MB` |
| Entrega | `DELIVERY_MODE`, `DELIVERY_UNIT`, `DELIVERY_POLO`, `DELIVERY_TEST` |
| Databricks | `DATABRICKS_UPLOAD_ENABLED`, `DATABRICKS_HOST`, `DATABRICKS_VOLUME_ROOT`, `DATABRICKS_AUTH_MODE`, `DATABRICKS_TOKEN`, `DATABRICKS_TIMEOUT_SECONDS`, `DATABRICKS_MAX_ATTEMPTS` |
| Manutenção | `LOCAL_BACKUP_ENABLED` |

`PORT` é fornecida pelo Render. Segredos (`APP_SECRET_KEY`, `BOOTSTRAP_USERS_JSON`, `GEMINI_API_KEY` e `DATABRICKS_TOKEN`) devem existir somente no ambiente do serviço.

## Opcionais com padrão no código

`GEMINI_MIN_INTERVAL_SECONDS`, `GEMINI_IMAGE_ENHANCEMENT`, `BACKUP_INTERVAL_HOURS`, `BACKUP_RETENTION_DAYS`, `RETENTION_ENABLED`, `DOCUMENT_RETENTION_DAYS` e `LOG_RETENTION_DAYS` têm padrão seguro e só precisam ser definidas quando o comportamento padrão for alterado. `TRUSTED_PROXY_IPS` só é usado quando `TRUST_CLOUDFLARE=true`, opção desativada no Render atual.

## Desenvolvimento e homologação local

`DELIVERY_FAKE_ROOT` seleciona o storage fictício. `DATABRICKS_CLI_PATH` e `DATABRICKS_CLI_PROFILE` pertencem apenas à homologação local via CLI/U2M e não devem ser configuradas no Render. Elas permanecem porque ainda são usadas pelo cliente e pelo script de homologação.

`DATABRICKS_CLIENT_ID` e `DATABRICKS_CLIENT_SECRET` permanecem suportadas pelo código existente para uma migração futura para OAuth M2M, mas não fazem parte da configuração do piloto atual e não devem ser adicionadas ao Render nesta etapa.

## Obsoletas ou removidas do fluxo atual

- `DATABRICKS_SQL_WAREHOUSE_ID`: era usada somente pela rota temporária `/teste-databricks`, agora removida.
- `PIPELINE_ATESTADOS_PATH`, `PIPELINE_BASE_GERAL_PATH` e `PIPELINE_OUTPUT_DIR`: não possuem referência no código atual e pertencem ao pipeline local antigo.

Essas quatro variáveis podem ser removidas do Render. A remoção não altera a Files API, o contrato JSON, os caminhos ou a entrega ao Volume.
# Persistência e fila

- `DATABASE_URL`: URL PostgreSQL. Obrigatória em `pilot`/`production`; nunca versionar.
- `QUEUE_BACKEND`: deve permanecer `local` em `pilot`/`production` enquanto `/tmp` não for compartilhado.
- `REDIS_URL`: conexão privada Redis/Key Value; obrigatória com backend `redis`.
- `QUEUE_NAME`: nome da fila RQ (padrão `atestados`).
- `QUEUE_JOB_TIMEOUT_SECONDS`: limite do job pesado (padrão 900).
- `QUEUE_RECONCILE_INTERVAL_SECONDS`: intervalo do reconciliador do worker (mínimo 30, padrão 60).
- `BRONZE_CHECK_ENABLED`: habilita confirmação assíncrona, somente leitura.
- `DATABRICKS_SQL_WAREHOUSE_ID`: Warehouse usado na Statement Execution API.

`DATA_DIR` continua servindo apenas para uploads temporários e SQLite local. Não é a
persistência do banco no Render.
