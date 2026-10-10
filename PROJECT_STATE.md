# PROJECT_STATE.md

Living document: how the project works right now and where everything lives. **Update it at the end of every task** (see the checklist in `CLAUDE.md`). Keep it factual and short; link to files instead of copying code.

- **Last updated:** 2026-10-11 (M1 chat A finished: schema and persistence)
- **Current milestone:** M1 in progress on branch `m1-foundation`. M1-1 and M1-2 done (user confirmed: 57 tests pass, ruff clean). Next: chat B (M1-3 footage/ffprobe, M1-4 commands/undo).
- **Overall status:** M0 verdict GO (see "M0 findings"). App code started: project schema, store, migrations, autosave timing under `backend/project/`. No runnable app yet (no `install.bat` / `run.bat`, no FastAPI app, no frontend).

## How to run / test

The app itself is not runnable yet. Backend logic is tested with pytest; spike scripts remain runnable from the repo root in PowerShell. **Always run commands from the repo root**, not from `docs\`.

```powershell
# setup (manual, until install.bat exists)
uv sync                      # Python 3.11, torch 2.6.0+cu126, chatterbox-tts, fastapi, uvicorn, pywebview, pydantic, pytest, ruff

# tests and lint (from repo root)
uv run pytest                # 57 tests (user confirmed passing)
uv run ruff check .

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
.\bin\ffmpeg.exe -hide_banner -y -ss 20 -t 10 -i "<video.mkv>" -map 0:v:0 -map "0:a:0?" -vf "scale=-2:1080" -c:v h264_nvenc -preset p5 -rc vbr -cq 23 -b:v 0 -pix_fmt yuv420p -c:a aac -b:a 192k scripts\spike\out\nvenc_test.mp4
```

First run of `tts_test.py` downloads the Chatterbox weights from Hugging Face (several GB, one-time network step). Later runs are offline.

## Repo map

Status values: `empty` (placeholder only), `partial`, `done`.

| Path | Purpose | Status |
|---|---|---|
| `CLAUDE.md` | AI instructions and business rules | done |
| `PROJECT_STATE.md` | this file | done |
| `IMPLEMENTATION_PLAN.md` | milestones and task checklist | done |
| `docs/DESIGN_SPEC.md` | full design spec (source of truth for behavior) | done |
| `docs/tasks/` | per-task breakdown files (`_TEMPLATE.md`, `M0-spike.md`, `M1-foundation.md`) | partial |
| `pyproject.toml`, `uv.lock`, `.python-version` | uv project: Python 3.11 only, torch pinned to 2.6.0 from the cu126 index; pydantic, pytest, ruff added | partial |
| `conftest.py` | repo-root marker so pytest can import `backend` | done |
| `scripts/spike/*` | M0 spike scripts (check_cuda, tts_test, tts_grid, player_spike with reusable `parse_range`/`iter_file`) | done (spike) |
| `scripts/spike/out/` | spike output, git-ignored | n/a |
| `backend/__init__.py` | package marker | done |
| `backend/app.py` | FastAPI entry point | not created |
| `backend/project/schema.py` | pydantic v2 schema, `SCHEMA_VERSION = 1`, `new_id()` | done (M1-1) |
| `backend/project/store.py` | folder layout, create/load/save, atomic write, `.bak` rotation | done (M1-2) |
| `backend/project/migrations.py` | `migrate()` chain, `MIGRATIONS` registry (empty at v1) | done (M1-2) |
| `backend/project/autosave.py` | pure `AutosaveTracker` (debounce + max wait); no scheduler thread yet | done (M1-2) |
| `backend/project/footage.py` | ffprobe wrapper, Source detection | not created (M1-3) |
| `backend/project/commands.py` | command objects, undo/redo stack | not created (M1-4) |
| `backend/project/template.py` | channel template load/apply | not created (M1-5) |
| `backend/edl/` | clip list, time mapping, anchoring, ffmpeg graph builder | empty |
| `backend/voice/` | GPU worker, takes, cache keys, queue | empty |
| `backend/audio/` | FX chain, loudness, envelopes | empty |
| `backend/avatar/` | art loader, solver, compositor | empty |
| `backend/export/` | export pipeline, asset bundle | empty |
| `frontend/` | Svelte app (`src/`) | empty |
| `bin/` | ffmpeg/ffprobe (git-ignored) | has ffmpeg n8.1.3 + ffprobe locally |
| `templates/` | default channel template, emotion presets | empty |
| `scripts/` | install/run helpers | spike only |
| `tests/test_schema.py` | schema tests (29) | done |
| `tests/test_persistence.py` | migrations, autosave tracker, store tests (28) | done |

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

**Schema:** `backend/project/schema.py`, `schema_version = 1`. All models forbid unknown fields and validate on assignment.
- Conventions: times are **integer milliseconds** (source time for anchors); ids are 12-char lowercase hex (`new_id()`); paths in JSON are relative POSIX strings (no absolute, no `\`, no `..`).
- Entities: `Source`, `Clip`, `Line`, `Take`, `Placement`, `Keyframe`, `Reaction`, `VoiceProfile`, `FxChain` (+ `CompressorSettings`), `Anchor`, `EffectSpec`, `AvatarSettings`, `ExportSettings`, `ChannelTemplate` (first draft, `BookendRef` may use absolute paths), root `Project`.
- Root `Project` fields: `schema_version`, `name`, `seed`, `sources`, `clips`, `lines`, `takes`, `placements`, `keyframes`, `reactions`, `voice_profiles`, `fx_chain`, `game_audio_db` (default 0.0), `avatar`, `export`. Unique ids per collection are validated; cross-references are not.
- `Source` stores fps as `fps_num`/`fps_den` (property `fps`). `Clip` uses `in_ms`/`out_ms`, `speed` 0.25 to 8, `track`, `overlay`, `effects`. `Placement`, `Keyframe`, `Reaction` carry `orphaned: bool` (set by M2 logic; M1 stores only).

**Store API** (`backend/project/store.py`): `create_project(folder, project)`, `load_project(folder, *, use_backup=False, migrations=None)`, `save_project(folder, project)`, `ensure_layout(folder)`, `project_file`/`backup_file`. Errors: `ProjectError`, `ProjectExistsError`, `ProjectLoadError`.
- Save order: temp file (flush, fsync) in the project folder, copy current `project.json` to `.bak` (only if it is valid JSON), `os.replace` temp over `project.json`. Failure leaves the old file and cleans up temp files.

**Migrations** (`backend/project/migrations.py`): `migrate(data, target=SCHEMA_VERSION, migrations=None)`; register `MIGRATIONS[n] = fn` upgrading version n to n+1. Raises `MigrationError` / `ProjectTooNewError` (wrapped in `ProjectLoadError` by `load_project`).

**Autosave** (`backend/project/autosave.py`): `AutosaveTracker(AutosavePolicy(debounce_s=2.0, max_wait_s=15.0))`: `mark_dirty(now)`, `begin_save()` / `finish_save(token)`, `should_save(now)`, `seconds_until_due(now)`. The scheduler that drives it arrives with the backend API (M1-6).

Command API and backend endpoints: not implemented yet.

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
| 2026-10-11 | M1: ids are uuid4 hex truncated to 12 chars; JSON paths are relative POSIX strings (no absolute, no `..`) |
| 2026-10-11 | M1: fps stored as `fps_num`/`fps_den` so 59.94 (60000/1001) is exact |
| 2026-10-11 | M1: `Take` stores a text snapshot, `model_version`, and `raw_key` so it stays valid if the line is edited; `Placement` and the other timed items get their own `id` |
| 2026-10-11 | M1: default `game_audio_db` = 0.0 (tune in M4); default avatar position x 0.85, y 0.75 as fractions of the frame |
| 2026-10-11 | M1: `.bak` is only rotated from a `project.json` that parses as JSON, so a corrupt file never replaces a good backup; `load_project(use_backup=True)` is the recovery path |
| 2026-10-11 | M1: autosave policy defaults: 2 s debounce, 15 s max wait; timing logic is pure, scheduler comes with the API |
| 2026-10-11 | M1: pytest finds `backend` through a repo-root `conftest.py`; no pyproject pytest config needed |

## Known issues / open questions

- **Bookend clips (decide in M1-5):** intro/outro files likely live outside the project folder, but `Source.path` rejects absolute paths and `..`. The schema may need an extension (for example an external-source flag). `ChannelTemplate`/`BookendRef` are first drafts.
- Voice source not final: own voice or acted character (swappable via voice profile).
- Emotion range: neutral reference gives flat output; exaggeration >= 1.0 adds some expression but garbles slightly. Test an expressive reference clip and a non-"enhanced" clip in M3. Emotion preset numbers are still starting guesses.
- Seed reproducibility via `torch.manual_seed` is untested (matters for cache keys, rule 3).
- VRAM peak with the pywebview window open during generation is unmeasured.
- First generation after model load took 27 s (warmup); the UI should show progress and the worker should warm up on start.
- Effects slot contents not chosen (reverb, pitch shift, chorus, others).
- Avatar art naming convention `expression_eyes_mouth.png` to be confirmed against real files.
- OBS recordings have one mixed audio track (game and mic together); confirm this is the expected workflow.
- Harmless warnings seen: `pkg_resources` deprecation (from perth), diffusers `LoRACompatibleLinear` deprecation, `sdpa` attention note, unauthenticated Hugging Face Hub notice.
- Seek latency was measured on a 4.8 GB file by eye from the page log; no systematic benchmark.
- The folder-layout tree from a real `create_project` run was not pasted back in chat A (covered by `test_create_makes_layout_and_valid_file`).
- Schema validates unique ids but not cross-references (for example `Clip.source_id` pointing at a real source). Revisit when commands and orphan handling land.

## Next up

1. Commit M1-1/M1-2 on `m1-foundation` (see commit commands in chat), and commit this file.
2. Chat B: M1-3 footage/ffprobe and M1-4 commands/undo. Paste `CLAUDE.md`, this file, `M1-foundation.md`, and spec section 5 "Source" row + anchoring rule, section 9 "Undo/redo" bullet, section 3 step 2.
3. Chat C: M1-5 to M1-7, then merge and tag `m1-done`.
