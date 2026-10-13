# M3: Line bank and voice (line bank, takes, GPU worker, placing lines)

> **RECONCILED with `IMPLEMENTATION_PLAN.md` in M3 chat A (2026-10-13).** Where the earlier draft disagreed with the plan, the plan won: waveform blocks, Tighten, take delete with the storage manager, the voice profile settings screen and drag-to-place are all in M3. The decisions in the "Decisions" section were made in chat A and are final unless the user reopens them.

- **Milestone items:** M3-1 to M3-9 in `IMPLEMENTATION_PLAN.md` (listed below).
- **Spec sections:** 4.2 (Line bank tab, Voice lane, hotkeys N, G, Shift+G, M), 5 (Line, Take, Placement, VoiceProfile, the anchoring rule), 6 (voice system, take lifecycle, overflow), 11 (processes: GPU worker, queue), 2 (decisions locked)
- **Status:** chat A (S1, S2) written; S2 awaiting the user's pytest and ruff results. S3 onward not started.

## Plan items

- M3-1 Voice profile: reference clip import, hashing, settings screen
- M3-2 Emotion presets file and loader (`templates/`)
- M3-3 GPU worker process: queue, cancel, warm model, optional unload
- M3-4 Take store: cache keys, generate/reuse/reroll/star/delete, storage manager with sizes
- M3-5 Long-text chunking at sentence boundaries with crossfade join
- M3-6 Line bank UI and inspector: text, emotion, sliders, generate, take picker
- M3-7 Placement: drag onto timeline and hotkey M; voice lane with waveform blocks
- M3-8 In-context playback: voice audio synced with the preview
- M3-9 Overflow detection and fixes: tighten (time-stretch up to about 8%), nudge earlier, regenerate with lower cfg_weight; allow-overlap toggle

**Done when (from the plan):** write, generate, place, reroll, close the app, reopen, and play everything with zero regeneration.

## Goal

Lines written in a per-project line bank can be generated in the cloned voice on the local GPU, kept as takes, and placed on the footage. A placed line plays in sync with the video in the editor, shows as a waveform block on a voice lane, and warns when it runs into the next one. Generation never repeats work (cache keys), never blocks the UI, and can be cancelled. The voice FX chain and loudness normalisation belong to M4.

## How this task runs

Same method as M0 to M2 (see `CLAUDE.md`). M3 is the first milestone that needs the GPU and a second process, so it is split across **six fresh chats**, each getting `CLAUDE.md`, a freshly updated `PROJECT_STATE.md`, this file, and only the spec parts and source files listed for it. The assistant cannot run Chatterbox; every GPU result must come from the user's paste.

| Chat | Steps (plan items) | Paste these spec parts | Paste these source files |
|---|---|---|---|
| A | S1, S2 (decisions, M3-2, M3-5, key and overflow logic) | Sections 5, 6, 11 | `schema.py`, `scripts/spike/tts_test.py`, `tts_grid.py` (done) |
| B | S3 (M3-1 backend, M3-4 backend; no GPU) | Section 5, section 6 "Take lifecycle" | `schema.py`, `commands.py`, `session.py`, `app.py`, `summary.py`, `template.py`, `anchoring.py`, `backend/voice/*` from chat A |
| C | S4 (M3-3 GPU worker, queue, cancel, progress, generate endpoint) | Section 6 "Take lifecycle" and "Queue", section 11 "Processes" | `session.py`, `app.py`, `main.py`, the take store from chat B, `scripts/spike/tts_test.py` |
| D | S5 (M3-1 settings screen, M3-6 line bank UI, storage manager UI) | Section 4.2 (Line bank tab, status bar, hotkeys N, G, Shift+G), 4.1 | `frontend/src/App.svelte`, `Editor.svelte`, `api.ts` |
| E | S6 (M3-7 placement, voice lane, waveform blocks, drag and hotkey M) | Section 4.2 (Voice lane), section 5 anchoring rule | `Editor.svelte`, `Timeline.svelte`, `timeline.ts`, `backend/edl/timemap.py`, `backend/project/timeline.py`, `edit_ops.py` |
| F | S7, S8 (M3-8 playback, M3-9 overflow fixes, wrap-up) | Section 6 "Too-long line detection" | `Editor.svelte`, `Player.svelte`, `Timeline.svelte`, `timeline.ts`, `timemap.py` |

