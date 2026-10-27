from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from bot.db.models import User


def is_admin(user: User | None) -> bool:
    return user is not None and user.is_admin


def can_announce(user: User | None) -> bool:
    return user is not None and (user.is_admin or user.can_announce)


def can_call(user: User | None) -> bool:
    return user is not None and (user.is_admin or user.is_teacher)


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, user: User | None = None) -> bool:
        return is_admin(user)


class CanAnnounce(BaseFilter):
    async def __call__(self, event: TelegramObject, user: User | None = None) -> bool:
        return can_announce(user)
