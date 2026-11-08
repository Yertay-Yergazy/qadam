#!/usr/bin/env bash
# Forced command for the CD key (authorized_keys: restrict,command="...deploy.sh"). Only two operations exist:
#   load            - stdin: gzipped `docker save` tarball -> docker load
#   deploy <tag>    - switch IMAGE_TAG in .env, recreate the qadam project, health-check, roll back on failure
set -uo pipefail
cd /home/ubuntu/qadam
read -r cmd arg <<<"${SSH_ORIGINAL_COMMAND:-}"
case "$cmd" in
  load)
    gunzip | docker load ;;
  deploy)
    [[ "$arg" =~ ^main-[0-9a-f]{7,40}$ ]] || { echo "bad tag" >&2; exit 2; }
    for img in qadam-backend qadam-web; do
      docker image inspect "$img:$arg" >/dev/null 2>&1 || { echo "image $img:$arg not loaded" >&2; exit 2; }
    done
    PREV=$(grep '^IMAGE_TAG=' .env | cut -d= -f2)
    setTag() { sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$1/" .env; docker compose -p qadam up -d; }
    healthy() { for _ in $(seq 1 20); do curl -fs localhost:8081/api/health >/dev/null && return 0; sleep 3; done; return 1; }
    setTag "$arg"
    if healthy; then echo "Deployed $arg (was $PREV)"; exit 0; fi
    echo "Health check failed, rolling back to $PREV" >&2
    setTag "$PREV"; healthy || echo "Rollback also unhealthy!" >&2
    exit 1 ;;
  *)
    echo "denied" >&2; exit 126 ;;
esac