Branch: `m3-voice`, created at the start of chat A after M2 is merged and tagged `m2-done`. Keep the branch across chats, commit after each confirmed step, merge and tag `m3-done` after chat F.

## Prerequisites (user does these first)

- [ ] M2 merged to `main`, tagged `m2-done`; `uv run pytest`, `uv run ruff check .` and `npm run check` pass on `main`
- [ ] Chatterbox still works on this machine (`scripts\spike\seed_check.py` ran: done in chat A)
- [ ] A reference clip chosen for the default voice profile (spec 12: own voice or acted character), as a local `.wav`
- [ ] A test project with a real recording on the timeline (from M2)
- [ ] GPU mostly free while testing; note the VRAM headroom with the app window open (M0 did not measure it)

## Scope

**In (all nine plan items):**
- **M3-2 / M3-5 / key logic (chat A):** emotion presets file and loader, take cache key and seed policy, sentence splitter and crossfade join, overflow detection and nudge slack. All pure, with pytest
- **M3-1:** voice profile with real validation (clip exists, decodes, sensible length; hash on demand), import by copying into the project, and a settings screen
- **M3-4:** line bank commands on the `CommandStack` (add, edit text, emotion, the two slider overrides, allow-overlap, set active take, star), take store (`media/takes_raw/`, atomic writes, reuse by key, reroll), take delete and the storage manager with sizes
- **M3-3:** GPU worker process, one-at-a-time queue, cancel, progress, warm-up, optional unload; generate and reroll endpoints and a job-status endpoint
- **M3-6:** line bank tab with inspector (text, emotion, sliders), generate and reroll, take picker (play, star, set active), status bar, hotkeys N, G, Shift+G
- **M3-7:** `Placement` commands, voice lane on the canvas timeline with waveform blocks, place at playhead (M), drag a line from the bank onto the lane, drag to move, remove. Waveform peaks are computed on demand by the backend
- **M3-8:** Web Audio playback of placed takes in sync with the video, including seek, pause and cuts
- **M3-9:** overflow warning, allow-overlap toggle, Nudge earlier, Regenerate with lower cfg_weight, Tighten (time-stretch up to about 8 percent, rendered by the backend into `media/takes_fx/`)
- pytest for every pure module and every command; `ruff` clean; `npm run check` clean

**Out:**
- Voice FX chain, loudness normalise, silence trimming, Voice FX tab (M4); game audio level; mouth envelopes (M5 or M4, per plan)
- Avatar, expression and parameter lanes, reactions (M5); export and the ffmpeg graph (M6)
- Per-emotion reference clips, A/B take compare, loop-line playback, global favourites library (CLAUDE.md out-of-scope list)
- Network access after the first-run model download (rule 8); anything that touches footage (rule 2)

## Facts already established (do not re-ask)

- Chatterbox: original `ChatterboxTTS` 0.1.7, torch 2.6.0+cu126, `generate(text, audio_prompt_path, exaggeration, cfg_weight, temperature, ...)`, sample rate 24000. No seed argument: the seed is applied with `torch.manual_seed` before each call.
- **Seed check (chat A, user ran `seed_check.py`):** by ear, the runs with seed 1234 sound the same and seed 99 sounds different. A bit-exact comparison was not reported, so treat reproducibility as "same to the ear". The cache-key rule does not depend on it: same key means reuse the saved take.
- M0 timings on the RTX 4060 Laptop (8 GB): model load about 9 s, first generation about 27 s, later lines about real time, VRAM 3.6 GiB peak during generation. Peak with the app window open not measured.
- Voice quality with the neutral reference: realistic but flat; exaggeration 1.0 to 1.2 adds movement but garbles. Presets are guesses to tune by ear. `cfg_weight` is pacing guidance (lower = slower), not speed.
- `Take` stores a text snapshot, params, `model_version` and `raw_key`; `Line` holds text, emotion, overrides, active take id, allow-overlap; `Placement` has `orphaned`; `VoiceProfile` has reference clip path(s). Ids are 12-char hex; times are integer ms.
- M2 gives M3: the command contract and `CommandStack`; `Session` with save on every change; `timemap.to_timeline` / `to_source`; orphan parking and `check_references`; typed `api.ts`; `Editor.svelte` with `playheadMs` shared by `Player` and `Timeline`; the hotkey handler; HTTP 400 with `detail` for errors.
- Rules in `CLAUDE.md` that bite here: 1, 3, 7, 8, 10, 11, 14, 15.

