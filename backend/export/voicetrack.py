"""Voice tracks of an export (M6-2): ``voice_processed.wav``, ``voice_raw.wav``, ``lines/``.

Every playing placement (not orphaned, on the timeline, with a take) is placed at its
timeline start and overlapping lines are summed (rule 10). Both tracks are mono 32-bit
float WAV at the takes' own rate (24 kHz from Chatterbox), as long as the timeline, so
a sum above 0 dBFS never clips; the final mix limits it. The raw track uses the raw
takes cut, faded and stretched like the processed ones (``render_aligned_raw``), so
the two tracks line up sample for sample.

``voice_schedule``, ``mix_cues`` and ``line_file_name`` are pure; ``write_voice_tracks``
does the file work through callables, so tests can feed it synthetic audio.
"""

import os
import re
import shutil
import threading
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile

from backend.edl.timemap import round_half_up
from backend.export.errors import ExportCancelled, ExportError
from backend.project.timeline import TimelineState

PROCESSED_NAME = "voice_processed.wav"
RAW_NAME = "voice_raw.wav"
LINES_DIR = "lines"
SLUG_MAX = 32


@dataclass(frozen=True)
class VoiceCue:
    placement_id: str
    take_id: str
    stretch: float
    start_ms: int
    duration_ms: int
    line_text: str


@dataclass(frozen=True)
class VoiceTrackReport:
    lines: int
    sample_rate: int
    samples: int
    peak: float  # largest absolute sample of the processed sum (above 1.0: the mix limits it)
    cut_ms: int  # voice audio past the end of the timeline, left out


def voice_schedule(timeline: TimelineState) -> list[VoiceCue]:
    """The placements that make sound, by start time (ties by id)."""
    cues = [
        VoiceCue(
            placement_id=p.id,
            take_id=p.take_id,
            stretch=p.stretch,
            start_ms=p.start_ms,
            duration_ms=p.duration_ms,
            line_text=p.line_text,
        )
        for p in timeline.placements
        if not p.orphaned
        and p.start_ms is not None
        and p.take_id is not None
        and p.duration_ms is not None
    ]
    return sorted(cues, key=lambda c: (c.start_ms, c.placement_id))


def ms_to_samples(ms: int, rate: int) -> int:
    """Sample index of a time in ms (round half up, exact)."""
    return round_half_up(Fraction(ms * rate, 1000))


def mix_cues(
    items: Iterable[tuple[int, np.ndarray]], rate: int, total_ms: int
) -> tuple[np.ndarray, float, int]:
    """Sum mono clips placed at ``start_ms`` into a track ``total_ms`` long.

    Returns (track, peak, cut_ms): audio past the end is left out and its length
    (the longest such tail) reported.
    """
    total = ms_to_samples(max(total_ms, 0), rate)
    track = np.zeros(total, dtype=np.float32)
    cut = 0
    for start_ms, audio in items:
        start = ms_to_samples(start_ms, rate)
        clip = np.asarray(audio, dtype=np.float32).reshape(-1)
        end = start + clip.size
        if start >= total:
            cut = max(cut, clip.size)
            continue
        if end > total:
            cut = max(cut, end - total)
            clip = clip[: total - start]
        track[start : start + clip.size] += clip
    peak = float(np.max(np.abs(track))) if track.size else 0.0
    cut_ms = round_half_up(Fraction(cut * 1000, rate)) if cut else 0
    return track, peak, cut_ms


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = slug[:SLUG_MAX].rstrip("-")
    return slug or "line"


def line_file_name(index: int, start_ms: int, text: str) -> str:
    """``001_01-05_hello-there.wav``: order, timeline start (minutes-seconds), text."""
    seconds = max(start_ms, 0) // 1000
    return f"{index:03d}_{seconds // 60:02d}-{seconds % 60:02d}_{_slug(text)}.wav"


def _write_float_wav(dest: Path, samples: np.ndarray, rate: int) -> None:
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            soundfile.write(str(tmp), samples, rate, subtype="FLOAT", format="WAV")
            os.replace(tmp, dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    except (OSError, RuntimeError) as exc:
        raise ExportError(f"cannot write {dest.name}: {exc}") from exc


def _read(path: Path) -> tuple[np.ndarray, int]:
    try:
        data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    except (OSError, RuntimeError) as exc:
        raise ExportError(f"cannot read {path.name}: {exc}") from exc
    return data.mean(axis=1) if data.shape[1] > 1 else data[:, 0], int(rate)


def write_voice_tracks(
    cues: list[VoiceCue],
    total_ms: int,
    out_dir: Path,
    *,
    processed_for: Callable[[VoiceCue], Path],
    raw_for: Callable[[VoiceCue], tuple[np.ndarray, int]],
    should_stop: Callable[[], bool] = lambda: False,
    progress: Callable[[float], None] = lambda fraction: None,
) -> VoiceTrackReport:
    """Write both voice tracks and one processed file per cue into ``out_dir``.

    ``processed_for`` gives the processed take file of a cue (rendered if needed);
    ``raw_for`` the aligned raw audio. All takes must share one sample rate.
    """
    lines_dir = out_dir / LINES_DIR
    processed: list[tuple[int, np.ndarray]] = []
    raw: list[tuple[int, np.ndarray]] = []
    rate: int | None = None
    for index, cue in enumerate(cues, start=1):
        if should_stop():
            raise ExportCancelled("export cancelled")
        path = processed_for(cue)
        audio, take_rate = _read(path)
        raw_audio, raw_rate = raw_for(cue)
        for r in (take_rate, raw_rate):
            if rate is None:
                rate = r
            elif r != rate:
                raise ExportError(
                    f"takes have different sample rates ({rate} and {r} Hz); cannot mix them"
                )
        processed.append((cue.start_ms, audio))
        raw.append((cue.start_ms, raw_audio))
        dest = lines_dir / line_file_name(index, cue.start_ms, cue.line_text)
        try:
            lines_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
        except OSError as exc:
            raise ExportError(f"cannot write {dest.name}: {exc}") from exc
        progress(index / (len(cues) + 1))
    rate = rate if rate is not None else 24_000
    track, peak, cut_ms = mix_cues(processed, rate, total_ms)
    _write_float_wav(out_dir / PROCESSED_NAME, track, rate)
    raw_track, _, _ = mix_cues(raw, rate, total_ms)
    _write_float_wav(out_dir / RAW_NAME, raw_track, rate)
    progress(1.0)
    return VoiceTrackReport(
        lines=len(cues), sample_rate=rate, samples=int(track.size), peak=peak, cut_ms=cut_ms
    )
