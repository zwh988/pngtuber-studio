# M3: Voice (line bank, takes, GPU worker, placing lines)

> **DRAFT.** Written at the end of M2 chat D from `DESIGN_SPEC.md`, `PROJECT_STATE.md` and `CLAUDE.md`, **without `IMPLEMENTATION_PLAN.md` in view**. The first M3 chat must read the plan's M3 items, reconcile this file with them (ids, scope, order), and have the user approve the result before any code. Anything here that contradicts the plan loses to the plan.

- **Milestone items:** M3 in `IMPLEMENTATION_PLAN.md` (ids to fill in: `M3-?`).
- **Spec sections:** 4.2 (Line bank tab, Voice lane, hotkeys N, G, Shift+G, M), 5 (Line, Take, Placement, VoiceProfile, the anchoring rule), 6 (voice system, take lifecycle, overflow), 11 (processes: GPU worker, queue), 2 (decisions locked)
- **Status:** not started.

## Goal

Lines written in a per-project line bank can be generated in the cloned voice on the local GPU, kept as takes, and placed on the footage. A placed line plays in sync with the video in the editor and warns when it runs into the next one. Generation never repeats work (cache keys), never blocks the UI, and can be cancelled. Raw takes only: the voice FX chain, waveforms and loudness belong to M4.

## How this task runs

Same method as M0 to M2 (see `CLAUDE.md`). M3 is the first milestone that needs the GPU and a second process, so it is split across **five fresh chats**, each getting `CLAUDE.md`, a freshly updated `PROJECT_STATE.md`, this file, and only the spec parts and source files listed for it. The assistant cannot run Chatterbox; every GPU result must come from the user's paste.

| Chat | Steps | Paste these spec parts | Paste these source files |
|---|---|---|---|
| A | S1, S2 (decisions, pure modules, seed check) | Sections 5 (Line, Take, VoiceProfile rows), 6 | `backend/project/schema.py`, `scripts/spike/tts_test.py` and `tts_grid.py` |
| B | S3 (commands, take store, session, API; no GPU) | Section 5, section 6 "Take lifecycle" | `schema.py`, `commands.py`, `session.py`, `app.py`, `summary.py`, the pure modules from chat A |
| C | S4 (GPU worker, queue, cancel, progress, generate endpoint) | Section 6 "Take lifecycle" and "Queue", section 11 "Processes" | `session.py`, `app.py`, `main.py`, the take store from chat B, `scripts/spike/tts_test.py` |
| D | S5 (line bank UI, generate, takes list, preview a take) | Section 4.2 (Line bank tab, status bar, hotkeys N, G, Shift+G) | `frontend/src/App.svelte`, `Editor.svelte`, `api.ts` |
| E | S6, S7 (voice lane, placement, audible playback in context, overflow, wrap-up) | Section 4.2 (Voice lane), section 6 "Too-long line detection", section 5 anchoring rule | `Editor.svelte`, `Player.svelte`, `Timeline.svelte`, `timeline.ts`, `backend/edl/timemap.py` |

