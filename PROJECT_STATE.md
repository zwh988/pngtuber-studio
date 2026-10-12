# PROJECT_STATE.md

Living document: how the project works right now and where everything lives. **Update it at the end of every task** (see the checklist in `CLAUDE.md`). Keep it factual and short; link to files instead of copying code.

- **Last updated:** 2026-10-12 (M2 chat C: S6 backend API and S7 media server done, committed)
- **Current milestone:** M2 in progress, branch `m2-timeline` (M1 merged and tagged `m1-done`). Chat A: S1 (decisions) and S2 (`timemap.py`). Chat B: S3 to S5 (clip commands, orphan parking, `check_references`). Chat C: S6 (timeline state, edit endpoints, undo/redo, batch edits) and S7 (media endpoint with Range support), all user-confirmed passing and committed. Next: chat D (S8 editor screen, S9 wrap-up). Merge and tag `m2-done` only after chat D.
- **Overall status:** M0 verdict GO (see "M0 findings"). The app runs: a pywebview window shows a Svelte project screen backed by FastAPI (create from template, open, Recent, footage scan, rescan, relink). New in M2 so far: time mapping, clip commands, orphan logic and the reference check (pure backend, chats A and B), and now the whole backend for the editor (chat C): `GET /api/timeline`, one endpoint per edit operation, undo/redo, grouped batch edits, and `GET /media/source/{id}` serving footage with Range requests. **There is still no editor screen**; the typed frontend API for it is in `frontend/src/api.ts`. No voice, audio, avatar or export. No `install.bat` / `run.bat` yet.

## How to run / test

**Always run commands from the repo root**, not from `docs\`.

```powershell
# setup (manual, until install.bat exists)
uv sync                      # Python 3.11, torch 2.6.0+cu126, chatterbox-tts, fastapi, uvicorn, pywebview, pydantic, pytest, ruff, httpx (dev)

# tests and lint (from repo root)
uv run pytest                # all pass (user confirmed after M2-S7). Test count not recorded: 406 tests at M2-S6a; `test_timeline_edit.py`, `test_edit_ops.py` and `test_media.py` were added after, so record the number from the next summary line
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
uv run python scripts\spike\player_spike.py --video "<path to video.mkv>"          # pywebview window, prints Range requests
uv run python scripts\dev\media_check.py --project "<project folder>"   # window playing a project source through /media/source/{id}; prints each request (throwaway dev check)
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
| `docs/tasks/` | per-task breakdown files (`_TEMPLATE.md`, `M0-spike.md`, `M1-foundation.md`, `M2-timeline.md`) | partial |
| `pyproject.toml`, `uv.lock`, `.python-version` | uv project: Python 3.11 only, torch pinned to 2.6.0 from the cu126 index; pydantic, fastapi, uvicorn, pywebview; dev: pytest, ruff, httpx | partial |
| `conftest.py` | repo-root marker so pytest can import `backend` | done |
| `scripts/spike/*` | M0 spike scripts (check_cuda, tts_test, tts_grid, player_spike with reusable `parse_range`/`iter_file`) | done (spike) |
| `scripts/spike/out/` | spike output, git-ignored | n/a |
| `scripts/dev/media_check.py` | throwaway manual check: pywebview window with a `<video>` on the real media endpoint | done (M2-S7), dev only |
| `backend/__init__.py` | package marker | done |
| `backend/app.py` | FastAPI app factory `create_app(static_dir=None, session=None)`, `/api/*` routes (project, footage, recent, timeline and edits), `/media/source/{source_id}`, serves `frontend/dist` | done (M1-6, M2-S6, S7) |
| `backend/main.py` | app shell: uvicorn in a thread on a free 127.0.0.1 port plus pywebview window; `Api` class with `pick_folder` / `pick_file` | done (M1-6) |
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
| `backend/project/session.py` | `Session`: the one open project, new/open, footage scan, relink, recent list, timeline state, edits, undo/redo, `source_path`, save on change | done (M1-6, M2-S6, S7) |
| `backend/project/summary.py` | pure `ProjectSummary` (with `problem_count`), `FootageItem`, `FootageReport`, `summarize`, `describe_source` | done (M1-6, M2-S6) |
| `backend/project/recent.py` | recent projects list: pure add/remove/parse plus atomic load/save | done (M1-6) |
| `backend/project/relink.py` | pure `to_footage_relpath`, `relink_mismatches` | done (M1-6) |
| `backend/edl/__init__.py` | package marker | done (M2-S2) |
| `backend/edl/timemap.py` | pure time mapping: `clip_spans`, `timeline_duration`, `to_timeline`, `to_source`, frame helpers (`snap_to_frame`, `ms_to_frame`, `frame_to_ms`), `round_half_up` | done (M2-S2) |
| `backend/edl/anchoring.py` | pure orphan and reference logic: `anchored_items`, `items_in_source_range`, `find_orphans`, `edge_anchors`, `park_anchor`, `check_references`, `ReferenceProblem` | done (M2-S5) |
| `backend/edl/` (rest) | ffmpeg graph builder (M6) | empty |
| `backend/media/ranges.py` | pure `parse_range`; `iter_file` (chunked read of a byte range) | done (M2-S7) |
| `backend/media/serve.py` | `range_response(path, range_header)`: 200 / 206 / 416 streaming response | done (M2-S7) |
| `backend/voice/` | GPU worker, takes, cache keys, queue | empty |
| `backend/audio/` | FX chain, loudness, envelopes | empty |
| `backend/avatar/` | art loader, solver, compositor | empty |
| `backend/export/` | export pipeline, asset bundle | empty |
| `frontend/` | Svelte 5 + TypeScript (strict) + Vite 6 project screen: `package.json`, `package-lock.json` (committed), `vite.config.ts`, `svelte.config.js`, `tsconfig.json`, `index.html`; `src/main.ts`, `src/App.svelte`, `src/api.ts` (typed fetch wrappers, timeline and edit functions, `sourceMediaUrl`), `src/pywebview.d.ts`, `src/vite-env.d.ts`. `node_modules/` and `dist/` are git-ignored | partial (project screen only) |
| `bin/` | ffmpeg/ffprobe (git-ignored) | has ffmpeg n8.1.3 + ffprobe locally |
| `templates/default_channel.json` | default channel template (no bookends, "Default voice" without reference clips, FX/avatar/export defaults) | done (M1-5) |
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

