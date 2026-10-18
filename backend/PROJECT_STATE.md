# PROJECT_STATE.md

Living document: how the project works right now and where everything lives. **Update it at the end of every task** (see the checklist in `CLAUDE.md`). Keep it factual and short; link to files instead of copying code.

- **Last updated:** 2026-10-17 (M3 chat D: S5 voice UI, rounds a to e, each confirmed by the user in the app window: voice profile section, line bank tab with inspector, generate, reroll, cancel, take picker, status bar, storage manager, hotkeys N, G, Shift+G)
- **Current milestone:** M3 (voice) in progress on branch `m3-voice`. Chats A (S1, S2), B (S3), C (S4) and D (S5) are done. Chat D's UI ran against the real backend and the real GPU worker: the user confirmed write, generate, reuse of an existing take with no GPU job, reroll, cancel, star, set active, take delete and line delete from the app window (see "Voice UI"). Backend rows that said "written, untested" are marked as passing pytest (963 passed in the chat C report) and used from the S5 UI. The pytest and `worker_check.py` results after the stdin fix were not pasted to chat D, so re-run the full suite once before the S8 merge. Next: chat E (S6: placement commands, voice lane with waveform blocks, hotkey M, drag from the bank). M2 is complete (merged and tagged by the user before branching).
- **Overall status:** M0 verdict GO (see "M0 findings"). The app runs: a pywebview window shows a Svelte project screen (create from template, open, Recent, footage scan, rescan, relink) and, new in M2, a **video editor screen** reached from "Open editor": add footage to the timeline, a player that plays across the cuts (segment hopping, clip speed with pitch preserved), a custom canvas timeline (ruler, clips, cut markers, speed badges, playhead, zoom and scroll), clip selection, drag to trim and reorder, the hotkeys from spec 4.2, and unlimited undo/redo. The backend behind it (time mapping, clip commands, orphan logic, reference check, timeline API, media server) is pure and tested (490 tests passing). Voice generation now works end to end (M3): a voice profile section on the project screen, a Line bank tab (write lines, emotion and slider overrides, generate, reroll, cancel, take picker), a status bar with the GPU queue and takes on disk, and a Storage tab with confirmed deletes. Nothing yet places a line on the footage or plays it in the editor (S6 to S8), and there is no avatar, voice FX or export. No `install.bat` / `run.bat` yet.

## How to run / test

**Always run commands from the repo root**, not from `docs\`.

```powershell
# setup (manual, until install.bat exists)
uv sync                      # Python 3.11, torch 2.6.0+cu126, chatterbox-tts, fastapi, uvicorn, pywebview, pydantic, pytest, ruff, httpx (dev)

# tests and lint (from repo root)
uv run pytest                # 490 passed, 1 warning at the end of M2 (user confirmed, 2026-10-12). M3 chat A adds 60 tests (expected 550 total; the user reported all passing, the exact count was not pasted) M3 chat B adds tests in rounds a to d (voice profile, line commands, line ops, line bank, take store, generation, references, command stack failures, endpoints); written without running, so the count is to be reported by the user; M3 chat C (S4) adds tests for the worker protocol, fake worker, worker loop, subprocess worker (starts real Python processes, no GPU), job models, job queue, job endpoints and the session project key; written without running, so these are unconfirmed
uv run ruff check .

# frontend (needs Node.js LTS: node v24.21.0 / npm 11.19.0 on the dev machine; build-time only)
cd frontend
npm install
npm run build                # writes frontend/dist (git-ignored); the backend serves it
npm run check                # svelte-check, TypeScript strict
cd ..

# run the app (window titled "PNGtuber Studio"); rebuild the frontend first after any frontend change
uv run python -m backend.main

# ffmpeg (not committed, bin/ is git-ignored): BtbN 8.1 release branch, NOT master or 9.0 (see M0 findings)
$zip = "$env:TEMP\ffmpeg-n81.zip"; $dir = "$env:TEMP\ffmpeg-n81"
Invoke-WebRequest -Uri "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-win64-gpl-8.1.zip" -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $dir -Force
Copy-Item "$dir\*\bin\ffmpeg.exe" bin\ -Force
Copy-Item "$dir\*\bin\ffprobe.exe" bin\ -Force

