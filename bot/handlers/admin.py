import secrets
from collections import Counter, defaultdict
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import utcnow
from bot.db.models import Call, Floor, Group, Invite, Role, StaffRole, User
from bot.filters import IsAdmin
from bot.handlers.start import _add_staff_role
from bot.i18n import t
from bot.services.common import chunk_lines, find_floor, q, resolve_user, user_link
from bot.services.roles import is_valid_key, trigger_cache
from bot.services.users import user_badges

router = Router(name="admin")
router.message.filter(F.chat.type == ChatType.PRIVATE, IsAdmin())

PERMS = ("admin", "announcer", "teacher")


def _args(command: CommandObject) -> list[str]:
    return (command.args or "").split()


async def _role_by_key(session: AsyncSession, key: str) -> Role | None:
    return await session.scalar(select(Role).where(Role.key == key.lstrip("#/").lower()))


async def _answer_chunks(message: Message, lines: list[str]) -> None:
    for chunk in chunk_lines(lines):
        await message.answer(chunk)


@router.message(Command("admin"))
async def cmd_admin(message: Message, lang: str):
    await message.answer(t(lang, "help_admin"))


# ---------- Roles ----------

@router.message(Command("roles"))
async def cmd_roles(message: Message, session: AsyncSession, lang: str):
    roles = (await session.scalars(select(Role).order_by(Role.key))).all()
    if not roles:
        await message.answer(t(lang, "roles_empty"))
        return
    counts = dict((await session.execute(
        select(StaffRole.role_id, func.count(func.distinct(StaffRole.user_id))).group_by(StaffRole.role_id)
    )).all())
    lines = [t(lang, "roles_title")]
    for r in roles:
        triggers = " ".join(f"#{w}" for w in r.triggers)
        line = f"{q(r.emoji)} <b>{q(r.name)}</b> — {q(triggers)} · {t(lang, 'staff_count', n=counts.get(r.id, 0))}"
        if r.floor_based:
            line += f" · {t(lang, 'floor_based')}"
        lines.append(line)
    await _answer_chunks(message, lines)


