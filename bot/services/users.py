from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Floor, Role, StaffRole, User
from bot.i18n import t
from bot.services.common import q


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
