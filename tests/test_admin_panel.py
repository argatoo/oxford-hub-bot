"""The /admin button panel and the admin "/" menu."""
from aiogram.methods import DeleteMyCommands, EditMessageText, SendMessage, SetMyCommands
from sqlalchemy import select

from bot.callbacks import AdmCb
from bot.db.models import Floor, Invite, Role

ADMIN, TEACHER = 1, 3


def edits(h, chat_id):
    return [r for r in h.api.requests if isinstance(r, EditMessageText) and r.chat_id == chat_id]


def buttons(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


async def click(h, uid, **cb):
    await h.callback(uid, AdmCb(**cb).pack())


async def test_admin_opens_panel_with_sections(h):
    await h.register(ADMIN)
    await h.private(ADMIN, "/admin")
    panel = h.api.sent(ADMIN)[-1]
    assert "Admin panel" in panel.text
    assert {AdmCb(s=s).pack() for s in ("roles", "floors", "staff", "groups", "announce", "stats")} <= set(
        buttons(panel.reply_markup)
    )


async def test_add_role_and_toggle_floor_via_buttons(h):
    await h.register(ADMIN)
    await click(h, ADMIN, s="roles")
    assert "rol yo'q" in edits(h, ADMIN)[-1].text.lower()

    await click(h, ADMIN, s="role_add")
    await h.private(ADMIN, "7bad")  # invalid key: stays in input mode
    assert "yaramaydi" in h.api.sent(ADMIN)[-1].text
    await h.private(ADMIN, "cleaner 🧹 Tozalovchi")
    assert "Rol qo'shildi" in h.api.sent(ADMIN)[-1].text

    async with h.sessionmaker() as s:
        role = await s.scalar(select(Role))
    assert role.key == "cleaner" and role.emoji == "🧹" and not role.floor_based

    await click(h, ADMIN, s="role_floor", v=role.id)
    async with h.sessionmaker() as s:
        assert (await s.get(Role, role.id)).floor_based

    # After leaving input mode, plain text is no longer taken as a new role.
    await h.private(ADMIN, "doctor 🩺 Shifokor")
    async with h.sessionmaker() as s:
        assert len((await s.scalars(select(Role))).all()) == 1


async def test_delete_role_needs_confirmation(h):
    await h.register(ADMIN)
    await h.private(ADMIN, "/addrole doctor 🩺 Shifokor")
    async with h.sessionmaker() as s:
        role_id = (await s.scalar(select(Role))).id
    await click(h, ADMIN, s="role_del", v=role_id)
    assert AdmCb(s="role_del_ok", v=role_id).pack() in buttons(edits(h, ADMIN)[-1].reply_markup)
    async with h.sessionmaker() as s:
        assert await s.get(Role, role_id) is not None
    await click(h, ADMIN, s="role_del_ok", v=role_id)
    async with h.sessionmaker() as s:
        assert await s.get(Role, role_id) is None


async def test_floors_add_and_delete(h):
    await h.register(ADMIN)
    await click(h, ADMIN, s="floor_add")
    await h.private(ADMIN, "2-qavat")
    async with h.sessionmaker() as s:
        floor = await s.scalar(select(Floor))
    assert floor.name == "2-qavat"
    await click(h, ADMIN, s="floor_del", v=floor.id)
    await click(h, ADMIN, s="floor_del_ok", v=floor.id)
    async with h.sessionmaker() as s:
        assert await s.scalar(select(Floor)) is None


async def test_invite_wizard_for_teachers(h):
    await h.register(ADMIN)
    await click(h, ADMIN, s="inv")
    await click(h, ADMIN, s="inv_u", a="teacher")
    assert AdmCb(s="inv_go", a="teacher", w=30).pack() in buttons(edits(h, ADMIN)[-1].reply_markup)
    await click(h, ADMIN, s="inv_go", a="teacher", w=30)
    assert "start=" in edits(h, ADMIN)[-1].text
    async with h.sessionmaker() as s:
        inv = await s.scalar(select(Invite))
    assert inv.kind == "teacher" and inv.uses_left == 30


async def test_invite_wizard_asks_floor_for_floor_based_role(h):
    await h.register(ADMIN)
    await h.private(ADMIN, "/addrole cleaner 🧹 Tozalovchi")
    await h.private(ADMIN, "/rolefloor cleaner on")
    await h.private(ADMIN, "/addfloor 2-qavat")
    async with h.sessionmaker() as s:
        role = await s.scalar(select(Role))
        floor = await s.scalar(select(Floor))

    await click(h, ADMIN, s="inv_u", a="role", v=role.id)
    assert AdmCb(s="inv_f", a="role", v=role.id, w=1).pack() in buttons(edits(h, ADMIN)[-1].reply_markup)
    await click(h, ADMIN, s="inv_f", a="role", v=role.id, w=1)
    await click(h, ADMIN, s="inv_go", a="role", v=role.id, w=1, f=floor.id)
    async with h.sessionmaker() as s:
        inv = await s.scalar(select(Invite))
    assert (inv.role_id, inv.floor_id, inv.uses_left) == (role.id, floor.id, 1)


async def test_invite_rejects_tampered_uses(h):
    await h.register(ADMIN)
    await click(h, ADMIN, s="inv_go", a="admin", w=999)
    async with h.sessionmaker() as s:
        assert await s.scalar(select(Invite)) is None


async def test_announce_button_starts_announcement(h):
    await h.register(ADMIN)
    await h.bot_added(-100500, ADMIN)
    await click(h, ADMIN, s="announce")
    await h.private(ADMIN, "Ertaga bayram")
    assert "Qaysi guruhlarga" in h.api.sent(ADMIN)[-1].text


async def test_stats_and_groups_screens(h):
    await h.register(ADMIN)
    await click(h, ADMIN, s="stats", w=30)
    assert "30" in edits(h, ADMIN)[-1].text
    await click(h, ADMIN, s="groups")
    assert edits(h, ADMIN)[-1].text


async def test_non_admin_cannot_use_panel(h):
    await h.register(ADMIN)
    await h.private(ADMIN, "/invite teacher")
    code = h.api.sent(ADMIN)[-1].text.split("start=")[1].split()[0]
    await h.register(TEACHER, code)
    h.api.requests.clear()
    await h.private(TEACHER, "/admin")
    assert "tushunmadim" in h.api.sent(TEACHER)[-1].text
    await click(h, TEACHER, s="roles")
    assert edits(h, TEACHER) == []


async def test_admin_gets_admin_menu_others_dont(h):
    await h.register(ADMIN)
    menus = [r for r in h.api.requests if isinstance(r, SetMyCommands) and getattr(r.scope, "chat_id", None) == ADMIN]
    assert menus and "admin" in [c.command for c in menus[-1].commands]

    await h.register(TEACHER)
    assert any(
        isinstance(r, DeleteMyCommands) and getattr(r.scope, "chat_id", None) == TEACHER for r in h.api.requests
    )
    assert not any(
        isinstance(r, SetMyCommands) and getattr(r.scope, "chat_id", None) == TEACHER for r in h.api.requests
    )


async def test_admin_invite_link_gives_admin_menu(h):
    await h.register(ADMIN)
    await h.private(ADMIN, "/invite admin")
    code = h.api.sent(ADMIN)[-1].text.split("start=")[1].split()[0]
    await h.register(20, code)
    menus = [r for r in h.api.requests if isinstance(r, SetMyCommands) and getattr(r.scope, "chat_id", None) == 20]
    assert menus and menus[-1].commands[0].command == "admin"
    assert any(isinstance(r, SendMessage) and r.chat_id == 20 and "/admin" in r.text for r in h.api.requests)
