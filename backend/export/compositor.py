"""Avatar compositor for the export (M6-4): draws the frame track with the full-size art.

The frame track (``backend/avatar/track.py``) is the solver sampled at 30 fps; this
module only DRAWS it (rule 5), with the same placement maths as the preview canvas
(``frontend/src/avatarTrack.ts`` ``layout``): the sprite's bottom centre sits at
(x * width, y * height), at scale 1 it is ``height_fraction`` of the frame high, it
turns about that point and squash makes it (1 + squash) wider and (1 - squash) taller.
A shared fixture (``frontend/src/avatarLayout.fixture.json``) is checked by pytest and
vitest, so both sides place the avatar the same way.

Drawing: each sprite is scaled down once to the largest height the track needs
(premultiplied alpha, Lanczos), then every frame is one affine transform of that copy
into the sprite's on-screen box (bilinear), pasted on a transparent full frame. Each
output is straight-alpha RGBA, ready for ffmpeg ``overlay`` or a PNG file.
"""

import math
from collections import deque
from collections.abc import Iterator, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from backend.avatar.art import AvatarArt
from backend.avatar.track import FrameTrack, sprite_path_for_key
from backend.export.errors import ExportError


@dataclass(frozen=True)
class Layout:
    """Where a sprite lands: anchor (bottom centre), size at squash 0, rotation in
    radians, and the squash factors. Same fields as ``Layout`` in avatarTrack.ts."""

    ax: float
    ay: float
    w: float
    h: float
    rot: float
    sx: float
    sy: float


def layout(
    x: float,
    y: float,
    scale: float,
    rotation_deg: float,
    squash: float,
    frame_w: float,
    frame_h: float,
    image_aspect: float,
    height_fraction: float,
    left: float = 0.0,
    top: float = 0.0,
) -> Layout:
    h = height_fraction * frame_h * scale
    return Layout(
        ax=left + x * frame_w,
        ay=top + y * frame_h,
        w=h * image_aspect,
        h=h,
        rot=rotation_deg * math.pi / 180,
        sx=1 + squash,
        sy=1 - squash,
    )


def corners(lay: Layout) -> list[tuple[float, float]]:
    """Screen corners of the sprite (top left, top right, bottom right, bottom left)."""
    cos, sin = math.cos(lay.rot), math.sin(lay.rot)
    out = []
    for u, v in ((-lay.w / 2, -lay.h), (lay.w / 2, -lay.h), (lay.w / 2, 0.0), (-lay.w / 2, 0.0)):
        px, py = u * lay.sx, v * lay.sy
        out.append((lay.ax + px * cos - py * sin, lay.ay + px * sin + py * cos))
    return out


def screen_box(lay: Layout, frame_w: int, frame_h: int) -> tuple[int, int, int, int] | None:
    """Integer pixel box (x0, y0, x1, y1) the sprite covers, clipped to the frame;
    None when nothing of it is on screen."""
    pts = corners(lay)
    x0 = max(0, math.floor(min(p[0] for p in pts)))
    y0 = max(0, math.floor(min(p[1] for p in pts)))
    x1 = min(frame_w, math.ceil(max(p[0] for p in pts)))
    y1 = min(frame_h, math.ceil(max(p[1] for p in pts)))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def affine_for(
    lay: Layout, box_x: int, box_y: int, sprite_w: int, sprite_h: int, pad: int = 0
) -> tuple[float, float, float, float, float, float]:
    """Pillow AFFINE data mapping a pixel of the box (origin at screen (box_x, box_y))
    back to the sprite image: screen -> undo translate, rotate, squash -> sprite px.
    ``sprite_w`` x ``sprite_h`` is the picture itself; ``pad`` transparent pixels
    around it in the image (so edges blend: Pillow never blends past the border)."""
    if lay.w <= 0 or lay.h <= 0 or lay.sx == 0 or lay.sy == 0:
        raise ValueError("the sprite has no size")
    cos, sin = math.cos(lay.rot), math.sin(lay.rot)
    kx, ky = sprite_w / lay.w, sprite_h / lay.h
    ox, oy = box_x - lay.ax, box_y - lay.ay
    a, b = kx / lay.sx * cos, kx / lay.sx * sin
    d, e = -ky / lay.sy * sin, ky / lay.sy * cos
    c = a * ox + b * oy + kx * lay.w / 2 + pad
    f = d * ox + e * oy + ky * lay.h + pad
    return a, b, c, d, e, f


