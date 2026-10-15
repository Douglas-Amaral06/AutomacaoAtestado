# Observabilidade operacional

Administradores veem no dashboard os indicadores de 24 horas: recebidos, extraídos,
aprovados, rejeitados e falhas classificadas por componente (Gemini, Databricks, fila
e Bronze), além do tempo médio de extração,
entregas ao Volume e estado da Bronze. Analistas não recebem esses agregados.

A taxa operacional de sucesso é:

```text
(extrações concluídas + entregas concluídas) /
(extrações concluídas + falhas Gemini + entregas concluídas + falhas Databricks)
```

Rejeição humana e classificação válida como “não-atestado” não são falhas técnicas.
As métricas usam apenas IDs, estados e horários; não registram CPF, CID, nome ou conteúdo.

`GET /healthz` continua sendo liveness simples. `GET /diagnostico`, restrito a admin,
retorna somente `ok`, `degraded` ou `unavailable` para banco, Redis, worker e configuração
Databricks, sem URLs ou secrets.

## Bronze

Após `status_entrega=entregue_volume`, um job consulta apenas `id_documento` em
`renapsi_prd.bronze_atestados.atestado_whatsapp`, via Statement Execution API e parâmetro
tipado. Backoff: 30 s, 2 min, 5 min e 15 min. A Bronze é apenas observabilidade:
falha ou ausência nunca reverte `entregue_volume` e nunca bloqueia aprovação.
