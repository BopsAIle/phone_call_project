#!/usr/bin/env bash
# Bật Docker runtime nếu chưa chạy, rồi docker compose up (Postgres, Redis, và ngrok nếu có token).
set -euo pipefail
cd "$(dirname "$0")/.."

# Docker Desktop để credential helper ở đây; nếu chưa "Install CLI tools" thì docker pull sẽ lỗi.
[ -d /Applications/Docker.app/Contents/Resources/bin ] && export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"

if ! docker info >/dev/null 2>&1; then
  if [ -d /Applications/Docker.app ] || [ -d "$HOME/Applications/Docker.app" ]; then
    echo ">> Docker daemon chưa chạy, đang mở Docker Desktop..."
    open -a Docker
  elif command -v colima >/dev/null; then
    echo ">> Docker daemon chưa chạy, đang colima start..."
    colima start
  elif [ -d /Applications/OrbStack.app ]; then
    echo ">> Docker daemon chưa chạy, đang mở OrbStack..."
    open -a OrbStack
  else
    echo "!! Không tìm thấy Docker runtime. Cài Docker Desktop, hoặc: brew install colima docker docker-compose"
    exit 1
  fi
  for i in $(seq 1 60); do
    docker info >/dev/null 2>&1 && break
    sleep 2
    [ "$i" = 60 ] && { echo "!! Docker không lên sau 120s"; exit 1; }
  done
fi

# Biến cho compose: .env ở root (ngrok), phần còn lại suy ra từ AI/.env
if [ -f .env ]; then set -a; . ./.env; set +a; fi
export AI_BRIDGE_PORT="${AI_BRIDGE_PORT:-$(grep -E '^AI_BRIDGE_PORT=' AI/.env 2>/dev/null | cut -d= -f2)}"
export AI_BRIDGE_PORT="${AI_BRIDGE_PORT:-8071}"
export NGROK_DOMAIN="${NGROK_DOMAIN:-$(grep -E '^TELNYX_STREAM_URL=' AI/.env 2>/dev/null | sed -E 's#^[^=]*=wss?://([^/]+).*#\1#')}"

profile=()
if [ -n "${NGROK_AUTHTOKEN:-}" ] && [ -n "$NGROK_DOMAIN" ]; then
  profile=(--profile ngrok)
  echo ">> docker compose up -d (postgres:5433, redis:6379, ngrok -> https://$NGROK_DOMAIN)"
else
  echo ">> docker compose up -d (postgres:5433, redis:6379)"
  echo ">> ngrok tắt: điền NGROK_AUTHTOKEN (và NGROK_DOMAIN nếu AI/.env chưa có TELNYX_STREAM_URL) vào file .env ở root"
fi
# ${profile[@]+...}: bash 3.2 của macOS coi mảng rỗng là unbound khi set -u
docker compose ${profile[@]+"${profile[@]}"} up -d --wait --wait-timeout 90
docker compose ${profile[@]+"${profile[@]}"} ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}'