# spike scripts
uv run python scripts\spike\check_cuda.py
uv run python scripts\spike\tts_test.py --ref "<path to reference.wav>"          # writes scripts\spike\out\
uv run python scripts\spike\tts_grid.py --ref "<ref1.wav>" "<ref2.wav>"           # settings grid, writes scripts\spike\out\grid\
uv run python scripts\spike\seed_check.py --ref "<ref.wav>"                     # seed reproducibility check (M3-S1), writes scripts\spike\out\seed_check\
uv run python scripts\spike\worker_check.py --ref "<ref.wav>"                     # M3-3: the real GPU worker end to end, timings and GPU memory; add --cancel-after 1 to see a cancel between pieces; log in scripts\spike\out\worker_check\worker.log
uv run python scripts\spike\player_spike.py --video "<path to video.mkv>"          # pywebview window, prints Range requests
.\bin\ffmpeg.exe -hide_banner -y -ss 20 -t 10 -i "<video.mkv>" -map 0:v:0 -map "0:a:0?" -vf "scale=-2:1080" -c:v h264_nvenc -preset p5 -rc vbr -cq 23 -b:v 0 -pix_fmt yuv420p -c:a aac -b:a 192k scripts\spike\out\nvenc_test.mp4
```

First run of `tts_test.py` downloads the Chatterbox weights from Hugging Face (several GB, one-time network step). Later runs are offline.

Per-user data outside the repo: recent projects list at `%APPDATA%\PNGtuberStudio\recent.json`.

## Repo map

Status values: `empty` (placeholder only), `partial`, `done`.

| Path | Purpose | Status |
|---|---|---|
| `CLAUDE.md` | AI instructions and business rules | done |
| `PROJECT_STATE.md` | this file | done |
| `IMPLEMENTATION_PLAN.md` | milestones and task checklist | done |
| `docs/DESIGN_SPEC.md` | full design spec (source of truth for behavior) | done |
| `docs/tasks/` | per-task breakdown files (`_TEMPLATE.md`, `M0-spike.md`, `M1-foundation.md`, `M2-timeline.md` done, `M3-voice.md` reconciled with the plan in M3 chat A) | partial |
| `docs/API_MODELS.md` | request and response shapes the frontend uses for voice, lines, takes, storage and jobs, plus (M3 chat E) a digest of the schema, command stack, time mapping, session, timeline and editor contracts so those files need not be pasted again; update it when one of them changes | done (M3 chat D, extended in chat E) |
| `pyproject.toml`, `uv.lock`, `.python-version` | uv project: Python 3.11 only, torch pinned to 2.6.0 from the cu126 index; pydantic, fastapi, uvicorn, pywebview; dev: pytest, ruff, httpx | partial |
| `conftest.py` | repo-root marker so pytest can import `backend` | done |
| `scripts/spike/*` | M0 spike scripts (check_cuda, tts_test, tts_grid, seed_check, player_spike with reusable `parse_range`/`iter_file`); M3-3 diagnostics: `worker_check.py` (drives the real GPU worker without the app: heartbeat while loading, `--trace N`, `--load-timeout`, `--cancel-after N`), `launch_probe.py` and `thread_probe.py` (time the Chatterbox import under different launch settings and worker setups; kept because the stdin finding came from them) | done (spike); diagnostics written for M3 |
| `scripts/spike/out/` | spike output, git-ignored | n/a |
| `backend/__init__.py` | package marker | done |
| `backend/app.py` | FastAPI app factory `create_app(static_dir=None, session=None, jobs=None)`, `/api/*` routes (project, footage, recent, timeline and edits, voice, lines, takes, storage, voice jobs), `/media/source/{source_id}`, `/media/take/{take_id}`, serves `frontend/dist`. `jobs` is the generation queue; by default one is built around the real worker and nothing starts until the first job | done (M1-6, M2-S6, S7); voice and job routes done (pytest passed; used from the S5 UI) (M3) |
| `backend/main.py` | app shell: uvicorn in a thread on a free 127.0.0.1 port plus pywebview window; `Api` class with `pick_folder` / `pick_file`; builds the `JobQueue` around a `SubprocessWorker` and calls `jobs.close()` after the window closes, which stops the GPU worker | done (M1-6); queue wiring done (pytest passed; used from the S5 UI) (M3-3) |
| `backend/project/schema.py` | pydantic v2 schema, `SCHEMA_VERSION = 1`, `new_id()` | done (M1-1, extended M1-5) |
| `backend/project/store.py` | folder layout, create/load/save, atomic write, `.bak` rotation | done (M1-2) |
| `backend/project/migrations.py` | `migrate()` chain, `MIGRATIONS` registry (empty at v1) | done (M1-2) |
| `backend/project/autosave.py` | pure `AutosaveTracker` (debounce + max wait). **Not wired**; the app saves on every change instead (see decisions) | done (M1-2), unused |
| `backend/project/footage.py` | ffprobe wrapper, probe parsing, `footage/` scan producing Sources | done (M1-3) |
| `backend/project/commands.py` | `Command` base, M1 commands, `CommandStack` undo/redo with groups | done (M1-4) |
| `backend/project/clip_commands.py` | track-0 clip commands: `AddClip`, `RemoveClip` (parks orphans), `SetSpeed`, `ReorderClip` | done (M2-S3, S5) |
| `backend/project/cut_commands.py` | `SplitClip`, `TrimClip`, `RippleDelete` (frame snapping, minimum clip length, orphan parking, split re-pointing) | done (M2-S4, S5) |
| `backend/project/parking.py` | applies and undoes orphan parking: `collect_cut_away`, `park_cut_away`, `restore_parked`, `ParkedItem` | done (M2-S5) |
| `backend/project/timeline.py` | pure `build_timeline` and the models `TimelineState`, `TimelineClip`, `TimelineSource`, `TimelineProblem`, `EditResult` | done (M2-S6) |
| `backend/project/edit_ops.py` | pure edit op models (`AddClipOp` ... `RippleDeleteOp`), `EditOp` union, `EditBatch`, `build_command(op)` | done (M2-S6c) |
| `backend/project/template.py` | channel template load, validate, apply to a new project | done (M1-5) |
| `backend/project/session.py` | `Session`: the one open project, new/open, footage scan, relink, recent list, timeline state, edits, undo/redo, `source_path`, save on change; M3: voice profile, line bank, takes, storage, `project_key()` | done (M1-6, M2-S6, S7); M3 parts done (pytest passed; used from the S5 UI) |
| `backend/project/summary.py` | pure `ProjectSummary` (with `problem_count`), `FootageItem`, `FootageReport`, `summarize`, `describe_source` | done (M1-6, M2-S6) |
| `backend/project/recent.py` | recent projects list: pure add/remove/parse plus atomic load/save | done (M1-6) |
| `backend/project/relink.py` | pure `to_footage_relpath`, `relink_mismatches` | done (M1-6) |
| `backend/edl/__init__.py` | package marker | done (M2-S2) |
| `backend/edl/timemap.py` | pure time mapping: `clip_spans`, `timeline_duration`, `to_timeline`, `to_source`, frame helpers (`snap_to_frame`, `ms_to_frame`, `frame_to_ms`), `round_half_up` | done (M2-S2) |
| `backend/edl/anchoring.py` | pure orphan and reference logic: `anchored_items`, `items_in_source_range`, `find_orphans`, `edge_anchors`, `park_anchor`, `check_references`, `ReferenceProblem` | done (M2-S5) |
| `backend/edl/` (rest) | ffmpeg graph builder (M6) | empty |
| `backend/media/ranges.py` | pure `parse_range`; `iter_file` (chunked read of a byte range) | done (M2-S7) |
| `backend/media/serve.py` | `range_response(path, range_header)`: 200 / 206 / 416 streaming response | done (M2-S7) |
| `backend/voice/` | voice system package. Pure modules (chat A); voice profile, take store and generation planning (chat B); worker protocol, GPU worker, subprocess client, generation queue and job models (chat C) | partial |
| `backend/voice/__init__.py` | package marker | done (M3 chat A, user confirmed) |
| `backend/voice/presets.py` | emotion presets: `EmotionPreset`, `parse_presets`, `resolve_params`, `load_presets_file` (the only I/O) | done (M3-2, user confirmed) |
| `backend/voice/keys.py` | `normalize_text`, `raw_key`, `base_seed`, `next_unused_seed`, `SEED_MODULUS` | done (M3-4 groundwork, user confirmed) |
| `backend/voice/chunking.py` | `split_sentences`, `plan_chunks`, `chunk_seed`, `crossfade_join` | done (M3-5 pure part, user confirmed; the worker integration is M3-3) |
| `backend/voice/overflow.py` | `PlacedLine`, `Overflow`, `find_overflows`, `available_slack_ms` | done (M3-9 groundwork, user confirmed) |
| `backend/voice/profile.py` | pure: `AudioInfo`, `check_reference` (under 1 s refused; warnings under 5 s, over 30 s, under 16 kHz), `clean_stem`, `reference_filename`, `reference_relpath`, `VoiceState`, `build_voice_state` | done (pytest passed; used from the S5 UI) (M3-1, chat B) |
| `backend/voice/reference.py` | reference clip I/O: `read_audio_info` (soundfile), `hash_file`, `FileHashCache`, `import_reference`, `VoiceProfileError` | done (pytest passed; used from the S5 UI) (M3-1) |
| `backend/voice/linebank.py` | pure: `LineItem`, `LineBankState`, `build_line_item`, `build_line_bank` | done (pytest passed; used from the S5 UI) (M3-4) |
| `backend/voice/takes.py` | pure take logic: `NewTake`, `find_take_by_key`, `build_take`, `remove_takes`, `remove_line_and_takes`, `TakeItem`, `AddTakeResult`, `TakeDeleteReport`, `StorageReport`, `build_storage_report`, `TakeError` | done (pytest passed; used from the S5 UI) (M3-4) |
| `backend/voice/takestore.py` | take file I/O in `media/takes_raw/`: `TakeStore` (atomic `write_raw`, `copy_raw`, `size`, `unreferenced`, `delete_files`) | done (pytest passed; used from the S5 UI) (M3-4) |
| `backend/voice/generation.py` | pure: `plan_generation` gives a `GenerationPlan` (parameters, seed, raw key, chunks); `GenerationError` | done (pytest passed; used from the S5 UI) (M3-4) |
| `backend/voice/protocol.py` | pure: JSON-line worker protocol. Commands `load`, `generate`, `cancel`, `unload`, `shutdown`; events `ready`, `progress`, `done`, `cancelled`, `unloaded`, `error`; `encode_message`, `decode_command`, `decode_event`, `ProtocolError`, `build_generate_command(job_id, plan, output_path)` | done (pytest passed; used from the S5 UI) (M3-3, S4a) |
| `backend/voice/worker_client.py` | `WorkerClient` interface (`alive`, `start`, `send`, `next_event`, `close`) and `WorkerError` | done (pytest passed; used from the S5 UI) (S4a) |
| `backend/voice/fakeworker.py` | in-process `FakeWorker` for tests: writes real WAVs, advances one piece per `next_event`; switches `fail_load`, `fail_chunk_index`, `crash_on_chunk_index` with `crash_count`, `step_delay_s`, and `crash()` | done (pytest passed; used from the S5 UI) (S4a; extended in S4c) |
| `backend/voice/engine.py` | `Engine` interface; `ChatterboxEngine` (torch and chatterbox imported only on load; `torch.manual_seed(seed)` before each `generate`); `ToneEngine` (sine tones, no GPU); `chatterbox_model_version()` reads package metadata, so a take can be planned and reused without starting the worker | done (pytest passed; used from the S5 UI) (S4b, S4c) |
| `backend/voice/workerloop.py` | `WorkerLoop`: the worker's logic apart from stdio and torch: warm-up before `ready`, pieces in order, cancel check after each piece, `crossfade_join`, atomic WAV write, failures become `error` events | done (pytest passed; used from the S5 UI) (S4b) |
| `backend/voice/worker_main.py` | worker process entry point (`python -m backend.voice.worker_main`; `--engine tone` for tests; env `PNGTUBER_WORKER_TRACE=<s>` dumps all thread stacks to the log): protocol on a duplicate of the real stdout with fd 1 aimed at stderr, commands read from a private duplicate of stdin with fd 0 aimed at NUL (Windows: see decisions log), a reader thread applies a cancel at once | written; tone-engine paths tested by the user, real GPU path still unconfirmed |
| `backend/voice/subprocess_worker.py` | `SubprocessWorker`, the real `WorkerClient`: argument-list `Popen`, no console window, stderr appended to `%APPDATA%\PNGtuberStudio\worker.log` (rotated at 5 MB); a dead process queues a fatal `ErrorEvent` naming the running job; `default_worker_log_path()` | done (pytest passed; used from the S5 UI) (S4b; adjusted in S4c) |
| `backend/voice/jobs.py` | pure: `JobItem`, `JobStatus`, `finished_to_forget` | done (pytest passed; used from the S5 UI) (S4c) |
| `backend/voice/jobqueue.py` | `JobQueue` and `GenerationHost`: one GPU job at a time on one thread; `submit`, `submit_unload`, `cancel`, `status`, `wait`, `close`; restart and retry once on a crash or stall; load and stall timeouts | done (pytest passed; used from the S5 UI) (S4c) |
| `backend/voice/fakehost.py` | in-memory stand-in for the open project (keys, seeds, takes) for queue and endpoint tests | done (pytest passed; used from the S5 UI) (S4c) |
| `backend/project/voice_commands.py` | `AddVoiceProfile`, `SetReferenceClip` (path must be inside `media/voice/`) | done (pytest passed; used from the S5 UI) (M3-1) |
| `backend/project/line_commands.py` | `AddLine`, `RemoveLine`, `SetLineText`, `SetLineEmotion`, `SetLineExaggeration`, `SetLineCfgWeight`, `SetAllowOverlap`, `SetActiveTake`, `StarTake`, `NoChange` | done (pytest passed; used from the S5 UI) (M3-4) |
| `backend/project/line_ops.py` | line edit op models (tag `op`), `LineEditBatch`, `build_line_command` | done (pytest passed; used from the S5 UI) (M3-4) |
| `backend/audio/` | FX chain, loudness, envelopes | empty |
| `backend/avatar/` | art loader, solver, compositor | empty |
| `backend/export/` | export pipeline, asset bundle | empty |
| `frontend/` | Svelte 5 + TypeScript (strict) + Vite 6: `package.json`, `package-lock.json` (committed), `vite.config.ts`, `svelte.config.js`, `tsconfig.json`, `index.html`; `src/main.ts`, `src/App.svelte` (project screen with a Voice section; switches to the editor with a `view` flag), `src/api.ts` (typed fetch wrappers: timeline and edit functions, `sourceMediaUrl`, and the voice, line bank, take, job and storage types and functions, `takeMediaUrl`), `src/pywebview.d.ts`, `src/vite-env.d.ts`, and the editor files below. `node_modules/` and `dist/` are git-ignored | partial (project screen, video editor, voice UI) |
| `frontend/src/Editor.svelte` | editor screen: player, canvas timeline, selected-clip bar, clip table, undo/redo, hotkeys (M2); a Footage / Line bank / Storage tab strip, voice job polling and the status bar, hotkeys N, G, Shift+G (M3 chat D) | done (M2-S8; voice UI user confirmed, S5) |
| `frontend/src/Player.svelte` | one `<video>` playing the whole sequence from the playhead: segment hopping, playback rate, scrub bar; exports `toggle()` and `pause()` | done (M2-S8) |
| `frontend/src/Timeline.svelte` | custom canvas timeline: ruler, video strip lane, cut markers, speed badges, playhead, selection, zoom and scroll, drag trim and reorder | done (M2-S8) |
| `frontend/src/timeline.ts` | pure display and playback helpers: `clipIndexAt`, `toSource`, `stepFrame`, `trimTarget`, `withTrim`, `dropSlot` | done (M2-S8) |
| `frontend/src/format.ts` | `clock(ms)` as m:ss.mmm | done (M2-S8) |
| `frontend/src/LineBank.svelte` | Line bank tab: line list and inspector (text, emotion, exaggeration and pacing sliders, allow-overlap, remove), Generate, Reroll, Cancel, take picker (play, star, use); exports `addLine()` and `generateSelected(reroll)` for the hotkeys | done (M3-6, user confirmed) |
| `frontend/src/ParamSlider.svelte` | slider with a live drag value, one save on release, "from the emotion preset" or "custom" and Reset to preset | done (M3-6, user confirmed) |
| `frontend/src/StorageList.svelte` | Storage tab: totals, per-line takes with sizes, inline-confirmed Delete take and Delete line and takes, unreferenced files (read-only) | done (M3-4 UI, user confirmed) |
| `frontend/src/voice.ts` | pure display helpers: job text and state tests, `latestJobFor`, `liveJobFor`, `workerText`, `voiceStatusText`, `cleanPathInput`, `newLineId`, `takeCountText`, `formatBytes`, `deleteReportText`, `normalizeText` | done (M3 chat D) |
| `bin/` | ffmpeg/ffprobe (git-ignored) | has ffmpeg n8.1.3 + ffprobe locally |
| `templates/default_channel.json` | default channel template (no bookends, "Default voice" without reference clips, FX/avatar/export defaults) | done (M1-5) |
| `templates/emotion_presets.json` | the five emotion presets from spec 6 (exaggeration, cfg_weight, default avatar expression); tune by ear | done (M3-2, user confirmed) |
| `scripts/` | install/run helpers | spike only |
| `tests/test_schema.py` | schema tests (29) | done |
| `tests/test_persistence.py` | migrations, autosave tracker, store tests (28) | done |
| `tests/test_footage.py` | ffprobe parsing (canned JSON), scan planning, folder scan with fake probe (25) | done |
| `tests/test_commands.py` | commands, undo/redo, groups, rollback, on_change (33) | done |
| `tests/test_template.py` | template load, validate, apply (34) | done |
| `tests/test_session.py` | folder-name validation, summary, new/open (24) | done |
| `tests/test_recent.py` | recent list logic, store, session recording, endpoints (13) | done |
| `tests/test_footage_api.py` | rescan, save on change, missing files, save failure, footage endpoints (11) | done |
| `tests/test_relink.py` | relink helpers, session relink, endpoint (17) | done |
| `tests/test_app.py` | hello, static serving, project endpoints (8) | done |
| `tests/test_timemap.py` | rounding, frame snapping, spans, speeds, trims, reorder, boundaries, round trips at 60 and 59.94 fps (38) | done (M2-S2) |
| `tests/test_clip_commands.py` | `AddClip`, `RemoveClip`, `SetSpeed`, `ReorderClip`: positions, other tracks, undo/redo, groups | done (M2-S3) |
| `tests/test_cut_commands.py` | `SplitClip`, `TrimClip`, `RippleDelete`: snapping, speed, minimum length, item re-pointing, undo/redo, groups | done (M2-S4) |
| `tests/test_anchoring.py` | pure anchoring: item lookup, edge anchors, parking choice and ties, `find_orphans`, `check_references` | done (M2-S5) |
| `tests/test_orphans.py` | orphan flagging and parking inside the commands, exact undo/redo, re-parking, rollback in a group, edits that must not orphan | done (M2-S5) |
| `tests/test_timeline.py` | `build_timeline` (spans, positions, speeds, 59.94 fps, other tracks, missing file, broken references), `GET /api/timeline` (10) | done (M2-S6a) |
| `tests/test_timeline_edit.py` | `add_clip`, undo/redo, save and reopen, `problem_count`, add/undo/redo endpoints (14) | done (M2-S6b) |
| `tests/test_edit_ops.py` | op models, `build_command`, each operation through the session, batches as one undo step, all-or-nothing, every edit endpoint | done (M2-S6c) |
| `tests/test_media.py` | `parse_range`, `iter_file`, media endpoint (200/206/416/404, spaces in paths, external sources, no path from the URL) | done (M2-S7) |
| `tests/test_voice_presets.py` | presets parsing, validation, resolve, shipped file, file errors | user confirmed passing (M3 chat A) |
| `tests/test_voice_keys.py` | cache key stability and sensitivity, normalisation, float noise, seeds | user confirmed passing (M3 chat A) |
| `tests/test_voice_chunking.py` | sentence splitting, chunk packing, seeds, crossfade join | user confirmed passing (M3 chat A) |
| `tests/test_voice_overflow.py` | overflow detection, allow-overlap flag, slack | user confirmed passing (M3 chat A) |
| `tests/test_voice_profile.py`, `test_voice_reference.py`, `test_voice_commands.py`, `test_voice_session.py` | voice profile: checks, names, state, import and hashing, commands, session and endpoints | done (pytest passed; M3 chat B, round a) |
| `tests/test_line_commands.py`, `test_line_ops.py`, `test_linebank.py`, `test_lines_session.py` | line bank commands, ops, state, session and endpoints | done (pytest passed; used from the S5 UI) (round b) |
| `tests/test_takes.py`, `test_takestore.py`, `test_takes_session.py`, `test_command_stack_failures.py` | take logic, files, session lifecycle, failing revert or redo | done (pytest passed; used from the S5 UI) (round c) |
| `tests/test_generation.py`, `test_generation_session.py`, `test_voice_references.py`, `test_takes_api.py` | seed policy and keys, generate/reuse/reroll/reopen with a fake generator, reference checks for lines and takes, take and storage endpoints | done (pytest passed; used from the S5 UI) (round d) |
| `tests/test_voice_protocol.py`, `test_fake_worker.py`, `test_worker_loop.py`, `test_subprocess_worker.py` | protocol encoding and validation, fake worker, worker logic with a recording engine, a real subprocess with the tone engine (cancel across the process boundary, stray prints, crash and restart) | done (pytest passed; used from the S5 UI) (S4a, S4b) |
| `tests/test_jobs.py`, `test_job_queue.py`, `test_jobs_api.py`, `test_session_project_key.py` | job models and pruning; queue reuse, order, cancel, crash restart, timeouts, unload; job endpoints; the session project key guard | done (pytest passed; used from the S5 UI) (S4c) |

## Project folder layout (user data, not in this repo)

```
MyRack/
  project.json          source of truth
  project.json.bak      previous saved version (rotated on each save)
  footage/              user places recordings here (never copied)
  media/voice/  media/takes_raw/  media/takes_fx/  media/envelopes/   (voice/ holds the reference clip copy, M3-1)
  exports/
```

## Schema and key interfaces

**Schema:** `backend/project/schema.py`, `schema_version = 1` (not bumped in M1). All models forbid unknown fields and validate on assignment.
- Conventions: times are **integer milliseconds** (source time for anchors); ids are 12-char lowercase hex (`new_id()`); paths in JSON are POSIX strings (no `\`, no `..`): relative for project footage, absolute only for `external` sources.
- Entities: `Source`, `Clip`, `Line`, `Take`, `Placement`, `Keyframe`, `Reaction`, `VoiceProfile`, `FxChain` (+ `CompressorSettings`), `Anchor`, `EffectSpec`, `AvatarSettings`, `ExportSettings`, `BookendRef`, `ChannelTemplate`, root `Project`.
- `Source`: `id`, `external` (default false), `path`, `duration_ms`, `fps_num`/`fps_den` (property `fps`), `width`, `height`, `audio_tracks`. When `external` is true the path must be absolute POSIX (template bookends live outside the project); otherwise it must be relative.
- `ChannelTemplate`: `name`, `intro` / `outro` (`BookendRef(path)` or null), `voice_profile`, `fx_chain`, `avatar`, `export`, `game_audio_db`.
- Root `Project` fields: `schema_version`, `name`, `seed`, `sources`, `clips`, `lines`, `takes`, `placements`, `keyframes`, `reactions`, `voice_profiles`, `fx_chain`, `game_audio_db` (default 0.0), `avatar`, `export`. Unique ids per collection are validated; cross-references are not.
- `Clip` uses `in_ms`/`out_ms`, `speed` 0.25 to 8, `track`, `overlay`, `effects`. `Placement`, `Keyframe`, `Reaction` carry `orphaned: bool`, set by the M2 commands (see "Anchoring and parking API"). **No schema change in M2 so far; no migration needed.**
- M3 chat B: **no schema change**; `VoiceProfile.reference_clips[0]` holds the relative path `media/voice/<stem>-<hash8><ext>`. The only later schema change planned is `Placement.stretch` in S8 (schema version 2).

**Store API** (`backend/project/store.py`): `create_project(folder, project)`, `load_project(folder, *, use_backup=False, migrations=None)`, `save_project(folder, project)`, `ensure_layout(folder)`, `project_file`/`backup_file`. Errors: `ProjectError`, `ProjectExistsError`, `ProjectLoadError`.
- Save order: temp file (flush, fsync) in the project folder, copy current `project.json` to `.bak` (only if it is valid JSON), `os.replace` temp over `project.json`. Failure leaves the old file and cleans up temp files.

**Migrations** (`backend/project/migrations.py`): `migrate(data, target=SCHEMA_VERSION, migrations=None)`; register `MIGRATIONS[n] = fn` upgrading version n to n+1. Raises `MigrationError` / `ProjectTooNewError` (wrapped in `ProjectLoadError` by `load_project`).

**Autosave tracker** (`backend/project/autosave.py`): `AutosaveTracker(AutosavePolicy(debounce_s=2.0, max_wait_s=15.0))`: `mark_dirty(now)`, `begin_save()` / `finish_save(token)`, `should_save(now)`, `seconds_until_due(now)`. Currently unused; revisit in M2 if drag edits make save-per-change too chatty.

**Time mapping API** (`backend/edl/timemap.py`, pure, no I/O; M2-S2, user confirmed tests pass):
- The timeline is track 0 of `Project.clips`: a gapless sequence in list order. Clips with `track != 0` are ignored by every function here.
- `clip_spans(clips) -> list[ClipSpan]`; `ClipSpan(clip_id, index, start_ms, end_ms, in_ms, out_ms, speed)` with property `duration_ms`; `index` is the position in the list that was passed in. `clip_duration_ms(clip)`, `timeline_duration(clips)` (0 when empty).
- `to_timeline(clips, anchor, *, spans=None) -> int | None`: `start + round((source_ms - in) / speed)`. `None` when the clip is not on track 0 or `source_ms` is outside `[in_ms, out_ms]`. `source_ms == out_ms` is accepted and maps to the clip end.
- `to_source(clips, timeline_ms, *, spans=None) -> Anchor | None`: `in + round((t - start) * speed)`, clamped to `out_ms - 1`. `None` outside `[0, duration)`. A boundary time belongs to the clip that starts there. Zero-length spans are skipped.
- Rounding: `round_half_up` (exact Fraction math; speed is read from its decimal `repr`, so 1.1 is exact). `ms_to_frame`, `frame_to_ms` (frame k at `round(k * 1000 * fps_den / fps_num)`), `snap_to_frame(ms, fps_num, fps_den)`. The module takes fps as arguments; commands look up the source fps and snap before calling.
- Round-trip bounds (asserted in tests): timeline to source to timeline is exact at speed >= 1 and within `1/speed` ms below 1; source to timeline to source is within `speed/2 + 0.5` ms.

**Anchoring and parking API** (`backend/edl/anchoring.py` is pure; `backend/project/parking.py` changes in-memory objects only; M2-S5, user confirmed tests pass):
- `AnchoredItem = Placement | Keyframe | Reaction`. `anchored_items(project, clip_id=None)` (placements, then keyframes, then reactions), `items_in_source_range(project, clip_id, lo, hi)` (`lo` inclusive, `hi` exclusive, `hi=None` unbounded), `item_kind(item)`, `find_orphans(project)` (items flagged `orphaned`; for the export pre-flight).
- `edge_anchors(clips, cut_ms, *, spans=None) -> (before, after)`: `before` = `Anchor(last clip ending at or before cut_ms, out_ms - 1)`, `after` = `Anchor(first clip starting at or after cut_ms, in_ms)`; either is `None` when there is no footage on that side. `park_anchor(clips, cut_ms, offset_ms, region_ms, *, spans=None) -> Anchor | None` picks the nearer edge by old-timeline distance (offset clamped to the region), a tie goes to `before`, and it returns `None` when no clip survives.
- `check_references(project) -> list[ReferenceProblem]`; `ReferenceProblem(kind, owner_id, missing_id, message)` with kind `clip_missing_source` or `item_missing_clip`. It only reports; it never changes the project and never blocks loading. M3 chat B added a separate `check_voice_references(project)` (kinds `take_missing_line`, `line_missing_take`, `placement_missing_line`, `placement_missing_take`); it is separate because the M2 tests build placements without lines. `ProjectSummary.problem_count` counts both; `TimelineState.problems` still comes from `check_references` only.
- `parking.py`: a command calls `collect_cut_away(project, cuts, region_start_ms)` **before** changing clips (`cuts` = `(clip_id, lo, hi_or_None)` source ranges; offsets are measured in the old timeline), then `park_cut_away(project, cut_away, *, cut_ms, region_ms)` **after**, keeps the returned `list[ParkedItem(item, old_anchor, old_orphaned)]`, and calls `restore_parked(parked)` in `revert`. An item with no surviving clip is flagged and keeps its anchor.

**Timeline state and edit API** (`timeline.py` and `edit_ops.py` are pure; M2-S6, user confirmed tests pass):
- `build_timeline(project, *, can_undo, can_redo, undo_label, redo_label, missing_source_ids) -> TimelineState`. `TimelineState`: `clips`, `duration_ms`, `other_track_clips` (clips on tracks other than 0, counted but not listed), `orphan_count`, `problems`, `can_undo`, `can_redo`, `undo_label`, `redo_label`, `save_error`. `TimelineClip`: `id`, `position` (among track-0 clips), `source_id`, `start_ms`, `end_ms`, `duration_ms`, `in_ms`, `out_ms`, `speed`, `overlay`, `source` (a `TimelineSource` or null). `TimelineSource`: `id`, `external`, `fps_num`, `fps_den`, `fps`, `width`, `height`, `duration_ms`, `file_missing`. `TimelineProblem`: `kind`, `owner_id`, `missing_id`, `message`. `EditResult(label | null, timeline)` is what undo and redo return.
- Edit ops (`edit_ops.py`): `AddClipOp`, `RemoveClipOp`, `SetSpeedOp`, `ReorderClipOp`, `SplitClipOp`, `TrimClipOp`, `RippleDeleteOp`. Each has an `op` literal tag (`add_clip`, `remove_clip`, `set_speed`, `reorder_clip`, `split_clip`, `trim_clip`, `ripple_delete`) and rejects unknown fields. `EditBatch(label, ops)` needs a non-empty label and at least one op. `build_command(op)` returns the matching clip command. `right_clip_id` is optional on split and ripple-delete; pass your own 12-char hex id when a later op in the same batch has to refer to the new clip.
- Session additions: `timeline()`, `add_clip(source_id, position=None)`, `undo()` and `redo()` (return `EditResult`; nothing to undo or redo gives `label=None`, not an error), `edit(ops, label=None)` (one op without a label is a plain undo step; several ops or a label run as one group, all or nothing), `source_path(source_id) -> Path | None` (from the open project's source list only). `CommandError` and `ValueError` from commands become `SessionError`.
- Media (`backend/media/`): `parse_range(header, size)` returns inclusive `(start, end)` or None (malformed, multi-range, unsatisfiable); `iter_file(path, start, end, chunk)`; `range_response(path, range_header)` gives 200 with the whole file, 206 for a satisfiable single range, 416 with `Content-Range: bytes */size` otherwise, and a 404 JSON if the file cannot be read.

**Footage API** (`backend/project/footage.py`):
- Pure: `parse_rate(text) -> (num, den)`, `parse_probe(data, rel_path, source_id=None) -> Source` (ffprobe JSON from `-show_streams -show_format`), `plan_scan(found, known) -> ScanPlan(to_probe, present, missing)`.
- I/O: `default_ffprobe_path()` (= `<repo>/bin/ffprobe.exe`), `run_ffprobe(path, ffprobe=None, timeout_s=60)`, `list_footage_files(project_folder)` (relative POSIX paths under `footage/`, recursive), `scan_footage(project_folder, known=(), *, probe=None) -> ScanResult(new_sources, present, missing, errors)`.
- `scan_footage` never modifies the project and never touches the files; the caller adds `new_sources` through `AddSource`. A missing ffprobe raises `FfprobeNotFoundError`; a bad single file lands in `errors` as `(rel_path, message)`.
- Frame rate comes from `avg_frame_rate`, falling back to `r_frame_rate` when it is `0/0`. Duration comes from `format.duration` (fallback: stream duration), rounded to integer ms. Audio tracks = count of audio streams. Recognised extensions: `.mkv .mp4 .mov .avi .webm .m4v .flv .ts`. Known sources are matched to files case-insensitively.
- Errors: `FootageError` (base), `FfprobeNotFoundError`, `ProbeError`.

**Command API** (`backend/project/commands.py`):
- `Command` (abstract): `label`, `apply(project)`, `revert(project)`. `apply` validates first and raises `CommandError` before changing anything; it records what it needs to undo itself, and may be re-applied after `revert` (redo).
- Commands: `AddSource(source)` (rejects duplicate id or case-insensitive duplicate path; stores a deep copy), `RemoveSource(source_id)` (refused with `CommandError` while any clip uses the source; undo restores the original list position), `RenameProject(name)` (strips; empty name rejected at construction), `RelinkSource(source_id, new_path)` (path only, no re-probe; rejects invalid paths and paths used by another source).
- `CommandStack(project, on_change=None)`: `execute(cmd)`, `group(label)` context manager, `undo()` / `redo()` (return the label or `None`), `clear()`, `can_undo`, `can_redo`, `undo_label`, `redo_label`, `in_group`, `project`. A new command clears redo. A group is one undo step; if its block raises, applied commands are reverted, nothing is recorded, and the previous redo stack is restored. Nested groups merge into the outermost. Undo, redo and clear raise `CommandError` while a group is open. `on_change` fires once per top-level change (execute outside a group, committed group, undo, redo) and never for failures, empty groups or rollbacks.
- M3 chat B: if a `revert` (undo) or an `apply` during redo raises `CommandError`, the commands already done are undone again, the step stays on its stack and the error is re-raised (before, the entry was dropped). `AddLine.revert` refuses once the line has takes or placements.

**Clip command API** (`backend/project/clip_commands.py`, `backend/project/cut_commands.py`; M2-S3 to S5, user confirmed tests pass). All follow the command contract above, edit **track-0 clips only** (a clip on another track or an unknown id is refused), and leave other-track clips untouched. Positions count among track-0 clips, not raw list indices. All times are integer ms.
- `AddClip(source_id, *, position=None, clip_id=None)`: a clip covering the whole source (in 0, out `duration_ms`, speed 1, overlay on). Default position is before a trailing bookend (last clip, `external` source, `overlay=False`), else the end. Refused for an unknown source, a duplicate clip id, a bad position, or a source shorter than one frame. The clip id is generated when the command is created, so redo reuses it.
- `RemoveClip(clip_id)`: ripple; items anchored to the clip are flagged and parked. `SetSpeed(clip_id, speed)`: 0.25 to 8; setting the current speed is refused (no empty undo step); later clips ripple, anchors keep their source time. `ReorderClip(clip_id, new_position)`: `new_position` is the position after the move; the same position is refused; anchors are untouched.
- `SplitClip(timeline_ms, *, right_clip_id=None)`: splits the clip under the time. The cut snaps to the source frame grid. The left half keeps the clip id, the right half gets `right_clip_id` and is inserted right after it; items at or after the cut move to the right half. Refused at an existing cut, outside the timeline, or when a half would be under one frame.
- `TrimClip(clip_id, edge, source_ms)`: `edge` is `"in"` or `"out"`; the value is a **source** time, snapped to the frame grid (not at 0 or the source's end, and clamped to the source). It can also extend a clip. Refused when under one frame would remain, or when the clip already has that edge. Items in the trimmed-away footage are flagged and parked.
- `RippleDelete(start_ms, end_ms, *, right_clip_id=None)`: removes the timeline range `[start, end)` and closes the gap: covered clips are removed, partly covered clips trimmed, and a clip that strictly contains the range is split (left keeps the id, right gets `right_clip_id`). Items in the removed footage are flagged and parked; items after a split move to the right half. Refused for an empty or out-of-range range, when it would leave under one frame of a clip (the message says to extend or shorten the range), or when it is shorter than one source frame.
- Constants `SPEED_MIN = 0.25`, `SPEED_MAX = 8.0`. Commands that create a clip (`SplitClip`, `RippleDelete`) expose `right_clip_id` so the API and UI can read the new id.

**Template API** (`backend/project/template.py`): `default_template_path()` (= `<repo>/templates/default_channel.json`), `normalize_bookend_path(raw)` (backslashes to forward slashes), `parse_template(data)`, `load_template_file(path=None)`, `external_source(probed, path)` (turns a probed Source into an `external` one), `apply_template(template, name, *, intro_source=None, outro_source=None, seed=None) -> Project`. Error: `TemplateError`.
- The caller probes bookend files (Session does this with ffprobe) and passes the Sources in. A bookend in the template without a matching source, or the reverse, is an error.
- Applied bookends become ordinary clips with `overlay=False`, covering the whole source; intro first, outro last. The template's voice profile is copied with a fresh id. The template object is never mutated. Name is stripped; empty is rejected.

**Session API** (`backend/project/session.py`): `Session(*, template_path=None, probe=None, recent_path=None, audio_info=None, presets=None)`. Holds the one open project and its `CommandStack`; thread-safe (re-entrant lock).
- `current() -> ProjectSummary | None`, `new_project(parent, name)`, `open_project(folder)`, `footage() -> FootageReport`, `rescan_footage()`, `relink_source(source_id, new_path)`, `recent() -> list[RecentItem]`, `forget_recent(folder)`, plus the timeline, edit, undo/redo and `source_path` methods above. Errors: `SessionError`; other module errors (`ProjectError`, `TemplateError`, `FootageError`) pass through.
- M3 chat B additions: `voice()`, `set_voice_reference(path)`; `lines()`, `edit_lines(ops, label=None)`; `takes(line_id)`, `reuse_take(new, *, make_active=True)`, `add_take(new, samples, sample_rate, *, make_active=True)`, `plan_generation(line_id, *, model_version, reroll=False)`, `delete_take(id)`, `delete_line(id)`, `storage()`, `take_path(take_id)`. `audio_info` replaces the audio header reader in tests; `presets` replaces `templates/emotion_presets.json` (loaded on first use otherwise). M3 chat C (S4) additions: `project_key()` (the open project's folder as text, or None); `plan_generation`, `reuse_take` and `add_take` take `project_key=None` and raise `SessionError` ("the open project changed ...") when it is not the open project's key.
- `clean_folder_name(name)` (pure): Windows-safe project name (no `< > : " / \ | ? *`, no trailing dot, no reserved names such as CON or LPT1).
- Opening or creating runs a footage scan automatically; new files are added with `AddSource` inside one `Add footage` group. Scan trouble on open (for example no ffprobe) never blocks opening; it appears in the footage report `errors`.
- Every change through the stack saves `project.json` immediately (`on_change`). A failed save sets `ProjectSummary.save_error` and does not block the edit.
- After the opening footage scan the undo history is cleared (M2-S6b), so the first Ctrl+Z cannot remove sources found on open. A later Rescan is undoable.
- `recent_path=None` (the default, used by tests) records nothing; `backend/main.py` passes `default_recent_path()`.
- Relink rules: source must exist and not be `external`; the picked file must exist and lie inside `<project>/footage/`; it is re-probed and refused unless resolution and frame rate match exactly, length is within 100 ms, and the audio track count matches; picking the source's current path is a no-op.

