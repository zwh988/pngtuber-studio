# M7: Polish (install, first run, settings, hotkeys, templates, error handling, clean install)

> Written 2026-11-17 after M6 from `IMPLEMENTATION_PLAN.md` (M7-1 to M7-5), `docs/DESIGN_SPEC.md` sections 4.4 and 11, `PROJECT_STATE.md` (known issues and "Next up") and the code as of `m6-done`. The plan wins where this file and it disagree. Nothing here has been built. The questions under "Decisions" are for the user at the start of M7; the answers go into the decisions log in `PROJECT_STATE.md`.

- **Milestone items:** M7-1 to M7-5.
- **Branch:** `m7-polish` (from `main` at `m6-done`).
- **Done when (plan):** a fresh install works from `install.bat` to a finished export.

## Facts already established (do not re-ask)

- **Setup today is manual** (`PROJECT_STATE.md`, "How to run / test"): `uv sync`; ffmpeg and ffprobe from the BtbN 8.1 release branch copied into `bin/` by hand (never `master` or 9.0: they need driver 610+); `npm install` and `npm run build` in `frontend/` (Node is needed only to build; `frontend/dist` is git-ignored); `uv run python -m backend.main`.
- **Pins that `install.bat` must keep:** `setuptools<81` (resemble-perth imports `pkg_resources`; M0 decision), CUDA torch 2.6.0+cu126 through `uv.lock`, Python 3.11 through `uv`.
- **Model weights:** `ChatterboxTTS.from_pretrained(device="cuda")` downloads several GB from Hugging Face the first time (`backend/voice/engine.py`). `HF_HUB_OFFLINE` is not set yet, so the worker may still contact the Hub later (rule 8 is not enforced yet; M3 chat C). The first generation after a load takes about 27 s (warm-up).
- **Paths that assume the repo layout:** `default_ffmpeg_path()` and `default_ffprobe_path()` are `<repo>/bin/*.exe`; templates are in `<repo>/templates/`; the recent list is `%APPDATA%\PNGtuberStudio\recent.json`.
- **Hotkeys are hard-coded** in `Editor.svelte` `onKeyDown`: Space, `,` `.`, G and Shift+G, N, M, S, E, R, Delete, `[` `]`, Ctrl+Z / Ctrl+Y. Spec 4.2 lists them.
- **Templates:** `templates/default_channel.json` is applied when a project is created (`backend/project/template.py`: `load_template_file`, `apply_template`; bookends as `external` sources). There is no UI to save or change a template.
- **Settings that already have a home:** the voice reference (project screen), the art folder (project screen), FX presets (Voice FX tab), takes and storage (Storage tab), avatar base motion (Avatar tab). Emotion presets live in `templates/emotion_presets.json` with no UI. Export choices start from `Project.export` but are not saved back (M6 known issue).
- **Carried over from earlier milestones (Next up item 3):** UI-1d (lane colours, a clearer selected state), UI-1e (icon buttons), `takes_fx` sizes in the storage manager, clean-up of `media/envelopes/` and `media/avatar_preview/`.

## Decisions (settled 2026-11-17, see the decisions log in `PROJECT_STATE.md`)

