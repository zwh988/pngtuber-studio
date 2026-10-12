# CLAUDE.md

Working instructions for AI assistants on this repo. Read this file fully at the start of every task. It is short on purpose.

## Project in one paragraph

PNGtuber Studio is a local Windows desktop app (Python backend + web UI in a pywebview window) that turns a recorded 9-ball pool rack into a finished PNGtuber video. The user cuts and splices footage, writes voice lines freely into a line bank, generates them in a cloned voice (Chatterbox, local GPU), places them on the footage, tunes voice FX, keys avatar expressions and motion on timeline lanes, previews live, and exports a 1080p MP4 plus every individual asset. Fully offline after first-run model download.

## How this project is worked on (no agent tooling)

The user works in a plain chat. You cannot see the repository, run code, install anything, or edit files in place. The user copies files into the chat by hand, applies your output by hand, runs everything themselves on Windows (PowerShell), and pastes results back. Plan every response around that:

- You only know what the user pasted this session. Never assume file contents you were not shown.
- You cannot verify anything. Never say code "works" or "passes". Say it is untested until the user reports a result.
- Every deliverable must be easy to apply by hand (see "Delivering changes").

## Context protocol (do this, in order)

1. Read `PROJECT_STATE.md` (always). It says what exists and where it lives.
2. Read the task you were given (`docs/tasks/<task>.md`) or the matching milestone in `IMPLEMENTATION_PLAN.md`.
3. Read only the `docs/DESIGN_SPEC.md` sections the task references. If the spec was not pasted, ask for those sections by number.
4. Work only from the source files the user pasted. If you need another, ask for it by exact path, and for just the function or section when possible.

## Efficiency rules

- Do not request files "just in case". Ask for a specific path (and function or section) only when the task needs it.
- Do not repeat files already in the chat, and do not echo unchanged code.
- Ask for trimmed output, not whole logs: the last 30 lines of a log, the traceback, or the single failing test.
- No drive-by refactors, renames, reformatting, or backlog features. Stay inside the task scope.
- For changes touching more than two files, state a plan in 5 lines or fewer, then implement.
- Keep replies short: what changed, how to verify, what is next.
- If a design-changing ambiguity blocks you, ask one specific question. Otherwise state your assumption in one line and proceed.

## Delivering changes

- **Standing rule: deliver code as a zip.** Whenever file creation is available in the chat, every code drop (new or changed files, tests, `PROJECT_STATE.md`, `CLAUDE.md`) is delivered as one downloadable zip that mirrors the repo layout, with paths relative to the repo root. The user extracts it in the repo root and overwrites. Do not paste code into the reply for the user to copy by hand, and do not ask first. Name it after the step (for example `m2-s6a.zip`) and include the extract command below.
- A zip contains **complete files**, never fragments. For an edited file the user already pasted, apply the change to that pasted file, keep everything else identical (including line endings), and ship the whole file. Never ship a file that was not pasted this session unless creating it new; ask for it by path instead.
- Briefly list what is in the zip (path plus one line each) and which files are new versus overwritten, so the user can check `git diff` after extracting.
- Extract command (PowerShell, from the repo root; adjust the zip path): `Expand-Archive -Path "$env:USERPROFILE\Downloads\<name>.zip" -DestinationPath . -Force`
- Only when file creation is not available: label every code block with its repo-relative path (for example `backend/edl/timemap.py`), give complete files for new files and files with more than a few changes, and use exact "find this / replace with" pairs for small edits. Never say "update the function" without showing the exact change.
- Windows commands are PowerShell, one block per step, copy-pasteable, with the working directory stated (assume the repo root).
- After the code, list "Run this" commands and "Paste back" items (what output you need to see).
- Write tests for pure logic, but remember the user runs them. Give the exact `pytest` command.

## Verification

- Work in small steps the user can check in a minute or two. Prefer several short rounds over one large untested drop.
- When something fails, ask for the traceback and the exact command that produced it before proposing fixes. Do not guess at fixes for errors you have not seen.
- Distinguish clearly between "untested", "user confirmed", and "known broken".

## End-of-task checklist (required)

- [ ] Output the **complete updated `PROJECT_STATE.md`** (repo map entries touched, how to run/test, schema changes, known issues, decision log). The user pastes it over the old file.
- [ ] List the `IMPLEMENTATION_PLAN.md` item IDs to tick (for example "tick M1-1, M1-2"). Do not rewrite the whole plan.
- [ ] If behavior differs from the spec, give the replacement text for only the affected section of `docs/DESIGN_SPEC.md` and add it to the decision log.
- [ ] Suggest a one-line commit message and the merge/tag commands from the Git workflow section.

## Git workflow (solo project, applied by hand)

The user commits and merges themselves. The assistant reminds them at the right moments and supplies the commands (PowerShell, from the repo root).

