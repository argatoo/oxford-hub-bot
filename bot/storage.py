import json
from collections.abc import Mapping
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

from bot.db.models import FsmState
from bot.db.session import get_sessionmaker


class SqlStorage(BaseStorage):
    """FSM storage in the bot's own database.

    Conversations only happen in private chats, so group chats (negative ids) are
    skipped entirely — that saves a DB round trip for every message in 29 busy groups.
    """

    @staticmethod
    def _key(key: StorageKey) -> str:
        return ":".join(str(p) for p in (
            key.bot_id, key.chat_id, key.user_id,
            key.thread_id or "", key.business_connection_id or "", key.destiny,
        ))

    @staticmethod
    def _skip(key: StorageKey) -> bool:
        return key.chat_id < 0

    async def _save(self, key: StorageKey, **values) -> None:
        async with get_sessionmaker()() as session:
            row = await session.get(FsmState, self._key(key))
            if row is None:
                row = FsmState(key=self._key(key), state=None, data="{}")
                session.add(row)
            for name, value in values.items():
                setattr(row, name, value)
            if row.state is None and row.data == "{}":
                if row in session.new:
                    session.expunge(row)
                else:
                    await session.delete(row)
            await session.commit()

    async def _load(self, key: StorageKey) -> FsmState | None:
        async with get_sessionmaker()() as session:
            return await session.get(FsmState, self._key(key))

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        if self._skip(key):
            return
        await self._save(key, state=state.state if isinstance(state, State) else state)

    async def get_state(self, key: StorageKey) -> str | None:
        if self._skip(key):
            return None
        row = await self._load(key)
        return row.state if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        if self._skip(key):
            return
        await self._save(key, data=json.dumps(dict(data), ensure_ascii=False))

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        if self._skip(key):
            return {}
        row = await self._load(key)
        return json.loads(row.data) if row else {}

    async def close(self) -> None:
        pass
