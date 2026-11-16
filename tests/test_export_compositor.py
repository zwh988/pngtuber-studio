"""Avatar compositor (M6-4): placement maths shared with the preview, drawing with
Pillow, frame caching, the overlay-off spans and the floor frame rule."""

import json
from pathlib import Path

import pytest
from PIL import Image

from backend.avatar.art import parse_art
from backend.avatar.solver import BaseTransform, SolverInput, build_solver
from backend.avatar.track import (
    FrameTrack,
    build_frame_track,
    input_version,
    track_frame_at,
)
from backend.export.compositor import (
    SPRITE_PAD,
    Compositor,
    SpriteBank,
    corners,
    layout,
    needed_height,
    screen_box,
    sprite_files,
    sprite_frames,
)
from backend.export.errors import ExportError

FIXTURE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "avatarLayout.fixture.json"


@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"])
def test_layout_matches_the_shared_fixture(case: dict) -> None:
    p, f = case["pose"], case["frame"]
    lay = layout(
        p["x"], p["y"], p["scale"], p["rotation"], p["squash"], f["width"], f["height"],
        case["imageAspect"], case["heightFraction"], f["left"], f["top"],
    )  # fmt: skip
    for name, value in case["expected"].items():
        assert getattr(lay, name) == pytest.approx(value, abs=1e-6)


def test_corners_and_box() -> None:
    lay = layout(0.5, 1.0, 1.0, 0.0, 0.0, 400, 300, 0.5, 0.5)  # 75 x 150, bottom centre (200, 300)
    assert corners(lay) == [(162.5, 150.0), (237.5, 150.0), (237.5, 300.0), (162.5, 300.0)]
    assert screen_box(lay, 400, 300) == (162, 150, 238, 300)
    turned = layout(0.5, 1.0, 1.0, 90.0, 0.0, 400, 300, 0.5, 0.5)
    x0, _y0, x1, y1 = screen_box(turned, 400, 300) or (0, 0, 0, 0)
    assert (x0, x1, y1) == (200, 350, 300)  # the top now points right; bottom half off screen
    gone = layout(2.0, 1.0, 1.0, 0.0, 0.0, 400, 300, 0.5, 0.5)
    assert screen_box(gone, 400, 300) is None


