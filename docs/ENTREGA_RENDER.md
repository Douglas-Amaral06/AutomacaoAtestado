# Entrega da refatoração — piloto Render

O projeto existente foi adaptado para entrada exclusiva pelo painel: upload autenticado, validação de arquivos, fila, Gemini, revisão humana e confirmação somente após documento/SHA/JSON entregues. O prompt Gemini e a integração Databricks foram preservados. Falhas mantêm correções e estado pendente; rejeições não enviam.

## Configuração e operação

O [README](../README.md) contém instalação local, bootstrap dos usuários e **lista exata das variáveis de ambiente do Render**. O [render.yaml](../render.yaml) define o serviço.

- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health: `/healthz`
- Usuários: `BOOTSTRAP_USERS_JSON` secreto, com um administrador; Argon2id e identidade explícita ou HMAC estável com APP_SECRET_KEY.
- Render: Python 3.12.14, APP_ENV=pilot, cookies Secure, DATA_DIR temporário, backups automáticos desabilitados, uma instância/processo.
- Databricks: AUREA/SP, canal painel, DELIVERY_TEST=false, OAuth M2M.
- Validação: [contrato e homologação](INTEGRACAO_DATABRICKS_V2.md), [roteiro do piloto](PILOTO.md).

## Schema e fluxo

Migração idempotente e transacional da fila preserva atestados, contas, IDs, vínculos, metadados úteis e leases. Remove unicidade do SHA e estruturas antigas de autenticação; adiciona polo/origem. SQLite continua temporário.

Login → upload → sessão/CSRF/permissão → limites → MIME/estrutura/SHA → UUID/fila → Gemini em segundo plano → revisão → aprovação → documento → conferir SHA remoto → JSON → confirmação.

Arquivos repetidos são aceitos e sinalizados. Reserva atômica impede entregas concorrentes. Colisões do ID contratual local são bloqueadas antes da escrita e orientam novo recebimento, sem modificar a fórmula homologada. Um confirmado não é reenviado se perder o arquivo local.

## Testes

- Compileall: sucesso.
- Suíte completa: **125 testes passaram**, sem falhas.
- Após ajuste final da mensagem de colisão: **3 testes adicionais passaram**, cobrindo colisão sem sobrescrita, limite efetivo de corpo e ausência de Content-Length.
- **128 casos verificados**; uma advertência de dependência do pytest.
- `git diff --check`: sem erros de whitespace.
- Referências restantes revisadas: contrato/nulos, migração e seus testes, rotas antigas comprovadamente ausentes e extensão de arquivo.

Não foram usados o banco real, documentos reais ou credenciais para os testes. Não houve deploy, commit, push ou chamadas reais Gemini/Databricks. As alterações locais preexistentes foram preservadas e adaptadas.

## Pendências externas

1. Provisionar o serviço na conta Render e preencher os segredos.
2. Disponibilizar credenciais M2M e permissões ao workspace/Volume; validar conectividade da nova hospedagem.
3. Informar aprovação/região do processamento externo, caso ainda não existam; bloqueio atual preservado.
4. Frequência validar o roteiro operacional e engenharia conferir ingestão Bronze com origem painel.

Não dependem do piloto: AWS, banco externo, Fluig ou login corporativo.

## Inventário

A lista abaixo inclui alterações que já existiam antes da sessão. `M` = modificado; `D` = removido; `??` = criado/não versionado. As 100 saídas antigas do simulador foram removidas; as duas bases CSV utilizadas pelos testes foram mantidas. Também foram removidos os arquivos locais sem relação com o projeto: `build_cv.py`, `output/pdf/CV_Douglas_Amaral_Tecnologia_Atualizado.pdf` e `tmp/cv_preview.png`. A imagem fictícia de atestado em `output/documentos_teste/` foi preservada.

```text
 M .env.example
 M .gitignore
 M README.md
 M SECURITY.md
 D app/absence.py
 M app/database.py
 M app/databricks_delivery.py
 M app/main.py
 M app/maintenance.py
 M app/processing.py
 M app/rate_limit.py
 M app/security.py
 D app/spreadsheet_pipeline.py
 M app/storage_client.py
 M app/templates/base.html
 M app/templates/dashboard.html
 M app/templates/login.html
 M app/templates/logs.html
 D app/templates/pairing.html
 M app/templates/reports.html
 M app/templates/review.html
 M app/templates/users.html
 M app/validation.py
 D data/fixtures/resultado_ausencias_ficticias.csv
 M docs/INTEGRACAO_DATABRICKS_V2.md
 M docs/PILOTO.md
 M docs/RESPOSTAS_SECAO_13.md
 D extension/backend-config.js
 D extension/background.js
 D extension/content.js
 D extension/manifest.json
 D extension/popup.html
 D extension/popup.js
 D extension/renapsi-logo.png
 M requirements.txt
 M scripts/atualizar.ps1
 D scripts/configurar_pipeline.py
 M scripts/configurar_seguranca.ps1
 M scripts/criar_admin.py
 D scripts/gerar_dados_ficticios.py
 M scripts/homologar_databricks.py
 M scripts/homologar_entrega_fake.py
 D tests/test_absence.py
 M tests/test_databricks_delivery.py
 D tests/test_extension_config.py
 M tests/test_files.py
 M tests/test_security.py
 D tests/test_spreadsheet_pipeline.py
 M tests/test_workflow.py
?? app/bootstrap.py
?? app/config.py
?? app/export.py
?? app/static/js/upload.js
?? app/templates/upload.html
?? app/templates/upload_status.html
?? app/uploads.py
?? docs/ENTREGA_RENDER.md
?? render.yaml
?? tests/conftest.py
?? tests/test_bootstrap_migration.py
?? tests/test_panel_upload.py
D  data/fixtures/databricks_delivery/ (100 arquivos gerados)
```
