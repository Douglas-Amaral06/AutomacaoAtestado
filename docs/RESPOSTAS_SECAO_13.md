# Decisões operacionais do piloto

- Entrada: painel web autenticado; upload individual PDF/JPG/PNG.
- Destino São Paulo: unidade AUREA e polo SP, controlados pelo backend.
- Volume oficial: `/Volumes/renapsi_prd/bronze_atestados/atestado`.
- Confirmação exige original íntegro e JSON entregues; rejeição não envia.
- Operador: identidade opaca da sessão, mantida pelo bootstrap entre redeploys.
- Hospedagem: Render com SQLite/arquivos temporários e sem backups automáticos.
- Login: local durante o piloto; identidade corporativa e Fluig são fases futuras.
- Validação operacional: setor de Frequência com seus próprios usuários.

A integração Volume/Bronze já foi homologada segundo o contexto do projeto. O deploy Render exige configurar os segredos M2M e validar a conectividade da nova hospedagem; não exige reimplementar a integração. Consulte `PILOTO.md` e `INTEGRACAO_DATABRICKS_V2.md` para os critérios e evidências.
