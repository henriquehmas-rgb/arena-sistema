# Deploy — arena-sistema

## Visão geral

```
arenacacerense.com.br          → site estático (projeto separado, /docker/arena-cacerense/)
reservas.arenacacerense.com.br → Next.js (portal cliente + /admin)      [este repo]
api.arenacacerense.com.br      → FastAPI (REST /api/v1)                 [este repo]
```

VPS: `191.96.251.71` (`ssh vps`). Diretório: `/docker/arena-sistema/`. Traefik global da VPS
(rede `traefik`, já existente — compartilhada com todos os projetos) cuida de roteamento e
certificado TLS via labels no `docker-compose.yml`.

## Repositório

Público: https://github.com/henriquehmas-rgb/arena-sistema — **nunca commitar `infra/.env`**
(está no `.gitignore`; só `infra/.env.example` é versionado).

## Primeira implantação

```bash
ssh vps
cd /docker
gh repo clone henriquehmas-rgb/arena-sistema
cd arena-sistema/infra

# .env real — nunca commitar. Gerar segredos com openssl rand -hex.
cp .env.example .env
# editar .env: POSTGRES_PASSWORD, JWT_SECRET (openssl rand -hex 24 / -hex 32),
# FRONTEND_URL=https://reservas.arenacacerense.com.br,
# NEXT_PUBLIC_API_URL=https://api.arenacacerense.com.br/api/v1,
# PAGARME_MODE=simulado (até cadastrar as chaves reais)

docker compose up -d --build
docker exec arena-api alembic upgrade head
docker exec -e SEED_ADMIN_SENHA="$(openssl rand -hex 12)" arena-api python -m app.seed
# ↑ anote a senha impressa/gerada — é a senha do usuário admin@arenacacerense.com.br
```

### `docker-compose.override.yml`

Existe um override (`infra/docker-compose.override.yml`, versionado) que remove a
publicação de portas no host (`5432`, `6379`, `8000`, `3000`) do compose base — essas
portas são só um atalho de desenvolvimento local e colidem com outros projetos na VPS
compartilhada. O `docker compose up` já aplica os dois arquivos automaticamente (merge
padrão do Compose); não precisa passar `-f` manualmente. Postgres/Redis só ficam
acessíveis pela rede interna `app` do compose; api/web só pelo Traefik.

### DNS (Hostinger, zona `arenacacerense.com.br`)

Registros A, TTL 300:
- `reservas` → `191.96.251.71`
- `api` → `191.96.251.71`

O Traefik detecta os novos routers (labels `Host(...)` no compose) e emite os
certificados Let's Encrypt automaticamente assim que o DNS propagar — sem ação manual
adicional. Pode levar alguns minutos após a propagação.

### bcrypt/passlib

`backend/pyproject.toml` fixa `bcrypt<4.1` — versões mais novas do pacote `bcrypt`
removeram o atributo `__about__` que o `passlib` 1.7.4 (parado desde 2020) usa para
detectar a versão do backend, quebrando todo hash de senha com
`AttributeError`/`ValueError` no primeiro uso. Não remover esse pin sem trocar
`passlib` por uma alternativa mantida (ex. `pwdlib`).

## Deploy de uma atualização

```bash
ssh vps "cd /docker/arena-sistema && git pull && cd infra && docker compose up -d --build"
# se houve migração nova:
ssh vps "docker exec arena-api alembic upgrade head"
```

## Backup

`infra/backup-db.sh` — `pg_dump` diário comprimido em `infra/backups/`, rotação de 14
dias (configurável via `RETENCAO_DIAS`). Adicionar ao cron da VPS:

```bash
crontab -e
# adicionar:
30 3 * * * cd /docker/arena-sistema/infra && ./backup-db.sh >> backup.log 2>&1
```

## Smoke test pós-deploy

```bash
curl https://api.arenacacerense.com.br/api/v1/health
# {"status":"ok","db":true,"redis":true}

curl -I https://reservas.arenacacerense.com.br/
# HTTP/2 200
```

## Variáveis de ambiente sensíveis (`infra/.env`, nunca commitado)

Ver `infra/.env.example` para a lista completa e comentada. Resumo do que exige rotação
cuidadosa se vazar: `POSTGRES_PASSWORD`, `JWT_SECRET`, `PAGARME_API_KEY`,
`PAGARME_WEBHOOK_SECRET`, `SMTP_PASS`.

## Pagar.me em produção

Enquanto `PAGARME_MODE=simulado`, nenhuma chave real é necessária — pagamentos
"confirmam" sozinhos após ~5s (ver `backend/app/services/pagarme.py`). Para ativar
cobrança real:
1. Cadastrar `PAGARME_API_KEY` (chave secreta) e `PAGARME_WEBHOOK_SECRET` no `.env`.
2. Trocar `PAGARME_MODE` para `sandbox` (testes) ou `producao`.
3. Configurar o webhook `https://api.arenacacerense.com.br/api/v1/webhooks/pagarme` no
   painel da Pagar.me.
4. `docker compose up -d --build api` pra aplicar.
