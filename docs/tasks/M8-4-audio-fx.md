# M8-4: Audio FX on audio clips

- **Milestone item:** `IMPLEMENTATION_PLAN.md` M8-4 (audio FX on audio clips, one FX chain per clip; user 2026-11-20)
- **Spec sections:** 4.2, 5, 7, 10
- **Status:** done (branch `m8-4-audio-fx`, 2026-11-23; user confirmed in the app; not merged yet)

## Goal

Each music or sound-effect clip on an audio lane can have its own FX chain (EQ, compressor, effects, optional loudness levelling). The preview and the export play the same rendered audio (rule 5).

## How it works now (found in the code)

- Voice chain: `FxChain` (3-band EQ, compressor, effects list, loudness target) -> `processing_spec` (`backend/audio/chainspec.py`) -> Pedalboard render of a mono take (`backend/audio/render.py`), cached by key (rule 3). Effects come from one registry (`backend/audio/effects.py`: pitch shift, chorus).
- Audio clips: each imported file is decoded once to `media/audio_decoded/<file id>.wav`; the preview plays it through the music bus (`frontend/src/audioClipPlayback.ts`, `/media/audio/{id}`), the export mixes the same WAV (`backend/export/audioclips.py`). Clip level, fades and lane level are applied on top.

## Scope

**In:** a per-clip chain, its processing and cache, preview and export of the processed audio, the FX tab following the selection, apply to selected clips, reset.
**Out:** new effect types (decision 2), FX on the main footage sound, on lane recordings or on the whole music bus, presets for clip chains.

## Steps (each: user checks in the app, then a commit)

1. **Decisions** (below), logged here and in `PROJECT_STATE.md`.
2. **Data and maths:** `AudioClip.fx` (schema v10, None = no FX), commands (set, reset, apply one chain to several clips; undoable), the clip processing spec and its cache key (pure, tested).
3. **Render and serve:** the decoded file through the clip's chain (stereo, Pedalboard), cached by (file, spec), rendered in the background; a media route; the preview plays the processed file for a clip with FX.
4. **UI:** the FX tab follows the selection (voice, or the selected audio clip), an FX badge on the clip and in the clip bar, apply to selected clips, reset.
5. **Export:** `audio_clips.wav` mixes the processed audio; pre-flight for a chain that cannot be rendered; a test that the export and the preview file match.
6. **Wrap-up:** `PROJECT_STATE.md`, spec as built.

## Decisions

| # | Question | Answer |
|---|---|---|
| 1 | Which stages? | EQ, compressor and the effect list (no silence trim, no stretch). Loudness levelling off by default, a switch with its own target. Clip level and fades stay as they are (user, as recommended) |
| 2 | New effect types? | No: pitch shift and chorus only for now (user) |
| 3 | Preview | A rendered copy like the voice: the clip's file through its chain, cached by file and chain, so moving or trimming never re-renders; preview and export play that file (user, as recommended) |
| 4 | Where to edit | The Voice FX tab becomes "FX" and follows the selection: an audio clip's chain when one is selected, else the voice. Apply the clip's FX to every selected audio clip; reset. An FX badge on the clip (user, as recommended) |
| - | Assumption (stated) | The chain processes the clip's whole file once; the cut, fades, clip level and lane level come after it, so a reverb tail stops at the clip's end |

## As built

- Steps 2 to 5 landed in one commit (they share `session.py` and the tests); step 6 is the docs.
- Renders are made on demand (the preview's first request, pre-flight, export inputs), not by a background thread.

## Acceptance criteria

- [x] A clip's FX are heard in the preview and in the export, and they sound the same (same file)
- [x] Moving, trimming or splitting a clip never re-renders; changing its FX renders once
- [x] Every change is one undo step; old projects open (migration)
- [x] Tests for all pure logic; pytest, ruff, `npm run check`, `npm test`, `npm run build` clean
- [x] `PROJECT_STATE.md` and spec updated
