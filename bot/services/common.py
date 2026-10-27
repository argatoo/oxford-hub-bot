import html
import logging
import re
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Chat
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.models import Floor, Group, User
from bot.i18n import t

log = logging.getLogger(__name__)



def q(text: str) -> str:
    # Only used for text between tags, never inside attributes, so quotes can stay as they are.
    return html.escape(text, quote=False)


CLASS_RE = re.compile(
    r"(?<!\d)(1[01]|[1-9])\s*[-–— ]?\s*[\"'«“]?([A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ])(?![A-Za-zА-Яа-яЁё])"
)


def parse_class(title: str) -> tuple[int, str] | None:
    """'7-B sinf' -> (7, '7-B'); '10 «A»' -> (10, '10-A')."""
    m = CLASS_RE.search(title)
    if not m:
        return None
    grade = int(m.group(1))
    return grade, f"{grade}-{m.group(2).upper()}"


async def ensure_group(session: AsyncSession, chat: Chat) -> Group:
    group = await session.get(Group, chat.id)
    if group is None:
        group = Group(chat_id=chat.id, title=chat.title or str(chat.id), lang=settings.default_lang)
        parsed = parse_class(group.title)
        if parsed:
            group.grade, group.class_name = parsed
        session.add(group)
        await session.commit()
    elif chat.title and group.title != chat.title:
        group.title = chat.title
        await session.commit()
    return group


async def migrate_group(session: AsyncSession, old_id: int, new_id: int) -> None:
    """A group upgraded to a supergroup gets a new chat id."""
    if await session.get(Group, new_id) is not None:
        await session.execute(update(Group).where(Group.chat_id == old_id).values(is_active=False))
    else:
        await session.execute(update(Group).where(Group.chat_id == old_id).values(chat_id=new_id))
    await session.commit()


async def admin_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).where(User.is_admin))).all())


async def notify_admins(bot: Bot, session: AsyncSession, key: str, reply_markup=None, **kwargs) -> None:
    for admin in await admin_users(session):
        try:
            await bot.send_message(admin.id, t(admin.lang, key, **kwargs), reply_markup=reply_markup)
        except TelegramAPIError as e:
            log.warning("Cannot notify admin %s: %s", admin.id, e)


async def find_floor(session: AsyncSession, name: str) -> Floor | None:
    return await session.scalar(select(Floor).where(Floor.name == name.strip()))


async def resolve_user(session: AsyncSession, ref: str) -> User | None:
    """Accepts a Telegram id or @username."""
    ref = ref.strip()
    if ref.startswith("@"):
        users = (await session.scalars(select(User).where(User.username.is_not(None)))).all()
        return next((u for u in users if u.username.lower() == ref[1:].lower()), None)
    if ref.lstrip("-").isdigit():
        return await session.get(User, int(ref))
    return None


def user_link(user: User) -> str:
    return f'<a href="tg://user?id={user.id}">{q(user.full_name)}</a>'


def chunk_lines(lines: Iterable[str], limit: int = 3800) -> list[str]:
    chunks, cur = [], ""
    for line in lines:
        if cur and len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks
