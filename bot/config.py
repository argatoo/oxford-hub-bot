import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

LANGS = ("uz", "ru", "en")


def _normalize_db_url(url: str) -> str:
    # Supabase gives "postgresql://..." — SQLAlchemy needs the async driver name.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgresql+asyncpg") and "prepared_statement_cache_size" not in url:
        url += ("&" if "?" in url else "?") + "prepared_statement_cache_size=0"
    return url


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    database_url: str
    default_lang: str
    escalate_minutes: int
    urgent_escalate_minutes: int
    tz: timezone
    # Shared secret for Telegram's webhook and the Supabase cron call (Vercel mode).
    webhook_secret: str


def load_settings() -> Settings:
    admin_ids = frozenset(
        int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
    )
    default_lang = os.getenv("DEFAULT_LANG", "uz")
    if default_lang not in LANGS:
        default_lang = "uz"
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        admin_ids=admin_ids,
        database_url=_normalize_db_url(
            os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/bot.db")
        ),
        default_lang=default_lang,
        escalate_minutes=int(os.getenv("ESCALATE_MINUTES", "5")),
        urgent_escalate_minutes=int(os.getenv("URGENT_ESCALATE_MINUTES", "2")),
        tz=timezone(timedelta(hours=int(os.getenv("TZ_OFFSET_HOURS", "5")))),
        webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
    )


settings = load_settings()


def utcnow() -> datetime:
    # Naive UTC everywhere: SQLite drops tzinfo, so mixing aware/naive would break comparisons.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_time(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone(settings.tz).strftime("%H:%M")
