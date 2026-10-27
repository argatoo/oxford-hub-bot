"""The "/" command menu. Everyone gets the basic list; admins get their own, longer one."""
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User

log = logging.getLogger(__name__)

COMMANDS = {
    "uz": [("start", "Boshlash"), ("help", "Yordam"), ("announce", "E'lon yuborish"),
           ("me", "Mening ma'lumotlarim"), ("lang", "Tilni o'zgartirish"), ("cancel", "Bekor qilish")],
    "ru": [("start", "Начать"), ("help", "Помощь"), ("announce", "Отправить объявление"),
           ("me", "Мои данные"), ("lang", "Сменить язык"), ("cancel", "Отмена")],
    "en": [("start", "Start"), ("help", "Help"), ("announce", "Send an announcement"),
           ("me", "My profile"), ("lang", "Change language"), ("cancel", "Cancel")],
}

ADMIN_COMMANDS = {
    "uz": [("admin", "⚙️ Admin panel"), ("announce", "E'lon yuborish"), ("roles", "Rollar"),
           ("floors", "Qavatlar"), ("staff", "Xodimlar"), ("invite", "Taklif havolasi"),
           ("invites", "Faol havolalar"), ("groups", "Guruhlar"), ("stats", "Statistika"),
           ("help", "Yordam"), ("me", "Mening ma'lumotlarim"), ("lang", "Tilni o'zgartirish"),
           ("cancel", "Bekor qilish")],
    "ru": [("admin", "⚙️ Админ-панель"), ("announce", "Отправить объявление"), ("roles", "Роли"),
           ("floors", "Этажи"), ("staff", "Сотрудники"), ("invite", "Ссылка-приглашение"),
           ("invites", "Активные ссылки"), ("groups", "Группы"), ("stats", "Статистика"),
           ("help", "Помощь"), ("me", "Мои данные"), ("lang", "Сменить язык"),
           ("cancel", "Отмена")],
    "en": [("admin", "⚙️ Admin panel"), ("announce", "Send an announcement"), ("roles", "Roles"),
           ("floors", "Floors"), ("staff", "Staff"), ("invite", "Invite link"),
           ("invites", "Active invite links"), ("groups", "Groups"), ("stats", "Statistics"),
           ("help", "Help"), ("me", "My profile"), ("lang", "Change language"),
           ("cancel", "Cancel")],
}


def as_commands(items: list[tuple[str, str]]) -> list[BotCommand]:
    return [BotCommand(command=c, description=d) for c, d in items]


async def set_user_menu(bot: Bot, user: User) -> None:
    """Admins get the admin list in their own private chat; for others that override is removed."""
    scope = BotCommandScopeChat(chat_id=user.id)
    try:
        if user.is_admin:
            await bot.set_my_commands(as_commands(ADMIN_COMMANDS[user.lang]), scope=scope)
        else:
            await bot.delete_my_commands(scope=scope)
    except TelegramAPIError as e:
        log.warning("Cannot update menu for %s: %s", user.id, e)


async def sync_admin_menus(bot: Bot, session: AsyncSession) -> None:
    for admin in (await session.scalars(select(User).where(User.is_admin))).all():
        await set_user_menu(bot, admin)