- **`main` stays working.** Anything on `main` should at least start.
- **One branch per task**, named after the task (for example `m0-spike`, `m3-04-take-store`). At the start of a task, remind the user to run `git switch -c <branch>` after checking `git status` is clean.
- **Commit before pasting new AI code**, so `git restore .` can undo a bad drop.
- **Commit small and often** on the branch, after each step the user has run and confirmed. Suggest messages like `M3-04: add take cache keys`. Say when a good commit point is reached.
- **Docs go with the code.** The updated `PROJECT_STATE.md` and ticked plan items are committed in the same branch before merging.
- **Merge when the task's acceptance criteria pass.** Give the commands (`git switch main`, `git merge <branch>`, `git push`) or suggest opening a pull request on GitHub for a last diff review.
- **Tag finished milestones** (for example `git tag m0-done`).
- **Direct commits to `main`** are fine for doc edits, typo fixes, and tiny changes the user has already verified.
- **Check `git status` before each commit** for stray files. Never commit footage, audio, model weights, or binaries (see `.gitignore`); GitHub also rejects files over 100MB.

## Business rules (invariants: never violate without asking the user)

1. **Takes are never auto-deleted.** Only the user deletes them (storage manager). Every generation creates a take.
2. **Footage is never copied or modified.** The user places recordings in the project's `footage/` folder. The app references them by path relative to the project folder.
3. **Cache keys decide regeneration.** Raw take key = hash(text, voice profile id + reference clip hash, exaggeration, cfg_weight, seed, model version). Processed take key = hash(raw key, FX chain). Same key means reuse. Never spend GPU time on an existing key.
4. **Footage anchoring.** Every timed item (placements, keyframes, reactions) is anchored to (clip_id, source_time). Timeline time is computed by mapping through the clip list. Items whose anchor is cut away are flagged as orphans, never silently dropped.
5. **Preview equals export.** The Python avatar solver is the single source of truth. Renderers (browser canvas, Python compositor) only draw solver output. The solver is a pure function of (project state, time); all randomness is seeded.
6. **`project.json` is the single source of truth.** Atomic writes (temp file, then replace), autosave, rotating `.bak`, and a `schema_version` with a migration for every schema change.
7. **One GPU job at a time**, cancellable. The UI never blocks on GPU work.
8. **Offline at runtime.** No network calls after the first-run model download. No telemetry.
9. **Never commit** footage, audio, model weights, or binaries (see `.gitignore`).
10. **Overflow lines warn but are allowed.** The per-line `allow_overlap` flag silences the warning; overlapping audio is mixed.
11. **All edit operations are undoable** through the command/undo stack.
12. **Mouth animation** uses the loudness envelope by default. Rhubarb is only an optional later provider.
13. **Clip effects are pluggable.** New effects register in an effect registry (params, ffmpeg filter builder, preview applicator). Do not hardcode effects into the export loop.
14. **Subprocess hygiene.** Call ffmpeg and other tools with argument lists (never shell strings), use `pathlib`, and handle spaces in Windows paths.
15. **Voice cloning** is for the user's own voice or voices they have permission to use.

## Tech stack and conventions

- **Backend:** Python 3.11 (managed with `uv`), FastAPI + uvicorn, pydantic v2 models for the project schema, pywebview shell.
- **Voice:** Chatterbox (GPU) in a separate worker process. **Audio:** Pedalboard (EQ, compressor, effects), pyloudnorm (LUFS), soundfile, numpy.
- **Video:** bundled ffmpeg/ffprobe with NVENC in `bin/` (not committed).
- **Frontend:** Svelte + TypeScript (strict) + Vite, built to static files. The timeline is a custom canvas component.
- Keep logic pure and I/O at the edges: time mapping, anchoring, cache keys, overflow detection, and the avatar solver must be pure functions with no file or network access, so they are easy to test.
- Tests: `pytest` for backend logic (required for every pure module), `ruff` for lint/format.
- Type hints on all Python function signatures.

## Environment

- User machine: Windows, NVIDIA GPU with 6GB+ VRAM. Windows path rules apply. Commands are PowerShell.
- The user installs tools and downloads binaries (ffmpeg, model weights) by hand. Give exact install steps, and never assume a tool is already installed unless `PROJECT_STATE.md` says so.
- Chatterbox's `cfg_weight` is a pacing/guidance knob, not a literal speed control: lower values give slower, more deliberate delivery; higher exaggeration tends to speed speech up. Real speed changes are done by time-stretching audio.

## Out of scope for v1 (do not build unless asked)

Captions, A/B take compare, loop-line playback, vertical or 4K export, zoom/freeze/text effects, extra video tracks, music, global favorites library, Rhubarb provider, per-emotion reference clips, edited-proxy playback. The data model leaves room for them; see the backlog in `IMPLEMENTATION_PLAN.md`.
