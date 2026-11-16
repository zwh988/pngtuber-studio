"""Avatar art parser, config and sprite lookup (M5-1). Pure."""

from backend.avatar.art import (
    STATES,
    AvatarConfig,
    expression_for_emotion,
    parse_art,
    parse_config,
    resolve_expression,
    sprite_for,
    state_code,
)

OPEN_CLOSED = (True, False)


def full(folder: str) -> list[str]:
    number, name = folder.split("_", 1)
    return [
        f"{number}a_{name}_oicm.png",
        f"{number}b_{name}_oiom.png",
        f"{number}c_{name}_cicm.png",
        f"{number}d_{name}_ciom.png",
    ]


def listing(*folders: str) -> dict[str, list[str]]:
    return {f: full(f) for f in folders}


def test_state_codes() -> None:
    assert [state_code(s) for s in STATES] == ["oicm", "oiom", "cicm", "ciom"]


def test_a_complete_folder_parses_without_warnings() -> None:
    art = parse_art(listing("01_smile", "02_cheeky", "10_angry"))
    assert [e.id for e in art.expressions] == ["smile", "cheeky", "angry"]
    assert [e.order for e in art.expressions] == [1, 2, 10]
    assert all(e.complete for e in art.expressions)
    assert art.default_expression == "smile"
    assert art.warnings == ()
    assert art.get("Cheeky") is not None  # case-insensitive
    assert art.expressions[0].sprites[(False, True)] == "01_smile/01d_smile_ciom.png"


def test_order_is_by_number_not_by_name() -> None:
    art = parse_art(listing("10_angry", "02_cheeky"))
    assert [e.id for e in art.expressions] == ["cheeky", "angry"]


def test_other_files_are_ignored_and_bad_names_warn() -> None:
    files = {
        "01_smile": [*full("01_smile"), "looped_preview.mov", "notes.txt"],
        "02_cheeky": [*full("02_cheeky"), "cheeky.png", "02a_cheeky_xxcm.png"],
        "extras": ["a.png"],
    }
    art = parse_art(files)
    assert [e.id for e in art.expressions] == ["smile", "cheeky"]
    text = " ".join(art.warnings)
    assert "looped_preview" not in text
    assert "cheeky.png" in text and "02a_cheeky_xxcm.png" in text
    assert "'extras'" in text


def test_a_file_from_another_folder_and_duplicates_are_skipped() -> None:
    files = {
        "01_smile": [*full("01_smile"), "02a_cheeky_oicm.png", "01e_smile_oicm.png"],
    }
    art = parse_art(files)
    smile = art.expressions[0]
    assert smile.sprites[OPEN_CLOSED] == "01_smile/01a_smile_oicm.png"
    assert len(art.warnings) == 2


def test_names_with_spaces_and_upper_case_parse() -> None:
    art = parse_art({"03_Big Grin": ["03A_big grin_OICM.PNG"]})
    assert art.expressions[0].id == "Big Grin"
    assert art.expressions[0].sprites[OPEN_CLOSED] == "03_Big Grin/03A_big grin_OICM.PNG"


def test_missing_states_warn_and_fall_back_to_the_nearest() -> None:
    files = listing("01_smile")
    files["02_cheeky"] = ["02a_cheeky_oicm.png", "02b_cheeky_oiom.png"]  # no closed eyes
    art = parse_art(files)
    cheeky = art.get("cheeky")
    assert cheeky is not None and not cheeky.complete
    assert cheeky.missing == ["cicm", "ciom"]
    assert any("cheeky" in w and "cicm" in w for w in art.warnings)
    # Closed eyes fall back to open eyes of the same expression, mouth kept.
    assert sprite_for(art, "cheeky", (False, True)) == "02_cheeky/02b_cheeky_oiom.png"
    assert sprite_for(art, "cheeky", (False, False)) == "02_cheeky/02a_cheeky_oicm.png"


def test_open_mouth_falls_back_to_closed() -> None:
    art = parse_art({"01_smile": ["01a_smile_oicm.png", "01c_smile_cicm.png"]})
    assert sprite_for(art, "smile", (True, True)) == "01_smile/01a_smile_oicm.png"
    assert sprite_for(art, "smile", (False, True)) == "01_smile/01c_smile_cicm.png"


def test_unknown_or_empty_expression_uses_the_default() -> None:
    art = parse_art({**listing("01_smile"), "02_empty": []})
    assert any("'empty' has no sprites" in w for w in art.warnings)
    assert sprite_for(art, "nope", (True, True)) == "01_smile/01b_smile_oiom.png"
    assert sprite_for(art, "empty", (True, False)) == "01_smile/01a_smile_oicm.png"
    assert sprite_for(art, None, (True, False)) == "01_smile/01a_smile_oicm.png"


def test_nothing_to_draw() -> None:
    art = parse_art({})
    assert art.default_expression is None
    assert not art.usable
    assert sprite_for(art, "smile", OPEN_CLOSED) is None
    assert "no expression folders found" in art.warnings


def test_default_is_the_first_folder_with_sprites() -> None:
    art = parse_art({"01_blank": [], **listing("02_cheeky")})
    assert art.default_expression == "cheeky"


def test_resolve_expression_neutral_is_silent() -> None:
    art = parse_art(listing("01_smile", "02_cheeky"))
    assert resolve_expression(art, "neutral") == ("smile", None)
    assert resolve_expression(art, None) == ("smile", None)
    assert resolve_expression(art, "CHEEKY") == ("cheeky", None)
    chosen, warning = resolve_expression(art, "smug")
    assert chosen == "smile" and warning is not None and "smug" in warning


# ---- avatar.json -----------------------------------------------------------------


def test_config_sets_default_and_emotion_map() -> None:
    config = parse_config(
        {"default_expression": "Cheeky", "emotion_map": {"excited": "angry", "sad": "nope"}}
    )
    art = parse_art(listing("01_smile", "02_cheeky", "10_angry"), config)
    assert art.default_expression == "cheeky"
    assert dict(art.emotion_map) == {"excited": "angry"}
    assert any("'nope'" in w for w in art.warnings)
    assert expression_for_emotion(art, "excited", "excited") == ("angry", None)
    assert expression_for_emotion(art, "neutral", "neutral") == ("cheeky", None)


def test_config_unknown_default_warns_and_keeps_the_first() -> None:
    art = parse_art(listing("01_smile"), AvatarConfig(default_expression="grin"))
    assert art.default_expression == "smile"
    assert any("grin" in w for w in art.warnings)


def test_bad_config_parts_are_warnings() -> None:
    assert parse_config(None) == AvatarConfig()
    assert parse_config([1, 2]).warnings
    config = parse_config({"default_expression": 3, "emotion_map": {"a": 1}, "colour": "red"})
    assert config.default_expression is None
    assert dict(config.emotion_map) == {}
    assert len(config.warnings) == 3
    assert parse_config({"emotion_map": "x"}).warnings
