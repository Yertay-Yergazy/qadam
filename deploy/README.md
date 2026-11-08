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
