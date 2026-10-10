# PROJECT_STATE.md

Living document: how the project works right now and where everything lives. **Update it at the end of every task** (see the checklist in `CLAUDE.md`). Keep it factual and short; link to files instead of copying code.

- **Last updated:** 2026-10-10 (scaffold created, no code yet)
- **Current milestone:** M0 (risk spike), not started
- **Overall status:** design complete, repository scaffolded, nothing implemented

## How to run / test

Not runnable yet. Planned: `install.bat` (uv env + CUDA torch + model download) and `run.bat` (starts backend and opens the window). Update this section as soon as M0 produces a working command.

```
# fill in when real:
# setup:  ...
# run:    ...
# tests:  ...
```

## Repo map

Status values: `empty` (placeholder only), `partial`, `done`.

| Path | Purpose | Status |
|---|---|---|
| `CLAUDE.md` | AI instructions and business rules | done |
| `PROJECT_STATE.md` | this file | done |
| `IMPLEMENTATION_PLAN.md` | milestones and task checklist | done |
| `docs/DESIGN_SPEC.md` | full design spec (source of truth for behavior) | done |
| `docs/tasks/` | per-task breakdown files (`_TEMPLATE.md`, `M0-spike.md`) | partial |
| `backend/app.py` | FastAPI entry point | not created |
| `backend/project/` | project load/save, schema, undo/commands, migrations | empty |
| `backend/edl/` | clip list, time mapping, anchoring, ffmpeg graph builder | empty |
| `backend/voice/` | GPU worker, takes, cache keys, queue | empty |
| `backend/audio/` | FX chain, loudness, envelopes | empty |
| `backend/avatar/` | art loader, solver, compositor | empty |
| `backend/export/` | export pipeline, asset bundle | empty |
| `frontend/` | Svelte app (`src/`) | empty |
| `bin/` | ffmpeg/ffprobe (git-ignored) | empty |
| `templates/` | default channel template, emotion presets | empty |
| `scripts/` | install/run helpers | empty |
| `tests/` | pytest suites, small fixtures | empty |

## Project folder layout (user data, not in this repo)

```
MyRack/
  project.json          source of truth
  project.json.bak
  footage/              user places recordings here (never copied)
  media/takes_raw/  media/takes_fx/  media/envelopes/
  exports/
```

## Schema and key interfaces

Not implemented yet. When M1 lands, list here: the schema file path, `schema_version`, the command API, and the main backend endpoints/WebSocket events (one line each, with file paths).

## Decisions log

| Date | Decision |
|---|---|
| 2026-10-10 | Windows + NVIDIA 6GB+; Python backend + pywebview shell, fully offline after first run |
| 2026-10-10 | Footage editing = cut, splice, speed via an edit decision list (clip list + effects registry), built to scale |
| 2026-10-10 | Footage is placed manually in the project `footage/` folder; app never copies it |
| 2026-10-10 | Lines live in a per-project bank, are placed later; every generation is a kept take |
| 2026-10-10 | Overflow: warning + one-click fixes (tighten, nudge, regenerate); per-line allow-overlap |
| 2026-10-10 | Cloned voice via Chatterbox; voice profile abstraction so the reference can change |
| 2026-10-10 | Emotion = presets + per-line sliders (exaggeration, cfg_weight) |
| 2026-10-10 | Avatar drawn live; Python solver is single source of truth; expression, parameter lanes, and reactions are keyframed |
| 2026-10-10 | Mouth from loudness envelope (Rhubarb deferred) |
| 2026-10-10 | Game audio fixed level; voice bus = 3-band EQ, optional compressor, effects, LUFS normalize |
| 2026-10-10 | Export: 1080p MP4 + asset bundle (raw/processed voice, edited video, hard-linked raw video, optional overlay) |
| 2026-10-10 | Channel template auto-applies intro/outro, voice, FX, avatar, export defaults; bookends are ordinary clips |
| 2026-10-10 | Correction: Chatterbox `cfg_weight` is pacing guidance (lower = slower, more deliberate), not literal speed |
| 2026-10-10 | Work method: plain chat with no agent tooling; user pastes files in, applies output and runs everything by hand on Windows PowerShell |

## Known issues / open questions

- Prerequisites not yet confirmed on the user's machine: Git, uv, current NVIDIA driver, ffmpeg build with NVENC (see `docs/tasks/M0-spike.md`).
- Voice source not final: own voice or acted character (swappable via voice profile).
- Effects slot contents not chosen (reverb, pitch shift, chorus, others).
- Avatar art naming convention `expression_eyes_mouth.png` to be confirmed against real files.
- Recording frame rate (30 or 60) to be confirmed.
- Emotion preset numbers are starting guesses; tune by ear in M3.
- Chatterbox Python API details must be verified against its current README in M0.

## Next up

1. M0 risk spike: see `docs/tasks/M0-spike.md`.