@router.message(Command("addrole"))
async def cmd_addrole(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    args = _args(command)
    if not args:
        await message.answer(t(lang, "usage_addrole"))
        return
    key = args[0].lstrip("#/").lower()
    if not is_valid_key(key):
        await message.answer(t(lang, "bad_key", word=q(key)))
        return
    if key in await trigger_cache.get(session):
        await message.answer(t(lang, "key_taken", word=q(key)))
        return
    rest = args[1:]
    emoji = "👤"
    if rest and not any(ch.isalnum() for ch in rest[0]):
        emoji = rest.pop(0)[:16]
    name = " ".join(rest)[:64] or key.capitalize()
    role = Role(key=key, emoji=emoji, name=name)
    session.add(role)
    await session.commit()
    trigger_cache.invalidate()
    await message.answer(t(lang, "role_added", title=q(role.title), key=key))


@router.message(Command("delrole"))
async def cmd_delrole(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    args = _args(command)
    role = await _role_by_key(session, args[0]) if args else None
    if role is None:
        await message.answer(t(lang, "role_not_found"))
        return
    # Deleted explicitly too, in case the database does not enforce ON DELETE CASCADE.
    await session.execute(delete(StaffRole).where(StaffRole.role_id == role.id))
    await session.execute(delete(Invite).where(Invite.role_id == role.id))
    await session.delete(role)
    await session.commit()
    trigger_cache.invalidate()
    await message.answer(t(lang, "role_deleted", title=q(role.title)))


@router.message(Command("rolefloor"))
async def cmd_rolefloor(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    args = _args(command)
    if len(args) != 2 or args[1].lower() not in ("on", "off"):
        await message.answer(t(lang, "usage_rolefloor"))
        return
    role = await _role_by_key(session, args[0])
    if role is None:
        await message.answer(t(lang, "role_not_found"))
        return
    role.floor_based = args[1].lower() == "on"
    await session.commit()
    await message.answer(t(lang, "rolefloor_on" if role.floor_based else "rolefloor_off", title=q(role.title)))


@router.message(Command("alias"))
async def cmd_alias(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    args = _args(command)
    if len(args) < 2:
        await message.answer(t(lang, "usage_alias"))
        return
    role = await _role_by_key(session, args[0])
    if role is None:
        await message.answer(t(lang, "role_not_found"))
        return
    taken = await trigger_cache.get(session)
    aliases = role.aliases.split()
    for word in (w.lstrip("#/").lower() for w in args[1:]):
        if not is_valid_key(word):
            await message.answer(t(lang, "bad_key", word=q(word)))
            return
        if word in taken or word in aliases:
            await message.answer(t(lang, "key_taken", word=q(word)))
            return
        aliases.append(word)
    role.aliases = " ".join(aliases)
    await session.commit()
    trigger_cache.invalidate()
    await message.answer(t(lang, "alias_set", title=q(role.title), triggers=q(" ".join(f"#{w}" for w in role.triggers))))


@router.message(Command("unalias"))
async def cmd_unalias(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    args = _args(command)
    if len(args) != 2:
        await message.answer(t(lang, "usage_alias"))
        return
    role = await _role_by_key(session, args[0])
    if role is None:
        await message.answer(t(lang, "role_not_found"))
        return
    word = args[1].lstrip("#/").lower()
    role.aliases = " ".join(a for a in role.aliases.split() if a != word)
    await session.commit()
    trigger_cache.invalidate()
    await message.answer(t(lang, "alias_set", title=q(role.title), triggers=q(" ".join(f"#{w}" for w in role.triggers))))


# ---------- Floors ----------

@router.message(Command("floors"))
async def cmd_floors(message: Message, session: AsyncSession, lang: str):
    floors = (await session.scalars(select(Floor).order_by(Floor.id))).all()
    if not floors:
        await message.answer(t(lang, "floors_empty"))
        return
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
    await _answer_chunks(message, lines)


@router.message(Command("addfloor"))
async def cmd_addfloor(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    name = (command.args or "").strip()[:64]
    if not name:
        await message.answer(t(lang, "usage_addfloor"))
        return
    if await find_floor(session, name):
        await message.answer(t(lang, "floor_exists", name=q(name)))
        return
    session.add(Floor(name=name))
    await session.commit()
    await message.answer(t(lang, "floor_added", name=q(name)))


@router.message(Command("delfloor"))
async def cmd_delfloor(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    floor = await find_floor(session, command.args or "")
    if floor is None:
        await message.answer(t(lang, "floor_not_found"))
        return
    await session.execute(delete(StaffRole).where(StaffRole.floor_id == floor.id))
    for g in (await session.scalars(select(Group).where(Group.floor_id == floor.id))).all():
        g.floor_id = None
    await session.delete(floor)
    await session.commit()
    await message.answer(t(lang, "floor_deleted", name=q(floor.name)))


# ---------- Invites & staff ----------

async def _parse_target(session: AsyncSession, word: str) -> tuple[str, Role | None] | None:
    word = word.lstrip("#/").lower()
    if word in PERMS:
        return word, None
    role = await _role_by_key(session, word)
    return ("role", role) if role else None


def _target_label(lang: str, kind: str, role: Role | None) -> str:
    return q(role.title) if role else t(lang, f"perm_{kind}")


@router.message(Command("invite"))
async def cmd_invite(message: Message, command: CommandObject, session: AsyncSession, user: User, bot: Bot, lang: str):
    args = _args(command)
    target = await _parse_target(session, args[0]) if args else None
    if target is None:
        await message.answer(t(lang, "usage_invite"))
        return
    kind, role = target
    uses = 1
    if len(args) > 1:
        if not args[1].isdigit() or not 1 <= int(args[1]) <= 1000:
            await message.answer(t(lang, "usage_invite"))
            return
        uses = int(args[1])
    floor = None
    if len(args) > 2:
        floor = await find_floor(session, " ".join(args[2:]))
        if floor is None:
            await message.answer(t(lang, "floor_not_found"))
            return

    inv = Invite(
        code=secrets.token_urlsafe(9),
        kind=kind,
        role_id=role.id if role else None,
        floor_id=floor.id if floor else None,
        uses_left=uses,
        created_by=user.id,
    )
    session.add(inv)
    await session.commit()
    me = await bot.me()
    link = f"https://t.me/{me.username}?start={inv.code}"
    what = _target_label(lang, kind, role)
    if floor:
        what += f" ({q(floor.name)})"
    await message.answer(t(lang, "invite_created", what=what, uses=uses, link=link, code=inv.code))


@router.message(Command("invites"))
async def cmd_invites(message: Message, session: AsyncSession, lang: str):
    invites = (await session.scalars(
        select(Invite).where(Invite.is_active, Invite.uses_left > 0).order_by(Invite.created_at)
    )).all()
    if not invites:
        await message.answer(t(lang, "invites_empty"))
        return
    lines = [t(lang, "invites_title")]
    for inv in invites:
        role = await session.get(Role, inv.role_id) if inv.role_id else None
        lines.append(f"• <code>{inv.code}</code> — {_target_label(lang, inv.kind, role)} · {t(lang, 'uses_left', n=inv.uses_left)}")
    await _answer_chunks(message, lines)


@router.message(Command("revoke"))
async def cmd_revoke(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    inv = await session.get(Invite, (command.args or "").strip())
    if inv is None:
        await message.answer(t(lang, "inv_invalid"))
        return
    inv.is_active = False
    await session.commit()
    await message.answer(t(lang, "invite_revoked"))


@router.message(Command("staff"))
async def cmd_staff(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    args = _args(command)
    stmt = select(User).order_by(User.full_name)
    if args:
        target = await _parse_target(session, args[0])
        if target is None:
            await message.answer(t(lang, "role_not_found"))
            return
        kind, role = target
        if role:
            stmt = stmt.where(User.id.in_(select(StaffRole.user_id).where(StaffRole.role_id == role.id)))
        else:
            stmt = stmt.where({"admin": User.is_admin, "announcer": User.can_announce, "teacher": User.is_teacher}[kind])
    else:
        stmt = stmt.where(or_(
            User.is_admin, User.can_announce, User.is_teacher,
            User.id.in_(select(StaffRole.user_id)),
        ))
    users = (await session.scalars(stmt)).all()
    if not users:
        await message.answer(t(lang, "staff_empty"))
        return
    lines = [t(lang, "staff_title", n=len(users))]
    for u in users:
        uname = f" @{q(u.username)}" if u.username else ""
        badges = ", ".join(await user_badges(session, u, lang))
        lines.append(f"• {user_link(u)}{uname} <code>{u.id}</code> — {badges}")
    await _answer_chunks(message, lines)


async def _assign_args(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    args = _args(command)
    if len(args) < 2:
        await message.answer(t(lang, "usage_assign"))
        return None
    target_user = await resolve_user(session, args[0])
    if target_user is None:
        await message.answer(t(lang, "user_not_found"))
        return None
    target = await _parse_target(session, args[1])
    if target is None:
        await message.answer(t(lang, "role_not_found"))
        return None
    floor = None
    if len(args) > 2:
        floor = await find_floor(session, " ".join(args[2:]))
        if floor is None:
            await message.answer(t(lang, "floor_not_found"))
            return None
    return target_user, target[0], target[1], floor


@router.message(Command("assign"))
async def cmd_assign(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    parsed = await _assign_args(message, command, session, lang)
    if parsed is None:
        return
    target_user, kind, role, floor = parsed
    if kind == "admin":
        target_user.is_admin = True
    elif kind == "announcer":
        target_user.can_announce = True
    elif kind == "teacher":
        target_user.is_teacher = True
    else:
        await _add_staff_role(session, target_user.id, role.id, floor.id if floor else None)
    await session.commit()
    badges = ", ".join(await user_badges(session, target_user, lang)) or "—"
    await message.answer(t(lang, "assigned", user=user_link(target_user), roles=badges))


@router.message(Command("unassign"))
async def cmd_unassign(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    parsed = await _assign_args(message, command, session, lang)
    if parsed is None:
        return
    target_user, kind, role, floor = parsed
    if kind == "admin":
        target_user.is_admin = False
    elif kind == "announcer":
        target_user.can_announce = False
    elif kind == "teacher":
        target_user.is_teacher = False
    else:
        stmt = delete(StaffRole).where(StaffRole.user_id == target_user.id, StaffRole.role_id == role.id)
        if floor:
            stmt = stmt.where(StaffRole.floor_id == floor.id)
        await session.execute(stmt)
    await session.commit()
    badges = ", ".join(await user_badges(session, target_user, lang)) or "—"
    await message.answer(t(lang, "assigned", user=user_link(target_user), roles=badges))


# ---------- Groups & stats ----------

def group_sort_key(g: Group):
    return (g.grade or 99, g.label)


@router.message(Command("groups"))
async def cmd_groups(message: Message, session: AsyncSession, lang: str):
    groups = sorted((await session.scalars(select(Group).where(Group.is_active))).all(), key=group_sort_key)
    if not groups:
        await message.answer(t(lang, "groups_empty"))
        return
    floors = {f.id: f.name for f in (await session.scalars(select(Floor))).all()}
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
    await _answer_chunks(message, lines)


@router.message(Command("stats"))
async def cmd_stats(message: Message, command: CommandObject, session: AsyncSession, lang: str):
    days = int(command.args) if command.args and command.args.strip().isdigit() else 7
    since = utcnow() - timedelta(days=days)
    calls = (await session.scalars(select(Call).where(Call.created_at >= since))).all()
    if not calls:
        await message.answer(t(lang, "stats_empty", days=days))
        return
    roles = {r.id: r for r in (await session.scalars(select(Role))).all()}
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
    top = Counter(c.chat_id for c in calls).most_common(5)
    lines.append(t(lang, "stats_top"))
    for chat_id, n in top:
        label = groups[chat_id].label if chat_id in groups else str(chat_id)
        lines.append(f"• {q(label)}: {n}")
    await _answer_chunks(message, lines)
