#!/usr/bin/env bash
# Kiểm tra nhanh các endpoint như mục "Kiểm tra trước khi gọi" trong AI/RUNBOOK.md
cd "$(dirname "$0")/.."

probe() { # name url
  local code
  code=$(curl -s -o /tmp/.probe -w '%{http_code}' --max-time 8 "$2" || true)
  if [ "$code" = 200 ]; then printf '  OK   %-8s %s\n' "$1" "$2"; grep -q '^{' /tmp/.probe && { head -c 300 /tmp/.probe; echo; }
  else printf '  FAIL %-8s %s (http %s)\n' "$1" "$2" "${code:-000}"; fi
}
ai_port=${AI_BRIDGE_PORT:-$(grep -E '^AI_BRIDGE_PORT=' AI/.env 2>/dev/null | cut -d= -f2)}
probe BE    http://127.0.0.1:3001/api-docs
probe FE    http://localhost:3000/
probe AI    "http://127.0.0.1:${ai_port:-8080}/health"

# ngrok: hỏi inspector trong container lấy public URL rồi gọi /health qua đó
public=$(curl -s --max-time 3 http://127.0.0.1:4040/api/tunnels 2>/dev/null | sed -E 's/.*"public_url":"(https:[^"]+)".*/\1/')
if [ -n "$public" ] && [ "${public#https://}" != "$public" ]; then
  probe ngrok "$public/health"
else
  echo "  --   ngrok    không chạy (container aibridge-ngrok chưa bật, xem .env ở root)"
fi