**Recent list** (`backend/project/recent.py`): `RecentEntry(name, folder, last_opened)`, `RecentItem(+exists)`, pure `add_recent` (newest first, de-duplicated case-insensitively, max 10), `remove_recent`, `parse_recent` (tolerant), `folder_key`; I/O `default_recent_path()` (`%APPDATA%\PNGtuberStudio\recent.json`), `load_recent` (missing or corrupt gives `[]`), `save_recent` (atomic).

**HTTP API** (`backend/app.py`; errors are HTTP 400 with `{"detail": "<message>"}`):

| Method and path | Body | Returns |
|---|---|---|
| `GET /api/hello` | | `{app, status, schema_version}` |
| `GET /api/project` | | `ProjectSummary` or `null` |
| `POST /api/project/new` | `{name, parent}` | `ProjectSummary` |
| `POST /api/project/open` | `{folder}` | `ProjectSummary` |
| `GET /api/footage` | | `FootageReport {items, added, errors}` |
| `POST /api/footage/rescan` | | `FootageReport` |
| `POST /api/footage/relink` | `{source_id, path}` | `FootageReport` |
| `GET /api/recent` | | `RecentItem[]` |
| `POST /api/recent/remove` | `{folder}` | `RecentItem[]` |
| `GET /api/timeline` | | `TimelineState` |
| `POST /api/timeline/clips` | `{source_id, position?}` | `TimelineState` |
| `POST /api/timeline/undo`, `POST /api/timeline/redo` | | `EditResult {label, timeline}` |
| `POST /api/timeline/split` | `{timeline_ms, right_clip_id?}` | `TimelineState` |
| `POST /api/timeline/ripple-delete` | `{start_ms, end_ms, right_clip_id?}` | `TimelineState` |
| `POST /api/timeline/trim` | `{clip_id, edge: "in"\|"out", source_ms}` (**source** time) | `TimelineState` |
| `POST /api/timeline/reorder` | `{clip_id, new_position}` | `TimelineState` |
| `POST /api/timeline/speed` | `{clip_id, speed}` | `TimelineState` |
| `POST /api/timeline/remove` | `{clip_id}` | `TimelineState` |
| `POST /api/timeline/batch` | `{label, ops: EditOp[]}` (each op carries its `op` tag) | `TimelineState`, one undo step |
| `GET /media/source/{source_id}` | optional `Range` header | video bytes: 200, 206, or 416; 404 for an unknown source, a missing file, or no open project |
| `GET /api/voice` | | `VoiceState {status, ready, profile_id, name, reference_path, duration_ms, sample_rate, hash, problems, warnings}`; `status` is `no_profile`, `no_reference`, `file_missing`, `unreadable`, `invalid` or `ready` |
| `POST /api/voice/reference` | `{path}` (absolute path of an audio file) | `VoiceState`; checks and copies the clip into `media/voice/`; one undo step |
| `POST /api/voice/generate` | `{line_id}` | `JobItem`. State `reused` (no GPU, no worker started) when a take with the same raw key exists, otherwise `queued`; 400 when the line cannot be planned (no project, unknown line, voice reference not ready, empty text, unknown emotion) |
| `POST /api/voice/reroll` | `{line_id}` | `JobItem` with `reroll` true; the seed is chosen when the job's turn comes |
| `GET /api/voice/jobs` | | `JobStatus {jobs, active, worker, model_version, worker_message}`; poll about every 500 ms while `active`. `JobItem {id, kind, line_id, reroll, state, phase, chunks_done, chunk_count, reused, take_id, message}`; `kind` is `generate` or `unload`; `state` is `queued`, `running`, `cancelling`, `done`, `cancelled`, `failed` or `reused`; `phase` is `waiting`, `loading`, `generating`, `storing`, `unloading` or `finished`; `worker` is `stopped`, `loading`, `ready`, `unloaded` or `failed` |
| `POST /api/voice/jobs/cancel` | `{job_id}` | `JobStatus`; a queued job is dropped, a running job stops after the piece in flight and writes no take; 400 for an unknown or finished job |
| `POST /api/voice/worker/unload` | | `JobItem` (kind `unload`); runs after the jobs before it and frees the model's VRAM; the next generation loads the model again |
| `GET /api/lines` | | `LineBankState {lines, emotions, can_undo, can_redo, undo_label, redo_label, save_error}` |
| `POST /api/lines/edit` | `{label?, ops: LineEditOp[]}` | `LineBankState`. Ops: `add_line`, `remove_line`, `set_line_text`, `set_line_emotion`, `set_line_exaggeration` / `set_line_cfg_weight` (`value` or null), `set_allow_overlap`, `set_active_take`, `star_take`. One op without a label is one undo step; several ops or a label are one group; an op that changes nothing is skipped |
| `GET /api/lines/{line_id}/takes` | | `TakeItem[]`, oldest first |
| `POST /api/takes/delete` | `{take_id}` | `TakeDeleteReport`; not undoable and resets undo history |
| `POST /api/lines/delete` | `{line_id}` | `TakeDeleteReport` (the line and all its takes); refused while the line is placed |
| `GET /api/storage` | | `StorageReport {lines, take_count, total_bytes, missing_file_count, unreferenced, unreferenced_bytes}` |
| `GET /media/take/{take_id}` | optional `Range` header | take WAV bytes through `range_response`; 404 for an unknown take, a missing file or no open project |

