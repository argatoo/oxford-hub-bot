import asyncio
import logging
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramMigrateToChat, TelegramRetryAfter
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.common import migrate_group

log = logging.getLogger(__name__)


@dataclass
class BroadcastResult:
    sent: list[tuple[int, int]] = field(default_factory=list)  # (chat_id, message_id)
    failed: list[int] = field(default_factory=list)
    pin_failed: list[int] = field(default_factory=list)


async def broadcast(
    bot: Bot,
    session: AsyncSession,
    from_chat_id: int,
    message_id: int,
    chat_ids: list[int],
    pin: bool,
) -> BroadcastResult:
    result = BroadcastResult()
    for chat_id in chat_ids:
        target = chat_id
        for _attempt in range(3):
            try:
                msg = await bot.copy_message(target, from_chat_id, message_id)
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramMigrateToChat as e:
                await migrate_group(session, target, e.migrate_to_chat_id)
                target = e.migrate_to_chat_id
            except TelegramAPIError as e:
                log.warning("Broadcast to %s failed: %s", target, e)
                msg = None
                break
        else:
            msg = None

        if msg is None:
            result.failed.append(chat_id)
            continue
        result.sent.append((target, msg.message_id))
        if pin:
            try:
                await bot.pin_chat_message(target, msg.message_id)
            except TelegramAPIError:
                result.pin_failed.append(target)
        # Stay well under Telegram's ~30 messages/second limit.
        await asyncio.sleep(0.1)
    return result