def sprite_frames(track: FrameTrack) -> list[int]:
    """The sprite table index of every frame (-1: nothing drawn), from the runs."""
    out = [-1] * track.frame_count
    runs = track.sprite_runs
    for i, (start, index) in enumerate(runs):
        end = runs[i + 1][0] if i + 1 < len(runs) else track.frame_count
        for k in range(max(start, 0), min(end, track.frame_count)):
            out[k] = index
    return out


def needed_height(track: FrameTrack, frame_h: int) -> int:
    """Pixel height to prepare the sprites at: the tallest the track ever draws one."""
    tallest = 0.0
    for scale, squash in zip(track.scale, track.squash, strict=True):
        tallest = max(tallest, scale * (1 + abs(squash)))
    return max(1, math.ceil(track.height_fraction * frame_h * tallest))


def sprite_files(track: FrameTrack, art: AvatarArt, art_root: Path) -> dict[str, Path]:
    """Full-size file of every sprite the track uses, by its key ``expression/state``."""
    files: dict[str, Path] = {}
    for key in track.sprites:
        expression, _, state = key.partition("/")
        rel = sprite_path_for_key(art, expression, state)
        if rel is None:
            raise ExportError(f"the avatar art has no sprite {key}")
        files[key] = art_root / Path(*rel.split("/"))
    return files


def _pil() -> Any:
    try:
        from PIL import Image
    except ImportError as exc:
        raise ExportError("Pillow is not installed: run `uv add pillow`") from exc
    return Image


SPRITE_PAD = 2  # transparent pixels around a prepared sprite


class SpriteBank:
    """Sprites prepared once for drawing: premultiplied RGBA, at most ``height`` high
    (plus ``SPRITE_PAD`` transparent pixels on every side)."""

    def __init__(self, files: Mapping[str, Path], height: int) -> None:
        self._files = dict(files)
        self._height = height
        self._images: dict[str, Any] = {}
        self._aspects: dict[str, float] = {}

    def _load(self, key: str) -> None:
        image_mod = _pil()
        path = self._files.get(key)
        if path is None:
            raise ExportError(f"no file for sprite {key}")
        try:
            with image_mod.open(path) as image:
                image.load()
                rgba = image.convert("RGBA")
        except (OSError, ValueError) as exc:
            raise ExportError(f"cannot read the sprite {path.name}: {exc}") from exc
        self._aspects[key] = rgba.width / rgba.height
        premultiplied = rgba.convert("RGBa")
        if premultiplied.height > self._height:
            width = max(1, round(premultiplied.width * self._height / premultiplied.height))
            premultiplied = premultiplied.resize(
                (width, self._height), image_mod.Resampling.LANCZOS
            )
        padded = image_mod.new(
            "RGBa",
            (premultiplied.width + 2 * SPRITE_PAD, premultiplied.height + 2 * SPRITE_PAD),
            (0, 0, 0, 0),
        )
        padded.paste(premultiplied, (SPRITE_PAD, SPRITE_PAD))
        self._images[key] = padded

    def image(self, key: str) -> Any:
        if key not in self._images:
            self._load(key)
        return self._images[key]

    def aspect(self, key: str) -> float:
        """Width over height of the full-size file (what the preview's image has)."""
        if key not in self._aspects:
            self._load(key)
        return self._aspects[key]


Piece = tuple[int, int, np.ndarray]  # x0, y0 and a straight-alpha RGBA array (h, w, 4)


