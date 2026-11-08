# Deploy to https://qadam-kbtu.asia

1. **DNS** (A records to the server's public IP): `qadam-kbtu.asia` and `lk.qadam-kbtu.asia`.
2. **Firewall:** open 80/tcp, 443/tcp, 7881/tcp, 7882/udp.
3. On the server (Docker + compose installed):
   ```bash
   git clone <repo> && cd qadam
   mkdir -p data/recordings && chmod 777 data/recordings
   cp deploy/.env.prod.example .env      # fill in the secrets
   docker compose -f docker-compose.prod.yml up -d --build
   ```
4. Open https://qadam-kbtu.asia and log in as `ADMIN_EMAIL`. Add the team on **Команда**.
5. Smoke test: create a meeting → paste a transcript → draft appears in **Проверка** → approve → task on **Доска**
   with the «Со встречи» badge. Screenshot the login page with the padlock for the report (DoD3).

Backup: `docker run --rm -v qadam_qadam-db:/d -v $PWD:/b alpine tar czf /b/qadam-db-$(date +%F).tgz -C /d .`
Rollback: restore the archive into the volume and `docker compose -f docker-compose.prod.yml up -d`.

## CD to the shared dev VM (`.github/workflows/deploy.yml`)
After CI is green on `main` the workflow builds the images on the runner, ships them over SSH, restarts the
`qadam` compose project and rolls back if `/api/health` does not come up. Files for this stand: `deploy/stand/`.
Repository secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (a dedicated key, never a personal one),
`DEPLOY_KNOWN_HOSTS` (output of `ssh-keyscan -t ed25519 <host>`). Run manually: Actions → Deploy → Run workflow.
The CD key is restricted in the server's `authorized_keys` (`restrict,command="/home/ubuntu/qadam/deploy.sh"`): it can
only run `load` and `deploy <tag>` (`deploy/stand/deploy.sh`), cannot read `~/qadam/.env` and cannot open a shell.
The compose file lives on the server and is NOT uploaded by CD: when it changes, copy `deploy/stand/docker-compose.yml`
to `~/qadam/` by hand, and add new variables to `~/qadam/.env` by hand.