> **Settled:** decisions 2 to 5 as recommended. Decision 1 changed: only the user installs, but on any of their own machines with one double-click. `install.bat` bootstraps `uv`, a portable pinned Node (`tools\node\`) and ffmpeg without admin rights, then creates `run.bat` and a desktop shortcut. **Revised the same day:** the app may be given to anyone the user chooses, so `install.bat` must work from a GitHub zip without Git and fail clearly without an NVIDIA GPU, and S2 adds a licence (GPL-3.0-compatible, because Pedalboard is GPL), third-party notices and a short install README. The licence choice is asked at S2. Decision 6: UI-1d and UI-1e moved to UI-2 (`docs/tasks/UI-overhaul.md`), which runs before S2. The clean-ups and storage sizes stay in S4.

1. **Who installs it?** Only the user, on this machine and maybe a second one of their own, or other people too? This decides whether `install.bat` builds the frontend (needs Node) or the repo ships a built `frontend/dist`, whether ffmpeg is downloaded by the script, and whether licences matter (Pedalboard is GPL: only relevant if the app is given to others). **Recommendation:** only the user; `install.bat` checks for `uv` and Node, runs `uv sync`, builds the frontend, downloads the pinned ffmpeg 8.1 build into `bin/`, and creates `run.bat`.
2. **Weights download:** in `install.bat` (a console with a progress bar, before the app ever opens) or on first run inside the app (a "Download the voice model (about N GB)" screen)? **Recommendation:** in the app, as the first-run screen, with progress and a retry; after it finishes the worker always runs with `HF_HUB_OFFLINE=1` (rule 8). `install.bat` can offer to do it too.
3. **Hotkeys:** a read-only map (a "Keyboard shortcuts" panel, `?` to open) or rebindable keys saved per user? **Recommendation:** read-only map in M7 (the spec's "hotkey map"); rebinding is backlog unless the user wants it.
4. **Settings screen scope:** one Settings screen that links to what already exists and adds what has no home: emotion preset editing (exaggeration, cfg_weight, expression per preset), export defaults saved back to the project (undoable), the hotkey map, and the paths (ffmpeg, recent list, model cache). **Recommendation:** that, without moving the existing tabs.
5. **Channel templates:** "Save as template" writes the open project's bookends, voice profile, FX chain, avatar settings and export settings to a template file; "New project" picks a template. Should a template also be applicable to an open project (undoable, replacing those settings)? **Recommendation:** save and pick in M7; apply to an open project only if wanted.
6. **Carry-over items:** fold UI-1d, UI-1e and the clean-ups into M7-3, or leave them in the backlog? **Recommendation:** clean-ups and storage sizes in M7-3 (small, useful); UI-1d and UI-1e only if time allows.

## Steps

1. **S1 Decisions.** Settle the questions above, log them, branch `m7-polish`.
2. **S2 Install (M7-2, part 1).** `install.bat` and `run.bat`: check `uv` (and Node if building), `uv sync`, build the frontend, download the pinned ffmpeg into `bin/` (checked by the NVENC probe), clear messages for each failure. A dry run on the user's machine. **Manual check.**
3. **S3 First run (M7-2, part 2).** Model status and download with progress (backend job plus a first-run screen), `HF_HUB_OFFLINE=1` for the worker once the weights are present, warm-up shown as a phase instead of a silent 27 s. Tests with a fake downloader. **Manual check.**
4. **S4 Error handling and empty states (M7-3).** An audit list first: every screen with no data (no project, no footage, no clips, no lines, no takes, no art), every backend error the UI can show (missing ffmpeg, worker crash, disk full on save or export, a project from a newer version), and what the user should do next. Then the fixes, plus the agreed carry-overs (clean-up of envelopes and preview sprites, `takes_fx` sizes).
5. **S5 Settings and hotkey map (M7-1).** The Settings screen per decision 4 and the hotkey map per decision 3. Saving export defaults is an undoable command (rule 11). **Manual check.**
6. **S6 Channel templates (M7-4).** Save as template, pick a template for a new project (and apply to an open project if decided). Template files outside the repo (`%APPDATA%\PNGtuberStudio\templates\`) plus the built-in default. Tests for save and load round trips. **Manual check.**
7. **S7 Clean-install test (M7-5).** The user creates a fresh Windows user account, clones the repo, runs `install.bat`, then `run.bat`, makes a project from footage, generates a line, places it, and exports. Everything that goes wrong is fixed here. **Manual check (the milestone's "done when").**
8. **S8 Wrap-up.** `PROJECT_STATE.md`, ticks M7-1 to M7-5, spec sections 4.4 and 11 (packaging) as built, merge, tag `m7-done`.

## S4 audit (2026-11-17)

Empty states (what the screen shows with no data). "OK" means it already says what to do.

| Screen | With no data | Status |
|---|---|---|
| Home | "No recent projects yet. Create one, or open an existing project folder." | OK |
| Voice model page | missing / downloading / failed (Retry) / ready (S3) | OK |
| Project page, footage | "No footage yet. Put recordings in `<folder>\footage`, then Rescan" | OK |
| Project page, voice | problems as error banners ("no reference clip chosen") | OK |
| Project page, avatar | status text plus warnings | OK |
| Editor, no clips | stage: "Add a recording from the Footage tab." | OK |
| Editor, Footage tab with no sources | "No footage in this project yet. Go back to the project screen and Rescan." | OK |
| Line bank, no lines / no takes / nothing selected | "No lines yet. Add one ..." / "No takes yet. Generate this line ..." / "Select a line to edit it." | OK |
| Avatar tab, no art | warning banner "No usable avatar art: choose the art folder on the project screen." | OK |
| Storage tab, no lines | "No lines yet." (no next step) | after the Line bank and Storage merge (other session) |
| Export, pre-flight | errors and warnings with "Fix the errors ... then check again" | OK |

Errors the UI can show:

| Error | Before | After S4 |
|---|---|---|
| Missing ffmpeg (export) | "... (see PROJECT_STATE.md, How to run)" | "... (run install.bat again to download it)" (S2) |
| Missing ffprobe (footage scan) | "... see PROJECT_STATE.md, 'ffmpeg' ..." | "ffprobe not found at ... Run install.bat again to download it." |
| Voice model missing | worker load error | Generate refused: "download it from the start page" (S3) |
| Model fails to load (no CUDA, driver) | "could not load the model: <torch text>" | adds "If the GPU or driver changed, run install.bat again to check it." |
| Worker crash | "... see the worker log" (no path) | names the log file (`%APPDATA%\PNGtuberStudio\worker.log`) |
| No voice reference when generating | "the voice reference is not ready: no reference clip chosen" | adds "Choose a reference clip in the Voice section of the project screen." |
| Disk full / file in use / access denied (save, export, storing a take) | raw `[WinError 112] ...` | plain sentence with the drive or file and what to do (`backend/oserrors.py`) |
| Project from a newer app version | "project schema version 5 is newer than supported (4)" | "this project was saved by a newer version of PNGtuber Studio ... Update the app to open it; the project was not changed." |
| Backend not answering | "Failed to fetch" | "The app's background service is not answering. Close PNGtuber Studio and start it again ..." |
| Backend error without a reason (HTTP 500) | "HTTP 500" | "Something went wrong inside the app (HTTP 500). The console window shows the details." |
| GPU out of memory | already "the GPU ran out of memory (close other GPU programs and retry)" | OK |

Carry-overs: clean-up of `media/envelopes/` and `media/avatar_preview/` is done (on idle, same ten-minute rule as `takes_fx`). The `takes_fx` sizes in the storage manager wait for the Line bank and Storage merge.

## Acceptance checks (user runs these)

- On a fresh Windows user account: `install.bat` finishes without manual steps (other than installing `uv`, and Node if decision 1 needs it), `run.bat` opens the app, the first-run screen downloads the voice model, and a short project goes from footage to a finished export.
- After the download, the app works with the network cable unplugged (rule 8).
- Every screen has a sensible empty state; the errors in the S4 audit show a message that says what to do.
- The hotkey map lists every shortcut the editor handles.
- A template saved from `Rack 1` creates a new project with the same bookends, voice profile, FX chain, avatar settings and export settings.
- `uv run pytest`, `uv run ruff check .`, `npm run check`, `npm test` pass.

## Risks and open points

- **The weights download** is the one network step: it must be resumable or at least retryable, and its size and location must be stated before it starts.
- **CUDA torch in a fresh environment** is the most likely clean-install failure (driver, wheel index). `uv.lock` pins it; the install script should report the CUDA check (`scripts\spike\check_cuda.py`) at the end.
- **ffmpeg download:** the BtbN "latest" URL for the 8.1 branch changes over time; pin a dated release and record its version (M0 decision), and keep the manual steps as the fallback.
- **Scope creep:** settings and templates can grow without end. Keep to the decisions; everything else goes to the backlog.
