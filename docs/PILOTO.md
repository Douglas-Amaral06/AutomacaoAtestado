# Roteiro do piloto — Frequência / AUREA / SP

Executar na URL Render com documentos sintéticos ou autorizados. Registrar evidência por caso, sem CPF, nomes, conteúdo médico ou segredos em logs compartilhados. O código local não substitui a validação na conta Render e com a Service Principal do ambiente.

| Caso | Resultado esperado |
|---|---|
| 1. Login do analista | Sessão HttpOnly, Secure e SameSite; painel acessível |
| 2. JPG válido | Leitura e revisão com original preservado |
| 3. PNG válido | Leitura e revisão com original preservado |
| 4. PDF válido | Estrutura validada, leitura e revisão |
| 5. Arquivo corrompido, vazio, MIME falso ou acima do limite | Mensagem segura; nenhuma fila/arquivo residual |
| 6. Arquivo não-atestado | Ignorado, sem atestado válido nem envio externo ao Volume |
| 7. Mesmo documento duas vezes | Dois recebimentos, aviso de possível repetição; sem bloqueio por SHA |
| 8. Gemini indisponível | Arquivo preservado; retentativa e mensagem amigável |
| 9. Gemini 429 | Item pausado por quota; retomada pelo administrador |
| 10. Revisão | Original, campos e validações visíveis |
| 11. Correção manual | Campos enviados no JSON; dados auxiliares existentes preservados |
| 12. Rejeição com motivo | Rejeitado; nenhuma chamada de entrega |
| 13. Confirmação | Estado confirmado somente após entrega real concluída |
| 14. Original no Databricks | Documento no diretório correto do Volume |
| 15. JSON no Databricks | Nome-base igual ao documento e ao id_documento |
| 16. SHA | SHA-256 do JSON corresponde aos bytes originais e remotos |
| 17. Operador | origem.operador_id corresponde ao remetente autenticado; revisor identificado na revisão humana |
| 18. Unidade | AUREA, definida pelo backend |
| 19. Polo | SP, definido pelo backend |
| 20. Canal | painel; campos contratuais antigos nulos |
| 21. Rejeitado | Nenhum documento/JSON novo aparece no Volume |
| 22. Erro Databricks | Pendente/falha_entrega; edição preservada, aprovação pode ser tentada novamente |
| 23. Concorrência | Segunda aprovação/rejeição/exclusão bloqueada durante entrega |
| 24. Acesso indevido | Sem sessão, CSRF inválido e perfil sem upload recusados |
| 25. Redeploy com perda de SQLite | Usuários bootstrap recriados; mesmo operador_public_id; reenvio de pendentes pode ser necessário |
| 26. Confirmado sem arquivo local | Original retorna indisponível; não ocorre reenvio automático |
| 27. Administração | Relatórios, XLSX, reprocessamento e exclusão local funcionando |
| 28. Health check | /healthz retorna 200 sem dados sensíveis |
| 29. Bronze | Engenharia confirma ingestão e nulos do contrato de origem painel |

O caso 25 é validado também por teste automatizado com dois bancos independentes. Em ambiente real, realize-o de forma planejada após registrar o que está pendente; não apague o banco em uso apenas para testar.

Os casos de indisponibilidade/429/falha de integridade são cobertos offline pela suíte. Não provoque consumo artificial da quota real. Para testar falha de entrega no ambiente, use uma configuração controlada e depois restaure-a, preservando a chave interna e os usuários.

A aprovação em modo fake permanece pendente e é exibida como simulação local. O piloto recusa aprovação nesse modo. A validação final requer `DELIVERY_MODE=databricks` e, nesta etapa, o token temporário homologado. OAuth M2M fica para uma etapa posterior.
# Cutover PostgreSQL/Redis

1. Faça backup verificável do SQLite atual.
2. Provisione PostgreSQL e execute a aplicação uma vez para criar o schema.
3. Pare escrita no ambiente antigo e execute manualmente `scripts/migrate_sqlite_to_postgres.py`.
4. Valide contagens, login, histórico, fila e relatórios no PostgreSQL.
5. Mantenha `QUEUE_BACKEND=local`; não provisione/ative o Worker separado ainda.
6. Escolha e implemente armazenamento compartilhado em etapa futura antes de Redis/Worker.
7. Valide upload, Gemini, revisão e entrega no Volume oficial.
8. Configure o Warehouse e só então altere `BRONZE_CHECK_ENABLED=true`.
9. Confira `/diagnostico` com uma sessão administrativa.

Não ative produção enquanto uploads pendentes ainda dependerem de uma instância web que
pode reiniciar: os metadados sobreviverão no PostgreSQL, mas o arquivo local em `/tmp`
pode ser perdido. O Volume continua sendo a persistência oficial após a entrega.
