#!/usr/bin/env bash
# Kiểm tra Telnyx -> AI bridge theo tung lop.
#
#   ./scripts/telnyx-test.sh                                  # CHI kiem tra (khong ton tien)
#   ./scripts/telnyx-test.sh --dial +84xxxxxxxxx              # DAT CUOC GOI THAT (ton tien, do chuong)
#   ./scripts/telnyx-test.sh --dial +84xxxxxxxxx --webhook https://abc.ngrok-free.app/telnyx/webhook
#
# Mac dinh test dung host ma Telnyx dang cau hinh (webhook_event_url), tuc la test dung
# duong webhook that se di. Khong can sua Call Control App tren portal.
set -uo pipefail
cd "$(dirname "$0")/.."

DIAL=""
WEBHOOK_OVERRIDE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dial)      DIAL="${2:-}"; shift 2 2>/dev/null || shift ;;
    --dial=*)    DIAL="${1#--dial=}"; shift ;;
    --webhook)   WEBHOOK_OVERRIDE="${2:-}"; shift 2 2>/dev/null || shift ;;
    --webhook=*) WEBHOOK_OVERRIDE="${1#--webhook=}"; shift ;;
    -h|--help)   sed -n '2,9p' "$0"; exit 0 ;;
    *)           echo "tham so khong hop le: $1" >&2; exit 2 ;;
  esac
done

AI_ENV=AI/.env
getenv() { grep -E "^$1=" "$AI_ENV" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r'; }
API=https://api.telnyx.com/v2
ok()   { printf '  \033[1;32mOK  \033[0m %s\n' "$1"; }
bad()  { printf '  \033[1;31mFAIL\033[0m %s\n' "$1"; }
warn() { printf '  \033[1;33mWARN\033[0m %s\n' "$1"; }
info() { printf '  --   %s\n' "$1"; }
# doc vai cot ngan cach bang TAB tu json (ten app co the chua dau cach)
jsoncols() { python3 - "$@" <<'PY'
import json,sys
path, kind, *keys = sys.argv[1:]
try:
    rows = (json.load(open(path)).get("data") or [])
except Exception:
    rows = []
r = rows[0] if rows else {}
if kind == "number":
    r = next((x for x in rows if x.get("status") == "active"), r)
print("\t".join(str(r.get(k) or "") for k in keys))
PY
}

KEY=$(getenv TELNYX_API_KEY)
AI_PORT=$(getenv AI_BRIDGE_PORT); AI_PORT=${AI_PORT:-8071}
BE_PORT=$(grep -E '^PORT=' BE/.env 2>/dev/null | cut -d= -f2); BE_PORT=${BE_PORT:-8070}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "==============================================================="
echo " Telnyx -> AI bridge | AI local :$AI_PORT | BE local :$BE_PORT"
echo "==============================================================="

# [1] API key
echo "[1] Telnyx API key"
code=$(curl -s -o "$TMP/who" -w '%{http_code}' --max-time 20 -H "Authorization: Bearer $KEY" "$API/whoami")
[ "$code" = "200" ] && ok "GET /whoami -> 200" || bad "GET /whoami -> $code (key sai/het han?)"

# [2] So dien thoai + connection
echo "[2] So dang so huu"
curl -s --max-time 20 -H "Authorization: Bearer $KEY" "$API/phone_numbers?page%5Bsize%5D=20" -o "$TMP/num"
IFS=$'\t' read -r FROM_NUM CONN_ID <<<"$(jsoncols "$TMP/num" number phone_number connection_id)"
if [ -n "$FROM_NUM" ]; then ok "so $FROM_NUM | connection_id ${CONN_ID:-?}"
else bad "khong lay duoc so nao"; fi

# [3] Webhook ma Telnyx dang tro toi  (day la dich thuc te)
echo "[3] Call Control App -> webhook_event_url"
curl -s --max-time 20 -H "Authorization: Bearer $KEY" "$API/call_control_applications?page%5Bsize%5D=20" -o "$TMP/app"
IFS=$'\t' read -r APP_NAME APP_HOOK APP_VER <<<"$(jsoncols "$TMP/app" app application_name webhook_event_url webhook_api_version)"
info "app: ${APP_NAME:-?} | api version: ${APP_VER:-?}"
info "webhook_event_url: ${APP_HOOK:-?}"
if [ -n "$WEBHOOK_OVERRIDE" ]; then
  info "lan nay se goi voi webhook override: $WEBHOOK_OVERRIDE"
  TEST_HOOK="$WEBHOOK_OVERRIDE"
else
  TEST_HOOK="$APP_HOOK"
fi
HOOK_BASE=$(printf '%s' "$TEST_HOOK" | sed -E 's#^(https?://[^/]+).*#\1#')
case "$HOOK_BASE" in
  http://*|https://*) ok "host se test: $HOOK_BASE" ;;
  *) HOOK_BASE=""; bad "khong xac dinh duoc host webhook (gia tri: '$TEST_HOOK')" ;;
esac

