#!/bin/sh
set -e

echo "Aguardando o banco de dados..."
python - <<'PY'
import sys
import time

import psycopg

for tentativa in range(60):
    try:
        psycopg.connect(
            host=__import__("os").environ.get("POSTGRES_HOST", "db"),
            dbname=__import__("os").environ.get("POSTGRES_DB", "volix"),
            user=__import__("os").environ.get("POSTGRES_USER", "volix"),
            password=__import__("os").environ.get("POSTGRES_PASSWORD", "volix"),
            connect_timeout=3,
        ).close()
        sys.exit(0)
    except Exception:
        time.sleep(1)
print("Banco de dados indisponível após 60s", file=sys.stderr)
sys.exit(1)
PY

python manage.py migrate --noinput

exec "$@"