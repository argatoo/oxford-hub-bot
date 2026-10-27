import re
from pathlib import Path

from bot.i18n import TEXTS
from bot.services.common import parse_class
from bot.services.roles import is_valid_key, parse_triggers

TMAP = {"cleaner": 1, "clean": 1, "doctor": 2, "уборка": 1}


def test_hashtag_and_text():
    p = parse_triggers("#cleaner partada suv to'kilgan", TMAP)
    assert p.role_ids == [1] and not p.urgent and p.text == "partada suv to'kilgan"


def test_command_with_bot_username_and_urgent():
    p = parse_triggers("/doctor@school_bot! bola yiqildi", TMAP)
    assert p.role_ids == [2] and p.urgent and p.text == "bola yiqildi"


def test_alias_case_insensitive_and_cyrillic():
    assert parse_triggers("#CLEAN", TMAP).role_ids == [1]
    assert parse_triggers("нужна #уборка в классе", TMAP).role_ids == [1]


def test_multiple_roles_deduplicated():
    p = parse_triggers("#cleaner #doctor #clean", TMAP)
    assert p.role_ids == [1, 2]


def test_ignores_unknown_tags_and_urls():
    assert parse_triggers("#homework bugun", TMAP).role_ids == []
    assert parse_triggers("https://site.uz/cleaner", TMAP).role_ids == []
    assert parse_triggers("abc#cleaner", TMAP).role_ids == []


def test_unknown_tags_kept_in_text():
    p = parse_triggers("#cleaner #7B tez", TMAP)
    assert p.text == "#7B tez"


def test_key_validation():
    assert is_valid_key("cleaner")
    assert is_valid_key("уборщица")
    assert not is_valid_key("help")
    assert not is_valid_key("7b")
    assert not is_valid_key("a")


def test_parse_class():
    assert parse_class("7-B sinf") == (7, "7-B")
    assert parse_class("10 «a» Oxford") == (10, "10-A")
    assert parse_class("11-А класс") == (11, "11-А")
    assert parse_class("Oxford ota-onalar") is None


def test_every_used_text_key_exists_in_all_languages():
    src = "\n".join(p.read_text(encoding="utf-8") for p in Path("bot").rglob("*.py"))
    used = set(re.findall(r"\bt\([^,()]+,\s*[\"'](\w+)[\"']", src))
    used |= {f"perm_{k}" for k in ("admin", "announcer", "teacher")}
    used |= {"grp_pending", "grp_accepted", "grp_done", "grp_closed"}
    missing = sorted(k for k in used if k not in TEXTS)
    assert not missing, missing
    for key, variants in TEXTS.items():
        assert set(variants) == {"uz", "ru", "en"}, key
        # Same placeholders in every language.
        fields = {lang: set(re.findall(r"{(\w+)}", s)) for lang, s in variants.items()}
        assert fields["uz"] == fields["ru"] == fields["en"], key