class Compositor:
    """Draws the frame track. ``piece`` draws one frame's sprite box (thread-safe once
    the sprites are loaded); ``frames`` yields every frame as one reused full-frame
    buffer, drawing ahead on ``workers`` threads (Pillow releases the GIL while it
    transforms). Only the sprite's box changes between frames, so the full 8 MB frame is
    never rebuilt, and a frame with the same sprite and pose as the one before it is
    not drawn again."""

    def __init__(
        self, track: FrameTrack, bank: SpriteBank, width: int, height: int, workers: int = 3
    ) -> None:
        self.track = track
        self.bank = bank
        self.width = width
        self.height = height
        self.workers = max(1, workers)
        self.draws = 0  # how many pieces were drawn (tests, progress)
        self._sprites = sprite_frames(track)

    @property
    def frame_count(self) -> int:
        return self.track.frame_count

    @property
    def frame_size(self) -> int:
        return self.width * self.height * 4

    def pose(self, k: int) -> tuple[int, float, float, float, float, float]:
        t = self.track
        return (self._sprites[k], t.x[k], t.y[k], t.scale[k], t.rotation[k], t.squash[k])

    def preload(self) -> None:
        for key in self.track.sprites:
            self.bank.image(key)

    def piece(self, k: int) -> Piece | None:
        """The drawn sprite box of frame ``k``; None when nothing shows."""
        image_mod = _pil()
        index, x, y, scale, rotation, squash = self.pose(k)
        if index < 0 or scale <= 0:
            return None
        key = self.track.sprites[index]
        sprite = self.bank.image(key)
        lay = layout(
            x, y, scale, rotation, squash, self.width, self.height,
            self.bank.aspect(key), self.track.height_fraction,
        )  # fmt: skip
        if lay.sy <= 0 or lay.sx <= 0:
            return None
        box = screen_box(lay, self.width, self.height)
        if box is None:
            return None
        x0, y0, x1, y1 = box
        drawn = sprite.transform(
            (x1 - x0, y1 - y0),
            image_mod.Transform.AFFINE,
            affine_for(
                lay,
                x0,
                y0,
                sprite.width - 2 * SPRITE_PAD,
                sprite.height - 2 * SPRITE_PAD,
                SPRITE_PAD,
            ),
            resample=image_mod.Resampling.BILINEAR,
            fillcolor=(0, 0, 0, 0),
        )
        self.draws += 1
        return x0, y0, np.asarray(drawn.convert("RGBA"))

    def image(self, k: int) -> Any:
        """Frame ``k`` as a straight-alpha RGBA Pillow image of the full frame (PNG files)."""
        image_mod = _pil()
        canvas = image_mod.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        found = self.piece(k)
        if found is not None:
            x0, y0, array = found
            canvas.paste(image_mod.fromarray(array, "RGBA"), (x0, y0))
        return canvas

    def frame_bytes(self, k: int) -> bytes:
        """Raw RGBA bytes of one frame (width * height * 4)."""
        buffer = _FrameBuffer(self.width, self.height)
        buffer.show(self.piece(k))
        return bytes(buffer.view())

    def frames(self, start: int = 0, stop: int | None = None) -> Iterator[memoryview]:
        """Every frame from ``start`` to ``stop`` as raw RGBA. The view is one reused
        buffer: use it (write it to the pipe) before asking for the next frame."""
        stop = self.frame_count if stop is None else min(stop, self.frame_count)
        self.preload()
        buffer = _FrameBuffer(self.width, self.height)
        window = self.workers * 4
        pending: deque[tuple[int, Future[Piece | None] | None]] = deque()
        pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="avatar")
        next_k = start
        previous: object = None
        try:
            for _ in range(start, stop):
                while next_k < stop and len(pending) < window:
                    pose = self.pose(next_k)
                    same = pose == previous
                    previous = pose
                    pending.append((next_k, None if same else pool.submit(self.piece, next_k)))
                    next_k += 1
                _, future = pending.popleft()
                if future is not None:
                    buffer.show(future.result())
                yield buffer.view()
        finally:
            pool.shutdown(wait=True, cancel_futures=True)


class _FrameBuffer:
    """One full RGBA frame, changed only where the sprite was and is."""

    def __init__(self, width: int, height: int) -> None:
        self.array = np.zeros((height, width, 4), dtype=np.uint8)
        self._box: tuple[int, int, int, int] | None = None

    def show(self, piece: Piece | None) -> None:
        if self._box is not None:
            x0, y0, x1, y1 = self._box
            self.array[y0:y1, x0:x1] = 0
            self._box = None
        if piece is not None:
            x0, y0, array = piece
            h, w = array.shape[:2]
            self.array[y0 : y0 + h, x0 : x0 + w] = array
            self._box = (x0, y0, x0 + w, y0 + h)

    def view(self) -> memoryview:
        return memoryview(self.array.reshape(-1))
