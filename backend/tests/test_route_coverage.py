"""Tech-debt guard: every route of the app is walked automatically, no hand-maintained list.

A new endpoint that forgets `Depends(require(...))` / `current_user` fails this test.
"""
import re

import pytest
from app.main import app

# Routes that are intentionally reachable without a login. Anything else MUST answer 401.
PUBLIC = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/refresh"),  # authenticated by the httpOnly refresh cookie, not the bearer token
    ("POST", "/api/auth/logout"),  # idempotent, only clears the cookie
    ("POST", "/api/livekit/webhook"),  # authenticated by LiveKit's signed JWT (see test below)
}
DOCS = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
METHODS = {"get", "post", "put", "patch", "delete"}


def _all_routes() -> list[tuple[str, str]]:
    paths = app.openapi()["paths"]
    return sorted((m.upper(), p) for p, ops in paths.items() for m in ops if m in METHODS)


ROUTES = _all_routes()


def test_route_discovery_is_not_empty():
    assert len(ROUTES) >= 20, f"only {len(ROUTES)} routes found - did discovery break?"


def test_public_allowlist_has_no_stale_entries():
    assert PUBLIC <= set(ROUTES), PUBLIC - set(ROUTES)


@pytest.mark.parametrize("method,path", [r for r in ROUTES if r not in PUBLIC and r[1] not in DOCS])
def test_every_route_requires_login(anon, method, path):
    url = re.sub(r"\{[^}]+\}", "1", path)
    r = anon.request(method, url, json={} if method != "GET" else None)
    assert r.status_code == 401, f"{method} {path} answered {r.status_code} without credentials"


def test_webhook_rejects_unsigned_calls(anon):
    assert anon.post("/api/livekit/webhook", content="{}").status_code == 401
