# Integração Databricks — contrato 1.2 e origem painel

## Fluxo preservado

`DeliveryService` valida o contrato, escreve o documento por `StorageClient`, relê seus bytes e compara SHA-256, e só então grava o JSON-sinal. `DatabricksStorageClient` usa Files API e OAuth M2M. A aplicação só marca `confirmado / entregue_volume` após essa sequência concluir. Rejeições não acessam a integração.

Destino padrão: `/Volumes/renapsi_prd/bronze_atestados/atestado`.

Caminho: `AUREA/SP/AAAA/MM/DD/ID.pdf` (ou `.jpg` / `.png`) e `ID.json`.
ID preservado: `SP_AAAAMMDDTHHMMSS_sha8`.

## Origem e compatibilidade Bronze

A estrutura do JSON homologado é preservada: `versao_schema`, `id_documento`, `origem`, `arquivo`, `extracao`, `documento`. Somente a semântica do canal foi adaptada:

```json
{
  "canal": "painel",
  "operador_id": "opr_<32 caracteres hexadecimais>",
  "id_mensagem": null,
  "id_conversa": null,
  "whatsapp_remetente": null,
  "whatsapp_destinatario": null,
  "unidade": "AUREA",
  "polo": "SP",
  "data_recebimento": "2026-10-07T10:30:00-03:00",
  "teste": false
}
```

`id_mensagem`, `id_conversa` e `whatsapp_*` são campos exclusivamente contratuais de compatibilidade. São sempre null, inclusive na simulação; não existem no novo schema da fila nem são parâmetros do formulário. A validação rejeita valores preenchidos. Nenhum telefone fictício é criado.

`origem.operador_id` identifica quem enviou. `extracao.revisao_humana.operador_id` identifica quem aprovou, podendo ser outra pessoa. Ambos usam IDs opacos; nunca o nome de login. Horários são ISO-8601 com offset, normalizados para America/Sao_Paulo. O upload gera o recebimento no servidor; a configuração unidade/polo é preservada na fila mesmo se o ambiente mudar depois.

Tipos oficiais: `Atestado` e `Comprovante de horas`. CPF e CRM são strings numéricas; CID sem ponto no contrato. Campos ausentes são null; assinatura e carimbo são booleanos ou null. `arquivo.sha256`, tamanho, MIME, extensão sem ponto, caminho e nome devem corresponder ao original.

## Estados

| Estado | Significado |
|---|---|
| aguardando_aprovacao | Nenhuma entrega autorizada ainda |
| entregando | Revisão reservada; escrita em andamento |
| entregue_volume | Documento e JSON entregues; status confirmado |
| falha_entrega | Pendente; correções preservadas para nova tentativa |
| rejeitado | Nenhuma nova entrega |
| simulado_local | Exceção exclusiva de desenvolvimento; permanece pendente |

`entregue_volume` não é confirmação de ingestão Bronze. A ingestão é observada pela engenharia, como no contrato existente. Se o JSON falhar depois do documento, pode restar um original sem JSON no Volume; a retentativa reutiliza o mesmo ID e a mesma ordem, sem confirmar antecipadamente.

## Identificação e colisões

A fórmula homologada usa segundos e SHA abreviado. Dois uploads do mesmo conteúdo e polo no mesmo segundo podem produzir o mesmo ID. O backend aceita os uploads e sinaliza repetição, mas bloqueia uma segunda entrega local com ID já reservado por outro registro, evitando sobrescrever a revisão. Nesse caso, envie o documento novamente em outro instante. Não alteramos a fórmula ou inventamos um horário de recebimento.

Esse bloqueio é local ao SQLite do piloto. A fórmula continua tendo a limitação contratual para recebimentos simultâneos em instalações independentes. Use apenas uma instalação operacional; uma futura mudança de formato deve ser acordada com a engenharia. O cenário normal de reenvio em outro segundo cria outro ID.

## Homologação

