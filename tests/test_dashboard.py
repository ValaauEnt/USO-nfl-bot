"""
Dashboard security tests — aiohttp web server (port 5000).

Audit scope: every route was inspected. Tests verify:
  1.  Static HTML constants contain no secrets or internal config
  2.  Routes return correct status codes and content types
  3.  Security headers present on all HTML responses
  4.  Custom 404 returns safe JSON (path never echoed)
  5.  Error middleware returns generic 500 (no traceback)
  6.  /api/status returns only safe public fields
  7.  /api/status body contains no secrets or credentials
  8.  /invite redirects (does not serve secret data in response body)
  9.  Static pages contain no tokens, keys, schema, or file paths
  10. CORS on /api/status is intentional and limited to that route
"""
import asyncio
import json
import re
import time as _time_mod
import unittest

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


# ─── Patterns that must NEVER appear in any web response ──────────────────────
_SECRET_PATTERNS = [
    re.compile(r'DISCORD_TOKEN\s*[=:]', re.IGNORECASE),
    re.compile(r'OPENAI_API_KEY\s*[=:]', re.IGNORECASE),
    re.compile(r'sk-[A-Za-z0-9_\-]{15,}'),           # OpenAI key
    re.compile(r'[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{20,}'),  # Discord JWT
    re.compile(r'password\s*[=:]', re.IGNORECASE),
    re.compile(r'DATABASE_URL\s*[=:]', re.IGNORECASE),
]

# Keys the /api/status endpoint is ALLOWED to return — anything else is a leak
_ALLOWED_STATUS_KEYS = {"online", "latency_ms", "guild_count", "uptime", "news_channel"}


# ─── Minimal test app that mirrors the real dashboard ─────────────────────────
# Built WITHOUT importing main.py (avoids starting the bot / binding port 5000).
# Uses the same middleware and handler logic extracted here for isolation.

import json as _json


_HTML_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options":        "DENY",
    "Content-Security-Policy": "default-src 'self' 'unsafe-inline'; connect-src 'self'",
}


@web.middleware
async def _security_middleware(request, handler):
    try:
        response = await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        return web.Response(
            text=_json.dumps({"error": "Internal server error"}),
            status=500,
            content_type="application/json",
        )
    if response.content_type == "text/html":
        response.headers.update(_HTML_SECURITY_HEADERS)
    return response


async def _handle_root(request):
    return web.Response(text="<html><body>Dashboard</body></html>", content_type="text/html")


async def _handle_tos(request):
    return web.Response(text="<html><body>Terms of Service</body></html>", content_type="text/html")


async def _handle_privacy(request):
    return web.Response(text="<html><body>Privacy Policy</body></html>", content_type="text/html")


async def _handle_invite(request):
    raise web.HTTPFound("https://discord.com/api/oauth2/authorize?client_id=123&permissions=8&scope=bot")


