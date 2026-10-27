from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Floor, Role, StaffRole, User
from bot.i18n import t
from bot.services.common import q


async def add_staff_role(session: AsyncSession, user_id: int, role_id: int, floor_id: int | None) -> bool:
    """Adds the role unless the user already has it on that floor. Caller commits."""
    existing = await session.scalar(
        select(StaffRole).where(
            StaffRole.user_id == user_id,
            StaffRole.role_id == role_id,
            StaffRole.floor_id.is_(None) if floor_id is None else StaffRole.floor_id == floor_id,
        )
    )
    if existing:
        return False
    session.add(StaffRole(user_id=user_id, role_id=role_id, floor_id=floor_id))
    return True


async def user_badges(session: AsyncSession, user: User, lang: str) -> list[str]:
    badges = []
    if user.is_admin:
        badges.append(t(lang, "perm_admin"))
    if user.can_announce:
        badges.append(t(lang, "perm_announcer"))
    if user.is_teacher:
        badges.append(t(lang, "perm_teacher"))
    rows = (await session.execute(
        select(Role, Floor)
        .join(StaffRole, StaffRole.role_id == Role.id)
        .outerjoin(Floor, Floor.id == StaffRole.floor_id)
        .where(StaffRole.user_id == user.id)
        .order_by(Role.key)
    )).all()
    for role, floor in rows:
        badges.append(f"{q(role.title)} ({q(floor.name)})" if floor else q(role.title))
    return badges