1. Sem rede: `python scripts/homologar_entrega_fake.py`. Usa TESTE/ZZ, identidade opaca sintética explícita, campos contratuais antigos nulos, par e SHA verificados.
2. Sem rede: `python scripts/homologar_databricks.py --check-config`. Verifica configurações sem retornar credenciais.
3. Somente leitura: `python scripts/homologar_databricks.py --check-access`. Valida OAuth e acesso ao Volume. No Render, usar exclusivamente `DATABRICKS_AUTH_MODE=m2m`.
4. Na URL piloto, enviar documento autorizado, revisar e aprovar. Conferir ID no painel, bytes remotos, SHA, JSON, AUREA/SP, canal e operador. Conferir a linha Bronze com a engenharia.
5. Rejeitar outro documento e confirmar ausência de nova escrita. Simular falha controlada e verificar edição preservada/pedido pendente.

A Service Principal precisa estar habilitada no workspace e autorizada ao catálogo, schema e leitura/escrita do Volume. Segredos são variáveis Render, nunca valores no Git.

O utilitário de gravação sintética existente permanece disponível para validação técnica autorizada:

```text
python scripts/homologar_databricks.py --upload-fictitious --confirm-volume "/Volumes/renapsi_prd/bronze_atestados/atestado"
```

Exige `DATABRICKS_UPLOAD_ENABLED=true` e destino confirmado. A limpeza opcional usa `--cleanup-fictitious --document-relative-path "TESTE/ZZ/AAAA/MM/DD/ID.pdf" --confirm-id "ID"`; valida o JSON e o marcador de homologação antes de excluir JSON e documento. Não apaga diretórios nem linhas já ingeridas na Bronze. Nenhuma dessas operações reais é executada pela suíte.

## Evidências históricas preservadas

O contexto do projeto informa Volume/Bronze já homologados. As evidências abaixo pertencem à integração anterior e não comprovam o deploy Render ou suas credenciais M2M atuais:

**Evidência de 26/08/2026:** concluída pela interface corporativa. O usuário
autenticado visualizou o workspace Sagres, o catálogo `renapsi_prd`, o schema
`bronze_atestados` e o Volume `atestado`. A plataforma exibiu o caminho exato
`/Volumes/renapsi_prd/bronze_atestados/atestado`. Nenhum botão de upload,
criação de diretório ou alteração de permissão foi acionado. Essa evidência
comprova leitura pela identidade pessoal. A interface também apresentou
habilitados os controles **Upload to this volume** e **Create directory**, o que
indica permissão pessoal de escrita, mas nenhum deles foi acionado. A evidência
não comprova ainda o OAuth M2M da Service Principal.

**Evidência de 28/08/2026:** primeira entrega fictícia concluída com OAuth U2M
do usuário corporativo, usando a CLI oficial do Databricks e o destino
autorizado. O PDF foi enviado antes do JSON.

- Diretório: `/Volumes/renapsi_prd/bronze_atestados/atestado/UNI001/2026/08/28/`
- ID: `UNI001_20260828T091116_304b38fa`
- PDF: 630 bytes local e 630 bytes remoto.
- JSON: 1.373 bytes local e 1.373 bytes remoto.
- SHA-256 do PDF: `304b38fab6f8201b4ba4928b00250e5f250b3f5cb8bd05f76a70801e96608468`.
- Conteúdo: integralmente fictício, motor `HOMOLOGACAO-LOCAL`.
- Credenciais: token OAuth armazenado no cofre seguro do sistema operacional;
  nenhum token ou segredo foi colocado no projeto.

Os arquivos permanecem disponíveis para análise da engenharia de dados. Não
executar a limpeza antes de o engenheiro conferir o JSON e a eventual ingestão
na Bronze.


Para o novo piloto, registrar data, identidade da Service Principal (sem segredo), ID sintético, tamanhos, SHA e evidência de ingestão. Não registrar cabeçalhos de autenticação ou payloads médicos em logs compartilhados.