## Decisions (made in chat A; log in `PROJECT_STATE.md`)

1. **Worker protocol.** Subprocess started with an argument list; JSON lines over stdin and stdout (commands: load, generate, cancel, unload, shutdown; events: ready, progress, done, error). Library prints go to the log file so stdout stays clean. The backend uses a `WorkerClient` interface; tests use a `FakeWorker`. A crash triggers one automatic restart.
2. **Cancel.** Between sentence chunks. A single-chunk line finishes (a few seconds) and its result is discarded, so no take is written; the UI shows "Cancelling...". No kill and restart (9 s load plus 27 s warm-up).
3. **Seed policy.** `base_seed(project.seed, line_id)`; first generation uses the base seed; a reroll uses the lowest `base + k` whose key is not already one of the line's takes (`next_unused_seed`). Chunk `i` of a take uses `seed + i` (`chunk_seed`), so chunk 0 behaves exactly like the spike. No schema change.
4. **Progress.** Polling a job-status endpoint (about every 500 ms while a job is active). WebSocket only if polling feels slow.
5. **Reference clip.** Copied into `media/voice/` in the project, stored as a relative path. Validation: decodes, length sensible (warn under 5 s). Hash computed on demand, memoised in memory by size and mtime. No schema change.
6. **Playback in context.** Web Audio: takes decoded once, each placement's start is `to_timeline(anchor)`, scheduled from the player's clock and rescheduled on seek, pause or hop. Voice plays at 1x whatever the clip speed. M3 plays raw (or tightened) takes with no mix; M4 swaps in processed takes.
7. **Take file format and chunking.** Float32 24 kHz mono WAV. `MAX_CHUNK_CHARS = 200` (lines at or under it are never split), 40 ms equal-power crossfade. The worker loops over chunks and joins them, which is what makes cancel between chunks possible.
8. **Overflow.** Pure `find_overflows` over timeline start and the duration of the audio that plays; `allow_overlap` flags the result as allowed (no warning). Nudge earlier uses `available_slack_ms`. All three fixes ship in M3 (the plan puts Tighten here).
9. **Undo and deletes.** Each line edit is one undo step (text commits on blur or Enter). Generate is not undoable (takes persist). `RemoveLine` is an undoable command, allowed only for a line with no takes and no placements. A line with takes is deleted through the storage manager's "Delete line and its takes" (explicit confirmation, not undoable; allowed by rule 1 because the user does it). Deleting a take that is a line's active take clears the active take; to settle placement overrides in S3.
10. **Cache-key details.** Text is whitespace-normalised before hashing; floats are rounded to 4 decimals; chunking constants are not part of the key (changing them never invalidates existing takes).
11. **Tighten (new, from the plan).** Stored as a new `Placement.stretch` field (1.0 to about 1.08) with schema version 2 and a migration, added in S8 only. The stretched WAV is rendered by the backend (pedalboard time-stretch; `uv add pedalboard`, a one-time download) into `media/takes_fx/`, keyed by hash(raw key, stretch), and playback and overflow use its duration. No other M3 step changes the schema.
12. **Waveforms (new, from the plan).** The backend computes min/max peaks for a take on demand; nothing is stored in `project.json`.

## Steps

Each step ends with what to paste back and a commit point (`git status`, `git add`, `git commit -m "M3-n: ..."`).

