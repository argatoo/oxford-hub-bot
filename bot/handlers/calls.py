import contextlib

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.callbacks import CallCb
from bot.config import utcnow
from bot.db.models import Call, CallMessage, Role, User
from bot.filters import can_call, is_admin
from bot.i18n import t
from bot.services.calls import dispatch_call, refresh_call, schedule_delete, set_status
from bot.services.common import ensure_group
from bot.services.roles import parse_triggers, trigger_cache

router = Router(name="calls")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


@router.message(F.text | F.caption)
async def on_group_message(message: Message, session: AsyncSession, user: User | None, bot: Bot):
    text = message.text or message.caption or ""
    if "#" not in text and "/" not in text:
        return
    trigger_map = await trigger_cache.get(session)
    if not trigger_map:
        return
    parsed = parse_triggers(text, trigger_map)
    if not parsed.role_ids:
        return

    group = await ensure_group(session, message.chat)
    if not can_call(user):
        with contextlib.suppress(TelegramAPIError):
            notice = await message.reply(t(group.lang, "only_teachers"))
            await schedule_delete(session, message.chat.id, notice.message_id, after_seconds=20)
        return

    for role_id in parsed.role_ids:
        role = await session.get(Role, role_id)
        if role is not None:
            await dispatch_call(
                bot, session, message=message, group=group, role=role,
                text=parsed.text, urgent=parsed.urgent,
            )


@router.callback_query(CallCb.filter())
async def on_call_action(cb: CallbackQuery, callback_data: CallCb, session: AsyncSession, user: User | None, bot: Bot, lang: str):
    call_id = callback_data.call_id
    has_card = user is not None and await session.scalar(
        select(CallMessage.id).where(CallMessage.call_id == call_id, CallMessage.user_id == user.id)
    )
    if not has_card:
        await cb.answer(t(lang, "not_yours"), show_alert=True)
        return

    if callback_data.action == "acc":
        ok = await set_status(session, call_id, expect="pending",
                              status="accepted", accepted_by=user.id, accepted_at=utcnow())
        msg = "accepted_ok" if ok else "already_taken"
    elif callback_data.action == "done":
        ok = await set_status(session, call_id, expect="accepted", by=user.id,
                              status="done", done_at=utcnow())
        msg = "done_ok" if ok else "cannot_do"
    elif callback_data.action == "close" and is_admin(user):
        ok = await set_status(session, call_id, expect="pending", status="closed")
        msg = "closed_ok" if ok else "cannot_do"
    else:
        ok, msg = False, "cannot_do"

    call = await session.get(Call, call_id, populate_existing=True)
    if call is not None:
        await refresh_call(bot, session, call)
    await cb.answer(t(lang, msg), show_alert=not ok)
