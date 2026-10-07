# Automação de Atestados

Aplicação interna para recebimento, extração assistida por IA, revisão humana e entrega de atestados ao Databricks.

**Analista → Painel FastAPI → Upload → Validação → Gemini → Revisão humana → Databricks Volume/Bronze.**

O painel é a única entrada operacional. Python, FastAPI, Jinja2 e SQLite foram preservados. O prompt de extração Gemini e os clientes de storage homologados continuam sendo usados.

## Instalação local

Python 3.12 (a suíte foi executada com 3.12.14). No Windows:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\scripts\configurar_seguranca.ps1
.\iniciar.ps1
```

O script de segurança gera uma chave em `.env`, se necessário, e solicita uma senha de administrador sem exibi-la. Alternativamente, configure `APP_SECRET_KEY` com pelo menos 32 caracteres aleatórios e `BOOTSTRAP_USERS_JSON`, descrito abaixo. Não substitua um `.env` existente. Acesse http://127.0.0.1:8000.

No Linux: crie o ambiente com `python -m venv .venv`, instale `requirements.txt`, configure `.env` e execute `uvicorn app.main:app --host 127.0.0.1 --port 8000`.

Sem credenciais, `DELIVERY_MODE=disabled` permite desenvolver o painel e revisar. Uma aprovação nunca vira confirmação com a entrega desabilitada. A leitura depende de `GEMINI_API_KEY`, `PROCESSOR_CONTRACT_APPROVED=true` e `PROCESSOR_REGION` aprovada. O sistema não altera esses valores automaticamente.

## Usuários do piloto e recuperação após redeploy

Cadastre `BOOTSTRAP_USERS_JSON` como variável secreta no Render. Exemplo estrutural, com valores a substituir no ambiente (não versionar senhas):

```json
[
  {"usuario":"admin","nome":"Administrador","perfil":"admin","senha":"SUBSTITUIR_POR_SEGREDO_FORTE"},
  {"usuario":"analista01","nome":"Analista 01","perfil":"analista","senha":"SUBSTITUIR_POR_OUTRO_SEGREDO"}
]
```

Cada senha deve ter de 12 a 256 caracteres. Usuários usam 3 a 50 letras ASCII, números, ponto, hífen ou sublinhado. O bootstrap normaliza o usuário para minúsculas, valida o conjunto antes da gravação e armazena somente Argon2id. Não registra ou exibe senhas. Contas existentes mantêm senha, perfil, estado ativo e identidade; alterar o JSON não redefine a conta em um banco já existente.

O ID público tem formato `opr_<32 hex>` e é derivado de HMAC-SHA256 de `operador:<usuario>` com `APP_SECRET_KEY`. **Preserve a mesma chave, o mesmo usuário e os segredos no Render entre deploys.** A chave é gerada pelo Blueprint no primeiro provisionamento; ao recriar o serviço, restaure o mesmo valor do gerenciador de segredos.

Também é aceito `operador_public_id` explícito. Para transportar identidades de usuários anteriores ao bootstrap, copie os IDs exibidos em **Usuários** para esse campo no JSON. Isso preserva o vínculo com entregas históricas, sem trocar IDs já cadastrados. IDs devem ser únicos. Contas criadas apenas pelo painel desaparecem se o SQLite for perdido: inclua os usuários necessários no bootstrap. O piloto exige ao menos um administrador ativo na inicialização.

Administrador: revisão, upload, exclusão local, reprocessamento, exportação e relatórios. Analista: revisão e upload. Os dois usam sessão e CSRF; a identidade de envio vem exclusivamente da sessão.

## Upload e revisão

1. Faça login, clique **Enviar atestado** e selecione PDF, JPG/JPEG ou PNG.
2. Confira nome e tamanho; troque ou remova a seleção antes de enviar.
3. O backend confere tamanho, MIME, assinatura binária e estrutura. PDFs protegidos/corrompidos e imagens inválidas são recusados. O limite de upload é 15 MB; o limite de leitura Gemini é independente (8 MB por padrão). Imagens têm limite de 40 milhões de pixels para decodificação segura.
4. O original é salvo com UUID e SHA-256, junto do horário `America/Sao_Paulo`, usuário, origem `painel` e destino configurado `AUREA / SP`. O navegador não escolhe esses metadados.
5. A página de acompanhamento mostra fila, leitura, conclusão, documento não reconhecido ou falha. A leitura começa em segundo plano; o worker recupera itens pendentes a cada 20 segundos. Quotas e erros temporários preservam o arquivo. Administradores podem retomar ou reprocessar itens com falha.
6. Na revisão, confira original, nome, CPF, CID, data, dias, CRM/CRO, UF, assinatura, carimbo, observações e aviso INSS. Arquivos de mesmo SHA são aceitos e sinalizados como possível repetição.
7. **Aprovar e salvar** persiste as correções, reserva a revisão, valida o contrato, grava o original, relê o SHA e grava o JSON. Só a entrega real concluída produz `confirmado / entregue_volume` e exibe o ID Databricks.
8. **Rejeitar**, com motivo, não chama Databricks. Em falha de entrega, o registro continua pendente, com correções salvas e mensagem segura para nova tentativa.

Uma reserva bloqueia revisões e exclusões concorrentes durante a entrega. Reservas interrompidas podem ser retomadas após 30 minutos, reabrindo e aprovando novamente. Um confirmado não é reenviado automaticamente, mesmo se o original local desaparecer. Exclusão pelo painel remove apenas o registro/arquivo local, nunca arquivos do Volume ou linhas Bronze.

`/exportar.xlsx` permanece disponível ao administrador, gerado em memória e protegido contra fórmulas injetadas. Os campos matrícula, telefone, e-mail e empresa existentes são preservados quando ausentes do formulário; nenhuma planilha local é necessária.

## Render

Crie um **Blueprint** a partir deste repositório usando `render.yaml`. Ele define um Web Service Python, sem disco persistente, banco externo ou infraestrutura adicional. Configure os segredos solicitados antes de criar o serviço e preserve-os entre deploys.

- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/healthz` → `{"status":"ok"}` sem autenticação.
- Uma instância e um processo Uvicorn. Não usar `--reload` nem aumentar workers: SQLite e limites por usuário são locais ao processo.
- Após obter a URL, prefira restringir `ALLOWED_HOSTS` ao hostname exato do serviço; adicione o domínio próprio, se houver. O Blueprint permite `127.0.0.1,localhost,*.onrender.com` para o primeiro deploy.

