"""Admin data and actions, shared by the text commands (/roles, /invite …) and the button panel."""
import secrets
from collections import Counter, defaultdict
from datetime import timedelta

from aiogram import Bot
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import utcnow
from bot.db.models import Call, Floor, Group, Invite, Role, StaffRole, User
from bot.i18n import t
from bot.services.common import find_floor, group_sort_key, q, user_link
from bot.services.roles import is_valid_key, trigger_cache
from bot.services.users import add_staff_role, user_badges

PERMS = ("admin", "announcer", "teacher")
PERM_COLUMNS = {"admin": User.is_admin, "announcer": User.can_announce, "teacher": User.is_teacher}


# ---------- Roles ----------

async def role_by_key(session: AsyncSession, key: str) -> Role | None:
    return await session.scalar(select(Role).where(Role.key == key.lstrip("#/").lower()))


async def all_roles(session: AsyncSession) -> list[Role]:
    return list((await session.scalars(select(Role).order_by(Role.key))).all())


async def staff_counts(session: AsyncSession) -> dict[int, int]:
    return dict((await session.execute(
        select(StaffRole.role_id, func.count(func.distinct(StaffRole.user_id))).group_by(StaffRole.role_id)
    )).all())


def triggers_text(role: Role) -> str:
    return q(" ".join(f"#{w}" for w in role.triggers))


async def roles_lines(session: AsyncSession, lang: str) -> list[str]:
    roles = await all_roles(session)
    if not roles:
        return [t(lang, "roles_empty")]
    counts = await staff_counts(session)
    lines = [t(lang, "roles_title")]
    for r in roles:
        line = f"{q(r.emoji)} <b>{q(r.name)}</b> — {triggers_text(r)} · {t(lang, 'staff_count', n=counts.get(r.id, 0))}"
        if r.floor_based:
            line += f" · {t(lang, 'floor_based')}"
        lines.append(line)
    return lines


async def create_role(session: AsyncSession, lang: str, args: list[str]) -> tuple[Role | None, str]:
    """args: key [emoji] name… — returns the new role (or None) and the reply text."""
    if not args:
        return None, t(lang, "usage_addrole")
    key = args[0].lstrip("#/").lower()
    if not is_valid_key(key):
        return None, t(lang, "bad_key", word=q(key))
    if key in await trigger_cache.get(session):
        return None, t(lang, "key_taken", word=q(key))
    rest = args[1:]
    emoji = "👤"
    if rest and not any(ch.isalnum() for ch in rest[0]):
        emoji = rest.pop(0)[:16]
    name = " ".join(rest)[:64] or key.capitalize()
    role = Role(key=key, emoji=emoji, name=name)
    session.add(role)
    await session.commit()
    trigger_cache.invalidate()
    return role, t(lang, "role_added", title=q(role.title), key=key)


async def delete_role(session: AsyncSession, role: Role) -> None:
    # Deleted explicitly too, in case the database does not enforce ON DELETE CASCADE.
    await session.execute(delete(StaffRole).where(StaffRole.role_id == role.id))
    await session.execute(delete(Invite).where(Invite.role_id == role.id))
    await session.delete(role)
    await session.commit()
    trigger_cache.invalidate()


# ---------- Floors ----------

async def all_floors(session: AsyncSession) -> list[Floor]:
    return list((await session.scalars(select(Floor).order_by(Floor.id))).all())


async def floors_lines(session: AsyncSession, lang: str) -> list[str]:
    floors = await all_floors(session)
    if not floors:
        return [t(lang, "floors_empty")]
    groups = (await session.scalars(select(Group).where(Group.is_active))).all()
    by_floor = defaultdict(list)
    for g in groups:
        by_floor[g.floor_id].append(g.label)
    lines = [t(lang, "floors_title")]
    for f in floors:
        classes = ", ".join(sorted(by_floor.get(f.id, []))) or "—"
        lines.append(f"🏢 <b>{q(f.name)}</b>: {q(classes)}")
    if by_floor.get(None):
        lines.append(t(lang, "groups_without_floor", classes=q(", ".join(sorted(by_floor[None])))))
    return lines


async def create_floor(session: AsyncSession, lang: str, name: str) -> tuple[Floor | None, str]:
    name = name.strip()[:64]
    if not name:
        return None, t(lang, "usage_addfloor")
    if await find_floor(session, name):
        return None, t(lang, "floor_exists", name=q(name))
    floor = Floor(name=name)
    session.add(floor)
    await session.commit()
    return floor, t(lang, "floor_added", name=q(name))


async def delete_floor(session: AsyncSession, floor: Floor) -> None:
    await session.execute(delete(StaffRole).where(StaffRole.floor_id == floor.id))
    for g in (await session.scalars(select(Group).where(Group.floor_id == floor.id))).all():
        g.floor_id = None
    await session.delete(floor)
    await session.commit()


# ---------- Staff & invites ----------

async def parse_target(session: AsyncSession, word: str) -> tuple[str, Role | None] | None:
    word = word.lstrip("#/").lower()
    if word in PERMS:
        return word, None
    role = await role_by_key(session, word)
    return ("role", role) if role else None


def target_label(lang: str, kind: str, role: Role | None) -> str:
    return q(role.title) if role else t(lang, f"perm_{kind}")


