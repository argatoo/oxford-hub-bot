"""ASGI app for Vercel (`api/index.py` re-exports it).

One endpoint, told apart by headers so it works whatever path Vercel routes to it:
- Telegram update:  POST with header X-Telegram-Bot-Api-Secret-Token
- admin Mini App:   POST with header Authorization: tma <initData>
- periodic tick:    POST with header Authorization: Bearer <WEBHOOK_SECRET> (from Supabase Cron)
- anything else:    a plain health check
"""
import hmac
import json
import logging

from bot.app import process_update, run_tick
from bot.config import settings
from bot.webapp_api import handle_api

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TEXT = "text/plain; charset=utf-8"
JSON = "application/json; charset=utf-8"


def _matches(given: str | None, expected: str) -> bool:
    return bool(expected) and given is not None and hmac.compare_digest(given.encode(), expected.encode())


async def handle(method: str, headers: dict[str, str], body: bytes) -> tuple[int, str, str]:
    """Returns (status, body, content type)."""
    auth = headers.get("authorization")
    if auth is not None and auth.startswith("tma "):
        if method != "POST":
            return 405, "POST only", TEXT
        status, payload = await handle_api(auth[4:], body)
        return status, json.dumps(payload, ensure_ascii=False), JSON

    if not settings.webhook_secret:
        return 500, "WEBHOOK_SECRET is not configured", TEXT

    telegram_secret = headers.get("x-telegram-bot-api-secret-token")
    if telegram_secret is not None:
        if method != "POST" or not _matches(telegram_secret, settings.webhook_secret):
            return 403, "forbidden", TEXT
        try:
            await process_update(json.loads(body))
        except Exception:
            # Still answer 200: otherwise Telegram keeps re-sending the same broken update.
            log.exception("Failed to process update")
        return 200, "ok", TEXT

    if auth is not None:
        if method != "POST" or not _matches(auth, f"Bearer {settings.webhook_secret}"):
            return 403, "forbidden", TEXT
        try:
            await run_tick()
        except Exception:
            log.exception("Periodic tick failed")
            return 500, "tick failed", TEXT
        return 200, "tick ok", TEXT

    return 200, "Oxford Hub bot is running", TEXT


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] != "http":
        return

    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            break
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}

    status, text, content_type = await handle(scope["method"], headers, body)
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", content_type.encode()), (b"cache-control", b"no-store")],
    })
    await send({"type": "http.response.body", "body": text.encode()})