`ProjectSummary`: `name`, `folder`, `schema_version`, `source_count`, `clip_count`, `voice_status`, `avatar_status` ("not configured" or "path set" text only), `save_error`, `problem_count` (broken references from `check_references`; 0 when sound). Static frontend is mounted at `/` after the API routes; if `frontend/dist` has no `index.html`, `/` shows a "Frontend not built" page. Errors from commands are HTTP 400 `{"detail": message}`; a malformed request body is FastAPI's standard 422.

**pywebview bridge** (`backend/main.py` `Api`): `window.pywebview.api.pick_folder()` and `pick_file()` (video file filter) return a path or `null`. Works on both the older and newer pywebview dialog constants.

**Voice pure modules** (`backend/voice/`, M3 chat A; user confirmed pytest and ruff pass on the real repo after one lint fix round: RUF046, RUF007, I001). No I/O except `load_presets_file`.
- `presets.py`: `EmotionPreset(name, exaggeration, cfg_weight, expression)`; `PresetError`; `parse_presets(data)` for `{"presets": {name: {exaggeration, cfg_weight, expression}}}` (unknown or missing keys, out-of-range values, bools and NaN rejected; `neutral` required; file order kept); `resolve_params(emotion, exaggeration_override, cfg_weight_override, presets) -> (exaggeration, cfg_weight)` (override beats preset, each independently; unknown emotion raises `PresetError`); `default_presets_path()` (= `<repo>/templates/emotion_presets.json`); `load_presets_file(path=None)`.
- `keys.py`: `normalize_text` (collapse whitespace); `raw_key(*, text, voice_profile_id, reference_hash, exaggeration, cfg_weight, seed, model_version)` returns a SHA-256 hex (64 chars) of canonical JSON; text is normalised, floats rounded to 4 decimals, `-0.0` equals `0.0`, empty inputs and non-finite numbers raise `ValueError`; `base_seed(project_seed, line_id)`; `next_unused_seed(base, key_for_seed, existing_keys)` (lowest `base + k` whose key is unused, wraps at `SEED_MODULUS = 2**31`); first generation uses the base seed itself.
- `chunking.py`: `MAX_CHUNK_CHARS = 200`, `CROSSFADE_MS = 40`; `split_sentences(text)` (ends at `. ! ? ...` plus closing quotes, then whitespace; not after common abbreviations such as Mr or e.g., not after lone initials other than I and a, never inside decimals); `plan_chunks(text, max_chars=200)` (text at or under the limit is one normalised chunk; longer text is split into sentences, over-long sentences are cut at commas, then spaces, then hard, and pieces are packed greedily; `max_chars` below 20 raises); `chunk_seed(seed, index)` (chunk 0 keeps the take seed); `crossfade_join(chunks, sample_rate, crossfade_ms=40)` (mono float32, equal-power, fade shortened to half the shorter neighbour, output length is the sum minus the overlaps).
- `overflow.py`: `PlacedLine(placement_id, start_ms, duration_ms, allow_overlap)` (timeline start, duration of the audio that plays); `find_overflows(items) -> list[Overflow(placement_id, next_placement_id, overflow_ms, allowed)]` (only the immediately following placement counts; `allowed` mirrors the overflowing line's `allow_overlap`, callers warn only when it is false; sorted by start then id; negative values and duplicate ids raise); `available_slack_ms(items, placement_id)` (gap after the previous line's end, or the start itself for the first line; never negative).

**Voice backend (M3 chat B, rounds a to d; written without being run).**
- Voice profile: v1 uses `project.voice_profiles[0]`. `Session.set_voice_reference(path)` decodes the header (`soundfile`), checks it (`check_reference`), copies it to `media/voice/<stem>-<hash8><ext>` (allowed: .wav .flac .ogg .mp3; same file again reuses the copy) and sets it as the profile's only reference clip through `SetReferenceClip` (creates a "Default" profile first if there is none). The reference hash is `sha256` of the file bytes, memoised by path, size and mtime. `voice()` returns `VoiceState`.
- Line bank: line edits are commands on the shared `CommandStack`; ops in `line_ops.py`. Unknown emotions are refused (checked against the presets). `LineItem` carries the stored overrides, the effective values (preset, then override; null if the emotion is no longer in the presets) and take and placement counts; `generated` means the line has an active take.
- Take store: `media/takes_raw/<take_id>.wav`, float32 mono WAV written through a temp file and `os.replace`. `add_take` writes the file, appends the `Take`, makes it the line's active take (unless `make_active=False`) and saves. Takes are **not undoable** (rule 1). `reuse_take` finds a take with the same raw key (rule 3); a take of another line with the same key is copied into a new take for this line, no generation. If the record exists but its file is gone, `add_take` writes the audio back into the same record.
- Delete: `delete_take` / `delete_line` remove records (project saved first), then files. A line's active take that goes is cleared; a placement `take_override_id` that goes is cleared (the placement falls back to the line's active take); both are listed in `TakeDeleteReport`. Undo history is reset. A line delete is refused while placements use the line. Files that cannot be deleted are listed in `failed_files`.
- Generation flow for chat C: `plan = session.plan_generation(line_id, model_version=..., reroll=...)`; `session.reuse_take(plan.new_take)`; if None, the worker generates `plan.chunks` with `plan.reference_path` and `plan.new_take.seed` (chunk `i` uses `chunk_seed(seed, i)`), then `session.add_take(plan.new_take, samples, 24000)`. `plan_generation` needs a ready voice reference and a line with text and a known emotion; first generation uses `base_seed(project.seed, line_id)`, a reroll the lowest unused `base + k` among the line's takes.
- Storage: `storage()` gives sizes per line and take, missing files, and files in `media/takes_raw/` that no take points at (reported only; the app never deletes them by itself).