async def create_invite(
    session: AsyncSession, bot: Bot, creator_id: int, lang: str,
    kind: str, role: Role | None, floor: Floor | None, uses: int,
) -> str:
    inv = Invite(
        code=secrets.token_urlsafe(9),
        kind=kind,
        role_id=role.id if role else None,
        floor_id=floor.id if floor else None,
        uses_left=uses,
        created_by=creator_id,
    )
    session.add(inv)
    await session.commit()
    me = await bot.me()
    link = f"https://t.me/{me.username}?start={inv.code}"
    what = target_label(lang, kind, role)
    if floor:
        what += f" ({q(floor.name)})"
    return t(lang, "invite_created", what=what, uses=uses, link=link, code=inv.code)


async def active_invites(session: AsyncSession) -> list[tuple[Invite, Role | None]]:
    invites = (await session.scalars(
        select(Invite).where(Invite.is_active, Invite.uses_left > 0).order_by(Invite.created_at)
    )).all()
    return [(inv, await session.get(Role, inv.role_id) if inv.role_id else None) for inv in invites]


async def invites_lines(session: AsyncSession, lang: str) -> list[str]:
    invites = await active_invites(session)
    if not invites:
        return [t(lang, "invites_empty")]
    lines = [t(lang, "invites_title")]
    for inv, role in invites:
        lines.append(
            f"• <code>{inv.code}</code> — {target_label(lang, inv.kind, role)} · {t(lang, 'uses_left', n=inv.uses_left)}"
        )
    return lines


async def staff_users(session: AsyncSession, kind: str | None = None, role: Role | None = None) -> list[User]:
    stmt = select(User).order_by(User.full_name)
    if role is not None:
        stmt = stmt.where(User.id.in_(select(StaffRole.user_id).where(StaffRole.role_id == role.id)))
    elif kind in PERM_COLUMNS:
        stmt = stmt.where(PERM_COLUMNS[kind])
    else:
        stmt = stmt.where(or_(*PERM_COLUMNS.values(), User.id.in_(select(StaffRole.user_id))))
    return list((await session.scalars(stmt)).all())


async def staff_lines(session: AsyncSession, lang: str, users: list[User]) -> list[str]:
    if not users:
        return [t(lang, "staff_empty")]
    lines = [t(lang, "staff_title", n=len(users))]
    for u in users:
        uname = f" @{q(u.username)}" if u.username else ""
        badges = ", ".join(await user_badges(session, u, lang))
        lines.append(f"• {user_link(u)}{uname} <code>{u.id}</code> — {badges}")
    return lines


async def grant(session: AsyncSession, user: User, kind: str, role: Role | None, floor: Floor | None) -> None:
    if kind in PERM_COLUMNS:
        setattr(user, PERM_COLUMNS[kind].key, True)
    else:
        await add_staff_role(session, user.id, role.id, floor.id if floor else None)
    await session.commit()


async def revoke(session: AsyncSession, user: User, kind: str, role: Role | None, floor: Floor | None) -> None:
    if kind in PERM_COLUMNS:
        setattr(user, PERM_COLUMNS[kind].key, False)
    else:
        stmt = delete(StaffRole).where(StaffRole.user_id == user.id, StaffRole.role_id == role.id)
        if floor:
            stmt = stmt.where(StaffRole.floor_id == floor.id)
        await session.execute(stmt)
    await session.commit()


# ---------- Groups & stats ----------

async def groups_lines(session: AsyncSession, lang: str) -> list[str]:
    groups = sorted((await session.scalars(select(Group).where(Group.is_active))).all(), key=group_sort_key)
    if not groups:
        return [t(lang, "groups_empty")]
    floors = {f.id: f.name for f in await all_floors(session)}
    lines = [t(lang, "groups_title", n=len(groups))]
    for g in groups:
        line = f"• <b>{q(g.label)}</b>"
        if g.class_name and g.title != g.class_name:
            line += f" ({q(g.title)})"
        line += f" · {q(floors[g.floor_id]) if g.floor_id in floors else t(lang, 'no_floor')} · {g.lang}"
        if not g.bot_is_admin:
            line += f" · {t(lang, 'not_admin_warn')}"
        if not g.class_name:
            line += f" · {t(lang, 'no_class_warn')}"
        lines.append(line)
    lines.append(t(lang, "groups_hint"))
    return lines


async def stats_lines(session: AsyncSession, lang: str, days: int) -> list[str]:
    since = utcnow() - timedelta(days=days)
    calls = (await session.scalars(select(Call).where(Call.created_at >= since))).all()
    if not calls:
        return [t(lang, "stats_empty", days=days)]
    roles = {r.id: r for r in await all_roles(session)}
    groups = {g.chat_id: g for g in (await session.scalars(select(Group))).all()}

    by_role: dict[int | None, list[Call]] = defaultdict(list)
    for c in calls:
        by_role[c.role_id].append(c)
    lines = [t(lang, "stats_title", days=days, n=len(calls))]
    for role_id, items in by_role.items():
        accepted = [c for c in items if c.accepted_at]
        avg = (
            sum((c.accepted_at - c.created_at).total_seconds() for c in accepted) / len(accepted) / 60
            if accepted else 0
        )
        title = roles[role_id].title if role_id in roles else "❔"
        lines.append(t(
            lang, "stats_role",
            title=q(title), n=len(items), accepted=len(accepted),
            avg=f"{avg:.1f}", escalated=sum(c.escalated for c in items),
        ))
    lines.append(t(lang, "stats_top"))
    for chat_id, n in Counter(c.chat_id for c in calls).most_common(5):
        label = groups[chat_id].label if chat_id in groups else str(chat_id)
        lines.append(f"• {q(label)}: {n}")
    return lines