O TLS termina no proxy Render. `COOKIE_SECURE=true` garante cookies Secure mesmo quando a conexão interna usa HTTP; os links de assets e redirecionamentos são relativos. O comando mantém a confiança restrita de proxy do Uvicorn, sem `--forwarded-allow-ips=*`. Cabeçalhos Cloudflare não são usados. Quando o IP público não é fornecido por um proxy confiável, o bloqueio global de login pode agrupar conexões pelo IP do proxy, de forma conservadora; o bloqueio por conta continua ativo. Não amplie a confiança em cabeçalhos enviados pelo cliente para contornar isso.

Referências de configuração: [FastAPI no Render](https://render.com/docs/deploy-fastapi), [Blueprint](https://render.com/docs/blueprint-spec), [versão Python](https://render.com/docs/python-version).

### Variáveis exatas do Blueprint

| Variável | Valor no Render |
|---|---|
| `PYTHON_VERSION` | `3.12.14` |
| `APP_ENV` | `pilot` |
| `APP_SECRET_KEY` | Segredo aleatório persistente; gerado no primeiro provisionamento |
| `BOOTSTRAP_USERS_JSON` | JSON secreto com administrador e analistas |
| `DATA_DIR` | `/tmp/atestados` |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost,*.onrender.com`; depois hostname exato |
| `COOKIE_SECURE` | `true` |
| `TRUST_CLOUDFLARE` | `false` |
| `LOCAL_BACKUP_ENABLED` | `false` |
| `GEMINI_API_KEY` | Segredo da API |
| `GEMINI_MODEL` | `gemini-2.5-flash` |
| `PROCESSOR_CONTRACT_APPROVED` | `true` somente com aprovação organizacional existente |
| `PROCESSOR_REGION` | Identificador da região aprovada; não é configurada pela aplicação |
| `GEMINI_TIMEOUT_SECONDS` | `60` |
| `GEMINI_MAX_ATTEMPTS` | `2` |
| `GEMINI_MAX_OUTPUT_TOKENS` | `1024` |
| `GEMINI_MAX_DOCUMENT_MB` | `8` |
| `GEMINI_DAILY_REQUEST_LIMIT` | `50` |
| `GEMINI_DAILY_OUTPUT_TOKEN_BUDGET` | `50000` |
| `UPLOAD_RATE_LIMIT_PER_HOUR` | `30`, por usuário |
| `UPLOAD_DAILY_QUOTA_MB` | `300`, por usuário |
| `DELIVERY_MODE` | `databricks` |
| `DELIVERY_UNIT` | `AUREA` |
| `DELIVERY_POLO` | `SP` |
| `DELIVERY_TEST` | `false` |
| `DATABRICKS_UPLOAD_ENABLED` | `true` |
| `DATABRICKS_HOST` | URL HTTPS do workspace autorizado |
| `DATABRICKS_VOLUME_ROOT` | `/Volumes/renapsi_prd/bronze_atestados/atestado` |
| `DATABRICKS_AUTH_MODE` | `m2m` |
| `DATABRICKS_CLIENT_ID` | Identidade da Service Principal |
| `DATABRICKS_CLIENT_SECRET` | Segredo OAuth M2M |
| `DATABRICKS_TIMEOUT_SECONDS` | `60` |
| `DATABRICKS_MAX_ATTEMPTS` | `3` |

`PORT` é fornecida pelo Render. As demais opções locais estão em `.env.example`. `GEMINI_MIN_INTERVAL_SECONDS=13`, `GEMINI_IMAGE_ENHANCEMENT=true` e retenção desabilitada continuam como padrões; não é necessário configurá-las no Render. O piloto não usa CLI/U2M.

### Limitações aceitas do piloto

SQLite e uploads são temporários: podem desaparecer em redeploy/reconstrução/restart com perda do filesystem. Documentos ainda não confirmados podem exigir novo envio. Documentos confirmados permanecem no Databricks, que é a persistência oficial. O painel não reconstrói automaticamente seu histórico a partir do Volume. Reiniciar o processo também reinicia os limites de upload em memória; perder SQLite reinicia o orçamento local Gemini.

Backups ZIP automáticos não são iniciados com `LOCAL_BACKUP_ENABLED=false`. Scripts de backup/restore permanecem para uso local, com verificação de hashes e proteção de caminhos. Se configurou `DATA_DIR` personalizado, confira o destino do restore local antes de executá-lo.

## Banco e migração

Inicialização idempotente, executada no startup. A fila é reconstruída dentro de uma transação com preservação dos IDs, vínculos, hashes, arquivos, tentativas, horários, dono e leases; apenas as colunas operacionais são copiadas. Atestados e contas não são apagados. A unicidade do SHA foi removida. Índices operacionais ficam em status/disponibilidade e hash. Metadados de identidade do canal anterior são convertidos quando presentes; tabelas antigas de autenticação do canal são eliminadas somente após a cópia. Os campos antigos não usados da tabela de usuários podem permanecer sem dependência de runtime.

A fila atual contém `id`, `arquivo_hash`, `arquivo_original`, `arquivo_salvo`, `mime_type`, `status`, `tentativas`, `ultimo_erro`, `erro_amigavel`, `disponivel_em`, `atestado_id`, `criado_em`, `atualizado_em`, `data_recebimento`, `unidade`, `polo`, `origem`, `operador_id`, `lock_token`, `lock_expires_em`.

Antes de migrar uma instalação local com dados úteis, encerre a versão anterior e gere um backup local. Não há migração destrutiva de atestados nem chamadas externas na inicialização. Nenhum banco real foi necessário para testar a migração.

## Databricks e validação

Consulte [contrato e homologação](docs/INTEGRACAO_DATABRICKS_V2.md) e o [roteiro completo do piloto](docs/PILOTO.md).

```powershell
.venv\Scripts\python.exe scripts\homologar_entrega_fake.py
.venv\Scripts\python.exe scripts\homologar_databricks.py --check-config
.venv\Scripts\python.exe scripts\homologar_databricks.py --check-access
```

O primeiro usa somente storage local fictício. O segundo valida configuração sem rede. O terceiro autentica e lê o Volume, sem gravar. A homologação real pelo painel deve conferir o par, hash, operador, destino e ingestão Bronze. O estado `entregue_volume` confirma a entrega ao Volume; não consulta a conclusão da ingestão Bronze.

## Segurança e testes

Argon2id, sessões por hash, cookies HttpOnly/SameSite/Secure, CSRF, permissões, TrustedHost, CSP, proteção de login, limites de upload, validação de bytes/estrutura e logs sanitizados foram mantidos. Não há CORS permissivo. Dados e segredos locais estão excluídos do Git. Consulte [SECURITY.md](SECURITY.md).

```powershell
.venv\Scripts\python.exe -m compileall app
.venv\Scripts\python.exe -m pytest -q
```

Testes usam bancos temporários, extração simulada e storage local ou transporte HTTP substituído. Não acessam Gemini nem Databricks reais. As duas bases CSV sintéticas em `data/fixtures` alimentam o simulador Databricks; saídas geradas são ignoradas pelo Git.

## Próxima fase: integração Fluig

Após validar o piloto: um atestado entregue poderá originar uma tarefa Fluig, com ID, status e data de criação. Nenhum endpoint, mock ou campo de tarefa foi adicionado agora. A identidade interna e o serviço de ingresso são independentes de um futuro provedor corporativo de login.