## Project folder layout (user data, not in this repo)

```
MyRack/
  project.json          source of truth
  project.json.bak      previous saved version (rotated on each save)
  footage/              user places recordings here (never copied)
  media/takes_raw/  media/takes_fx/  media/envelopes/
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
- `check_references(project) -> list[ReferenceProblem]`; `ReferenceProblem(kind, owner_id, missing_id, message)` with kind `clip_missing_source` or `item_missing_clip`. It only reports; it never changes the project and never blocks loading.
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

**Session API** (`backend/project/session.py`): `Session(*, template_path=None, probe=None, recent_path=None)`. Holds the one open project and its `CommandStack`; thread-safe (re-entrant lock).
- `current() -> ProjectSummary | None`, `new_project(parent, name)`, `open_project(folder)`, `footage() -> FootageReport`, `rescan_footage()`, `relink_source(source_id, new_path)`, `recent() -> list[RecentItem]`, `forget_recent(folder)`, plus the timeline, edit, undo/redo and `source_path` methods above. Errors: `SessionError`; other module errors (`ProjectError`, `TemplateError`, `FootageError`) pass through.
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

`ProjectSummary`: `name`, `folder`, `schema_version`, `source_count`, `clip_count`, `voice_status`, `avatar_status` ("not configured" or "path set" text only), `save_error`, `problem_count` (broken references from `check_references`; 0 when sound). Static frontend is mounted at `/` after the API routes; if `frontend/dist` has no `index.html`, `/` shows a "Frontend not built" page. Errors from commands are HTTP 400 `{"detail": message}`; a malformed request body is FastAPI's standard 422.

**pywebview bridge** (`backend/main.py` `Api`): `window.pywebview.api.pick_folder()` and `pick_file()` (video file filter) return a path or `null`. Works on both the older and newer pywebview dialog constants.

## M0 findings (2026-10-10, user's machine)

**Machine:** Windows, RTX 4060 Laptop GPU (8 GB), NVIDIA driver 581.42.

**Versions that worked (user confirmed):** Python 3.11.17, torch 2.6.0+cu126, torchaudio 2.6.0+cu126, chatterbox-tts 0.1.7, numpy 1.26.4, transformers 5.2.0, ffmpeg n8.1.3-17-gc389840894 (BtbN GPL build, 8.1 branch). Other package versions are in `uv.lock`.

**Chatterbox (original `ChatterboxTTS`, not Turbo or Multilingual):**
- API: `ChatterboxTTS.from_pretrained(device="cuda")`, then `generate(text, audio_prompt_path=..., exaggeration=0.5, cfg_weight=0.5, temperature=0.8, ...)`. Sample rate is `model.sr` = 24000.
- `generate` has **no seed argument**. The scripts call `torch.manual_seed(seed)` before each call. Whether that makes output reproducible is **untested**.
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

- M2-S7: `scripts\dev\media_check.py` on the real 1440p60 recording: the video plays with sound through `GET /media/source/{id}` in the pywebview window and seeking works. The seek timings and request log were not recorded.

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

## Known issues / open questions

- Voice source not final: own voice or acted character (swappable via voice profile).
- Emotion range: neutral reference gives flat output; exaggeration >= 1.0 adds some expression but garbles slightly. Test an expressive reference clip and a non-"enhanced" clip in M3. Emotion preset numbers are still starting guesses.
- Seed reproducibility via `torch.manual_seed` is untested (matters for cache keys, rule 3).
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
- If a command's `revert` fails partway through an undo (should only happen on a bug), the undo entry is dropped and state may be partly reverted. Not handled; revisit if it ever appears.
- ffprobe reports a 12.8 s duration for a nominal 10 s `-c copy` clip (probably keyframe alignment; not verified).
- No file watcher for `footage/` (by design for M1): rescan on open plus the Rescan button.
- The project screen shows voice profile and avatar art as simple "not configured" / "path set" text only; real validation comes with M3-1 and M5-1.
- M2: at speed > 1, an anchor in the last half-speed milliseconds of a clip maps to that clip's end, which is the next clip's start, so a later `to_source` returns the next clip. Known quantization edge. Decided in chat B: parking ignores it (see decisions log). The editor UI (chat D) may want to treat it in hit-testing.
- M2: still images and freeze-frames are not supported in v1 (see decisions log). Revisit only if the user adds a backlog item.
- M2-S2 tests were first run in a sandbox with a stand-in `Clip`/`Anchor`, then confirmed by the user on the real repo (all passing, ruff clean after one PIE808 fix).
- M2 chat B: the S3 to S5 code and tests were written without being run by the assistant (no pydantic or pytest in its sandbox); the user ran them on the real repo and confirmed pytest and ruff pass. The test files use multiples of 50 ms because those land exactly on the 60 fps frame grid.
- M2: the clip commands are reachable through the Session and HTTP API (chat C) but there is **no editor UI yet** (chat D). Nothing in M2 creates placements, keyframes or reactions, so orphan behaviour is covered by unit tests with items built directly.
- M2: orphans cannot be resolved yet (no re-anchor command, no UI). A parked item sits exactly at a clip edge and keeps `orphaned=True` until a later milestone adds the resolve action.
- M2: the new command modules import private helpers across modules (`_find_source` from `commands.py`, `_find_timeline_clip` and `_min_clip_ms` from `clip_commands.py`). Fine for now; tidy if more modules need them.
- M2: `RippleDelete` refuses a range that would leave a sliver under one frame of a clip, so a drag selection near a cut may need to be extended or shortened. Chat D should surface the command's message.
- M2: a drag should send one call on mouse-up (one command is one undo step and one save); compound edits use `POST /api/timeline/batch`. If saving per change still feels slow in the editor, wire the `AutosaveTracker` then.

- M2 chat C: the S6 and S7 code and tests were written without being run by the assistant (no pydantic or pytest in its sandbox; only `parse_range` and `iter_file` were run there). The user ran everything and confirmed pytest, ruff and `npm run check` pass.
- M2: the media endpoint has no cache headers. After a relink the browser could show the old file for the same URL; the editor should add a cache-busting query (for example `?v=<n>`), which the server ignores. No HEAD route: add one if a client needs it.
- M2: the MIME type of `.mkv` depends on the Windows registry through `mimetypes`; if it ever fails to play on another machine, set it explicitly (`video/x-matroska`) after testing.
- M2: the test files `test_timeline.py`, `test_timeline_edit.py` and `test_edit_ops.py` each define their own small `hid()` helper (readable name to 12-char hex id). Tidy into a shared helper if more tests need it.
- M2: the test `test_external_source_is_served_from_its_absolute_path` uses a Windows drive path as the external source path; it passed on the dev machine.
- M2: `scripts\dev\media_check.py` is a throwaway check and can be deleted once the editor plays footage.
- M2: the plan file had M2-2 ticked and M2-3 not after chat B (the state file said tick M1, M3, M5). Fixed in the plan during the chat C wrap-up (see Next up).

## Next up

1. **Plan ticks:** M2-1, M2-3 and M2-5 are done. M2-2 was ticked by mistake and must be unticked (the timeline canvas does not exist yet). Chat D ticks M2-2, M2-4 and M2-6.
2. **Chat D (S8 editor screen, S9 wrap-up):** a Svelte editor reached from the project screen. Paste: `CLAUDE.md`, this file, `docs/tasks/M2-timeline.md`, `docs/DESIGN_SPEC.md` section 4.2 (player, video strip lane, hotkeys) and section 9 "Playback of cuts" and "Speed clips", `frontend/src/App.svelte`, `frontend/src/api.ts` (it already has the timeline types, `getTimeline`, the edit functions, `editBatch`, `undoEdit`, `redoEdit`, `sourceMediaUrl`). The assistant asks for other files by path.
3. **Facts for chat D:** every edit call returns the full `TimelineState`; redraw from it. The player plays each `TimelineClip` by seeking its source to `in_ms` and setting `playbackRate = speed` (pitch preserved), hopping at `end_ms`; video URL is `sourceMediaUrl(clip.source_id)`. Trims take **source** time (`[` and `]` convert the playhead with the clip's `in_ms` and `speed`, and `to_source` rules apply). A drag sends one op on mouse-up. Show the 400 `detail` text as-is (for example the ripple-delete sliver message). At speed > 1 an anchor in the last half-speed ms of a clip maps to the next clip (known edge). Add a cache-busting query to the media URL after a relink. Verify with the real 1440p60 recording.
4. Stay on branch `m2-timeline` through chat D. Commit this file there before starting chat D. Merge and tag `m2-done` only after chat D.
