# M1: Project foundation

- **Milestone items:** M1-1 to M1-7 in `IMPLEMENTATION_PLAN.md`
- **Spec sections:** 2 (decisions), 3 (workflow steps 1 and 2), 4.1 (project screen), 5 (data model), 9 (undo/redo bullet only), 11 (persistence, frontend)
- **Status:** not started

## Goal

A real project can be created, opened, saved and reopened. The backend owns `project.json` (pydantic v2 schema, atomic writes, autosave, rotating `.bak`, schema versioning), detects footage with ffprobe, applies a channel template, and routes every edit through an undoable command layer. A minimal Svelte project screen (new, open, recent, relink) runs in the pywebview window. Done when: create a project, add footage, restart the app, and everything is intact.

## How this task runs

Same method as M0 (see `CLAUDE.md`): the assistant writes files and commands, the user applies them and runs them in PowerShell from the repo root, then pastes results back. One step at a time; do not move on until the user confirms the previous step.

This milestone is about a week of work, so it is split across **three fresh chats**. Each chat gets `CLAUDE.md`, a freshly updated `PROJECT_STATE.md`, this file, and only the spec sections listed for it. At the end of each chat the assistant outputs the complete updated `PROJECT_STATE.md`; commit it before starting the next chat.

| Chat | Steps | Items | Paste these spec parts |
|---|---|---|---|
| A | 1, 2 | M1-1, M1-2 (+ their tests) | Section 5 (all), section 11 "Persistence" paragraph |
| B | 3, 4 | M1-3, M1-4 (+ their tests) | Section 5 "Source" row and anchoring rule, section 9 "Undo/redo" bullet, section 3 step 2 |
| C | 5, 6, 7 | M1-5, M1-6, M1-7, end-of-task | Section 2 "Intro/outro" row, section 3 step 1, section 4.1, section 5 "ChannelTemplate" row, section 11 "Frontend" paragraph |

Branch: `git switch -c m1-foundation` once at the start of chat A (after `git status` is clean). Keep the same branch across all three chats and commit after each confirmed step. Merge and tag only after chat C.

## Prerequisites (user does these first)

- [ ] M0 merged to `main`, tagged `m0-done`, pushed; `git status` clean
- [ ] **Dev tools:** `uv add --dev pytest ruff`, then `uv run pytest --version` and `uv run ruff --version` both work
- [ ] **Node.js LTS** installed (`node --version`, `npm --version`). Needed from step 6 only, so it can wait until chat C. It is a build-time tool; per spec section 11 the app needs no Node at runtime
- [ ] **Sample footage:** a short real clip for manual testing, kept outside the repo or in a git-ignored folder. The M0 test file (OBS MKV, 2560x1440, 60 fps, H.264, one stereo AAC track) is fine
- [ ] **Optional for step 5:** any short intro and outro clips to use as default bookend clips (outside the repo)

## Context pack

- `CLAUDE.md`
- `PROJECT_STATE.md` (current)
- This task file
- The spec parts for the current chat (table above)
- No app source files exist yet beyond `scripts/spike/` (reference only; do not paste unless the assistant asks for a specific function)

## Scope

**In:**
- Pydantic v2 schema for `project.json` v1: every entity in spec section 5 (Source, Clip, Line, Take, Placement, Keyframe, Reaction, VoiceProfile, FxChain, ChannelTemplate), with `schema_version`. Later milestones own the behavior of Line, Take, Keyframe and the rest; M1 only defines and persists them
- The migration mechanism (one registered stub step is enough)
- Project folder layout, create/open/save, atomic writes, autosave, rotating `.bak`
- ffprobe wrapper and footage detection producing Source entities, referenced by path relative to the project folder
- Command layer with undo/redo, including grouped operations (section 9: "grouped drag operations"), and the commands M1 needs (for example add/remove source, rename project)
- Channel template file in `templates/`, loader, and apply-on-create (section 3 step 1): bookend clips, voice profile, FX chain, avatar defaults, export settings
- FastAPI endpoints and a minimal Svelte + TypeScript (strict) + Vite project screen served as static files in the pywebview window, covering section 4.1: new project from template, open recent, open folder, footage files found, relink dialog
- pytest suites for every pure module; `ruff` clean

