from contextvars import ContextVar, Token
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from bot.db.models import Base

# The sessionmaker for the update being handled. A context variable (not a global)
# because on Vercel each request gets its own engine and requests may run concurrently.
_current: ContextVar[async_sessionmaker] = ContextVar("sessionmaker")


def use_sessionmaker(sessionmaker: async_sessionmaker) -> Token:
    return _current.set(sessionmaker)


def reset_sessionmaker(token: Token) -> None:
    _current.reset(token)


def get_sessionmaker() -> async_sessionmaker:
    return _current.get()


def make_engine(url: str, serverless: bool = False) -> AsyncEngine:
    kwargs = {}
    if serverless:
        # Short-lived functions: never keep connections between requests.
        kwargs["poolclass"] = NullPool
    if url.startswith("sqlite"):
        db_path = url.split("///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    elif url.startswith("postgresql+asyncpg"):
        # Supabase's pooler (pgbouncer, transaction mode) cannot keep prepared statements
        # between transactions: disable caching and give each statement a unique name.
        kwargs["connect_args"] = {
            "statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        }

    engine = create_async_engine(url, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def _enable_fk(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


async def ensure_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            # Supabase publishes the public schema through its REST API. With RLS on and no
            # policies, that API sees nothing; the bot connects as the table owner and is unaffected.
            for table in Base.metadata.sorted_tables:
                await conn.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))


async def init_db(engine: AsyncEngine) -> async_sessionmaker:
    await ensure_schema(engine)
    return async_sessionmaker(engine, expire_on_commit=False)
