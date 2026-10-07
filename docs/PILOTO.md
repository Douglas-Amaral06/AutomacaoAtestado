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

A aprovação em modo fake permanece pendente e é exibida como simulação local. O piloto recusa aprovação nesse modo. A validação final requer DELIVERY_MODE=databricks e OAuth M2M.
