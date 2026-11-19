# M8: Tracks and media (audio files on the timeline, extra video, PNG sequences)

> Drafted 2026-11-19, revised the same day after the user's answer: no work on the recordings' own audio tracks; audio (music, sound effects) comes in by **dragging files onto the timeline**. To start **after M7 is merged** (`m7-done`). Nothing here is built. The questions under "Decisions" are for the user at the start; the answers go into the decisions log in `PROJECT_STATE.md`. Each part is its own branch and the milestone can stop after any part.

- **Milestone items:** M8-1 to M8-3 (to add to `IMPLEMENTATION_PLAN.md` when the milestone starts).
- **Branches:** `m8-1-audio-clips`, then `m8-2` / `m8-3` only if decided.
- **Spec sections:** 4.2 (editor lanes), 5 (data model), 7 (audio chain), 9 (editing), 10 (export).
- **Order and size:** M8-1 (M) → M8-2 (L, optional) → M8-3 (M to L, optional). Decide on M8-2 and M8-3 after M8-1.

## Facts already established (do not re-ask)

- **Not in scope:** choosing or mixing the recordings' own audio streams (an OBS file with mic and game on separate tracks still contributes only its first stream, as now: `[i:a:0]` in `backend/export/editgraph.py`). The user does not need it (2026-11-19).
- **Other tracks today:** `Clip.track` exists (default 0). Clips on other tracks are counted (`TimelineState.other_track_clips`), warned about in the editor and the pre-flight (`other_tracks`), and left out of preview and export.
- **Avatar art is still images:** one PNG per expression and eye/mouth state (`backend/avatar/art.py`). The export *writes* a PNG sequence (the optional overlay); nothing reads one.
- **Voice lines already work the way audio clips will:** placed on a lane, played through Web Audio on the audio clock with a drift restart past 120 ms (`voicePlayback.ts`), mixed by the export (`voicetrack.py`). Audio clips reuse that path.
- **Rules that shape this:** footage is never copied or modified (rule 2: audio clips are not footage); every timed item is anchored to (clip_id, source_time) (rule 4); preview equals export (rule 5); schema changes need a migration (rule 6); every edit is undoable (rule 11).
- **Dropping files from Explorer:** a plain browser drop gives the page the file's bytes but not its path. pywebview can report the full path of dropped files to Python (to confirm with a short spike at the start of M8-1); otherwise the page sends the bytes and the backend saves them.

## Decisions (settle at the start)

1. **Where dropped audio files go.** (a) copied into the project's `audio/` folder (the project stays self-contained; the copy is what the project uses), or (b) referenced where they are, by path, relinked like footage when moved. **Recommendation:** (a): music and sound effects are small next to footage, and a project that still plays after the original file is moved or deleted is worth the copy.
2. **What audio clips follow when you cut.** Rule 4 anchors timed items to the footage, so a cut moves them with the picture. (a) anchor like voice lines (a sound effect stays on its moment in the footage; music jumps at a cut), (b) anchor to the timeline (music keeps playing across cuts; an exception to rule 4, written into `CLAUDE.md`), or (c) per clip: a "Stay with footage" switch, on by default for short clips and off for long ones. **Recommendation:** (c), with (a) for anything under 30 s.
3. **Ducking.** Lower audio clips under the voice lines automatically (a fixed level curve computed from the placements, the same in preview and export), per clip on or off? **Recommendation:** yes, off by default, one "duck under voice" switch per clip with a single depth setting in Settings.
4. **Extra video tracks (M8-2): what for?** (a) B-roll: a clip on track 1 covers the main picture full frame while track 0's audio continues; (b) picture-in-picture with position and scale; (c) skip. **Recommendation:** (a) only, or (c) if audio clips are enough.
5. **PNG sequences (M8-3): which meaning?** (a) animated avatar sprites (a looping idle or talking loop per expression), or (b) a transparent PNG sequence dropped on the video as an overlay (a sticker or effect), which needs M8-2's overlay track. **Recommendation:** ask which one is wanted before planning it in detail.

## Steps

### M8-1 Audio clips by drag and drop (decisions 1 to 3)

1. **Spike (half a step):** drop a file from Explorer onto the pywebview window and get its full path in Python; if that fails, upload the bytes. Decide the import path from the result.
2. **Schema v5:** `audio_clips: list[AudioClip{id, file (project-relative), anchor (clip_id, source_time) or timeline_ms per decision 2, in_ms, out_ms, gain_db, fade_in_ms, fade_out_ms, duck}]`, migration from v4. Commands add, move, trim, set level and fades, set duck, remove (undoable). Orphan handling as for placements when anchored to footage (rule 4).
3. **Import:** dropping one or more audio files (WAV, MP3, FLAC, OGG, M4A) on the timeline imports each (decision 1), probes it with ffprobe, decodes it once to a cached WAV for preview and peaks, and places it at the drop point. A file whose name and size match an earlier import is reused, not copied again.
4. **Timeline:** an Audio lane under the voice lane: blocks with a waveform (the existing peaks code), drag to move, edge-drag to trim, overlaps stacked in sub-rows. An inspector (Line bank style) for level, fades, duck and "Stay with footage".
5. **Preview:** an audio-clip bus in Web Audio, scheduled like the voice lines, with the fades and the duck curve applied as gain automation.
6. **Export:** the clips are mixed into the voice/music track before the final mix and limiter, using the same pure level curve as the preview; each imported file is also listed in `export.json`.
7. **Tests:** migration, commands, the anchoring per decision 2 (cut, ripple-delete, undo), the fade and duck curve (pure), the export mix, import reuse.

### M8-2 Extra video tracks (only if decision 4 is (a) or (b))

B-roll clips on track 1: a second video row, anchored like other items, preview by switching the picture during the clip (a second `<video>`), export with an `overlay` in the edit graph. Size L: the timeline, player and graph all change. Plan in detail only when chosen.

### M8-3 PNG sequences (only if decision 5 is chosen)

- **(a) Animated avatar sprites:** art layout gains optional frame folders per state (for example `01a_neutral_oiom/0001.png ...` plus a frame rate in `avatar.json`); the solver picks the frame from time (pure, rule 5); the frame track and the compositor handle many more images. Size M to L.
- **(b) Overlay sequence:** an overlay item on M8-2's track, read with ffmpeg's `image2` input in the export and as a sprite strip in the preview. Needs M8-2.

## Acceptance checks

- M8-1: dragging a music file and a sound effect onto the timeline places both at the drop point; they play in the preview and the export at the same times and levels, with fades and ducking; cutting the footage behaves as decision 2 says; undo removes each step; old projects open unchanged (migration).
- `uv run pytest`, `uv run ruff check .`, `npm run check`, `npm test` pass; `PROJECT_STATE.md` and the spec sections updated.

## Risks

- **Preview sync:** long music under many cuts is the case to test (the voice lines' drift restart covers short items well).
- **Drop path:** if pywebview cannot hand over file paths, large files go through an upload; fine for music and sound effects, which is all M8-1 accepts.
- **Scope creep:** no EQ or effects on audio clips beyond level, fades and ducking; no recording-stream mixing.
