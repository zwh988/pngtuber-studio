"""Parity (M6-8): the exported video shows exactly what the compositor draws for the
frame track at each time, over the edited footage.

The preview canvas and the compositor place the avatar with the same maths (checked by
the shared layout fixture in ``test_export_compositor.py`` and ``avatarTrack.test.ts``),
and both pick track frame ``floor(t * 30)``. This test closes the loop on the export
side: for sample output frames of a real ffmpeg render with a moving, turning,
squashing avatar, ``final_1080p.mp4`` must equal ``video_edited.mp4`` with the
compositor's frame laid over it, up to video compression, and the avatar must sit
where the compositor put it. Skipped without ``bin/ffmpeg.exe``.
"""

import math
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
import soundfile
from PIL import Image

from backend.avatar.track import FrameTrack, track_frame_at
from backend.export.compositor import Compositor, SpriteBank, needed_height
from backend.export.editgraph import OutputFormat
from backend.export.runner import make_plan, run_render
from backend.project.schema import Clip, Project, Source

BIN = Path(__file__).resolve().parents[1] / "bin"
FFMPEG = BIN / "ffmpeg.exe"
pytestmark = pytest.mark.skipif(not FFMPEG.is_file(), reason="bin/ffmpeg.exe is not installed")

W, H = 1920, 1080
FMT = OutputFormat(W, H, Fraction(60))
SRC = "1" * 12
SAMPLES = (0, 37, 89, 90, 121, 143, 179)  # output frames (60 fps)


def run(args: list[str]) -> bytes:
    result = subprocess.run(args, capture_output=True, timeout=180, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-2000:]
    return result.stdout


def textured_sprite(path: Path) -> Path:
    """120 x 240: red rises left to right, green top to bottom, a transparent notch."""
    x = np.linspace(0, 255, 120)[None, :].repeat(240, 0)
    y = np.linspace(0, 255, 240)[:, None].repeat(120, 1)
    rgba = np.stack([x, y, np.full_like(x, 60), np.full_like(x, 255)], axis=-1).astype(np.uint8)
    rgba[100:140, 40:80, 3] = 0
    Image.fromarray(rgba, "RGBA").save(path)
    return path


def moving_track() -> FrameTrack:
    n = 91
    k = np.arange(n)
    return FrameTrack(
        version="parity", fps=30, duration_ms=3000, frame_count=n, height_fraction=0.5,
        sprites=["a/oicm"], sprite_runs=[[0, 0], [60, -1], [70, 0]],  # hidden from 2.0 to 2.33 s
        x=list(0.3 + 0.4 * k / n), y=list(0.75 + 0.15 * np.sin(k / 7)),
        scale=list(1.0 + 0.3 * np.sin(k / 11)), rotation=list(20 * np.sin(k / 9)),
        squash=list(0.2 * np.sin(k / 5)),
    )  # fmt: skip


def grab(path: Path, frames: tuple[int, ...]) -> np.ndarray:
    select = "+".join(f"eq(n\\,{n})" for n in frames)
    raw = run([
        str(FFMPEG), "-v", "error", "-i", str(path), "-vf", f"select='{select}'", "-fps_mode", "passthrough",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])  # fmt: skip
    return np.frombuffer(raw, dtype=np.uint8).reshape(len(frames), H, W, 3).astype(np.float32)


def box(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def test_export_frames_equal_the_compositor_over_the_footage(tmp_path: Path) -> None:
    footage = tmp_path / "grey.mkv"
    run([
        str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x404040:s={W}x{H}:r=60:d=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "60", str(footage),
    ])  # fmt: skip
    voice = tmp_path / "voice.wav"
    soundfile.write(str(voice), np.zeros(72_000, dtype=np.float32), 24_000, subtype="FLOAT")
    project = Project(
        name="parity",
        sources=[Source(id=SRC, path="footage/grey.mkv", duration_ms=3000, fps_num=60, width=W, height=H)],
        clips=[Clip(id="a" * 12, source_id=SRC, in_ms=0, out_ms=3000)],
    )
    track = moving_track()
    sprite = textured_sprite(tmp_path / "sprite.png")
    compositor = Compositor(track, SpriteBank({"a/oicm": sprite}, needed_height(track, H)), W, H)
    out = tmp_path / "out"
    plan = make_plan(
        project, {SRC: footage}, FMT, ffmpeg=FFMPEG, voice_wav=voice, avatar=compositor, out_dir=out
    )
    run_render(plan)

    final, edited = grab(plan.final_path, SAMPLES), grab(plan.edited_path, SAMPLES)
    for i, n in enumerate(SAMPLES):
        k = track_frame_at(n * 1000 / 60, track.frame_count)
        assert k == n // 2  # on twos: output frame n shows track frame floor(n / 2)
        layer = np.asarray(compositor.image(k)).astype(np.float32)
        alpha = layer[..., 3:] / 255
        expected = layer[..., :3] * alpha + edited[i] * (1 - alpha)
        inside = alpha[..., 0] > 0.99
        outside = alpha[..., 0] == 0
        error_inside = float(np.abs(final[i] - expected)[inside].mean()) if inside.any() else 0.0
        error_outside = float(np.abs(final[i] - edited[i])[outside].mean())
        assert error_outside < 2.0, (n, error_outside)  # nothing drawn where the avatar is not
        if k in range(60, 70):
            assert not inside.any()  # the hidden stretch draws nothing
            continue
        assert error_inside < 8.0, (n, error_inside)  # same pixels, up to compression
        drawn = np.abs(final[i] - edited[i]).max(axis=-1) > 40
        want, got = box(alpha[..., 0] > 0.5), box(drawn)
        assert max(abs(a - b) for a, b in zip(want, got, strict=True)) <= 3, (n, want, got)
    assert math.isclose(track.rotation[45], 20 * math.sin(45 / 9))  # the sampled poses really turn