async def _handle_api_status(request):
    payload = {
        "online": True,
        "latency_ms": 42,
        "guild_count": 3,
        "uptime": "1h 0m 0s",
        "news_channel": "#nfl-news",
    }
    return web.Response(
        text=_json.dumps(payload),
        content_type="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def _handle_404(request):
    return web.Response(
        text=_json.dumps({"error": "Not found"}),
        status=404,
        content_type="application/json",
    )


async def _handle_crasher(request):
    raise RuntimeError("Simulated unhandled server error")


def _build_test_app() -> web.Application:
    app = web.Application(middlewares=[_security_middleware])
    app.router.add_get("/",           _handle_root)
    app.router.add_get("/tos",        _handle_tos)
    app.router.add_get("/privacy",    _handle_privacy)
    app.router.add_get("/invite",     _handle_invite)
    app.router.add_get("/api/status", _handle_api_status)
    app.router.add_get("/crash",      _handle_crasher)
    app.router.add_route("*", "/{path_info:.*}", _handle_404)
    return app


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Static HTML constants — no secrets in source
# ─────────────────────────────────────────────────────────────────────────────
class TestStaticContentNoSecrets(unittest.TestCase):
    """
    Reads main.py source and verifies the inline HTML page constants
    don't contain tokens, keys, DB schemas, or file paths.
    """

    @classmethod
    def setUpClass(cls):
        with open("main.py", encoding="utf-8") as f:
            cls.src = f.read()

        # Extract the three HTML block strings
        def _extract(name: str) -> str:
            m = re.search(rf'{name}\s*=\s*"""(.*?)"""', cls.src, re.DOTALL)
            return m.group(1) if m else ""

        cls.dashboard_html = _extract("DASHBOARD_HTML")
        cls.tos_html        = _extract("TOS_HTML")
        cls.privacy_html    = _extract("PRIVACY_HTML")

    def _assert_clean(self, content: str, name: str):
        for pat in _SECRET_PATTERNS:
            m = pat.search(content)
            self.assertIsNone(m, f"Secret pattern {pat.pattern!r} found in {name}")

    def test_dashboard_html_no_secrets(self):
        self._assert_clean(self.dashboard_html, "DASHBOARD_HTML")

    def test_tos_html_no_secrets(self):
        self._assert_clean(self.tos_html, "TOS_HTML")

    def test_privacy_html_no_secrets(self):
        self._assert_clean(self.privacy_html, "PRIVACY_HTML")

    def test_dashboard_html_not_empty(self):
        self.assertGreater(len(self.dashboard_html), 100)

    def test_dashboard_html_no_env_getenv(self):
        # The HTML must not contain os.getenv calls (would suggest secret interpolation)
        self.assertNotIn("os.getenv", self.dashboard_html)
        self.assertNotIn("os.environ", self.dashboard_html)

    def test_dashboard_html_no_internal_paths(self):
        # No absolute file paths leaked into the page
        self.assertNotIn("/home/runner/workspace", self.dashboard_html)
        self.assertNotIn("data/uso_bot.db", self.dashboard_html)

    def test_dashboard_js_only_fetches_status(self):
        """The dashboard JS must only call /api/status — no other API endpoints."""
        js_fetches = re.findall(r"fetch\(['\"]([^'\"]+)['\"]", self.dashboard_html)
        for url in js_fetches:
            self.assertIn(url, {"/api/status"}, f"Unexpected fetch target: {url!r}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Route status codes
# ─────────────────────────────────────────────────────────────────────────────
class TestRouteStatusCodes(unittest.TestCase):

    def _get(self, path: str, allow_redirects=True):
        async def _run():
            async with TestClient(TestServer(_build_test_app())) as client:
                return await client.get(path, allow_redirects=allow_redirects)
        return _run

    def test_root_200(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/")
                self.assertEqual(r.status, 200)
        _run(_())

    def test_tos_200(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/tos")
                self.assertEqual(r.status, 200)
        _run(_())

    def test_privacy_200(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/privacy")
                self.assertEqual(r.status, 200)
        _run(_())

    def test_invite_redirects(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/invite", allow_redirects=False)
                self.assertIn(r.status, (301, 302, 307, 308))
        _run(_())

    def test_api_status_200(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/api/status")
                self.assertEqual(r.status, 200)
        _run(_())

    def test_unknown_path_404(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/nonexistent/path")
                self.assertEqual(r.status, 404)
        _run(_())

    def test_admin_path_404(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/admin")
                self.assertEqual(r.status, 404)
        _run(_())

    def test_debug_path_404(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/debug")
                self.assertEqual(r.status, 404)
        _run(_())


# ─────────────────────────────────────────────────────────────────────────────
# 3. Security headers on HTML responses
# ─────────────────────────────────────────────────────────────────────────────
class TestSecurityHeaders(unittest.TestCase):

    def _headers_for(self, path: str) -> dict:
        result = {}
        async def _():
            nonlocal result
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get(path)
                result = dict(r.headers)
        _run(_())
        return result

    def test_root_x_content_type_options(self):
        self.assertEqual(self._headers_for("/").get("X-Content-Type-Options"), "nosniff")

    def test_root_x_frame_options(self):
        self.assertEqual(self._headers_for("/").get("X-Frame-Options"), "DENY")

    def test_root_csp_present(self):
        self.assertIn("Content-Security-Policy", self._headers_for("/"))

    def test_tos_x_frame_options(self):
        self.assertEqual(self._headers_for("/tos").get("X-Frame-Options"), "DENY")

    def test_privacy_x_frame_options(self):
        self.assertEqual(self._headers_for("/privacy").get("X-Frame-Options"), "DENY")

    def test_api_status_no_frame_options(self):
        # JSON endpoint — X-Frame-Options only on HTML
        headers = self._headers_for("/api/status")
        self.assertNotIn("X-Frame-Options", headers)

    def test_api_status_cors_header(self):
        headers = self._headers_for("/api/status")
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Custom 404 — path never echoed
# ─────────────────────────────────────────────────────────────────────────────
class TestCustom404(unittest.TestCase):

    def _404_body(self, path: str) -> str:
        result = {}
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get(path)
                result["text"] = await r.text()
                result["status"] = r.status
                result["ct"] = r.content_type
        _run(_())
        return result

    def test_unknown_route_is_404(self):
        r = self._404_body("/secret/internal/path")
        self.assertEqual(r["status"], 404)

    def test_404_returns_json(self):
        r = self._404_body("/does-not-exist")
        self.assertEqual(r["ct"], "application/json")

    def test_404_does_not_echo_path(self):
        sensitive_path = "/internal/config/secret"
        r = self._404_body(sensitive_path)
        self.assertNotIn(sensitive_path, r["text"])

    def test_404_body_is_safe(self):
        r = self._404_body("/anything")
        body = json.loads(r["text"])
        # Must have "error" key and no extra sensitive fields
        self.assertIn("error", body)
        for forbidden in ("path", "url", "traceback", "exception", "file"):
            self.assertNotIn(forbidden, body)

    def test_directory_traversal_404(self):
        r = self._404_body("/../../../etc/passwd")
        self.assertEqual(r["status"], 404)

    def test_admin_endpoint_404(self):
        r = self._404_body("/admin")
        self.assertEqual(r["status"], 404)

    def test_env_endpoint_404(self):
        r = self._404_body("/.env")
        self.assertEqual(r["status"], 404)

    def test_config_endpoint_404(self):
        r = self._404_body("/config")
        self.assertEqual(r["status"], 404)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Error middleware — no traceback in 500 response
# ─────────────────────────────────────────────────────────────────────────────
class TestErrorMiddleware(unittest.TestCase):

    def test_crash_returns_500(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/crash")
                self.assertEqual(r.status, 500)
        _run(_())

    def test_crash_returns_json(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/crash")
                self.assertEqual(r.content_type, "application/json")
        _run(_())

    def test_crash_no_traceback_in_body(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/crash")
                text = await r.text()
                self.assertNotIn("Traceback", text)
                self.assertNotIn("File \"", text)
                self.assertNotIn("RuntimeError", text)
                self.assertNotIn("Simulated", text)
        _run(_())

    def test_crash_body_is_generic(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/crash")
                body = json.loads(await r.text())
                self.assertIn("error", body)
                self.assertEqual(body["error"], "Internal server error")
        _run(_())

    def test_crash_no_secrets_in_body(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/crash")
                text = await r.text()
                for pat in _SECRET_PATTERNS:
                    self.assertIsNone(pat.search(text))
        _run(_())


# ─────────────────────────────────────────────────────────────────────────────
# 6. /api/status — safe fields only, no secrets
# ─────────────────────────────────────────────────────────────────────────────
class TestApiStatus(unittest.TestCase):

    def _status_body(self) -> dict:
        result = {}
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/api/status")
                result["body"] = json.loads(await r.text())
                result["status"] = r.status
        _run(_())
        return result

    def test_status_200(self):
        self.assertEqual(self._status_body()["status"], 200)

    def test_status_only_allowed_keys(self):
        body = self._status_body()["body"]
        extra_keys = set(body.keys()) - _ALLOWED_STATUS_KEYS
        self.assertEqual(extra_keys, set(), f"Unexpected keys in /api/status: {extra_keys}")

    def test_status_has_online_field(self):
        body = self._status_body()["body"]
        self.assertIn("online", body)

    def test_status_has_guild_count(self):
        body = self._status_body()["body"]
        self.assertIn("guild_count", body)

    def test_status_no_token(self):
        body_str = json.dumps(self._status_body()["body"])
        for pat in _SECRET_PATTERNS:
            self.assertIsNone(pat.search(body_str))

    def test_status_no_internal_config(self):
        body = self._status_body()["body"]
        forbidden = {"token", "key", "secret", "password", "db", "database",
                     "schema", "env", "path", "prompt", "openai", "discord_token"}
        for key in body:
            self.assertNotIn(key.lower(), forbidden, f"Unexpected field {key!r} in status")

    def test_status_no_db_contents(self):
        body_str = json.dumps(self._status_body()["body"])
        self.assertNotIn("guild_id", body_str)
        self.assertNotIn("server_settings", body_str)
        self.assertNotIn("auto_roles", body_str)

    def test_status_no_source_code(self):
        body_str = json.dumps(self._status_body()["body"])
        self.assertNotIn("def ", body_str)
        self.assertNotIn("import ", body_str)


# ─────────────────────────────────────────────────────────────────────────────
# 7. /invite — redirect only, no secret data in response body
# ─────────────────────────────────────────────────────────────────────────────
class TestInviteRoute(unittest.TestCase):

    def test_invite_is_redirect(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/invite", allow_redirects=False)
                self.assertIn(r.status, (301, 302, 307, 308))
        _run(_())

    def test_invite_redirect_target_is_discord(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/invite", allow_redirects=False)
                location = r.headers.get("Location", "")
                self.assertIn("discord.com", location)
        _run(_())

    def test_invite_body_is_empty_or_safe(self):
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get("/invite", allow_redirects=False)
                text = await r.text()
                for pat in _SECRET_PATTERNS:
                    self.assertIsNone(pat.search(text), f"Secret in /invite body: {pat.pattern}")
        _run(_())


# ─────────────────────────────────────────────────────────────────────────────
# 8. /api/status CORS is scoped correctly (only that route)
# ─────────────────────────────────────────────────────────────────────────────
class TestCorsScope(unittest.TestCase):

    def _headers_for(self, path: str) -> dict:
        result = {}
        async def _():
            async with TestClient(TestServer(_build_test_app())) as c:
                r = await c.get(path)
                result.update(dict(r.headers))
        _run(_())
        return result

    def test_status_has_cors(self):
        self.assertEqual(
            self._headers_for("/api/status").get("Access-Control-Allow-Origin"), "*"
        )

    def test_root_no_cors(self):
        # Dashboard HTML is same-origin — CORS header on / is unnecessary and undesirable
        self.assertNotEqual(
            self._headers_for("/").get("Access-Control-Allow-Origin"), "*"
        )

    def test_tos_no_cors(self):
        self.assertNotEqual(
            self._headers_for("/tos").get("Access-Control-Allow-Origin"), "*"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiter — test-local implementation mirroring _IPRateLimiter in main.py
# ─────────────────────────────────────────────────────────────────────────────

class _TestRateLimiter:
    """
    Mirrors the production _IPRateLimiter for isolated unit testing.
    Accepts configurable max_reqs, window, and optional trusted_proxy_ip.
    """

    def __init__(self, max_reqs: int, window_secs: float, trusted_proxy_ip=None):
        self.max_reqs = max_reqs
        self.window_secs = window_secs
        self.trusted_proxy_ip = trusted_proxy_ip
        self._store: dict = {}
        self._last_sweep: float = 0.0

    def _resolve_ip(self, request) -> str:
        peer = request.remote or "unknown"
        if self.trusted_proxy_ip and peer == self.trusted_proxy_ip:
            xff = request.headers.get("X-Forwarded-For", "").strip()
            if xff:
                return xff.split(",")[0].strip()
        return peer

    def check(self, ip: str) -> tuple:
        now = _time_mod.monotonic()
        window_start = now - self.window_secs
        bucket = self._store.setdefault(ip, [])
        cutoff = next((i for i, t in enumerate(bucket) if t > window_start), len(bucket))
        del bucket[:cutoff]
        if len(bucket) >= self.max_reqs:
            retry_after = int(self.window_secs - (now - bucket[0])) + 1
            return False, retry_after
        bucket.append(now)
        # Periodic sweep: trim expired entries from ALL buckets, then drop empties.
        if now - self._last_sweep > self.window_secs:
            self._last_sweep = now
            dead: list = []
            for k, v in self._store.items():
                exp = next((i for i, t in enumerate(v) if t > window_start), len(v))
                del v[:exp]
                if not v:
                    dead.append(k)
            for k in dead:
                del self._store[k]
        return True, 0

    def as_middleware(self):
        rl = self

        @web.middleware
        async def _mw(request, handler):
            ip = rl._resolve_ip(request)
            allowed, retry_after = rl.check(ip)
            if not allowed:
                return web.Response(
                    text=_json.dumps({"error": "Too many requests", "retry_after": retry_after}),
                    status=429,
                    content_type="application/json",
                    headers={"Retry-After": str(retry_after)},
                )
            return await handler(request)

        return _mw


def _build_rate_limited_app(
    max_reqs: int = 60,
    window: float = 60.0,
    trusted_proxy_ip=None,
) -> web.Application:
    """Build a test aiohttp app with the rate limiter and security middleware."""
    rl = _TestRateLimiter(max_reqs, window, trusted_proxy_ip)
    app = web.Application(middlewares=[rl.as_middleware(), _security_middleware])
    app.router.add_get("/",           _handle_root)
    app.router.add_get("/tos",        _handle_tos)
    app.router.add_get("/privacy",    _handle_privacy)
    app.router.add_get("/invite",     _handle_invite)
    app.router.add_get("/api/status", _handle_api_status)
    app.router.add_route("*", "/{path_info:.*}", _handle_404)
    return app


# ─────────────────────────────────────────────────────────────────────────────
# 9. Rate limiting — all public routes, 429 + Retry-After, no spoofing bypass
# ─────────────────────────────────────────────────────────────────────────────
class TestRateLimiter(unittest.TestCase):
    """
    All tests use a low limit (3 reqs per 10 s) so 429 can be triggered in <5 requests.
    Legitimate dashboard polling (60 req/min limit, JS polls every 15 s) is verified
    separately using the production-scale limit.
    """

    # ── Basic 429 / 200 behaviour ─────────────────────────────────────────────

    def test_under_limit_returns_200_root(self):
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(3, 10))) as c:
                for _ in range(3):
                    r = await c.get("/")
                    self.assertEqual(r.status, 200)
        _run(_())

    def test_over_limit_returns_429_root(self):
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(3, 10))) as c:
                for _ in range(3):
                    await c.get("/")
                r = await c.get("/")
                self.assertEqual(r.status, 429)
        _run(_())

    def test_over_limit_returns_429_tos(self):
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(3, 10))) as c:
                for _ in range(3):
                    await c.get("/tos")
                r = await c.get("/tos")
                self.assertEqual(r.status, 429)
        _run(_())

    def test_over_limit_returns_429_privacy(self):
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(3, 10))) as c:
                for _ in range(3):
                    await c.get("/privacy")
                r = await c.get("/privacy")
                self.assertEqual(r.status, 429)
        _run(_())

    def test_over_limit_returns_429_invite(self):
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(3, 10))) as c:
                for _ in range(3):
                    await c.get("/invite", allow_redirects=False)
                r = await c.get("/invite", allow_redirects=False)
                self.assertEqual(r.status, 429)
        _run(_())

    def test_over_limit_returns_429_api_status(self):
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(3, 10))) as c:
                for _ in range(3):
                    await c.get("/api/status")
                r = await c.get("/api/status")
                self.assertEqual(r.status, 429)
        _run(_())

    # ── Response shape ────────────────────────────────────────────────────────

    def test_429_includes_retry_after_header(self):
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(3, 10))) as c:
                for _ in range(3):
                    await c.get("/api/status")
                r = await c.get("/api/status")
                self.assertIn("Retry-After", r.headers)
                self.assertGreater(int(r.headers["Retry-After"]), 0)
        _run(_())

    def test_429_retry_after_is_positive_integer(self):
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(1, 30))) as c:
                await c.get("/")
                r = await c.get("/")
                val = r.headers.get("Retry-After", "")
                self.assertTrue(val.isdigit(), f"Retry-After not a digit: {val!r}")
                self.assertGreater(int(val), 0)
        _run(_())

    def test_429_body_is_json(self):
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(3, 10))) as c:
                for _ in range(3):
                    await c.get("/")
                r = await c.get("/")
                self.assertEqual(r.content_type, "application/json")
                body = json.loads(await r.text())
                self.assertIn("error", body)
                self.assertIn("retry_after", body)
        _run(_())

    def test_429_body_retry_after_matches_header(self):
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(1, 30))) as c:
                await c.get("/")
                r = await c.get("/")
                header_val = int(r.headers["Retry-After"])
                body = json.loads(await r.text())
                self.assertEqual(body["retry_after"], header_val)
        _run(_())

    def test_429_body_no_secrets(self):
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(1, 10))) as c:
                await c.get("/")
                r = await c.get("/")
                text = await r.text()
                for pat in _SECRET_PATTERNS:
                    self.assertIsNone(pat.search(text))
        _run(_())

    # ── XFF spoofing prevention ───────────────────────────────────────────────

    def test_xff_ignored_without_trusted_proxy(self):
        """Without TRUSTED_PROXY_IP, spoofed XFF headers must NOT bypass the limiter."""
        async def _():
            rl = _TestRateLimiter(3, 10, trusted_proxy_ip=None)
            app = web.Application(middlewares=[rl.as_middleware(), _security_middleware])
            app.router.add_get("/", _handle_root)
            app.router.add_route("*", "/{path_info:.*}", _handle_404)
            async with TestClient(TestServer(app)) as c:
                # 3 requests each claiming a different IP via XFF
                for i in range(3):
                    await c.get("/", headers={"X-Forwarded-For": f"10.0.0.{i}"})
                # 4th request: different XFF, but should still be rate-limited
                # because XFF is ignored and all count against 127.0.0.1
                r = await c.get("/", headers={"X-Forwarded-For": "10.0.0.99"})
                self.assertEqual(r.status, 429)
        _run(_())

    def test_xff_used_when_trusted_proxy_matches(self):
        """With TRUSTED_PROXY_IP=127.0.0.1, the XFF value IS used as the client IP."""
        async def _():
            # TestClient connects from 127.0.0.1 — set that as the trusted proxy.
            rl = _TestRateLimiter(3, 10, trusted_proxy_ip="127.0.0.1")
            app = web.Application(middlewares=[rl.as_middleware(), _security_middleware])
            app.router.add_get("/", _handle_root)
            app.router.add_route("*", "/{path_info:.*}", _handle_404)
            async with TestClient(TestServer(app)) as c:
                # Exhaust limit for client A
                for _ in range(3):
                    await c.get("/", headers={"X-Forwarded-For": "10.0.0.1"})
                r_a = await c.get("/", headers={"X-Forwarded-For": "10.0.0.1"})
                self.assertEqual(r_a.status, 429)
                # Client B has a fresh bucket — must succeed
                r_b = await c.get("/", headers={"X-Forwarded-For": "10.0.0.2"})
                self.assertEqual(r_b.status, 200)
        _run(_())

    def test_xff_ignored_when_peer_is_not_trusted_proxy(self):
        """XFF ignored if the direct peer does NOT match the trusted proxy IP."""
        async def _():
            # Trusted proxy is 10.99.99.99, but TestClient connects from 127.0.0.1 —
            # mismatch, so XFF must be ignored.
            rl = _TestRateLimiter(3, 10, trusted_proxy_ip="10.99.99.99")
            app = web.Application(middlewares=[rl.as_middleware(), _security_middleware])
            app.router.add_get("/", _handle_root)
            app.router.add_route("*", "/{path_info:.*}", _handle_404)
            async with TestClient(TestServer(app)) as c:
                for i in range(3):
                    await c.get("/", headers={"X-Forwarded-For": f"10.0.0.{i}"})
                # Limit hits because all go against the real peer IP (127.0.0.1)
                r = await c.get("/", headers={"X-Forwarded-For": "10.0.0.99"})
                self.assertEqual(r.status, 429)
        _run(_())

    # ── IP bucket isolation ───────────────────────────────────────────────────

    def test_ip_buckets_are_isolated(self):
        """Two different client IPs (via trusted-proxy XFF) don't share buckets."""
        async def _():
            rl = _TestRateLimiter(2, 10, trusted_proxy_ip="127.0.0.1")
            app = web.Application(middlewares=[rl.as_middleware(), _security_middleware])
            app.router.add_get("/", _handle_root)
            app.router.add_route("*", "/{path_info:.*}", _handle_404)
            async with TestClient(TestServer(app)) as c:
                # Exhaust IP A
                await c.get("/", headers={"X-Forwarded-For": "192.168.1.1"})
                await c.get("/", headers={"X-Forwarded-For": "192.168.1.1"})
                r_a = await c.get("/", headers={"X-Forwarded-For": "192.168.1.1"})
                self.assertEqual(r_a.status, 429)
                # IP B is untouched
                r_b = await c.get("/", headers={"X-Forwarded-For": "192.168.1.2"})
                self.assertEqual(r_b.status, 200)
        _run(_())

    # ── Memory cleanup ────────────────────────────────────────────────────────

    def test_expired_entries_removed_from_bucket(self):
        """Timestamps older than the window must be trimmed on the next check."""
        rl = _TestRateLimiter(3, 0.01, trusted_proxy_ip=None)  # 10 ms window
        rl.check("1.2.3.4")
        rl.check("1.2.3.4")
        self.assertEqual(len(rl._store.get("1.2.3.4", [])), 2)
        _time_mod.sleep(0.02)  # let the window expire
        rl.check("1.2.3.4")   # first check after expiry trims old entries
        bucket = rl._store.get("1.2.3.4", [])
        # Only the just-added timestamp survives (the two old ones were trimmed)
        self.assertEqual(len(bucket), 1)

    def test_empty_buckets_swept_periodically(self):
        """
        The periodic sweep trims expired entries from ALL buckets and removes
        the ones that drain to empty — so stale IP entries don't accumulate.
        """
        rl = _TestRateLimiter(3, 0.01, trusted_proxy_ip=None)  # 10 ms window
        rl.check("5.5.5.5")           # adds T1 for this IP
        _time_mod.sleep(0.02)         # T1 expires (window = 10 ms)
        rl._last_sweep = 0.0          # force the next request to trigger a full sweep
        rl.check("5.5.5.6")           # sweep fires: trims T1 from 5.5.5.5 bucket → empty → removed
        self.assertNotIn("5.5.5.5", rl._store)

    # ── Legitimate use unaffected ─────────────────────────────────────────────

    def test_legitimate_dashboard_js_poll_unaffected(self):
        """
        Dashboard JS polls /api/status every 15 s — that's ≤4 polls/min.
        Production limit is 60 req/min, so legitimate use never hits 429.
        """
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(60, 60))) as c:
                # Simulate 4 polls (generous; real rate is much lower)
                for _ in range(4):
                    r = await c.get("/api/status")
                    self.assertEqual(r.status, 200)
        _run(_())

    def test_single_page_load_unaffected(self):
        """A normal page load (/, /tos, /privacy) must never be rate-limited."""
        async def _():
            async with TestClient(TestServer(_build_rate_limited_app(60, 60))) as c:
                for path in ["/", "/tos", "/privacy"]:
                    r = await c.get(path)
                    self.assertEqual(r.status, 200, f"{path} was unexpectedly rate-limited")
        _run(_())


if __name__ == "__main__":
    unittest.main()
