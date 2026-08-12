#!/bin/bash
# Run on the VM, from inside the cloned repo root, after fpl_cache.db has
# been scp'd into data/ (see main deploy instructions -- the DB is
# deliberately NOT in git, it's transferred separately since it's a large,
# constantly-changing binary file that doesn't belong in version control).
set -euo pipefail

if [ ! -f data/fpl_cache.db ]; then
    echo "ERROR: data/fpl_cache.db not found -- scp it here first" >&2
    exit 1
fi

echo "== Building + starting backend =="
docker compose up -d --build

echo "== Installing Caddyfile =="
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy || sudo systemctl restart caddy

echo "== Done. Check: =="
echo "  docker compose ps"
echo "  docker compose logs -f backend"
echo "  curl -s https://<your-sslip-hostname>/api/health"
