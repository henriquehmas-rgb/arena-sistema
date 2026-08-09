#!/usr/bin/env bash
# Backup diário do Postgres do arena-sistema, com rotação de 14 dias.
#
# Uso: rodar via cron na VPS, no diretório infra/ deste repo (usa docker
# compose para achar o container `arena-postgres` e as credenciais do .env).
#
# Exemplo de linha de cron (rodar todo dia às 03:30, log em backup.log):
#   30 3 * * * cd /docker/arena-sistema/infra && ./backup-db.sh >> backup.log 2>&1
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

BACKUP_DIR="${BACKUP_DIR:-$DIR/backups}"
RETENCAO_DIAS="${RETENCAO_DIAS:-14}"
DATA="$(date +%Y-%m-%d_%H%M%S)"
ARQUIVO="$BACKUP_DIR/arena_${DATA}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date -Iseconds)] Iniciando backup em $ARQUIVO"

docker compose exec -T postgres pg_dump -U arena -d arena | gzip > "$ARQUIVO"

TAMANHO="$(du -h "$ARQUIVO" | cut -f1)"
echo "[$(date -Iseconds)] Backup concluído ($TAMANHO)"

# Rotação: remove backups mais antigos que RETENCAO_DIAS dias.
find "$BACKUP_DIR" -name 'arena_*.sql.gz' -mtime "+${RETENCAO_DIAS}" -print -delete

echo "[$(date -Iseconds)] Rotação concluída (retenção: ${RETENCAO_DIAS} dias)"
