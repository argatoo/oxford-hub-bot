"""Local mode: `python -m bot` runs the bot on this computer with long polling."""
import asyncio
import contextlib
import logging
import sys

from bot.app import get_dispatcher, make_bot, set_commands
from bot.config import settings
from bot.db.session import init_db, make_engine, use_sessionmaker
from bot.services.calls import periodic_loop
from bot.services.menus import sync_admin_menus


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.bot_token:
        sys.exit("BOT_TOKEN topilmadi. .env.example faylidan nusxa olib, .env yarating va tokenni yozing.")

    bot = make_bot()
    webhook = await bot.get_webhook_info()
    if webhook.url:
        if "--force-polling" not in sys.argv:
            await bot.session.close()
            sys.exit(
                f"Bot hozir Vercel'da ishlayapti (webhook: {webhook.url}).\n"
                "Kompyuterda ishga tushirsangiz, Vercel'dagi bot to'xtaydi. Baribir ishga tushirish uchun:\n"
                "  python -m bot --force-polling\n"
                "Keyin Vercel'ni qaytarish uchun: python -m bot.setup_webhook https://SIZNING-LOYIHA.vercel.app"
            )
        await bot.delete_webhook()

    engine = make_engine(settings.database_url)
    sessionmaker = await init_db(engine)
    use_sessionmaker(sessionmaker)
    dp = get_dispatcher()

    await set_commands(bot)
    async with sessionmaker() as session:
        await sync_admin_menus(bot, session)
    me = await bot.me()
    logging.info("Bot @%s started (polling)", me.username)

    periodic = asyncio.create_task(periodic_loop(bot, sessionmaker))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        periodic.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await periodic
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
