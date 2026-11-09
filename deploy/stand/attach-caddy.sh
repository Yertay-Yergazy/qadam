#!/usr/bin/env bash
# Attaches Qadam to the host's Caddy (the Digitron dev VM). Idempotent: run again after every Digitron deploy,
# because that deploy overwrites its Caddyfile and reloads Caddy.
#   qadam-kbtu.asia    -> qadam-web   (app + /api)
#   lk.qadam-kbtu.asia -> qadam-livekit (wss signalling)
set -euo pipefail
CF=$HOME/digitron/deploy/Caddyfile
C=digitron-prod-caddy-1

docker network connect qadam_default "$C" 2>/dev/null || true

add_block() {  # $1 = marker name, stdin = block body
  local mark="# --- $1 (attach-caddy.sh) ---"
  grep -qF "$mark" "$CF" && return 0
  [ -n "${BACKED:-}" ] || { cp "$CF" "$CF.bak.$(date +%Y%m%d%H%M%S)"; BACKED=1; }
  { printf '\n%s\n' "$mark"; cat; printf '# --- /%s ---\n' "$1"; } >> "$CF"
}

add_block qadam <<'BLOCK'
qadam-kbtu.asia {
	encode zstd gzip
	reverse_proxy qadam-qadam-web-1:80
}
BLOCK

add_block qadam-livekit <<'BLOCK'
lk.qadam-kbtu.asia {
	reverse_proxy qadam-qadam-livekit-1:7880
}
BLOCK

if ! docker exec "$C" caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
  echo "Caddyfile не проходит проверку, откатываю блоки qadam" >&2
  python3 - "$CF" <<'PY'
import sys,re
p=sys.argv[1]; s=open(p).read()
s=re.sub(r"\n# --- qadam(?:-livekit)? \(attach-caddy.sh\) ---.*?# --- /qadam(?:-livekit)? ---\n","",s,flags=re.S)
open(p,"w").write(s)
PY
  exit 1
fi
docker exec "$C" caddy reload --config /etc/caddy/Caddyfile --address localhost:2019
echo OK
