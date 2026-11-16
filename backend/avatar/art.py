"""Avatar art: parse an art folder listing into expressions and sprites (M5-1). Pure.

Convention (decision 2026-11-16, replaces spec 8's ``expression_eyes_mouth.png``):
one folder per expression named ``NN_name`` (``01_smile``), each holding PNGs named
``NNx_name_EEMM.png`` (``01a_smile_oicm.png``): ``oi``/``ci`` eyes open/closed,
``om``/``cm`` mouth open/closed; the letter ``x`` is ignored. The expression id is the
folder name without the number (``smile``); the number gives the order. All sprites
share one full-frame canvas, so every state of every expression has the same origin.

Optional ``avatar.json`` in the art folder: ``default_expression`` (an expression id;
default: the first by number) and ``emotion_map`` (emotion preset name to expression
id). Anything odd is a warning, never a crash. No file access here: ``scan.py`` reads
the folder and hands the listing in.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

FOLDER_RE = re.compile(r"^(\d{2})_(.+)$")
FILE_RE = re.compile(r"^(\d{2})([a-z])_(.+)_(oi|ci)(om|cm)\.png$", re.IGNORECASE)
CONFIG_NAME = "avatar.json"

# The name a preset uses for "no particular expression": always the default, silently.
NEUTRAL = "neutral"

# (eyes_open, mouth_open). The art has exactly these four states (spec 8, decision 9).
State = tuple[bool, bool]
STATES: tuple[State, ...] = ((True, False), (True, True), (False, False), (False, True))


def state_code(state: State) -> str:
    """``(True, False)`` -> ``"oicm"`` (the file name suffix)."""
    eyes, mouth = state
    return ("oi" if eyes else "ci") + ("om" if mouth else "cm")


def _fallback_order(state: State) -> list[State]:
    """States to try for a wanted state, nearest first (decision 4): closed eyes fall
    back to open eyes, an open mouth to a closed mouth, then the neutral state."""
    eyes, mouth = state
    order = [state, (True, mouth), (eyes, False), (True, False)]
    seen: list[State] = []
    for item in order:
        if item not in seen:
            seen.append(item)
    return seen


@dataclass(frozen=True)
class Expression:
    id: str
    order: int
    folder: str
    # State -> file path relative to the art folder (POSIX, "01_smile/01a_smile_oicm.png").
    sprites: Mapping[State, str]

    @property
    def complete(self) -> bool:
        return all(state in self.sprites for state in STATES)

    @property
    def missing(self) -> list[str]:
        return [state_code(s) for s in STATES if s not in self.sprites]


@dataclass(frozen=True)
class AvatarArt:
    expressions: tuple[Expression, ...]  # by order
    default_expression: str | None  # None only when there are no expressions
    emotion_map: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def get(self, expression_id: str) -> Expression | None:
        key = expression_id.casefold()
        return next((e for e in self.expressions if e.id.casefold() == key), None)

    @property
    def usable(self) -> bool:
        """At least one expression with at least one sprite."""
        return any(e.sprites for e in self.expressions)


@dataclass(frozen=True)
class AvatarConfig:
    default_expression: str | None = None
    emotion_map: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


def parse_config(data: Any) -> AvatarConfig:
    """Read the content of ``avatar.json`` (already JSON-decoded). Bad parts are warnings."""
    if data is None:
        return AvatarConfig()
    if not isinstance(data, dict):
        return AvatarConfig(warnings=(f"{CONFIG_NAME} must hold a JSON object; ignored",))
    warnings: list[str] = []
    default = data.get("default_expression")
    if default is not None and (not isinstance(default, str) or not default.strip()):
        warnings.append(f"{CONFIG_NAME}: default_expression must be a name; ignored")
        default = None
    emotion_map: dict[str, str] = {}
    raw_map = data.get("emotion_map", {})
    if not isinstance(raw_map, dict):
        warnings.append(f"{CONFIG_NAME}: emotion_map must be an object; ignored")
        raw_map = {}
    for emotion, expression in raw_map.items():
        if isinstance(expression, str) and expression.strip():
            emotion_map[str(emotion)] = expression.strip()
        else:
            warnings.append(f"{CONFIG_NAME}: emotion_map[{emotion!r}] must be a name; ignored")
    for key in data:
        if key not in ("default_expression", "emotion_map"):
            warnings.append(f"{CONFIG_NAME}: unknown setting {key!r} ignored")
    return AvatarConfig(
        default_expression=None if default is None else default.strip(),
        emotion_map=emotion_map,
        warnings=tuple(warnings),
    )


def parse_art(
    listing: Mapping[str, Sequence[str]], config: AvatarConfig | None = None
) -> AvatarArt:
    """Expressions and sprites from ``{folder name: [file names]}`` of an art folder.

    Folders not named ``NN_name`` are skipped with a warning; non-PNG files are
    ignored silently (an art folder may hold previews); a PNG that does not follow the
    naming rule, belongs to another folder, or repeats a state is skipped with a
    warning. Two folders with the same expression id: the lower number wins.
    """
    config = config or AvatarConfig()
    warnings: list[str] = list(config.warnings)
    found: list[Expression] = []
    for folder in sorted(listing):
        match = FOLDER_RE.match(folder)
        if match is None:
            warnings.append(f"folder {folder!r} is not named like 01_smile; skipped")
            continue
        number, expr_id = match.group(1), match.group(2)
        if any(e.id.casefold() == expr_id.casefold() for e in found):
            warnings.append(f"folder {folder!r} repeats the expression {expr_id!r}; skipped")
            continue
        sprites: dict[State, str] = {}
        for name in sorted(listing[folder]):
            if not name.lower().endswith(".png"):
                continue
            file_match = FILE_RE.match(name)
            if file_match is None:
                warnings.append(f"{folder}/{name}: name is not like {number}a_{expr_id}_oicm.png; skipped")
                continue
            f_number, _, f_name, eyes, mouth = file_match.groups()
            if f_number != number or f_name.casefold() != expr_id.casefold():
                warnings.append(f"{folder}/{name}: does not match its folder; skipped")
                continue
            state = (eyes.lower() == "oi", mouth.lower() == "om")
            if state in sprites:
                warnings.append(f"{folder}/{name}: a second {state_code(state)} sprite; skipped")
                continue
            sprites[state] = f"{folder}/{name}"
        expression = Expression(expr_id, int(number), folder, sprites)
        if not sprites:
            warnings.append(f"expression {expr_id!r} has no sprites")
        elif not expression.complete:
            warnings.append(
                f"expression {expr_id!r} is missing {', '.join(expression.missing)}; "
                "the nearest state is shown instead"
            )
        found.append(expression)
    found.sort(key=lambda e: (e.order, e.folder))

    with_sprites = [e for e in found if e.sprites]
    default: str | None = with_sprites[0].id if with_sprites else None
    if config.default_expression is not None:
        chosen = next(
            (e for e in with_sprites if e.id.casefold() == config.default_expression.casefold()),
            None,
        )
        if chosen is None:
            warnings.append(
                f"{CONFIG_NAME}: default expression {config.default_expression!r} "
                f"not found; using {default!r}"
            )
        else:
            default = chosen.id
    emotion_map: dict[str, str] = {}
    for emotion, expr_id in config.emotion_map.items():
        target = next((e for e in with_sprites if e.id.casefold() == expr_id.casefold()), None)
        if target is None:
            warnings.append(
                f"{CONFIG_NAME}: emotion {emotion!r} maps to unknown expression {expr_id!r}"
            )
            continue
        emotion_map[emotion] = target.id
    if not found:
        warnings.append("no expression folders found")
    return AvatarArt(tuple(found), default, emotion_map, tuple(warnings))


# --- lookups used by the solver and the renderers ---------------------------------


def resolve_expression(art: AvatarArt, name: str | None) -> tuple[str | None, str | None]:
    """The expression id to show for ``name`` and a warning when it had to fall back.

    ``None`` and ``"neutral"`` mean the default expression, without a warning. A name
    the art lacks (or whose folder has no sprites) falls back to the default.
    """
    if name is None or name.casefold() == NEUTRAL:
        return (art.default_expression, None)
    found = art.get(name)
    if found is not None and found.sprites:
        return (found.id, None)
    return (
        art.default_expression,
        f"expression {name!r} is not in the art; showing {art.default_expression!r}",
    )


def expression_for_emotion(
    art: AvatarArt, emotion: str, preset_expression: str | None
) -> tuple[str | None, str | None]:
    """Expression for a line emotion: ``emotion_map`` first, else the preset's own
    ``expression``, resolved with ``resolve_expression``."""
    mapped = art.emotion_map.get(emotion)
    if mapped is not None:
        return (mapped, None)
    return resolve_expression(art, preset_expression)


def sprite_for(art: AvatarArt, expression_id: str | None, state: State) -> str | None:
    """Relative file of the sprite to draw: the nearest state of that expression, then
    the same search in the default expression. None only when the art has no sprites."""
    candidates: list[Expression] = []
    for expr_id in (expression_id, art.default_expression):
        expression = None if expr_id is None else art.get(expr_id)
        if expression is not None and expression not in candidates:
            candidates.append(expression)
    candidates.extend(e for e in art.expressions if e not in candidates)
    for expression in candidates:
        for wanted in _fallback_order(state):
            path = expression.sprites.get(wanted)
            if path is not None:
                return path
        if expression.sprites:  # a lone odd state still beats nothing
            return expression.sprites[next(s for s in STATES if s in expression.sprites)]
    return None