def make_sprite(path: Path, w: int = 100, h: int = 200) -> Path:
    """Top quarter green, below it the left half red and the right half blue."""
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    image.paste((0, 255, 0, 255), (0, 0, w, h // 4))
    image.paste((255, 0, 0, 255), (0, h // 4, w // 2, h))
    image.paste((0, 0, 255, 255), (w // 2, h // 4, w, h))
    image.save(path)
    return path


def track(**kw: object) -> FrameTrack:
    base = {
        "version": "v", "fps": 30, "duration_ms": 100, "frame_count": 4, "height_fraction": 0.5,
        "sprites": ["a/oicm"], "sprite_runs": [[0, 0], [3, -1]],
        "x": [0.5] * 4, "y": [1.0] * 4, "scale": [1.0] * 4, "rotation": [0.0] * 4, "squash": [0.0] * 4,
    }  # fmt: skip
    base.update(kw)
    return FrameTrack(**base)


def colour(image: Image.Image, x: int, y: int) -> str:
    r, g, b, a = image.getpixel((x, y))
    if a < 10:
        return "clear"
    return {(255, 0, 0): "red", (0, 255, 0): "green", (0, 0, 255): "blue"}.get((r, g, b), f"{r},{g},{b},{a}")


def compositor(tmp_path: Path, **kw: object) -> Compositor:
    t = track(**kw)
    bank = SpriteBank({"a/oicm": make_sprite(tmp_path / "a.png")}, needed_height(t, 300))
    return Compositor(t, bank, 400, 300)


def test_draws_the_sprite_upright_at_its_anchor(tmp_path: Path) -> None:
    image = compositor(tmp_path).image(0)
    assert image.size == (400, 300) and image.mode == "RGBA"
    assert colour(image, 180, 250) == "red"
    assert colour(image, 220, 250) == "blue"
    assert colour(image, 200, 160) == "green"
    assert colour(image, 200, 140) == "clear"  # above the sprite
    assert colour(image, 150, 250) == "clear"  # left of it


def test_rotation_and_squash(tmp_path: Path) -> None:
    turned = compositor(tmp_path, rotation=[90.0] * 4, y=[0.5] * 4).image(0)  # anchor (200, 150)
    assert colour(turned, 200 + 135, 150 - 18) == "green"  # the top points right
    assert colour(turned, 200 + 60, 150 - 18) == "red"  # the left half is above the anchor
    assert colour(turned, 200 + 60, 150 + 18) == "blue"
    wide = compositor(tmp_path, squash=[0.5] * 4).image(0)  # 1.5x wide, half as tall
    assert colour(wide, 200 - 50, 280) == "red"  # beyond the unsquashed half width (37.5)
    assert colour(wide, 200, 140) == "clear"  # only 75 px tall now
    assert colour(wide, 200, 230) != "clear"


def test_edges_use_premultiplied_alpha(tmp_path: Path) -> None:
    image = compositor(tmp_path, scale=[0.73] * 4, rotation=[7.0] * 4).image(0)
    data = image.tobytes()
    pixels = [tuple(data[i : i + 4]) for i in range(0, len(data), 4)]
    soft = [(r, g, b) for r, g, b, a in pixels if 20 < a < 235]
    assert soft, "expected some anti-aliased edge pixels"
    # Straight-alpha blending would darken them (red at half alpha would read 127, 0, 0);
    # where two colours meet at the edge they share the brightness (176, 78, 0).
    assert all(sum(px) > 200 for px in soft)


def test_frame_bytes_and_blank(tmp_path: Path) -> None:
    comp = compositor(tmp_path)
    first = comp.frame_bytes(0)
    assert len(first) == comp.frame_size == 400 * 300 * 4
    assert first == comp.image(0).tobytes()
    assert comp.frame_bytes(3) == bytes(400 * 300 * 4)


def test_frames_stream_equals_single_frames_and_skips_repeats(tmp_path: Path) -> None:
    kw = {
        "frame_count": 8,
        "sprite_runs": [[0, 0], [5, -1], [6, 0]],
        "x": [0.5, 0.5, 0.6, 0.6, 0.6, 0.6, 0.4, 0.4],
        "y": [1.0] * 8, "scale": [1.0] * 8, "rotation": [0.0, 0.0, 0.0, 5.0, 5.0, 5.0, 0.0, 0.0],
        "squash": [0.0] * 8,
    }  # fmt: skip
    single = compositor(tmp_path, **kw)
    expected = [single.frame_bytes(k) for k in range(8)]
    stream = compositor(tmp_path, **kw)
    got = [bytes(view) for view in stream.frames()]
    assert got == expected  # the box is cleared and redrawn correctly between frames
    assert stream.draws == 4  # frames 0, 2, 3, 6 differ from the frame before; 5 is blank
    part = compositor(tmp_path, **kw)
    assert [bytes(v) for v in part.frames(2, 4)] == expected[2:4]
    early = compositor(tmp_path, **kw).frames()
    next(early)
    early.close()  # stopping early shuts the worker threads down


def test_sprite_frames_and_needed_height() -> None:
    t = track(frame_count=6, sprite_runs=[[0, 0], [2, -1], [4, 0]], x=[0.5] * 6, y=[1.0] * 6,
              scale=[1.0, 2.0, 1.0, 1.0, 1.0, 1.0], rotation=[0.0] * 6,
              squash=[0, 0, 0, 0, -0.25, 0])  # fmt: skip
    assert sprite_frames(t) == [0, 0, -1, -1, 0, 0]
    assert needed_height(t, 1080) == 1080  # 0.5 * 1080 * 2.0
    assert needed_height(track(scale=[1.0] * 4, squash=[-0.25] * 4), 1000) == 625


def test_sprite_files_and_bank_errors(tmp_path: Path) -> None:
    art = parse_art({"01_a": ["01a_a_oicm.png"]})
    files = sprite_files(track(), art, tmp_path)
    assert files == {"a/oicm": tmp_path / "01_a" / "01a_a_oicm.png"}
    with pytest.raises(ExportError, match="no sprite"):
        sprite_files(track(sprites=["b/oicm"]), art, tmp_path)
    with pytest.raises(ExportError, match="cannot read"):
        SpriteBank(files, 100).image("a/oicm")


def test_bank_prepares_a_smaller_copy_once(tmp_path: Path) -> None:
    bank = SpriteBank({"a/oicm": make_sprite(tmp_path / "a.png", 100, 200)}, 50)
    image = bank.image("a/oicm")
    assert image.size == (25 + 2 * SPRITE_PAD, 50 + 2 * SPRITE_PAD) and image.mode == "RGBa"
    assert bank.image("a/oicm") is image
    assert bank.aspect("a/oicm") == 0.5


def test_floor_frame_rule() -> None:
    assert [track_frame_at(ms, 31) for ms in (0, 33, 34, 49, 51, 100, 1000 / 30, -5, 99_999)] == [
        0, 0, 1, 1, 1, 3, 1, 0, 30,
    ]  # fmt: skip
    assert track_frame_at(500, 0) == 0


def test_overlay_off_spans_hide_the_avatar_and_change_the_version() -> None:
    art = parse_art({"01_a": ["01a_a_oicm.png", "01a_a_oiom.png", "01a_a_cicm.png", "01a_a_ciom.png"]})
    plain = SolverInput(duration_ms=1000, seed=1, base=BaseTransform(), default_expression="a")
    hidden = SolverInput(
        duration_ms=1000, seed=1, base=BaseTransform(), default_expression="a", hidden=[(0, 400)]
    )
    solver = build_solver(hidden)
    assert not solver.query(0).visible and not solver.query(399).visible and solver.query(400).visible
    frames = build_frame_track(solver, art, "v")
    assert frames.sprite_runs[0] == [0, -1] and frames.sprite_runs[1][0] == 12  # 400 ms at 30 fps
    assert input_version(plain, art) != input_version(hidden, art)