Branch: `git switch -c m3-voice` (or the plan's name) once at the start of chat A, after M2 is merged and tagged `m2-done` and `git status` is clean. Keep the branch across chats, commit after each confirmed step, merge and tag `m3-done` after chat E.

## Prerequisites (user does these first)

- [ ] M2 merged to `main`, tagged `m2-done`; `uv run pytest`, `uv run ruff check .` and `npm run check` pass on `main`
- [ ] Chatterbox still works on this machine: the M0 script (`scripts\spike\tts_test.py`) runs and produces a take (record the time and any new warnings)
- [ ] A reference clip chosen for the default voice profile (the open item in spec 12: own voice or acted character), as a local `.wav`, and its path noted
- [ ] A test project with a real recording on the timeline (from M2), so placement can be tried on real footage
- [ ] GPU mostly free while testing (close other GPU-heavy programs); note the VRAM headroom with the app window open (M0 did not measure it)
- [ ] `IMPLEMENTATION_PLAN.md` open, so the M3 item ids can be filled in at the top of this file

## Context pack

- `CLAUDE.md`, `PROJECT_STATE.md` (current), this file
- The spec parts and source files for the current chat (table above)
- Not the whole spec or whole files "just in case"; the assistant asks for a function or section by path

## Scope (proposed; confirm against the plan)

**In:**
- **Pure modules:** emotion presets (spec 6 table), take cache key (rule 3: hash of text, voice profile id plus reference clip hash, exaggeration, cfg_weight, seed, model version), a sentence splitter for long lines and the crossfade join plan, overflow detection (a placed line runs past the next placement's start), all with pytest
- **Voice profile** with real validation (the reference clip exists, is readable audio, is long enough; hash recorded). M1 stored only a path
- **Line bank commands** on the `CommandStack`: add, edit text, set emotion and the two slider overrides, set allow-overlap, set the active take, star a take, delete a line (takes stay on disk; rule 1). Edits are undoable; take creation itself is not an undo step (takes are never auto-deleted, so undo must not remove audio)
- **Take store:** raw takes as WAV files under `media/takes_raw/`, named from the raw key, written atomically; `Take` records in `project.json`; same key means reuse with no GPU run; reroll = new seed = new take; the storage manager's size query (delete UI can wait)
- **GPU worker:** a separate process holding Chatterbox, a one-at-a-time job queue, cancel, progress, warm-up after load (the first generation took about 27 s in M0), an option to unload the model. The backend talks to it through a small protocol that can be faked in tests
- **Generate endpoints** and a status feed for progress (how it reaches the UI is a decision below)
- **Line bank tab** in the editor (new line N, generate G, reroll Shift+G, takes list with play, star, set active), **status bar** GPU queue
- **Placement:** a `Placement` anchored to `(clip_id, source_ms)`, a **voice lane** on the canvas timeline (blocks, red edge on overflow), place at playhead M, drag to move, remove. Placements created through commands, so M2's orphan parking now has real users
- **Playback in context:** placed takes are heard in sync with the video in the editor (see decision 6)
- pytest for every pure module and every command; `ruff` clean; `npm run check` clean

**Out:**
- Voice FX chain, loudness normalize, silence trimming, waveforms on blocks, the Voice FX tab (M4); game audio level; mouth envelopes (M5, M4 for waveforms, to be confirmed against the plan)
- Avatar, expression and parameter lanes, reactions (M5); export and the ffmpeg graph (M6)
- Tighten (time-stretch) as an overflow fix, unless the plan puts it in M3 (it needs audio processing; proposal: M4). Nudge earlier and Regenerate are in scope
- Per-emotion reference clips, A/B take compare, loop-line playback, global favourites library (CLAUDE.md out-of-scope list)
- Network access after the first-run model download (rule 8); anything that touches footage (rule 2)

## Facts already established (do not re-ask)

- Chatterbox: original `ChatterboxTTS` 0.1.7, torch 2.6.0+cu126, `generate(text, audio_prompt_path, exaggeration, cfg_weight, temperature, ...)`, sample rate 24000. **No seed argument:** the seed is applied with `torch.manual_seed` before each call, and whether that makes output reproducible is **untested**.
- M0 timings on the RTX 4060 Laptop (8 GB): model load about 9 s, first generation about 27 s, later lines about real time (roughly 4.6 s for 5 to 6 s of audio), VRAM 3.6 GiB peak during generation. Peak with the app window open was not measured.
- Voice quality with the neutral reference: realistic but flat; exaggeration 1.0 to 1.2 adds movement but garbles. Emotion presets are guesses to tune by ear. `cfg_weight` is pacing guidance (lower = slower), not speed.
- `Take` already stores a text snapshot, `model_version` and `raw_key`; `Line` holds text, emotion, overrides, active take id, allow-overlap; `Placement` carries an `orphaned` flag; `VoiceProfile` exists with reference clip path(s). Ids are 12-char hex; times are integer ms; the default template has a "Default voice" profile without reference clips.
- M2 gives M3: the command contract and `CommandStack`; `Session` with save on every change; `timemap.to_timeline` / `to_source` (an anchor is mapped through the clip list, so a placed line follows the cuts); orphan parking and `check_references`; the typed `api.ts`, `Editor.svelte` with `playheadMs` shared by `Player` and `Timeline`, the hotkey handler, and the HTTP error convention (400 with `detail`).
- Rules in `CLAUDE.md` that bite here: 1 (takes never auto-deleted), 3 (cache keys decide regeneration), 7 (one GPU job at a time, cancellable, UI never blocks), 8 (offline at runtime), 10 (overflow warns but is allowed), 11 (edits undoable), 14 (subprocess hygiene), 15 (voice cloning only with permission).

## Decisions to make in S1 (assistant proposes in 5 lines or fewer each, user decides, log in `PROJECT_STATE.md`)

1. **Worker protocol:** how the backend talks to the GPU worker (a `multiprocessing` queue, JSON lines over stdin and stdout, or local HTTP), and how the worker is started, health-checked and restarted. It must be fakeable in tests so no test needs a GPU.
2. **Cancel:** a Chatterbox `generate` call cannot be interrupted midway. Options: cancel between sentence chunks, or kill and restart the worker (a 9 s reload plus warm-up). Pick one and say what the user sees.
3. **Seed policy:** per-line base seed, how a reroll picks the next seed, and the take key. First verify with a scratch script that `torch.manual_seed` before `generate` repeats the same audio; if it does not, the key still stands but "same key" means "reuse the saved take", not "regenerate identically".
4. **Progress and events:** the spec names a WebSocket for job events; M2 used plain HTTP only. Proposal: polling a job-status endpoint first (simple, testable), WebSocket later if polling feels slow.
5. **Reference clip handling:** where the clip lives (copied into the project, or referenced by absolute path like external sources), what validation runs (exists, decodes, length, sample rate), and when its hash is computed (once on set, recomputed when the file changes).
6. **Audible playback in context:** how placed takes play with the video. Proposal: schedule `<audio>` or Web Audio nodes from the player's hop logic, using `timemap` to turn a placement's anchor into a timeline start; seeking and pausing re-schedule. Decide what is in M3 (play in sync, simple) and what waits for M4's mix.
7. **Take file format and long text:** WAV sample format (float32 or PCM16 at 24 kHz mono), the sentence splitter's maximum chunk length, crossfade length, and where split and join happen (worker versus backend).
8. **Overflow:** definition (processed duration versus the next placement's start; M3 uses the raw take), where it is computed (pure backend function, returned with the timeline or placements state), and which fixes ship in M3 (Nudge earlier, Regenerate) versus M4 (Tighten).
9. **Commands and undo for lines and placements:** which line edits are one undo step, how "generate" relates to undo (proposal: not undoable, takes persist), and how deleting a line treats its placements and takes (proposal: refuse while placed, takes kept on disk).

## Steps

Each step ends with what to paste back and a commit point (`git status`, `git add`, `git commit -m "M3-...: ..."` using the plan ids).

1. **S1 Decisions and seed check.** Assistant reads the pasted spec parts, `schema.py` and the spike scripts, lists decisions 1 to 9 with one-line proposals, user decides. The assistant also gives a small scratch script for the seed reproducibility check; the user runs it. *Paste back:* your choices and the script's result.
2. **S2 Pure modules.** Presets, take cache key, sentence splitter and join plan, overflow detection, with pytest. *Paste back:* `uv run pytest`, `uv run ruff check .`.
3. **S3 Commands, take store, session, API.** Voice profile validation, line and take commands, `media/takes_raw/` store with atomic writes and reuse by key, `Session` methods and endpoints, tested with a **fake worker** (no GPU). Sub-rounds: (a) voice profile, (b) line commands, (c) take store and reuse, (d) endpoints. *Paste back:* each sub-round's pytest output.
4. **S4 GPU worker.** The worker process, queue, cancel, progress, warm-up and unload, the generate and reroll endpoints, status feed; the real model is exercised only by the user. Sub-rounds: (a) protocol and fake worker in tests, (b) the real worker with a single line, (c) cancel and queue order, (d) long text. *Paste back:* pytest output, the worker's log (last 30 lines), and the time and VRAM for a generation with the app window open.
5. **S5 Line bank UI.** Line bank tab, generate and reroll, takes list (play, star, set active), status bar, hotkeys N, G, Shift+G. *Paste back:* `npm run check`, and what you see in the window.
6. **S6 Placement.** Placement commands and endpoint, the voice lane, place at playhead (M), drag to move, overflow edge, audible playback in context, nudge earlier and regenerate fixes. Sub-rounds as the chat sees fit. *Paste back:* pytest, `npm run check`, what you see and hear.
7. **S7 Tests and wrap-up.** End-of-task checklist: complete `PROJECT_STATE.md`, plan items to tick, spec replacement text, commit message, merge and tag `m3-done`.

## Acceptance criteria

- [ ] `uv run pytest`, `uv run ruff check .` and `npm run check` are clean
- [ ] Writing a line and generating it produces a take file under `media/takes_raw/` and a `Take` in `project.json`; the take plays in the editor
- [ ] Generating the same inputs again reuses the saved take with **no GPU job** (visible in the status bar and the worker log)
- [ ] Reroll makes a new take with a new seed; the old take is still there; star and set-active work
- [ ] One GPU job runs at a time; a second request waits; cancel stops the job and leaves no half-written take; the UI stays responsive during generation
- [ ] A long line is split at sentence boundaries, generated in pieces and joined without a click
- [ ] A line placed on the footage stays attached to its moment when the footage is trimmed, reordered or sped up; deleting that footage flags the placement orphaned (and undo restores it)
- [ ] A placed line is heard in sync with the video, including after seeking and across a cut
- [ ] A line that runs past the next placement shows the overflow warning; allow-overlap silences it; Nudge earlier and Regenerate fix it
- [ ] Takes are never deleted by any command or by undo (rule 1)
- [ ] No network access at runtime after the model is downloaded (rule 8)
- [ ] Close the app, reopen the project: lines, takes, placements and the active take are intact
- [ ] `PROJECT_STATE.md` updated; M3 items ticked in `IMPLEMENTATION_PLAN.md`

## Notes

- Pure logic (presets, cache keys, sentence splitting, overflow detection, take-store bookkeeping) has no file, network or GPU access; I/O lives in thin wrappers (the take store, the worker client, `Session`).
- Every schema change needs a migration and a spec note. M3 may well need one (for example a per-line seed field or a voice-profile hash); the assistant must say so, bump `schema_version`, and add the migration.
- Never commit weights, audio or footage (rule 9). `media/` lives in the user's project folder, not in this repo.
- The assistant cannot see GPU errors until they are pasted: get the full traceback, the exact command, the last 30 lines of the worker log, and for the editor the browser console output before proposing a fix.
- Treat voice cloning as for the user's own voice or voices they have permission to use (rule 15).