**Out:**
- Timeline, clip operations, time mapping, orphan handling logic (M2)
- Voice, takes, line bank UI, reference clip import (M3). The project screen shows voice profile and avatar art status as simple "not configured" or "path set" text only; real validation arrives with M3-1 and M5-1
- Audio FX (M4), avatar (M5), export (M6)
- HTTP range media server, WebSocket job events, GPU worker (later milestones)
- File watcher for `footage/`: rescan on open plus a Rescan button is enough for M1
- `install.bat`, `run.bat`, first-run model download (M7)
- Any editing of footage or copying it into the project (invariant 2)
- Backlog features listed in `IMPLEMENTATION_PLAN.md`

## Facts already established (do not re-ask)

- Recording frame rate is **60** (M0): OBS MKV, H.264 High yuv420p, 2560x1440, one mixed stereo AAC track at 48 kHz. Export scales to 1080p.
- ffprobe is at `bin\ffprobe.exe` (ffmpeg n8.1.3). Call it with an argument list, JSON output (for example `-v error -show_streams -show_format -of json`).
- The spec defines these root-level facts beyond the entity table: a **project seed** keys all solver randomness (section 8), game audio is a fixed dB level (section 2), export settings are 1080p 16:9 with frame rate matching footage (section 4.3), and the line bank is per project (section 2).
- Bookend clips (intro/outro) have overlay off and carry no anchored items (section 5).
- Anchoring rule: every Placement, Keyframe and Reaction carries an anchor of (clip id, source time) (invariant 4).

## Decisions to make in step 1 (assistant proposes in 5 lines or fewer, user decides, log in `PROJECT_STATE.md`)

1. **Time representation:** seconds as float, integer milliseconds, or integer frames per source fps. This is the foundation M2's time mapping builds on, so choose deliberately. Sources at 59.94 fps (NTSC) should also work.
2. **Orphan state:** should Placement, Keyframe and Reaction carry an explicit `orphaned` flag (spec section 5: flagged and "parked at the nearest edge")? Default proposal: yes, a boolean field, no logic in M1.
3. **Id format:** short random string ids (for example uuid4 hex) versus counters.
4. **Path format in JSON:** relative POSIX-style (forward slashes) converted with `pathlib`, so projects survive moving between folders.

## Steps

Each step ends with what to paste back and a commit point (`git status`, `git add`, `git commit -m "M1-N: ..."`).

1. **Schema (M1-1).** Assistant takes the pasted section 5 and the facts above, lists the decisions above for the user to settle, then gives `backend/project/schema.py`: pydantic v2 models for all entities and a root `Project` model (name, `schema_version = 1`, project seed, the entity collections, game audio dB, avatar defaults, export settings; the assistant lists the assumed root fields in 5 lines or fewer for confirmation). Includes `tests/test_schema.py` (construct, serialize, validate bad input).
   *Paste back:* `uv run pytest` and `uv run ruff check .` output.
2. **Persistence (M1-2).** Assistant gives `backend/project/store.py` and `migrations.py`: create the project folder layout from section 5 (`project.json`, `footage/`, `media/takes_raw/`, `media/takes_fx/`, `media/envelopes/`, `exports/`); load; atomic save (temp file in the same folder, flush, `os.replace`); rotating `.bak`; an autosave scheduler whose timing logic is pure and testable (autosave on change); on load, check `schema_version` and run registered migrations in order. Paths via `pathlib`; must work with spaces in Windows paths. Tests: round-trip, failure during write leaves the old file intact, `.bak` rotation, migration chain runs in order.
   *Paste back:* `uv run pytest` and `uv run ruff check .` output; the folder tree it created (`Get-ChildItem -Recurse` on a throwaway folder).
3. **Footage and ffprobe (M1-3).** Assistant gives `backend/project/footage.py`: a thin subprocess wrapper around `bin\ffprobe.exe`; a pure function that parses ffprobe JSON into a Source entity (duration, fps parsed from the rational frame rate string, resolution, stream info including audio track count); a scan of the project's `footage/` folder; a clear error if ffprobe is missing. Footage is never copied or modified. Tests use a small canned ffprobe JSON fixture (video 2560x1440 at 60/1, one stereo AAC stream), plus a case for an NTSC rate and a file with no audio. Fixtures are JSON text, never video files.
   *Paste back:* `uv run pytest` output, plus the Source entities produced for your real clip (run the scan once on a test project).
