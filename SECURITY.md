# Segurança do piloto

- Argon2id com salt individual; bootstrap secreto e idempotente, sem senha em logs ou banco em texto puro.
- Identidade pública opaca persistente: HMAC/APP_SECRET_KEY + usuário ou ID explícito.
- Sessões aleatórias guardadas por SHA-256, expiração, vinculação ao navegador e verificação adicional de IP para administradores.
- Cookies HttpOnly, SameSite=Strict e Secure no Render; chave e segredos preservados entre deploys.
- CSRF e permissões em todas as mutações do painel; queries parametrizadas.
- Bloqueio de login por conta/IP e IP global; senha de comparação para usuários inexistentes.
- TrustedHost, CSP, proteção de frame, MIME sniffing e Referer. Sem CORS aberto.
- Upload autenticado antes do multipart; limites declarado e efetivo de requisição, limite por arquivo, quota por usuário, MIME, magic bytes, PDF/imagem validada, UUID e SHA-256.
- Extração externa bloqueada sem aprovação contratual e região declarada; orçamentos Gemini preservados.
- Leases na fila e reserva atômica de revisão; somente entrega real concluída confirma atestado.
- Documento enviado e relido para conferir SHA antes do JSON-sinal; OAuth M2M com credenciais externas.
- Erros de entrega/extracão usam referência de correlação; não expõem mensagens brutas, conteúdo, credenciais ou payload médico.
- Exportação XLSX em memória com fórmulas textuais neutralizadas.
- Backups locais verificam manifesto/hashes e caminhos; worker ZIP desabilitado no Render.
- `.env`, bancos, uploads, backups e saídas temporárias excluídos do Git.

O filesystem temporário é uma limitação expressamente aceita no piloto. Documentos aprovados têm persistência oficial no Databricks. Bootstrap não substitui uma gestão corporativa de identidade: senhas e APP_SECRET_KEY devem permanecer no gerenciador de segredos do ambiente.

Não confiar em cabeçalhos de proxy de origens arbitrárias. O serviço Render não utiliza cabeçalhos Cloudflare. O comando Uvicorn mantém sua lista restrita padrão; os cookies Secure e URLs relativas não dependem de interpretar o transporte interno como HTTPS.