**Voice worker and queue (M3 chat C, S4; written without being run).**
- Process: the GPU worker is `python -m backend.voice.worker_main`, started by `SubprocessWorker` with an argument list from the repo root. Commands arrive as JSON lines on stdin, events leave as JSON lines on stdout; everything else a library prints goes to stderr and into `%APPDATA%\PNGtuberStudio\worker.log`. Audio never travels over the pipe: the worker writes the joined take to the `output_path` in the generate command (a temp file under `%TEMP%\PNGtuberStudio-jobs`) and reports `done`; the queue reads it, calls `add_take` and deletes the temp file.
- Worker logic (`WorkerLoop`): `load` loads the model, warms it up with the built-in voice (a failed warm-up is only logged), then reports `ready` with the model version. `generate` runs the pieces in order (`chunks[i]` with `seeds[i]`, which the backend derives with `chunk_seed`), emits `progress` after each piece, joins pieces with `crossfade_join` and writes mono float32 WAV through a temp file. A cancel (applied at once by the reader thread) is checked after each piece: the piece in flight finishes, then `cancelled` is sent and no file is written; cancel wins over `done`, also on the last piece. An engine error ends the job with a non-fatal `error`; a failed load is a fatal `error` and the worker exits.
- Queue (`JobQueue`): one thread runs jobs in submit order and is the only thread that touches the worker. `submit` plans the line (`plan_generation`) and tries `reuse_take` at once; a hit is a finished job with state `reused`, no thread and no worker. Otherwise the job waits; when its turn comes it plans again (so rapid rerolls get seeds `base`, `base+1`, ... and a repeated request reuses its twin's take), starts and loads the worker if needed (the model then stays loaded), sends `generate`, waits for `done` and stores the take. Every host call carries the `project_key` seen at submit time, so a job whose project was closed fails with "the open project changed" instead of writing into another project.
- Failures: a fatal worker error, a dead process or a worker silent for `stall_timeout_s` (300 s) restarts the worker and retries the job once (the retry uses worker job id `<id>~2`); a second failure fails the job with the reason. A non-fatal worker error fails the job without a retry. Loading has its own timeout (`load_timeout_s`, 900 s because the first run downloads the weights). A cancelled job is never retried. If a result still arrives after a cancel, it is discarded.
- Cancel: a queued job becomes `cancelled` at once; a running job becomes `cancelling`, the queue thread sends the worker a cancel, and the job ends `cancelled` after the piece in flight (a single-piece line therefore finishes generating and its audio is thrown away; the UI should say "Cancelling..."). Finished jobs cannot be cancelled (400).
- Unload: `POST /api/voice/worker/unload` queues a job that sends `unload`; the worker stays alive without the model (`worker` is `unloaded`) and the next generation sends `load` again.
- Model version: `chatterbox_model_version()` (`chatterbox-tts <installed version>`, from package metadata) is part of every raw key and is known without the worker; when the worker reports `ready`, the queue checks it matches the planned version and fails the job otherwise.
- Check on the real GPU: `uv run python scripts\spike\worker_check.py --ref "<ref.wav>"` (see "How to run / test").

## Editor screen (frontend, M2-S8; user confirmed each sub-round in the app window)

- Reached from "Open editor" on the project screen (`App.svelte` `view` flag, no router). "Back to project" returns and refreshes the summary; opening or creating a project resets to the project screen. The editor renders outside `<main>` so it can use the full width.
- `Editor.svelte` holds the last `TimelineState` (every edit replaces it, so the screen always redraws from one object), `playheadMs`, `selectedId` and `busy`. `edit(action)` runs an edit and shows a 400 `detail` as the red message; `history()` runs undo and redo and shows "Undid: <label>". Playhead, selection and zoom are UI state only and are not saved.
- `Player.svelte` (props `clips`, `durationMs`, bindable `playheadMs`): plays from the playhead with one `<video>`. Next clip on the same source that starts exactly where this one ends: no seek. Same source, not contiguous: seek. Different source: the `src` is swapped (a hitch). Rate is `clip.speed` with `preservesPitch`. It writes the playhead each animation frame and remembers its own writes; any other change to the playhead (click, hotkey, scrub) or any edit pauses playback and re-cues the frame.
- `Timeline.svelte` (props `clips`, `durationMs`, bindable `playheadMs` and `selectedId`, `locked`, `label`, `ontrim`, `onreorder`): canvas drawn on every change. Ruler click or drag seeks. A click on a clip selects it and seeks. The outer 6 px of a clip is a trim handle; pressing a clip body and moving more than 4 px starts a reorder. A trim or reorder sends exactly one call on release (`ontrim` / `onreorder` resolve when the edit is done), so a drag is one undo step. During a trim drag the clips resize live; during a reorder a ghost and a drop marker show. Wheel scrolls, Ctrl+wheel zooms around the cursor, buttons and a slider also zoom and scroll; Fit shows everything; the view follows the playhead.
- Hotkeys (`Editor.svelte`, ignored while typing in a text, number or select field): Space play/pause, `,` and `.` step one **source** frame (crossing a cut lands on the neighbouring clip), S split at the playhead, Delete remove the selected clip, `[` and `]` cut the selected clip's in or out edge at the playhead (source time computed from the clip's `in_ms` and speed; after `[` the playhead moves to the clip start), Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z undo and redo.
- The selected-clip bar has a speed dropdown (0.25 to 8 presets, plus the clip's current value) and Remove clip.
- Pure helpers in `timeline.ts` mirror a few backend rules for display only (see decisions). There are no automated frontend tests; checks are `npm run check` and the manual run.


## Voice UI (frontend, M3 chat D / S5; user confirmed each round in the app window)

- **Project screen, Voice section** (`App.svelte`): shows `GET /api/voice` (status sentence, reference path, length, sample rate, 8-character fingerprint, problems red, warnings amber). A path box with "Use this path" and "Choose file..." (native picker, imports at once) call `POST /api/voice/reference`. Quotes from "Copy as path" are stripped.
- **Editor tabs** (`Editor.svelte`): Footage, Line bank and Storage. All three panels stay mounted and are hidden with the `hidden` attribute, so selection and drafts survive a tab switch.
- **Line bank** (`LineBank.svelte`, props `reloadToken`, `onedited`, `jobs`, `onjobchange`): the list shows number, text preview, emotion, take count and "placed". Text commits on blur or Enter (Escape reverts) as one undo step; emotion, allow-overlap and slider releases are one undo step each. Edits are sent through a promise chain so a blur and a click right after it cannot overlap. New lines get a client-made 12-hex id so the new line can be selected and focused at once. Remove line is enabled only with no takes and no placements.
- **Undo state:** line edits share the project's command stack, so after each one the editor refreshes only the undo and redo fields of its timeline state (`syncHistory`), and after an undo or redo it bumps `lineReload` so the line bank reloads.
- **Jobs:** `Editor.svelte` owns the job list. `refreshJobs` polls `GET /api/voice/jobs` every 500 ms while `active` (2 s retry after an error) and reloads the lines, undo state and storage when a live job ends. Generate and Reroll call `jobsChanged` so a `reused` job (finished at once) also reloads.
- **Take picker:** takes newest first with Play/Stop (a plain `Audio` on `/media/take/<id>`), length, seed, the two values used, "older text" when the line text changed, Star, and Use this take / Active.
- **Status bar** (sticky): voice model state, GPU queue (current job text, "+N waiting", Cancel), the last finished job (for example "Reused an existing take (no GPU time)"), and "Takes on disk: size (count)" with a red missing-file count.
- **Storage tab:** totals, lines with their takes and sizes, Delete take and Delete line and takes with an inline confirmation (no browser dialog), a notice of what was freed or cleared, unreferenced files listed read-only. Deletes are permanent and not undoable (rule 1: only this explicit action deletes takes).
- **Hotkeys** (ignored while typing): N new line (opens the Line bank tab), G generate and Shift+G reroll the selected line.
- Types live in `api.ts`; the shapes are listed in `docs/API_MODELS.md`. There are no automated frontend tests; checks are `npm run check`, `npm run build` and the manual run.

## M0 findings (2026-10-10, user's machine)

**Machine:** Windows, RTX 4060 Laptop GPU (8 GB), NVIDIA driver 581.42.

**Versions that worked (user confirmed):** Python 3.11.17, torch 2.6.0+cu126, torchaudio 2.6.0+cu126, chatterbox-tts 0.1.7, numpy 1.26.4, transformers 5.2.0, ffmpeg n8.1.3-17-gc389840894 (BtbN GPL build, 8.1 branch). Other package versions are in `uv.lock`.

**Chatterbox (original `ChatterboxTTS`, not Turbo or Multilingual):**
- API: `ChatterboxTTS.from_pretrained(device="cuda")`, then `generate(text, audio_prompt_path=..., exaggeration=0.5, cfg_weight=0.5, temperature=0.8, ...)`. Sample rate is `model.sr` = 24000.
- `generate` has **no seed argument**. The scripts call `torch.manual_seed(seed)` before each call. Reproducible by ear (M3 chat A); bit-exact check not reported.
- Timings: import 5.3 s, model load 9.0 s (weights cached). First generation 27.4 s (one-time warmup), later lines about 4.6 s for 5 to 6 s of audio (roughly real time). The progress bar shows about 35 to 40 it/s.
- VRAM: 2.99 GiB after load, 3.60 GiB peak during generation, 4.83 of 8.00 GiB in use device-wide (desktop apps included). Peak with a browser or pywebview window open at the same time was **not measured**.
- Voice quality (user confirmed): with the neutral reference (`NanairoMiku_Ref_02_Neutral-enhanced-v2.wav`), voices sound realistic but flat. Neutral 0.50/0.50 usable, slightly slow. Excited 0.75/0.35 sounded flat and sarcastic. Nervous 0.65/0.40 sounded the same as neutral. Exaggeration 1.0 to 1.2 adds some cadence and pitch movement, but the voice gets slightly garbled ("underwater"). Open questions: whether a reference clip with real emotion widens the range, and whether the "enhanced" reference clip contributes to the artifacts.

**Player (user confirmed):** hand-written HTTP Range endpoint in FastAPI plus `<video>` in a pywebview window plays a 4.8 GB, 10 min OBS MKV (H.264, 2560x1440, 60 fps, AAC stereo) with sound. Seeks completed in 17 to 281 ms. The browser issues open-ended `bytes=N-` requests, answered with 206.

**NVENC (user confirmed):** `h264_nvenc` works with ffmpeg n8.1.3. A 10 s 1440p60 to 1080p60 encode ran at 4.4x to 4.9x realtime, about 12 to 13 MB per 10 s at `-cq 23`. Output plays with picture and audio correct. The ffmpeg `master` build (N-127271) and 9.0 builds fail on this driver with "Required: 13.1 Found: 13.0 / minimum driver 610". Working command is in "How to run / test".

**Footage facts (user's OBS recordings):** MKV, H.264 High yuv420p bt709, 2560x1440, 60 fps, single stereo AAC track (48 kHz), about 62 Mbps. Recording frame rate is 60.

**Go / no-go: GO.** All three risks cleared. Caveat: emotional range from the voice clone is limited with a neutral reference clip, so emotion presets alone may not be enough. Treat in M3 (tune by ear, try an expressive reference clip).

## M1 manual checks (user confirmed)

- M1-3 scan of a real OBS clip (10 s `-c copy` cut) produced: path `footage/clip10.mkv`, 2560x1440, 60/1, 1 audio track, duration 12812 ms. Resolution, rate and audio match. The duration is above the requested 10 s, probably because a stream copy starts at a keyframe (not verified; not a detection bug as far as known).
- M1-6 (user confirmed): app window opens with the project screen; New project (with a folder named with a space), Open (Browse and typed path), Recent list (reopen, missing marker, Remove leaves the folder on disk), footage table with Rescan, missing footage flagged, relink to a moved file all work.
- M1 acceptance run (user confirmed): create from template, add footage, close and reopen from Recent with everything intact; move footage out and back; relink a file moved into a subfolder of `footage/`.

## M2 manual checks (user confirmed)

- M2-S7: `scripts\dev\media_check.py` (deleted after M2-S8, which plays the same endpoint) on the real 1440p60 recording: the video plays with sound through `GET /media/source/{id}` in the pywebview window and seeking works. The seek timings and request log were not recorded.
- M2-S8a to S8f (user confirmed "all pass" after each sub-round, with `npm run check` and `npm run build` clean and no console errors): add to timeline, undo/redo buttons; playing a clip with correct start and end; playing across several clips with hopping and speed; canvas timeline (ruler, clips, cut markers, playhead, click and drag to seek, zoom, scroll); selection and all hotkeys; drag trim and reorder with one undo step per drag.
- M2 end (2026-10-12): `uv run pytest` gives 490 passed, 1 warning; `uv run ruff check .` all checks passed. At wrap-up the user did not itemise the nine-step manual acceptance run from `docs/tasks/M2-timeline.md` or paste a final `npm run check`; each editor sub-round had been confirmed on its own (above). Tick the manual acceptance boxes in the task file after running it once more on the real recording.

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
| 2026-10-10 | M0: use original `ChatterboxTTS` 0.1.7. It requires `torch==2.6.0`, so the project pins torch 2.6.0+cu126 from the cu126 index and `requires-python = "==3.11.*"` |
| 2026-10-10 | M0: pin `setuptools<81`. `resemble-perth` imports `pkg_resources`; without it `PerthImplicitWatermarker` is `None` and model load fails with a `TypeError`. Include in `install.bat`/lockfile |
| 2026-10-10 | M0: Chatterbox `generate` has no seed parameter; the seed in the take cache key is applied via `torch.manual_seed` before each call (reproducibility to be verified in M3) |
| 2026-10-10 | M0: bundle a pinned ffmpeg **release-branch** build (BtbN GPL 8.1.x), never `master` or 9.0. Newer builds need NVENC API 13.1 (driver 610+); driver 581.42 provides 13.0. Record the ffmpeg version in the install script and show a clear error if NVENC fails to open |
| 2026-10-10 | M0: video playback = custom Range endpoint (`scripts/spike/player_spike.py`: `parse_range`, `iter_file`) served to a `<video>` tag; OBS MKV/H.264 plays and seeks without remuxing |
| 2026-10-10 | M0: recordings are 2560x1440@60; export scales to 1080p (verified with NVENC, `scale=-2:1080`) |
| 2026-10-11 | M1: **time = integer milliseconds** everywhere (user choice). Exact to compare and hash. At 59.94 fps a frame is 16.683 ms, so M2 frame lookups must round to the nearest frame, never floor |
| 2026-10-11 | M1: items carry an explicit `orphaned: bool` (Placement, Keyframe, Reaction). M1 stores it only; M2 sets it |
| 2026-10-11 | M1: ids are uuid4 hex truncated to 12 chars; JSON paths are relative POSIX strings (no absolute, no `..`), except `external` sources (see 2026-10-12) |
| 2026-10-11 | M1: fps stored as `fps_num`/`fps_den` so 59.94 (60000/1001) is exact |
| 2026-10-11 | M1: `Take` stores a text snapshot, `model_version`, and `raw_key` so it stays valid if the line is edited; `Placement` and the other timed items get their own `id` |
| 2026-10-11 | M1: default `game_audio_db` = 0.0 (tune in M4); default avatar position x 0.85, y 0.75 as fractions of the frame |
| 2026-10-11 | M1: `.bak` is only rotated from a `project.json` that parses as JSON, so a corrupt file never replaces a good backup; `load_project(use_backup=True)` is the recovery path |
| 2026-10-11 | M1: autosave policy defaults: 2 s debounce, 15 s max wait; timing logic is pure. **Superseded 2026-10-12:** the app saves on every change; the tracker is unused |
| 2026-10-11 | M1: pytest finds `backend` through a repo-root `conftest.py`; no pyproject pytest config needed |
| 2026-10-11 | M1: fps for a Source comes from ffprobe `avg_frame_rate` (fallback `r_frame_rate` when `0/0`); duration from container `format.duration` rounded to integer ms. Variable-frame-rate files are not specially handled |
| 2026-10-11 | M1: footage scan is recursive under `footage/`, recognises `.mkv .mp4 .mov .avi .webm .m4v .flv .ts`, matches known sources to files case-insensitively (Windows), and only builds Source objects; adding them is a command |
| 2026-10-11 | M1: command contract: validate then mutate, raise `CommandError` before any change; each command records its own undo data (no project snapshots); groups are atomic (rollback on exception, redo stack restored); undo/redo not allowed while a group is open |
| 2026-10-11 | M1: `RemoveSource` is refused while any clip references the source (guards the missing cross-reference validation); `AddSource` rejects duplicate id or duplicate path |
| 2026-10-11 | M1: `RelinkSource` changes the path only and does not re-probe metadata (the re-probe check lives in `Session.relink_source`, see 2026-10-12) |
| 2026-10-11 | M1: `CommandStack` takes an optional `on_change` callback (fires once per top-level change) as the autosave hook |
| 2026-10-12 | M1: **bookend clips outside the project folder** are `Source` entries with `external = true` and an absolute POSIX path (decided in M1-5). Template paths may be written with backslashes and are normalised. Bookend clips cover the whole source, `overlay=False`, intro first and outro last |
| 2026-10-12 | M1: applying a template gives the new project its own copy of the voice profile with a fresh id; the template itself is never mutated. The default template ships with no bookends |
| 2026-10-12 | M1: the backend holds one open project in a `Session`; all edits go through its `CommandStack`; every change is **saved immediately** (no debounce) and a failed save is surfaced as `save_error`, never silently. Revisit debounce in M2 if needed |
| 2026-10-12 | M1: recent projects are stored per user at `%APPDATA%\PNGtuberStudio\recent.json` (max 10, newest first, de-duplicated case-insensitively). Entries for folders that no longer exist are shown as missing and removed only by the user. "Remove" never touches the project folder |
| 2026-10-12 | M1: project name = folder name (`<parent>\<name>`), validated Windows-safe; a folder that already holds a `project.json` is refused |
| 2026-10-12 | M1: footage is scanned automatically on open/create and by Rescan. New files are added in one undoable group. Missing files are flagged from disk and never removed automatically. Scan trouble on open never blocks opening |
| 2026-10-12 | M1: relink requires the picked file to be inside `<project>/footage/`, re-probes it, and refuses a mismatch (resolution and frame rate exact, length within 100 ms, same audio track count). Relinking `external` sources is not supported yet |
| 2026-10-12 | M1: API errors are HTTP 400 with `{"detail": message}`; the frontend shows `detail` text as-is |
| 2026-10-12 | M1: frontend is Svelte 5 + TypeScript strict + Vite 6, built with `npm run build` to `frontend/dist` and served by FastAPI. Node is needed only to build. `package-lock.json` is committed |
| 2026-10-12 | M1: native pickers go through a pywebview `js_api` (`pick_folder`, `pick_file`); the api object holds no window reference. The page falls back to typed paths when not running in the app window |
| 2026-10-12 | M2: timeline = track 0 of `Project.clips`, a gapless sequence in list order, ripple everywhere. The UI edits track 0 only. Clips on other tracks are ignored by time mapping (an anchor pointing at one maps to `None`) and preserved untouched by every command |
| 2026-10-12 | M2: rounding is half up with exact math (never banker's, never floor). Clip timeline length = `round((out - in) / speed)`; source to timeline = `start + round((source_ms - in) / speed)`; timeline to source clamps to `out - 1`. A valid anchor has `in <= source_ms < out`; `to_timeline` also accepts `source_ms == out` (clip end). Implemented and tested in M2-S2 |
| 2026-10-12 | M2: cut points and trim edges snap to the nearest frame of that source; the playhead and anchors never snap; a source's own ends (0 and `duration_ms`) are not snapped. `timemap.py` takes fps as arguments; commands do the snapping |
| 2026-10-12 | M2: round-trip error is not always 1 ms. Timeline to source to timeline is exact at speed >= 1, within `1/speed` ms below 1; source to timeline to source within `speed/2 + 0.5` ms. At speed > 1 an anchor in the last half-speed ms of a clip maps to the clip end, which is the next clip's start (quantization edge, tested) |
| 2026-10-12 | M2: orphan parking (built in M2-S5): the anchor is rewritten to the nearest surviving clip edge and `orphaned=True` is set; the command stores the old anchor and flag so undo restores them exactly. "Nearest" is measured in the **old** timeline, from the item's old position to the two ends of the removed footage (after a ripple both edges sit at the same new time); ties go to the earlier edge. The earlier edge is the last frame of the clip before the cut (`out_ms - 1`), the later edge is `in_ms` of the clip after it. If no clip survives the anchor is left as is and flagged (reported by `check_references`). Nothing un-orphans except undo; resolving is a later re-anchor command |
| 2026-10-12 | M2: "add to timeline" (built in M2-S3) adds a clip covering the whole source (in 0, out `duration_ms`, speed 1, overlay on). It inserts before a trailing bookend (last clip, `external` source, `overlay=False`), otherwise at the end, or at an explicit position |
| 2026-10-12 | M2: reference validation is a separate pure `check_references(project)` returning `ReferenceProblem`s (clip missing source, item missing clip). It never makes an old file unloadable; `Project` gets no cross-reference validator. **Changed from the earlier plan:** the commands do not call it (each already validates its own target ids, and refusing every edit on a file with one old broken reference seemed worse). The session is to call it after load (S6) |
| 2026-10-12 | M2: a clip must be at least one source frame long (`max(1, frame_to_ms(1, fps))` ms of source time). Splitting at an existing cut or outside the timeline is refused with a clear message. Ripple-delete trims partially covered clips and removes fully covered ones, and refuses a range that would leave under one frame of a clip or that is shorter than one source frame. Built in M2-S3 and S4 |
| 2026-10-12 | M2: speed changes ripple later clips (their start moves, their anchors do not). Anchors inside a changed clip keep their source time, so their timeline time scales with the clip. Built as `SetSpeed` (M2-S3) |
| 2026-10-12 | M2: on split the left half keeps the original clip id and the right half gets a new id. Anchored items with `source_ms >= split point` are re-pointed to the right half (not orphaned); an anchor exactly at the split point goes to the right half. Built as `SplitClip` (M2-S4) |
| 2026-10-12 | M2: ripple-delete of a range strictly inside one clip leaves two clips (left keeps the id, right is new). Anchors inside the deleted range are orphaned and parked; anchors after it move to the right half's id. Built as `RippleDelete` (M2-S4, S5) |
| 2026-10-12 | M2: still-frame images as footage and freeze-frame of part of a clip are not in v1 (CLAUDE.md out-of-scope: freeze effects; the footage scan only knows video files). The model leaves room through `Clip.effects` and the effect registry. Possible backlog item; no M2 change |
| 2026-10-12 | M2 (chat B): the clip commands live in new files `backend/project/clip_commands.py` and `backend/project/cut_commands.py`, not in `commands.py`, which stays the M1 base layer (`Command`, `CommandStack`, source commands). The new files import `Command`, `CommandError` and `_find_source` from it |
| 2026-10-12 | M2 (chat B): clip commands edit track-0 clips only; positions (`AddClip.position`, `ReorderClip.new_position`) count among track-0 clips, not raw list indices. Commands that create a clip take an optional id (`clip_id`, `right_clip_id`) generated at construction so redo reuses the same id |
| 2026-10-12 | M2 (chat B): `TrimClip` takes a source time (the `[` and `]` hotkeys convert the playhead to source time first) and can extend a clip as well as shorten it. No-op edits (same speed, same position, same edge) are refused so they never create an empty undo step |
| 2026-10-12 | M2 (chat B): orphan parking is applied by `RemoveClip`, `TrimClip` and `RippleDelete` through `backend/project/parking.py` (collect before the edit, park after, restore on revert). `ReorderClip`, `SetSpeed` and `SplitClip` orphan nothing. An already orphaned item that is cut again is re-parked and stays flagged; undo restores its previous anchor and flag. This replaced the temporary "refused while anchored" guards used in S3 and S4 |
| 2026-10-12 | M2 (chat B): the speed > 1 quantization edge is **ignored by parking**. A parked `out_ms - 1` anchor stays tied to its own clip; only UI hit-testing could notice the edge |
| 2026-10-12 | M2 (chat C): API shape = one endpoint per edit operation, each returning the full `TimelineState`, so the editor always redraws from one object. Undo and redo return `EditResult {label, timeline}`. The edit op models are the request bodies, so there is one definition per operation |
| 2026-10-12 | M2 (chat C): compound edits go through `POST /api/timeline/batch`, which runs the ops in a `CommandStack.group` (one undo step, one save, all or nothing). A drag sends a single op on mouse-up, which is already one undo step. The client may supply `right_clip_id` so later ops in a batch can name a clip the batch creates |
| 2026-10-12 | M2 (chat C): the timeline state only lists track-0 clips; clips on other tracks are counted in `other_track_clips` and left untouched. Missing footage files are flagged per source (`file_missing`) by the session, not by the pure builder |
| 2026-10-12 | M2 (chat C): the undo history is cleared after the footage scan on open and create, so Ctrl+Z can never undo "Add footage" and remove sources. Rescan during editing stays undoable |
| 2026-10-12 | M2 (chat C): `check_references` is run by the session, not by the commands. Its count is in `ProjectSummary.problem_count` and its details in `TimelineState.problems`. Old files with broken references still load |
| 2026-10-12 | M2 (chat C): the media endpoint is `GET /media/source/{source_id}`. The file path comes only from the open project's source list; an unknown id, a missing file or no open project is a 404. Single ranges only. MIME type is the M0 behaviour (`mimetypes` guess, else `application/octet-stream`), which is what was proven to play the OBS MKVs. No HEAD route and no cache headers (the M0 spike had neither) |
| 2026-10-12 | M2 (chat C): malformed request bodies keep FastAPI's 422 with a list `detail`. Overriding it globally could change existing endpoints; user mistakes go through the commands and come back as readable 400s |
| 2026-10-12 | Work method: code is delivered as a zip that mirrors the repo layout (complete files, extracted in the repo root). `CLAUDE.md` "Delivering changes" was amended to make this standing |
| 2026-10-12 | M2 (chat D): the editor is one screen reached from the project screen by a `view` flag in `App.svelte` (no router). The playhead, selection and zoom are UI state, not saved in `project.json` |
| 2026-10-12 | M2 (chat D): playback = one `<video>` hopping between clips. Contiguous clips on one source (next `in_ms` equals this `out_ms`) continue without a seek; other hops on the same source seek; a different source swaps `src` (accepted hitch per spec 9). Rate comes from `clip.speed` with pitch preserved |
| 2026-10-12 | M2 (chat D): `Editor.svelte` owns `playheadMs` and binds it to the player and the timeline. The player recognises its own writes, so an outside change pauses and re-cues, and any edit (a change in the clip layout) pauses playback |
| 2026-10-12 | M2 (chat D): `frontend/src/timeline.ts` mirrors a few time-mapping rules for display, playback, frame stepping and drag previews (`toSource` clamps to `out - 1`, spans from `start_ms`, trim targets snapped to the source frame grid). The backend `timemap.py` and the commands stay the source of truth and snap trims themselves; a mismatch could only show as a playhead off by about a millisecond or a drag preview that differs slightly from the result |
| 2026-10-12 | M2 (chat D): selection is one clip, chosen by clicking it. **Delete removes the selected clip** (`remove_clip`, the same ripple as ripple-deleting its span); there is no time-range selection yet, so the UI never sends `ripple_delete` (the endpoint stays tested). `[` and `]` cut the selected clip's edge at the playhead in source time. Spec 4.2 text updated (see wrap-up replacement) |
| 2026-10-12 | M2 (chat D): frame stepping moves one **source** frame (at 2x one step is about 8.3 ms of timeline); stepping past a cut lands on the neighbouring clip, backwards on its last millisecond |
| 2026-10-12 | M2 (chat D): drags: the outer 6 px of a clip is a trim handle, a press on the body that moves more than 4 px is a reorder, anything on the ruler or empty space scrubs. One call per drag on release, with the drag picture kept until the backend answers. Drags that would edit are ignored while an edit is in flight |
| 2026-10-12 | M2 (chat D): hotkeys are hard-coded to the spec 4.2 defaults and ignored while typing in a field; Space is also swallowed on key release so a focused button is not clicked. A remappable hotkey setting is not built |
| 2026-10-12 | M2 (chat D): the speed control is a dropdown of presets (0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 8) plus the clip's current value; other values only through the API |
| 2026-10-12 | M2 (chat D): no backend or schema change in chat D, and none in M2 overall: `schema_version` stays 1 and no migration was needed |
| 2026-10-13 | M3 (chat A): `docs/tasks/M3-voice.md` reconciled with the plan. The plan wins over the draft: waveform blocks (M3-7), Tighten (M3-9), take delete and the storage manager with sizes (M3-4), the voice profile settings screen (M3-1) and drag-to-place are in M3. Six chats (A to F) instead of five |
| 2026-10-13 | M3 (chat A): seed check. The user ran `seed_check.py` and judged by ear that seed 1234 repeats and seed 99 differs; a bit-exact comparison was not reported. The cache-key rule does not rely on it: same key means reuse the saved take |
| 2026-10-13 | M3 (chat A): worker protocol is a subprocess with JSON lines over stdin and stdout (commands load, generate, cancel, unload, shutdown; events ready, progress, done, error), behind a `WorkerClient` interface with a `FakeWorker` for tests; library prints go to the log file; one automatic restart after a crash |
| 2026-10-13 | M3 (chat A): cancel happens between sentence chunks. A single-chunk line finishes and its result is discarded (no take written); the UI shows "Cancelling...". No kill and restart |
| 2026-10-13 | M3 (chat A): seed policy. A line's first seed is `base_seed(project.seed, line_id)`; a reroll takes the lowest `base + k` whose key is not already among the line's takes; chunk `i` of a take uses `seed + i`. No schema change |
| 2026-10-13 | M3 (chat A): cache-key details. Text is whitespace-normalised before hashing, floats are rounded to 4 decimals, and the chunking constants are not part of the key, so changing them never invalidates existing takes |
| 2026-10-13 | M3 (chat A): job progress by polling a status endpoint (about 500 ms while a job is active); WebSocket only if polling feels slow |
| 2026-10-13 | M3 (chat A): the reference clip is copied into `media/voice/` in the project and stored as a relative path; validated (decodes, length sensible, warn under 5 s); its hash is computed on demand and memoised by size and mtime. No schema change |
| 2026-10-13 | M3 (chat A): take files are float32 24 kHz mono WAV under `media/takes_raw/`; lines up to 200 characters are never split; longer lines are chunked at sentence boundaries and joined by the worker with a 40 ms equal-power crossfade |
| 2026-10-13 | M3 (chat A): in-context playback uses Web Audio, scheduled from the player's clock with each start from `to_timeline(anchor)`, rescheduled on seek, pause and hop; voice plays at 1x regardless of clip speed; M3 plays raw or tightened takes, M4 swaps in processed ones |
| 2026-10-13 | M3 (chat A): overflow is computed by a pure function over timeline start plus audio duration; `allow_overlap` marks the result as allowed (no warning). Nudge earlier, Regenerate and Tighten all ship in M3 (the plan puts Tighten there) |
| 2026-10-13 | M3 (chat A): undo and deletes. Each line edit is one undo step (text commits on blur or Enter); Generate is not undoable. `RemoveLine` is an undoable command only for a line with no takes and no placements. A line with takes is deleted from the storage manager ("Delete line and its takes", explicit confirmation, not undoable; allowed by rule 1 because the user does it). Deleting a take that is a line's active take clears the active take; what happens to placement take overrides is to be settled in S3 |
| 2026-10-13 | M3 (chat A): Tighten is stored as a new `Placement.stretch` (about 1.0 to 1.08), schema version 2 with a migration, added only in S8. The stretched WAV is rendered by the backend (pedalboard time-stretch, one-time `uv add pedalboard`) into `media/takes_fx/`, keyed by hash(raw key, stretch). No other M3 step changes the schema |
| 2026-10-13 | M3 (chat A): waveform peaks are computed on demand by the backend and not stored in `project.json` |
| 2026-10-13 | M3 (chat A): unknown emotion on a line makes generation fail with a clear message (`PresetError`); there is no silent fallback to neutral |
| 2026-10-13 | M3 (chat A): lint conventions learned from the user's ruff run: write `round(x)` not `int(round(x))` (RUF046); iterate successive pairs with `itertools.pairwise` (RUF007); keep imports sorted and wrapped for 88 columns (I001); new code should aim for 88 columns |
| 2026-10-14 | M3 (chat B): a deleted take that a placement uses as `take_override_id` clears the override; the placement falls back to the line's active take; the delete report lists the affected placements. Nothing is orphaned or silently dropped |
| 2026-10-14 | M3 (chat B): take and line deletes reset the undo history (older steps such as set-active-take or star could point at what is gone). The delete confirmation should say so |
| 2026-10-14 | M3 (chat B): undoing `AddLine` is refused once the line has takes or placements (takes are generated outside the undo stack). `CommandStack.undo`/`redo` now keep the step and restore the project when a revert or redo apply raises `CommandError` |
| 2026-10-14 | M3 (chat B): v1 uses the first voice profile only; setting a reference replaces it (single clip). Allowed audio types .wav .flac .ogg .mp3; under 1 s refused; warnings under 5 s, over 30 s, under 16 kHz (starting values, tune by ear) |
| 2026-10-14 | M3 (chat B): the new take becomes the line's active take by default; reusing a take re-activates it. Pressing Generate (not reroll) after a reroll therefore re-activates the base-seed take; the UI decides whether to offer it |
| 2026-10-14 | M3 (chat B): a take of another line with the same raw key is copied (new take, same key, copied file) so no GPU time is spent (rule 3) |
| 2026-10-14 | M3 (chat B): delete order is save the project, then delete files; if the save fails the files are kept and an error is raised. Files nothing points at are reported by the storage report and never deleted automatically |
| 2026-10-14 | M3 (chat B): line edits that change nothing raise `NoChange` and `Session.edit_lines` skips them without an undo step, so the UI can send edits on blur without comparing values |
| 2026-10-14 | M3 (chat B): generation planning (`plan_generation`) is pure and lives with the take store; chat C owns the worker, queue, job status and the generate endpoint and calls plan, reuse, worker, add. `model_version` is supplied by the caller (the worker reports it) |
| 2026-10-14 | M3 (chat B): broken links between lines, takes and placements are reported by a separate `check_voice_references` (four kinds), not by `check_references`: the M2 tests build placements without lines and assert exact results. `problem_count` counts both |
| 2026-10-14 | M3 (chat B): no schema change in S3; the new folder `media/voice/` is added to the project layout |
| 2026-10-15 | M3 (chat C): worker protocol details. Audio goes through a file named in the generate command (`output_path`), not over the pipe. Events added to M3 decision 1: `cancelled` (so a cancelled job cannot be mistaken for `done`) and `unloaded`. Stdout stays clean because the worker duplicates the real stdout and points fd 1 at stderr |
| 2026-10-15 | M3 (chat C): cancel is checked after each piece and wins over `done`, so a single-piece job finishes and its result is discarded (M3 decision 2). The cancel reaches the worker through a reader thread; the queue thread is the only one that sends it |
| 2026-10-15 | M3 (chat C): the model version in the cache key comes from `chatterbox_model_version()` (package metadata), not from the running worker, so planning and reuse work with no GPU process; the queue verifies the worker's reported version on `ready` |
| 2026-10-15 | M3 (chat C): the worker warms up (a throwaway generation with the model's built-in voice) before it reports `ready`, so the 27 s first-generation cost is paid at load. A warm-up failure is logged and ignored |
| 2026-10-15 | M3 (chat C): reuse is decided at submit time (instant `reused` job, no worker) and again when a queued job's turn comes. Queued jobs plan at their turn, so rapid rerolls get consecutive seeds and `plan_generation` needed no change |
| 2026-10-15 | M3 (chat C): jobs carry the `project_key` (project folder) seen at submit; `Session.plan_generation`, `reuse_take` and `add_take` refuse a stale key. Opening another project does not cancel jobs; they fail with a clear message when their turn comes |
| 2026-10-15 | M3 (chat C): one automatic restart and retry per job on a fatal error, a dead process or a stall (300 s without any event while generating); a second failure fails the job. Starting values, not measured. There is no kill-on-cancel (decision 2); the stall timeout is the only way a stuck worker is replaced |
| 2026-10-15 | M3 (chat C): unload is a queued job (`kind` `unload`) so it runs after earlier jobs; the worker process stays alive without the model. Progress stays polling (`GET /api/voice/jobs`, M3 decision 4); spec section 11 should say so (see the replacement text in the chat C hand-off) |
| 2026-10-15 | M3 (chat C): worker log `%APPDATA%\PNGtuberStudio\worker.log`, appended with a start line per launch and rotated to `worker.log.1` above 5 MB; temp job audio under `%TEMP%\PNGtuberStudio-jobs`, deleted after use |
| 2026-10-16 | M3 (chat C): **Windows: never leave a thread blocked reading the original stdin pipe.** A probe showed the Chatterbox import took 8 s normally but did not finish in 150 s once a thread was blocked in `sys.stdin.buffer.readline()` (a pending synchronous read on a pipe handle stalls other calls on that handle, which libraries make while importing). The worker now moves the command pipe to a private descriptor and points fd 0 at NUL, like it already does for stdout. Launch settings (no-window flag, redirected stderr, env vars) were ruled out by `launch_probe.py` (7 to 8 s each) |
| 2026-10-16 | M3 (chat C): the queue deletes a job's temp WAV before marking the job finished (a test saw `done` with the file still on disk); lint: `BLE001` is enabled, the deliberate broad `except Exception` in the worker loop and queue thread carry `# noqa: BLE001` with a reason |
| 2026-10-17 | M3 (chat D): voice profile settings live on the project screen, not in the editor. The editor's footage panel became a tab strip (Footage, Line bank, Storage); Inspector and Voice FX tabs from spec 4.2 come with later milestones |
| 2026-10-17 | M3 (chat D): the job list is owned by `Editor.svelte` (one poll for the status bar and the line bank). Undo and redo state is refreshed field by field after line edits so the player and timeline are not redrawn |
| 2026-10-17 | M3 (chat D): the frontend generates new line ids (12 hex characters via `crypto.getRandomValues`) and sends them in `add_line`; the backend accepted them |
| 2026-10-17 | M3 (chat D): deletes in the storage list use an inline confirmation instead of `window.confirm`, which is unreliable in the pywebview shell. The line bank's Remove line stays for empty lines only (M3 decision 9) |
| 2026-10-17 | M3 (chat D): `docs/API_MODELS.md` holds the response and request shapes the frontend relies on, so they need not be pasted again; keep it in step with `api.ts` |

## Known issues / open questions

- Voice source not final: own voice or acted character (swappable via voice profile).
- Emotion range: neutral reference gives flat output; exaggeration >= 1.0 adds some expression but garbles slightly. Test an expressive reference clip and a non-"enhanced" clip in M3. Emotion preset numbers are still starting guesses.
- Seed reproducibility via `torch.manual_seed`: same to the ear (user, M3 chat A); a bit-exact comparison was not reported. Rule 3 does not depend on it (same key means reuse).
- VRAM peak with the pywebview window open during generation is unmeasured.
- First generation after model load took 27 s (warmup); the UI should show progress and the worker should warm up on start.
- Effects slot contents not chosen (reverb, pitch shift, chorus, others).
- Avatar art naming convention `expression_eyes_mouth.png` to be confirmed against real files.
- OBS recordings have one mixed audio track (game and mic together); confirm this is the expected workflow.
- Harmless warnings seen: `pkg_resources` deprecation (from perth), diffusers `LoRACompatibleLinear` deprecation, `sdpa` attention note, unauthenticated Hugging Face Hub notice; pytest shows one Starlette `TestClient` DeprecationWarning about an `anyio` alias (inside site-packages, goes away with a library update); `npm install` warns that esbuild has an install script not yet allowed (the build works).
- Seek latency was measured on a 4.8 GB file by eye from the page log; no systematic benchmark.
- The schema validates unique ids but not cross-references. `check_references` reports broken ones; the session runs it for `ProjectSummary.problem_count` and `TimelineState.problems` (M2-S6). `RemoveSource` still refuses while a clip uses the source.
- **Rescan after a move creates a duplicate:** if a footage file is moved to another path inside `footage/` and the user clicks Rescan before relinking, the new location is added as a new source and the old one stays missing. Relink first. A "looks like the same file" hint is a possible later improvement.
- Relinking `external` (template bookend) sources is not supported. Bookend probing is implemented but has never run against a real intro/outro clip (the default template has none), so treat it as untested until a template with bookends is tried.
- `RelinkSource` itself is still path-only; the metadata check is in `Session.relink_source`. M2 code that relinks must go through the session or repeat the check.
- Save per change (no debounce) is fine for M1; drag edits in M2 may need the `AutosaveTracker` after all.
- `scan_footage` probes files one after another (sync, 60 s timeout each) inside the request. Fine for a few recordings; a big batch would make Rescan wait.
- `default_ffprobe_path()` assumes `bin/ffprobe.exe` at the repo root. Revisit when `install.bat`/packaging lands (M7).
- The built frontend (`frontend/dist`) is git-ignored; `install.bat` (M7) must build it or ship it.
- (Fixed in M3 chat B, untested) A command whose `revert` fails during undo used to drop the entry; the stack now keeps the step and restores the project. See the decisions log.
- ffprobe reports a 12.8 s duration for a nominal 10 s `-c copy` clip (probably keyframe alignment; not verified).
- No file watcher for `footage/` (by design for M1): rescan on open plus the Rescan button.
- The project screen shows voice profile and avatar art as simple "not configured" / "path set" text only; real validation comes with M3-1 and M5-1. M3 chat B: `GET /api/voice` gives the real voice state; `ProjectSummary.voice_status` is still the simple text.
- M2: at speed > 1, an anchor in the last half-speed milliseconds of a clip maps to that clip's end, which is the next clip's start, so a later `to_source` returns the next clip. Known quantization edge. Decided in chat B: parking ignores it (see decisions log). The editor does not treat it (nothing in the UI creates anchored items yet).
- M2: still images and freeze-frames are not supported in v1 (see decisions log). Revisit only if the user adds a backlog item.
- M2-S2 tests were first run in a sandbox with a stand-in `Clip`/`Anchor`, then confirmed by the user on the real repo (all passing, ruff clean after one PIE808 fix).
- M2 chat B: the S3 to S5 code and tests were written without being run by the assistant (no pydantic or pytest in its sandbox); the user ran them on the real repo and confirmed pytest and ruff pass. The test files use multiples of 50 ms because those land exactly on the 60 fps frame grid.
- M2: nothing in M2 creates placements, keyframes or reactions, so orphan behaviour is covered by unit tests with items built directly. The editor shows `orphan_count` and the reference problems as plain text only; there is no UI to resolve an orphan.
- M2: orphans cannot be resolved yet (no re-anchor command, no UI). A parked item sits exactly at a clip edge and keeps `orphaned=True` until a later milestone adds the resolve action.
- M2: the new command modules import private helpers across modules (`_find_source` from `commands.py`, `_find_timeline_clip` and `_min_clip_ms` from `clip_commands.py`). Fine for now; tidy if more modules need them.
- M2: `RippleDelete` refuses a range that would leave a sliver under one frame of a clip. The editor has no range selection, so its UI never sends ripple-delete (Delete uses `remove_clip`); if range selection is added, show the command's message (errors from edits already appear as the red message).
- M2: drags send one call on release (user confirmed one undo step per drag). Save per change was fine in the editor, so the `AutosaveTracker` is still unused.

- M2 chat C: the S6 and S7 code and tests were written without being run by the assistant (no pydantic or pytest in its sandbox; only `parse_range` and `iter_file` were run there). The user ran everything and confirmed pytest, ruff and `npm run check` pass.
- M2: the media endpoint has no cache headers, and the editor does not add a cache-busting query. After a relink (done on the project screen, which unmounts the editor) the browser could show the old file for the same URL; add `?v=<n>` to `sourceMediaUrl` if it ever happens. No HEAD route: add one if a client needs it.
- M2: the MIME type of `.mkv` depends on the Windows registry through `mimetypes`; if it ever fails to play on another machine, set it explicitly (`video/x-matroska`) after testing.
- M2: the test files `test_timeline.py`, `test_timeline_edit.py` and `test_edit_ops.py` each define their own small `hid()` helper (readable name to 12-char hex id). Tidy into a shared helper if more tests need it.
- M2: the test `test_external_source_is_served_from_its_absolute_path` uses a Windows drive path as the external source path; it passed on the dev machine.

- M2 editor: **audio at extreme speeds.** Chromium mutes `<video>` audio when the playback rate is above 4x or below 0.25x, so an 8x clip is expected to preview silently (export is unaffected). Not confirmed on the user's machine.
- M2 editor: the hop to a clip on a different source swaps the video `src` and shows a hitch; its length was not measured. Hops within one source use a seek or none.
- M2 editor: no time-range selection (Delete removes the whole selected clip), no auto-scroll when dragging the playhead past the canvas edge, and any edit stops playback.
- M2 editor: the playhead, selection and zoom are not saved; reopening the editor starts at 0. Source names come from the footage list loaded when the editor opens (Rescan and Relink are on the project screen).
- M2 editor: very short or zoomed-out clips have a smaller trim handle (a third of the clip width, up to 6 px); zoom in to grab them.
- M2 editor: the frontend has no automated tests. `timeline.ts` is checked by `npm run check` and by hand; the assistant ran its helpers once in a scratch node script (not committed). Add a small test runner if frontend logic grows.
- M2 editor: `timeline.ts` duplicates a few time-mapping rules from `backend/edl/timemap.py` (display only). If the backend rounding rules ever change, update both.
- M2: the wrap-up did not include an itemised manual acceptance run or a final `npm run check` paste (see "M2 manual checks").

- M3 chat A: user confirmed all tests pass and ruff is clean (after the lint fix round). `ruff format --check` was not reported; some lines run up to about 100 characters while ruff's isort wraps at 88, so a format pass may reflow a few lines.
- M3: the take-delete versus `take_override_id` rule is settled (clears the override). `check_voice_references` covers lines, takes and placements (chat B, untested); the editor's `TimelineState.problems` does not include it yet (add in S5 if the UI should show it).
- M3: Tighten needs `pedalboard` (not yet in `pyproject.toml`); `uv add pedalboard` is a one-time download in S8.
- M3: the abbreviation list in `split_sentences` is small and English only; a miss only changes where a long line is cut, never what is said.
- **M3 chat B: all S3 code and tests (rounds a to d) were written without being run by the assistant** (the sandbox has no pydantic, pytest, soundfile or fastapi; only syntax checks ran). The user runs everything together; until then every `written, untested` item above is unconfirmed.
- M3 chat B: `soundfile` is assumed to be installed as a Chatterbox dependency; if `import soundfile` fails, run `uv add soundfile`. Reference clip headers and take WAVs both use it.
- M3 chat B: `backend/media/serve.py` was not shown, so the MIME type `range_response` gives for `.wav` is unchecked (the take media test checks status and bytes only). If the browser refuses to play a take, paste `serve.py`.
- M3 chat B: take WAV writes are atomic (temp file, `os.replace`) but not `fsync`ed; a crash right after a generation can leave a record whose file is missing or short. The storage report shows missing files, and `add_take` writes the audio back for the same key.
- M3 chat B: a template voice profile whose `reference_clips` holds an absolute path outside the project is not handled (the default template has none).
- M3 chat B: ruff style. New code keeps imports sorted and wrapped, but many test lines run past 88 columns (up to about 100), as in chat A; a `ruff format` pass may reflow them.
- **M3 chat C: status after the first real run (user's machine):** the full pytest suite passed (963) except one queue race, since fixed; ruff is clean after two small fixes. `ChatterboxEngine` had never run before `worker_check.py`, which hung in the model import because of the Windows stdin stall (fixed in `worker_main.py`, see decisions log). Superseded in part: in S5 the user generated, reused, rerolled and cancelled from the app window, so the real engine path works. The `worker_check.py` output and the VRAM figure were still not pasted.
- M3 chat C: `crossfade_join` is called as `crossfade_join(list_of_arrays, sample_rate)` per the description in this file; `chunking.py` itself was not shown to chat C.
- M3 chat C: the warm-up assumes `ChatterboxTTS.from_pretrained` loads built-in conditionals so `generate(text)` works without a reference; if it does not, the warm-up error is only logged and the first real job pays the cost.
- M3 chat C: `HF_HUB_OFFLINE` is not set for the worker because the first run must download the weights; rule 8 (no network after the download) is enforced with the first-run step in M7. Until then the worker may contact Hugging Face.
- M3 chat C: Chatterbox prepares the reference conditionals on every `generate` call; caching them per (reference, exaggeration) would save time on long lines. Not done.
- M3 chat C: jobs live in memory only (the status keeps the newest 30 finished jobs); closing the app drops them. Takes are stored as soon as each job finishes.
- M3 chat C: the status has no WebSocket; the UI polls `GET /api/voice/jobs`. A running job whose project was closed still uses the GPU until it finishes; its result is refused.
- M3 chat C: `SubprocessWorker.alive` now reads under a lock and no longer calls `process.poll()`; a process that died but whose reader has not noticed yet shows `alive` until the next send fails or the reader finishes.
- M3 chat C: `test_subprocess_worker.py` and `test_job_queue.py` use real threads and processes with timeouts of 30 to 40 s; a slow machine or antivirus scan may need longer waits (look at `TIMEOUT_S` and `WAIT_S`).
- M3 chat D: all S5 rounds were written without being run by the assistant; the user ran each in the app window and confirmed it works (`npm run check` and `npm run build` clean). No itemised paste of every manual step was kept.
- M3 chat D: the native file picker (`pick_file` in `main.py`) was not changed; whether it lists audio files was left to the user's run, and a path can always be typed or pasted into the box.
- M3 chat D: the status bar does not name the line a job belongs to (only the phase and piece count); the line bank shows the job text for the selected line. The Unload model button is not built (`unloadWorker` exists in `api.ts`). Loudness meter in the status bar waits for M4.
- M3 chat D: the take picker plays through a plain `Audio` element, separate from the editor's video player; playing a take does not pause the video. Voice playback in sync with the video is S7.
- M3 chat D: the job list is in memory on the backend, so after closing and reopening the app the status bar starts empty ("Last job" is gone) even though the takes remain.
- M3 chat D: a line edit that fails (400) leaves the field as typed and shows the backend message above the list; there is no per-field error.
- M3 chat D: the Storage tab refreshes on open, on job end and after deletes, not on a timer. Deleting a line that has placements is refused by the backend (not exercised yet, the UI cannot place lines).

## Next up

1. **Commit (user):** commit chat D's last round (`M3-6: storage manager, disk usage and generate hotkeys`) if not done, then this file and the ticked plan. Re-run `uv run pytest` and `uv run ruff check .` on `m3-voice` once (the last full-suite figure in this file is from before the stdin fix) and paste the count.
2. **Tick in `IMPLEMENTATION_PLAN.md`:** M3-1, M3-2, M3-3, M3-4 and M3-6. Tick M3-5 once a line of several sentences has been generated from the app and played with no click at the joins (not tried in S5). Leave M3-7, M3-8 and M3-9. Merge and tag `m3-done` only at the end of M3 (S8); no merge after S5.
3. **Chat E (S6):** fresh chat with `CLAUDE.md`, this file, `docs/tasks/M3-voice.md`, spec section 4.2 (Voice lane) and the anchoring rule in section 5, plus `Editor.svelte`, `Timeline.svelte`, `timeline.ts`, `backend/edl/timemap.py`, `backend/project/timeline.py` and `edit_ops.py` (and `docs/API_MODELS.md`, which now also has the core contracts digest, so `schema.py`, `commands.py`, `session.py` and `api.ts` need not be pasted again; `backend/app.py`, `LineBank.svelte` and `Player.svelte` are still needed). It builds the `Placement` commands and endpoint, the voice lane with waveform blocks (peaks computed on demand by the backend), place at the playhead (M), drag from the bank, drag to move, and remove. `LineBank.svelte` already shows "placed" from `placement_count`.
4. **Chat F (S7, S8):** Web Audio playback in sync with the player, then overflow fixes and Tighten (schema version 2, `Placement.stretch`).
5. **Open questions M3 inherits:** the reference clip and voice source (own voice or acted character); VRAM peak with the app window open; emotion presets are guesses; whether an expressive reference clip widens the range; the stall and load timeouts are starting values.
