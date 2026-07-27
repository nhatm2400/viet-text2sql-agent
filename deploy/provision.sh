#!/usr/bin/env bash
# viet-text2sql-agent — VPS provisioning. Idempotent: safe to re-run.
#
# NO DOCKER. Every component below is a native OS package or a single static binary managed by
# systemd. This is a hard project constraint (see docs/DECISIONS.md), and it is the reason
# Postgres comes from the PGDG apt repo (where postgresql-16-pgvector is a prebuilt package,
# no compiler needed) rather than from a container image.
#
# Target : Ubuntu 22.04 / 24.04 LTS on a small VPS (Hetzner CX22, 2 vCPU / 4 GB, is the default
#          plan; Oracle Always Free A1 is opportunistic upside only — verify capacity at signup).
# Usage  : sudo bash deploy/provision.sh
#
# THIS SCRIPT WAS NOT EXECUTED AGAINST ANY SERVER WHILE SCAFFOLDING THIS REPO.
#
# What it does NOT do, on purpose:
#   - it never writes a secret to disk; DB password and tunnel token come from the environment
#   - it never runs db/seed.py (data loading is a separate, explicit step)
#   - it never starts a Cloudflare Tunnel (see deploy/cloudflared/README.md)

set -euo pipefail

APP_USER="${APP_USER:-t2sql}"
APP_DIR="${APP_DIR:-/opt/t2sql}"
REPO_URL="${REPO_URL:-https://gitlab.com/CHANGEME/viet-text2sql-agent.git}"
PG_VERSION=16
DB_NAME="${DB_NAME:-t2sql}"
DB_APP_USER="${DB_APP_USER:-t2sql_app}"
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-8501}"

# Passwords must come from the environment. Refusing to generate a default is deliberate: a
# provisioning script that invents a password is a provisioning script that ships one.
: "${DB_APP_PASSWORD:?set DB_APP_PASSWORD before running (it is never stored in this repo)}"
: "${DB_RO_PASSWORD:?set DB_RO_PASSWORD before running (it is never stored in this repo)}"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
  echo "run as root: sudo bash deploy/provision.sh" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
log "1/8  Base packages"
# ---------------------------------------------------------------------------
apt-get update -qq
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg lsb-release git \
  python3 python3-venv python3-pip \
  debian-keyring debian-archive-keyring apt-transport-https

# ---------------------------------------------------------------------------
log "2/8  PostgreSQL ${PG_VERSION} + pgvector (PGDG apt — prebuilt, no compilation)"
# ---------------------------------------------------------------------------
if [[ ! -f /etc/apt/sources.list.d/pgdg.list ]]; then
  install -d /usr/share/postgresql-common/pgdg
  curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
  echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list
  apt-get update -qq
fi
apt-get install -y "postgresql-${PG_VERSION}" "postgresql-${PG_VERSION}-pgvector"
systemctl enable --now postgresql

# ---------------------------------------------------------------------------
log "3/8  Caddy (single static binary, automatic HTTPS — no nginx, no container)"
# ---------------------------------------------------------------------------
if ! command -v caddy >/dev/null 2>&1; then
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y caddy
fi

# ---------------------------------------------------------------------------
log "4/8  cloudflared (native .deb + systemd service; never Docker-dependent)"
# ---------------------------------------------------------------------------
if ! command -v cloudflared >/dev/null 2>&1; then
  ARCH=$(dpkg --print-architecture)
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb" \
    -o /tmp/cloudflared.deb
  dpkg -i /tmp/cloudflared.deb
  rm -f /tmp/cloudflared.deb
fi

# ---------------------------------------------------------------------------
log "5/8  Service user and application checkout"
# ---------------------------------------------------------------------------
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR"

if [[ -d "$APP_DIR/.git" ]]; then
  sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
else
  sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi

sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -e "$APP_DIR"

# ---------------------------------------------------------------------------
log "6/8  Database, extension, schema, roles, trace table"
# ---------------------------------------------------------------------------
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
  || sudo -u postgres createdb "$DB_NAME"

sudo -u postgres psql -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector"

sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='${DB_APP_USER}') THEN
    CREATE ROLE ${DB_APP_USER} LOGIN;
  END IF;
END
\$\$;
ALTER ROLE ${DB_APP_USER} PASSWORD '${DB_APP_PASSWORD}';
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_APP_USER};
SQL

sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$APP_DIR/db/schema.sql"
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$APP_DIR/db/traces.sql"
# roles.sql revokes everything from t2sql_ro and grants back SELECT on the allowlisted tables
# only; it also sets statement_timeout and default_transaction_read_only on the role.
sudo -u postgres psql -d "$DB_NAME" -v ro_password="'${DB_RO_PASSWORD}'" -f "$APP_DIR/db/roles.sql"

# ---------------------------------------------------------------------------
log "7/8  Environment file (0600, owned by the service user, never in git)"
# ---------------------------------------------------------------------------
ENV_FILE="$APP_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<ENV
OFFLINE_MODE=0
MODEL_PROVIDER=anthropic
ANTHROPIC_API_KEY=
DATABASE_URL=postgresql+psycopg://${DB_APP_USER}:${DB_APP_PASSWORD}@localhost:5432/${DB_NAME}
DATABASE_URL_RO=postgresql+psycopg://t2sql_ro:${DB_RO_PASSWORD}@localhost:5432/${DB_NAME}
MAX_ITERATIONS=6
MAX_ROWS=1000
STATEMENT_TIMEOUT_MS=5000
API_PORT=${API_PORT}
UI_PORT=${UI_PORT}
ENV
  echo "  wrote $ENV_FILE — add ANTHROPIC_API_KEY by hand"
else
  echo "  $ENV_FILE already exists, leaving it alone"
fi
chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# ---------------------------------------------------------------------------
log "8/8  systemd units and Caddy"
# ---------------------------------------------------------------------------
install -m 644 "$APP_DIR/deploy/systemd/t2sql-api.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/systemd/t2sql-ui.service"  /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile

systemctl daemon-reload
systemctl enable --now t2sql-api t2sql-ui
systemctl reload caddy || systemctl restart caddy

# Nightly pg_dump, 7-day rotation. Enough to recover a demo; explicitly NOT a production backup.
install -d -o "$APP_USER" -g "$APP_USER" /var/backups/t2sql
cat > /etc/cron.d/t2sql-backup <<CRON
0 3 * * * postgres pg_dump ${DB_NAME} | gzip > /var/backups/t2sql/${DB_NAME}-\$(date +\%F).sql.gz && find /var/backups/t2sql -name '*.sql.gz' -mtime +7 -delete
CRON

log "Done."
cat <<NEXT

  Next steps (manual, on purpose):
    1. edit ${ENV_FILE} and set ANTHROPIC_API_KEY
    2. sudo -u ${APP_USER} ${APP_DIR}/.venv/bin/python ${APP_DIR}/db/seed.py
    3. set the domain in /etc/caddy/Caddyfile, then: systemctl reload caddy
    4. set up the tunnel: see deploy/cloudflared/README.md
    5. verify:  systemctl status t2sql-api t2sql-ui
                curl -s localhost:${API_PORT}/health
NEXT
