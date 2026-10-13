# Checklist de QA do piloto

Use apenas documentos sintéticos ou formalmente autorizados. Registre evidências sem copiar CPF, conteúdo médico, tokens ou senhas. Preencha **Status** com `Não testado`, `OK` ou `Falhou` e use **Observações** para data, responsável e `correlation_id`, quando houver.

| # | Cenário | Pré-condição | Passos | Resultado esperado | Status | Observações |
|---:|---|---|---|---|---|---|
| 1 | Upload válido | Analista ativo e arquivo sintético aceito | Entrar, abrir **Enviar atestado**, selecionar o arquivo e enviar | Arquivo entra na fila e segue para extração | Não testado | — |
| 2 | Upload inválido | Analista ativo e arquivo vazio, corrompido ou com MIME não aceito | Tentar enviar o arquivo | Mensagem segura; nenhum arquivo ou item de fila residual | Não testado | — |
| 3 | PDF | PDF sintético válido e não protegido | Enviar e acompanhar o processamento | PDF validado, extraído e disponível para revisão | Não testado | — |
| 4 | JPG/PNG | Uma imagem JPG e uma PNG válidas | Enviar cada formato separadamente | Ambos são validados, extraídos e preservados | Não testado | — |
| 5 | Campos completos | Documento sintético legível com todos os campos | Enviar e abrir a revisão | Campos reconhecidos aparecem preenchidos para conferência | Não testado | — |
| 6 | Campos faltantes | Documento sintético sem um ou mais campos opcionais | Enviar e abrir a revisão | Ausências aparecem como vazias/nulas, sem valores inventados | Não testado | — |
| 7 | Correção manual | Atestado aguardando aprovação | Alterar um campo e salvar por aprovação | Correção é persistida e aparece no JSON entregue | Não testado | — |
| 8 | Alteração de CPF | Registro em revisão | Informar CPF fictício válido e aprovar | CPF normalizado para 11 dígitos no registro e JSON | Não testado | — |
| 9 | Alteração de CID | Registro em revisão | Informar CID de teste e aprovar | CID normalizado conforme o contrato | Não testado | — |
| 10 | Alteração de CRM/UF | Registro em revisão | Informar CRM fictício e UF válida | CRM numérico e UF maiúscula aparecem no JSON | Não testado | — |
| 11 | Dias de afastamento | Registro em revisão | Alterar os dias para um inteiro válido | Valor numérico corrigido é persistido e entregue | Não testado | — |
| 12 | Data | Registro em revisão | Alterar para uma data válida | Data corrigida aparece no painel e JSON | Não testado | — |
| 13 | Aprovação | Registro válido e Databricks disponível | Clicar **Aprovar e salvar** | Documento e JSON são enviados antes de `confirmado / entregue_volume` | Não testado | — |
| 14 | Rejeição com motivo | Registro pendente | Selecionar rejeição, informar motivo e confirmar | Registro fica rejeitado e não há escrita no Volume | Não testado | — |
| 15 | Rejeição sem motivo | Registro pendente | Tentar rejeitar com motivo vazio | Operação é bloqueada e o registro continua pendente | Não testado | — |
| 16 | Duplicidade | Mesmo arquivo sintético disponível | Enviar o arquivo duas vezes | Ambos são registrados e o segundo exibe aviso de possível repetição | Não testado | — |
| 17 | Reprocessamento | Item de extração com falha e usuário administrador | Usar a ação de reprocessar | Item volta à fila, registra tentativa e preserva o original | Não testado | — |
| 18 | Falha Gemini | Falha controlada ou indisponibilidade conhecida | Enviar documento e acompanhar | Arquivo é preservado; erro seguro e referência são exibidos | Não testado | — |
| 19 | Falha Databricks | Falha temporária controlada, sem alterar contrato ou path | Aprovar um registro | Correções são salvas; estado fica `falha_entrega`; há `correlation_id` | Não testado | — |
| 20 | Nova tentativa | Registro em `falha_entrega` e serviço restabelecido | Reabrir e aprovar novamente | Entrega termina e estado muda para `confirmado / entregue_volume` | Não testado | — |
| 21 | Documento no Volume | Aprovação concluída | Localizar o caminho exibido/contratual no Volume | Original existe no diretório esperado com o nome do ID | Não testado | — |
| 22 | JSON correspondente | Documento confirmado no Volume | Localizar o `.json` ao lado do original | JSON existe com o mesmo nome-base do documento | Não testado | — |
| 23 | `id_documento` | Par entregue | Comparar painel, nomes dos arquivos e conteúdo JSON | O mesmo ID aparece nos três locais e respeita o formato contratado | Não testado | — |
| 24 | Status de entrega | Registro aprovado | Conferir painel e banco/log operacional | Status é `entregue_volume`; não implica ingestão Bronze | Não testado | — |
| 25 | Exclusão permitida | Registro fora do estado `entregando` e administrador ativo | Excluir pelo painel | Registro e arquivo local deixam de existir; Volume não é apagado | Não testado | — |
| 26 | Exclusão durante entrega | Entrega mantida em andamento de forma controlada | Tentar excluir o registro como administrador | Solicitação recebe conflito e não interrompe a entrega | Não testado | — |
| 27 | Acesso como analista | Usuário analista ativo | Entrar e navegar pelo painel | Upload e revisão acessíveis; administração, logs, relatórios, exportação, exclusão e reprocessamento bloqueados | Não testado | — |
| 28 | Acesso como administrador | Usuário administrador ativo | Entrar e navegar pelas funções administrativas | Gestão de usuários, logs, relatórios, exportação e ações administrativas acessíveis | Não testado | — |
| 29 | Área sem permissão | Sessão de analista ativa | Acessar diretamente URLs administrativas | Servidor responde 403 e nenhuma alteração ocorre | Não testado | — |
| 30 | Logout e expiração | Sessão autenticada | Fazer logout; depois testar uma sessão expirada | Cookie é invalidado e páginas protegidas exigem novo login | Não testado | — |

## Fechamento do piloto

Antes de iniciar com usuários reais, confirme que todos os cenários críticos (1, 2, 13–15, 18–24 e 27–30) estão `OK`. Para falhas, registre somente a referência segura, o horário e a ação realizada. A engenharia deve conferir separadamente a ingestão Bronze; `entregue_volume` confirma apenas o par gravado no Volume.