1. **S1 Decisions and seed check (chat A, done).**
2. **S2 Pure modules (chat A).** `backend/voice/presets.py` (M3-2), `keys.py`, `chunking.py` (M3-5), `overflow.py`, `templates/emotion_presets.json`, four test files. *Paste back:* `uv run pytest`, `uv run ruff check .`.
3. **S3 Backend: voice profile, line commands, take store, session, API (chat B; M3-1, M3-4; no GPU).** Sub-rounds: (a) voice profile import and validation, (b) line commands, (c) take store, reuse by key, delete, storage sizes, (d) endpoints. Tested with a fake worker.
4. **S4 GPU worker (chat C; M3-3).** (a) protocol and fake worker, (b) real worker with a single line, (c) cancel and queue order, (d) long text. *Paste back:* pytest, the worker log (last 30 lines), time and VRAM with the app window open.
5. **S5 UI (chat D; M3-1, M3-6).** Voice profile settings screen, line bank tab, generate and reroll, take picker, status bar, storage manager list, hotkeys N, G, Shift+G.
6. **S6 Placement (chat E; M3-7).** Placement commands and endpoint, voice lane with waveform blocks, M, drag from the bank, drag to move, remove.
7. **S7 Playback (chat F; M3-8).** Web Audio scheduling in sync with the player.
8. **S8 Overflow fixes and wrap-up (chat F; M3-9).** Warning edge, allow-overlap, Nudge, Regenerate, Tighten (schema v2). End-of-task checklist, merge, tag `m3-done`.

## Acceptance criteria

- [ ] `uv run pytest`, `uv run ruff check .` and `npm run check` are clean
- [ ] A voice profile accepts a reference clip (copied into the project, validated, hashed); the settings screen shows its state
- [ ] Writing a line and generating it produces a take file under `media/takes_raw/` and a `Take` in `project.json`; the take plays in the editor
- [ ] Generating the same inputs again reuses the saved take with **no GPU job** (visible in the status bar and the worker log)
- [ ] Reroll makes a new take with a new seed; the old take is still there; star and set-active work
- [ ] One GPU job runs at a time; a second request waits; cancel stops the job and leaves no half-written take; the UI stays responsive during generation
- [ ] A long line is split at sentence boundaries, generated in pieces and joined without a click
- [ ] The storage manager lists takes with sizes per line; deleting takes (and a line with its takes) works only through it, after confirmation
- [ ] A line placed on the footage stays attached to its moment when the footage is trimmed, reordered or sped up; deleting that footage flags the placement orphaned (and undo restores it)
- [ ] Placed lines show as waveform blocks on the voice lane; M places at the playhead; dragging from the bank places; dragging a block moves it
- [ ] A placed line is heard in sync with the video, including after seeking and across a cut
- [ ] A line that runs past the next placement shows the overflow warning; allow-overlap silences it; Nudge earlier, Regenerate and Tighten (up to about 8 percent) fix it
- [ ] Takes are never deleted by undo or by anything except the user's explicit delete (rule 1)
- [ ] No network access at runtime after the model is downloaded (rule 8)
- [ ] **Plan "done when":** write, generate, place, reroll, close the app, reopen, and play everything with zero regeneration
- [ ] `PROJECT_STATE.md` updated; M3-1 to M3-9 ticked in `IMPLEMENTATION_PLAN.md`

## Notes

- Pure logic (presets, cache keys, seeds, chunking, overflow, take-store bookkeeping) has no file, network or GPU access; I/O lives in thin wrappers (the take store, the worker client, `Session`, `load_presets_file`).
- Every schema change needs a migration and a spec note. The only planned one is `Placement.stretch` in S8 (decision 11); say so before adding anything else.
- Never commit weights, audio or footage (rule 9). `media/` lives in the user's project folder, not in this repo.
- The assistant cannot see GPU errors until they are pasted: get the full traceback, the exact command, the last 30 lines of the worker log, and for the editor the browser console output before proposing a fix.
- Treat voice cloning as for the user's own voice or voices they have permission to use (rule 15).
