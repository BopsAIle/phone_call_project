#!/usr/bin/env bash
# Dừng các service do make dev khởi chạy. Chỉ giết tiến trình của repo này,
# không đụng tới tiến trình khác dù đang chiếm cùng cổng.
cd "$(dirname "$0")/.."
ROOT=$(pwd)
PIDFILE="$ROOT/.dev.pids"

kill_tree() {
  local pid=$1
  for c in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$c"; done
  kill -TERM "$pid" 2>/dev/null
}

if [ -f "$PIDFILE" ]; then
  for p in $(cat "$PIDFILE"); do
    ps -p "$p" >/dev/null 2>&1 && { echo ">> dừng pid $p ($(ps -p "$p" -o command= | cut -c1-60))"; kill_tree "$p"; }
  done
  rm -f "$PIDFILE"
fi

# Dọn sót: chỉ tiến trình có đường dẫn repo này trong command line
for pid in $(pgrep -f "$ROOT/(BE|FE|AI)/" 2>/dev/null); do
  echo ">> dừng tiến trình sót pid $pid ($(ps -p "$pid" -o command= | cut -c1-60))"
  kill_tree "$pid"
done

# Cảnh báo nếu cổng vẫn bận bởi tiến trình lạ
for p in 3000 3001 8080; do
  pid=$(lsof -nP -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null | head -1)
  [ -n "$pid" ] && echo "!! cổng $p vẫn bận bởi pid $pid (không thuộc repo, không giết): $(ps -p "$pid" -o command= | cut -c1-60)"
done
echo ">> đã dừng service của repo"
