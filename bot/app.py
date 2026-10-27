"""Wiring shared by both ways of running the bot: local polling (`python -m bot`) and Vercel webhooks."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, Update
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import settings
from bot.db.session import ensure_schema, make_engine, reset_sessionmaker, use_sessionmaker
from bot.handlers import admin, announce, calls, groups, start
from bot.middlewares import DbMiddleware
from bot.services.calls import run_periodic
from bot.storage import SqlStorage

COMMANDS = {
    "uz": [("start", "Boshlash"), ("help", "Yordam"), ("announce", "E'lon yuborish"),
           ("me", "Mening ma'lumotlarim"), ("lang", "Tilni o'zgartirish"), ("cancel", "Bekor qilish")],
    "ru": [("start", "Начать"), ("help", "Помощь"), ("announce", "Отправить объявление"),
           ("me", "Мои данные"), ("lang", "Сменить язык"), ("cancel", "Отмена")],
    "en": [("start", "Start"), ("help", "Help"), ("announce", "Send an announcement"),
           ("me", "My profile"), ("lang", "Change language"), ("cancel", "Cancel")],
}

_dispatcher: Dispatcher | None = None
_schema_ready = False


def get_dispatcher() -> Dispatcher:
    # Routers can belong to only one dispatcher, so it is built once per process.
    global _dispatcher
    if _dispatcher is None:
        dp = Dispatcher(storage=SqlStorage())
        dp.update.outer_middleware(DbMiddleware())
        # Order matters: the group catch-all (calls) and the private fallback go last.
        dp.include_routers(
            start.router,
            admin.router,
            announce.router,
            groups.router,
            calls.router,
            start.fallback_router,
        )
        _dispatcher = dp
    return _dispatcher


def make_bot() -> Bot:
    return Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


async def set_commands(bot: Bot) -> None:
    scope = BotCommandScopeAllPrivateChats()
    for lang, items in COMMANDS.items():
        commands = [BotCommand(command=c, description=d) for c, d in items]
        await bot.set_my_commands(commands, scope=scope, language_code=lang)
        if lang == settings.default_lang:
            await bot.set_my_commands(commands, scope=scope)


@asynccontextmanager
async def request_scope() -> AsyncIterator[tuple[Bot, async_sessionmaker]]:
    """Fresh bot + DB engine for one serverless request.

    Nothing is reused between requests: the platform may run each one on a different
    event loop, and aiohttp/asyncpg connections cannot cross loops.
    """
    global _schema_ready
    engine = make_engine(settings.database_url, serverless=True)
    if not _schema_ready:
        await ensure_schema(engine)
        _schema_ready = True
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    token = use_sessionmaker(sessionmaker)
    bot = make_bot()
    try:
        yield bot, sessionmaker
    finally:
        reset_sessionmaker(token)
        await bot.session.close()
        await engine.dispose()


async def process_update(payload: dict) -> None:
    async with request_scope() as (bot, _):
        update = Update.model_validate(payload, context={"bot": bot})
        await get_dispatcher().feed_update(bot, update)


async def run_tick() -> None:
    async with request_scope() as (bot, sessionmaker):
        async with sessionmaker() as session:
            await run_periodic(bot, session)