4. **Commands and undo (M1-4).** Assistant gives `backend/project/commands.py`: command objects that apply to and invert against a project state (pure, no I/O), an undo/redo stack with grouping (one undo reverts a whole group), and the commands M1 needs. Every edit goes through it (invariant 11). Tests: apply/undo/redo round-trip, grouped undo, redo cleared after a new command.
   *Paste back:* `uv run pytest` and `uv run ruff check .` output.
5. **Channel template (M1-5).** Assistant gives `templates/default_channel.json` (bookend clips, voice profile, FX chain, avatar defaults, export settings; bookends are ordinary clips with overlay off), `backend/project/template.py` (load, validate, apply to a new project), and tests. Items that later milestones implement (FX, avatar, voice reference clip) are stored as plain settings only. If you have no intro/outro clips, the template ships with none.
   *Paste back:* `uv run pytest` output; the template file as written, so the next chat can see it.
6. **Backend API and project screen (M1-6).** Assistant gives `backend/app.py` (FastAPI: create from template, open, save, list recent, scan footage, relink) and the Svelte + TypeScript (strict) + Vite scaffold in `frontend/`, built to static files served by the backend, opened in the pywebview shell. Recent projects live in a per-user config file outside the repo and outside any project (assumption: under `%APPDATA%`; confirm). Work in sub-rounds: (a) scaffold plus a "hello" endpoint, (b) new and open, (c) recent list, (d) footage list, Rescan and relink missing footage.
   *Paste back:* for each sub-round, what you see in the window and any traceback or browser-console error; `git status` (make sure `node_modules/` and build output are git-ignored).
7. **Tests and wrap-up (M1-7).** Assistant checks the test list against the plan (round-trip save/load, atomic write failure, migration stub) and fills any gap, then runs the end-of-task checklist: complete updated `PROJECT_STATE.md` (repo map, how to run the app, schema version, command API and main endpoints with file paths, decisions from step 1), plan items to tick (M1-1 to M1-7), replacement text for any spec section whose behavior changed, suggested commit message and merge/tag commands (`m1-done`).
   *Paste back:* final `uv run pytest` and `uv run ruff check .` output; the result of the manual acceptance run below.

## Acceptance criteria

- [ ] `uv run pytest` passes; `uv run ruff check .` is clean
- [ ] A new project from the default channel template creates the section 5 folder layout and a valid `project.json` with `schema_version` and a project seed
- [ ] Killing the process during a save never corrupts `project.json` (covered by a test); `.bak` rotates
- [ ] Footage placed in `footage/` is detected with correct resolution, frame rate, duration and streams, and is never copied or modified
- [ ] Every M1 edit is undoable and redoable through the command layer, and a grouped operation undoes as one step
- [ ] The default channel template applies on project creation
- [ ] The project screen shows new, recent, open folder, footage found, and relink
- [ ] Manual run: create a project, add footage, close the app, reopen it from the recent list; everything is intact
- [ ] Moving a footage file out and back in is handled through relink, without losing anything else
- [ ] `PROJECT_STATE.md` updated; M1 items ticked in `IMPLEMENTATION_PLAN.md`

## Notes

- Pure logic (schema validation, migrations, autosave timing, ffprobe parsing, commands, template apply) has no file or network access, per `CLAUDE.md`. I/O lives in thin wrappers.
- Every later schema change needs a migration. M1 does not need to bump `schema_version`, but the mechanism must be proven by the stub test.
- The Range-request code in `scripts/spike/player_spike.py` is for M2/M3 playback. Do not wire it into M1.
- The M0 spike confirmed uvicorn in a thread plus pywebview works; reuse that shape for the app shell.
- If the schema needs a field the spec does not define, state the assumption in one line and list it for a spec update at the end of the task.
- The assistant cannot see errors until the user pastes them; get the full traceback and exact command before suggesting a fix.