# [4] AI local
echo "[4] AI bridge tai may (127.0.0.1:$AI_PORT)"
code=$(curl -s -o "$TMP/h" -w '%{http_code}' --max-time 5 "http://127.0.0.1:$AI_PORT/health")
if [ "$code" = "200" ]; then ok "GET /health -> 200 $(grep -o '"ready":[a-z]*' "$TMP/h" | head -1)"
else bad "GET /health -> ${code:-000} (app.py chua chay?)"; fi

# [5] BE local
echo "[5] NestJS BE tai may (127.0.0.1:$BE_PORT)"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$BE_PORT/api-docs")
[ "$code" = "200" ] && ok "GET /api-docs -> 200" || bad "GET /api-docs -> ${code:-000}"

# [6] Duong cong khai - dung dich Telnyx se POST toi
echo "[6] Duong cong khai ma Telnyx se goi: ${HOOK_BASE:-?}"
if [ -n "$HOOK_BASE" ]; then
  code=$(curl -s -o "$TMP/hp" -w '%{http_code}' --max-time 20 "$HOOK_BASE/health")
  if [ "$code" = "200" ] && grep -q '"status":"ok"' "$TMP/hp"; then
    ok "GET $HOOK_BASE/health -> 200 (AI bridge tra loi dung)"
  elif [ "$code" = "404" ]; then
    bad "GET $HOOK_BASE/health -> 404: host nay KHONG phai AI bridge (thuong la BE NestJS dang chiem domain)"
    info "body: $(head -c 130 "$TMP/hp" | tr -d '\n')"
  elif [ "$code" = "502" ]; then
    bad "GET -> 502: reverse proxy song nhung khong toi duoc AI bridge (AI_BRIDGE_HOST phai la 0.0.0.0)"
  else
    bad "GET $HOOK_BASE/health -> ${code:-000}"
  fi

  code=$(curl -s -o "$TMP/wp" -w '%{http_code}' --max-time 20 -X POST -H 'Content-Type: application/json' \
        -d '{"data":{"event_type":"call.initiated","payload":{"direction":"incoming"}}}' "$HOOK_BASE/telnyx/webhook")
  if [ "$code" = "401" ]; then ok "POST /telnyx/webhook khong ky -> 401 (route song, chu ky duoc kiem)"
  elif [ "$code" = "404" ]; then bad "POST /telnyx/webhook -> 404 (AI bridge khong duoc phoi ra host nay)"
  else bad "POST /telnyx/webhook -> ${code:-000} (mong doi 401)"; fi

  # WS bat buoc HTTP/1.1: qua Cloudflare neu de curl tu dam phan se ra HTTP/2
  # va handshake Upgrade bi bo qua -> 404 gia (khong phai loi that).
  code=$(curl -s --http1.1 -o /dev/null -w '%{http_code}' --max-time 20 \
        -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
        -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' "$HOOK_BASE/telnyx/media?token=sai")
  if [ "$code" = "403" ] || [ "$code" = "401" ]; then ok "WS /telnyx/media -> $code (route song qua TLS/proxy)"
  elif [ "$code" = "101" ]; then ok "WS /telnyx/media -> 101 (handshake thanh cong?)"
  elif [ "$code" = "404" ]; then bad "WS /telnyx/media -> 404 (proxy khong forward duoc WebSocket)"
  else warn "WS /telnyx/media -> ${code:-000} (ky vong 403 khi token sai)"; fi
else
  bad "khong co webhook URL de test"
fi

# [7] Dat cuoc goi that (tuy chon)
echo "[7] Dat cuoc goi that"
if [ -z "$DIAL" ]; then
  info "bo qua. Them --dial +84xxxxxxxxx de chay (TON TIEN, do chuong so do)"
elif [ -z "$FROM_NUM" ] || [ -z "$CONN_ID" ] || [ -z "$HOOK_BASE" ]; then
  bad "thieu so / connection_id / webhook URL"
else
  HOOK="${WEBHOOK_OVERRIDE:-$APP_HOOK}"
  info "goi $FROM_NUM -> $DIAL | webhook: $HOOK"
  code=$(curl -s -o "$TMP/call" -w '%{http_code}' --max-time 25 -X POST "$API/calls" \
    -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
    -d "{\"connection_id\":\"$CONN_ID\",\"from\":\"$FROM_NUM\",\"to\":\"$DIAL\",\"webhook_url\":\"$HOOK\",\"webhook_url_method\":\"POST\"}")
  if [ "$code" = "200" ] || [ "$code" = "201" ]; then
    ok "Telnyx da dat cuoc goi -> $code"
    python3 - "$TMP/call" <<'PY'
import json,sys
d=(json.load(open(sys.argv[1])).get("data") or {})
print("       call_control_id:", d.get("call_control_id"))
print("       call_leg_id    :", d.get("call_leg_id"))
PY
    info "xem log AI bridge: phai co 'call.initiated' -> 'call.answered ... starting stream' -> 'WS /telnyx/media accepted'"
    info "ngat may: POST $API/calls/<call_control_id>/actions/hangup"
  else
    bad "Telnyx tu choi -> $code"; head -c 300 "$TMP/call"; echo
  fi
fi
echo "==============================================================="
