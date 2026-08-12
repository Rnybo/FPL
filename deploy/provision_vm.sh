#!/bin/bash
# One-time VM setup: Docker + Caddy, run once on a fresh Oracle Cloud
# Always Free Ubuntu ARM instance. Idempotent-ish (safe to re-run).
set -euo pipefail

echo "== Installing Docker =="
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
fi

echo "== Installing Docker Compose plugin =="
sudo apt-get update -y
sudo apt-get install -y docker-compose-plugin

echo "== Installing Caddy =="
if ! command -v caddy &>/dev/null; then
    sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
        sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | \
        sudo tee /etc/apt/sources.list.d/caddy-stable.list
    sudo apt-get update -y
    sudo apt-get install -y caddy
fi

echo "== Done. Next: copy the repo + Caddyfile, then run deploy/deploy.sh =="
