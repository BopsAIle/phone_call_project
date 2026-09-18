#!/usr/bin/env bash
# Chạy BE, FE, ngrok, AI cùng lúc trong một terminal, log có prefix màu.
# Ctrl+C dừng tất cả. Giả định Docker đã lên (make infra) và deps đã cài (make deps).
# PID các service ghi vào .dev.pids để `make stop` dọn được kể cả khi terminal đã đóng.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
PIDFILE="$ROOT/.dev.pids"

PIDS=()
kill_tree() { # giết con trước rồi tới cha
  local pid=$1
  for c in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$c"; done
  kill -TERM "$pid" 2>/dev/null
}
cleanup() {
  trap - INT TERM EXIT
  echo; echo ">> đang dừng các service..."
  for pid in "${PIDS[@]}"; do kill_tree "$pid"; done
  sleep 1
  for pid in "${PIDS[@]}"; do kill -KILL "$pid" 2>/dev/null; done
  rm -f "$PIDFILE"
  echo ">> đã dừng. Docker vẫn chạy nền; tắt bằng: make stop"
  exit 0
}
trap cleanup INT TERM EXIT

# run <TAG> <màu ANSI> <thư mục> <lệnh...>
# Dùng process substitution để $! là PID thật của service (không phải của bộ lọc log).
run() {
  local tag=$1 color=$2 dir=$3; shift 3
  ( cd "$dir" && exec "$@" ) > >(while IFS= read -r line; do
      printf '\033[%sm[%-5s]\033[0m %s\n' "$color" "$tag" "$line"
    done) 2>&1 &
  PIDS+=($!)
  echo "$!" >> "$PIDFILE"
}

wait_port() { # host port timeout_s label
  local i
  for ((i=0; i<$3; i++)); do
    (exec 3<>/dev/tcp/$1/$2) 2>/dev/null && return 0
    sleep 1
  done
  echo "!! $4 không lên sau $3s (cổng $2)"; return 1
}

# Nếu lần trước còn sót tiến trình thì dọn trước
[ -f "$PIDFILE" ] && { echo ">> dọn tiến trình sót từ lần chạy trước"; for p in $(cat "$PIDFILE"); do kill_tree "$p"; done; sleep 1; }
: > "$PIDFILE"

# Cổng phải rảnh trước khi chạy, tránh nest/vite/uvicorn tự nhảy sang cổng khác hoặc chết im.
AI_PORT=${AI_BRIDGE_PORT:-$(grep -E '^AI_BRIDGE_PORT=' AI/.env 2>/dev/null | cut -d= -f2)}
AI_PORT=${AI_PORT:-8071}
busy=0
# Cổng FE đọc từ vite.config.ts để không lệch khi đổi cổng (mặc định 3070)
FE_PORT=${FE_PORT:-$(grep -oE 'port:[[:space:]]*[0-9]+' FE/vite.config.ts 2>/dev/null | head -1 | grep -oE '[0-9]+')}
FE_PORT=${FE_PORT:-3070}
# Cổng BE đọc từ BE/.env để không lệch khi đổi cổng (mặc định 8070)
BE_PORT=${BE_PORT:-$(grep -E '^PORT=' BE/.env 2>/dev/null | cut -d= -f2)}
BE_PORT=${BE_PORT:-8070}
for p in "$FE_PORT" "$BE_PORT" "$AI_PORT"; do
  pid=$(lsof -nP -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null | head -1)
  if [ -n "$pid" ]; then
    echo "!! cổng $p đang bị chiếm bởi pid $pid: $(ps -p "$pid" -o command= | cut -c1-80)"
    busy=1
  fi
done
[ "$busy" = 1 ] && { echo "!! Dừng tiến trình đó rồi chạy lại make dev (hoặc đổi AI_BRIDGE_PORT trong AI/.env)."; rm -f "$PIDFILE"; trap - EXIT; exit 1; }

run BE  "1;34" BE npm run start:dev
run FE  "1;35" FE npm run dev

# ngrok chạy trong Docker (docker-compose.yml, profile ngrok) — make infra đã lo.
NGROK_UP=$(docker compose --profile ngrok ps --status running --format '{{.Name}}' 2>/dev/null | grep -c aibridge-ngrok || true)
NGROK_DOMAIN=$(grep -E '^NGROK_DOMAIN=' .env 2>/dev/null | cut -d= -f2)
NGROK_DOMAIN=${NGROK_DOMAIN:-$(grep -E '^TELNYX_STREAM_URL=' AI/.env 2>/dev/null | sed -E 's#^[^=]*=wss?://([^/]+).*#\1#')}

# AI chạy SAU BE để sync catalog ngay lúc khởi động (AI/RUNBOOK.md)
wait_port 127.0.0.1 "$BE_PORT" 90 "NestJS BE" || true
run AI  "1;32" AI "$ROOT/AI/.venv/bin/python" app.py

echo
echo ">> Dashboard  http://localhost:$FE_PORT"
echo ">> Swagger    http://localhost:$BE_PORT/api-docs"
echo ">> AI health  http://127.0.0.1:$AI_PORT/health"
if [ "$NGROK_UP" = 1 ]; then
  echo ">> ngrok      https://$NGROK_DOMAIN/health   (inspector: http://localhost:4040)"
else
  echo ">> ngrok      TẮT — điền NGROK_AUTHTOKEN vào .env ở root rồi chạy lại make dev"
fi
echo ">> Ctrl+C để dừng tất cả"
wait
