"""Music and sound effects of an export (M8-1): ``audio_clips.wav``.

The audio-lane clips are mixed with the same rules as the editor preview
(``frontend/src/audioMix.ts``), so what is heard is what is exported (rule 5):

- A clip plays at clip gain + lane gain (dB). It is silent when its lane is muted, or
  when some lane is soloed and its lane is not.
- Fades are linear in amplitude: 0 at the clip start up to full level at
  ``fade_in_ms``; full level at ``length - fade_out_ms`` down to 0 at the clip end.
- A mono file plays on both channels at its own level (Web Audio's up-mix).

Each clip is read from its decoded WAV (48 kHz, ``media/audio_decoded``), placed at
its timeline start and summed into one stereo 32-bit float track as long as the
timeline. Audio past the end of the timeline is left out (the export stops there).
The final mix adds this track to the game audio and the voice before the limiter,
where the preview's music bus joins its limiter too.

``gain_points``, ``audible_lane_ids``, ``audio_clip_schedule``, ``clip_envelope`` and
``mix_audio_clips`` are pure; ``write_audio_clip_track`` reads and writes files.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile

from backend.audio.clipimport import DECODED_RATE
from backend.export.errors import ExportCancelled, ExportError
from backend.export.voicetrack import _write_float_wav, ms_to_samples
from backend.project.schema import AudioClip, AudioLane, Project

AUDIO_CLIPS_NAME = "audio_clips.wav"


def db_to_gain(db: float) -> float:
    return float(10 ** (db / 20))


def gain_points(clip: AudioClip, lane_gain_db: float) -> list[tuple[int, float]]:
    """Level points of a clip: (ms from the clip start, linear gain), in time order.

    The same points as ``gainPoints`` in ``frontend/src/audioMix.ts``.
    """
    length = clip.length_ms
    g = db_to_gain(clip.gain_db + lane_gain_db)
    points: list[tuple[int, float]] = [(0, 0.0 if clip.fade_in_ms > 0 else g)]
    if clip.fade_in_ms > 0:
        points.append((clip.fade_in_ms, g))
    if clip.fade_out_ms > 0:
        out_start = length - clip.fade_out_ms
        if out_start > points[-1][0]:
            points.append((out_start, g))
        points.append((length, 0.0))
    else:
        points.append((length, g))
    return points


def audible_lane_ids(lanes: list[AudioLane]) -> set[str]:
    """Lanes that are heard: not muted, and soloed when any lane is soloed."""
    any_solo = any(lane.solo for lane in lanes)
    return {lane.id for lane in lanes if not lane.mute and (lane.solo or not any_solo)}


@dataclass(frozen=True)
class AudioClipCue:
    clip_id: str
    file_id: str
    start_ms: int
    in_ms: int
    length_ms: int
    points: tuple[tuple[int, float], ...]


def audio_clip_schedule(project: Project, total_ms: int) -> list[AudioClipCue]:
    """The clips that make sound before ``total_ms``, by start time (ties by id)."""
    lanes = {lane.id: lane for lane in project.audio_lanes}
    heard = audible_lane_ids(project.audio_lanes)
    cues = [
        AudioClipCue(
            clip_id=clip.id,
            file_id=clip.file_id,
            start_ms=clip.timeline_ms,
            in_ms=clip.in_ms,
            length_ms=clip.length_ms,
            points=tuple(gain_points(clip, lanes[clip.lane_id].gain_db)),
        )
        for clip in project.audio_clips
        if clip.lane_id in heard and clip.timeline_ms < total_ms
    ]
    return sorted(cues, key=lambda c: (c.start_ms, c.clip_id))


def clip_envelope(
    points: tuple[tuple[int, float], ...], samples: int, rate: int
) -> np.ndarray:
    """Linear gain for each of ``samples`` samples from the clip start."""
    times_ms = np.arange(samples, dtype=np.float64) * (1000.0 / rate)
    xs = np.array([p[0] for p in points], dtype=np.float64)
    ys = np.array([p[1] for p in points], dtype=np.float64)
    return np.interp(times_ms, xs, ys, left=0.0, right=0.0).astype(np.float32)


def _stereo(audio: np.ndarray) -> np.ndarray:
    data = np.asarray(audio, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] == 1:
        return np.repeat(data, 2, axis=1)
    return data[:, :2]


def mix_audio_clips(
    items: list[tuple[AudioClipCue, np.ndarray]], rate: int, total_ms: int
) -> tuple[np.ndarray, float, int]:
    """Sum the clips (each with its file's samples, ``(n,)`` or ``(n, channels)``) into
    a stereo ``(samples, 2)`` track ``total_ms`` long.

    Returns (track, peak, cut_ms): audio past the end is left out and the longest such
    tail reported.
    """
    total = ms_to_samples(max(total_ms, 0), rate)
    track = np.zeros((total, 2), dtype=np.float32)
    cut = 0
    for cue, audio in items:
        data = _stereo(audio)
        first = ms_to_samples(cue.in_ms, rate)
        count = ms_to_samples(cue.length_ms, rate)
        piece = data[first : first + count]
        if piece.shape[0] == 0:
            continue
        piece = piece * clip_envelope(cue.points, piece.shape[0], rate)[:, None]
        start = ms_to_samples(cue.start_ms, rate)
        if start >= total:
            cut = max(cut, piece.shape[0])
            continue
        end = start + piece.shape[0]
        if end > total:
            cut = max(cut, end - total)
            piece = piece[: total - start]
        track[start : start + piece.shape[0]] += piece
    peak = float(np.max(np.abs(track))) if track.size else 0.0
    cut_ms = round(cut * 1000 / rate) if cut else 0
    return track, peak, cut_ms


@dataclass(frozen=True)
class AudioClipTrackReport:
    clips: int
    sample_rate: int
    peak: float
    cut_ms: int
    # Imported files the exported clips use: project path and original name.
    files: list[dict[str, str]]


def write_audio_clip_track(
    project: Project,
    total_ms: int,
    out_dir: Path,
    decoded_paths: Mapping[str, Path],
    *,
    should_stop: Callable[[], bool] = lambda: False,
) -> AudioClipTrackReport | None:
    """Write ``audio_clips.wav`` into ``out_dir``; None when no clip is heard.

    ``decoded_paths`` maps a file id to its decoded 48 kHz WAV. A heard clip whose
    file is not there is an error (pre-flight reports it first).
    """
    cues = audio_clip_schedule(project, total_ms)
    if not cues:
        return None
    files = {f.id: f for f in project.audio_files}
    cache: dict[str, np.ndarray] = {}
    items: list[tuple[AudioClipCue, np.ndarray]] = []
    for cue in cues:
        if should_stop():
            raise ExportCancelled("export cancelled")
        if cue.file_id not in cache:
            path = decoded_paths.get(cue.file_id)
            name = files[cue.file_id].name if cue.file_id in files else cue.file_id
            if path is None or not path.is_file():
                raise ExportError(f"the audio file {name} is missing")
            try:
                data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
            except (OSError, RuntimeError) as exc:
                raise ExportError(f"cannot read the audio file {name}: {exc}") from exc
            if rate != DECODED_RATE:
                raise ExportError(
                    f"{name}: decoded at {rate} Hz, expected {DECODED_RATE}"
                )
            cache[cue.file_id] = data
        items.append((cue, cache[cue.file_id]))
    track, peak, cut_ms = mix_audio_clips(items, DECODED_RATE, total_ms)
    _write_float_wav(out_dir / AUDIO_CLIPS_NAME, track, DECODED_RATE)
    used = sorted({cue.file_id for cue in cues})
    return AudioClipTrackReport(
        clips=len(cues),
        sample_rate=DECODED_RATE,
        peak=peak,
        cut_ms=cut_ms,
        files=[
            {"path": files[i].path, "name": files[i].name} for i in used if i in files
        ],
    )
