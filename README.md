# PNGtuber Studio

Local Windows app that turns a recorded 9-ball pool rack into a finished PNGtuber video: cut footage, write and generate cloned-voice lines, direct an avatar on a timeline, export a 1080p video plus every individual asset. Runs fully offline after the first-run model download.

**Status:** M0 to M6 are built: editing, voice generation, voice FX, the avatar and export all work. M7 (install and polish) is in progress. See `PROJECT_STATE.md`.

## Install

**You need:** Windows 10 or 11 (64-bit), an NVIDIA GPU with 6 GB VRAM or more and driver 570 or newer ([download](https://www.nvidia.com/Download/index.aspx)), about 15 GB free disk space, and an internet connection for the install and the first run. Admin rights are not needed.

1. Get the app folder: **Code > Download ZIP** on GitHub (then right-click the zip, **Properties**, tick **Unblock**, **OK**, and extract it), or `git clone`. A short path without special characters, such as `D:\PNGtuberStudio`, works best.
2. Double-click **`install.bat`**. It checks the GPU and driver, then downloads into the app folder: uv and Python 3.11 with the Python packages (about 3 GB), a portable Node.js to build the window, and ffmpeg 8.1. It ends with a CUDA and video-encoder check, and creates `run.bat` and a **PNGtuber Studio** desktop shortcut. If Windows shows "Windows protected your PC", click **More info > Run anyway**.
3. Start the app from the desktop shortcut (or `run.bat`). The first time, it downloads the voice model (several GB, once). After that it runs offline.

`install.bat` is safe to run again: it skips what is already done and repairs what is missing. If it stops, the red line says what to do, and the full log is in `install.log`.

## Voice cloning

The app clones the voice in the reference clip you give it. **Use only your own voice, or a voice whose owner has given you permission.** Generated audio carries Resemble AI's inaudible Perth watermark.

## Licence

GPL-3.0-or-later (see `LICENSE`). Third-party components and their licences are listed in `THIRD_PARTY_NOTICES.md`.

## Docs

| File | Purpose |
|---|---|
| `CLAUDE.md` | Instructions and business rules for AI assistants |
| `PROJECT_STATE.md` | Living snapshot: what exists, where it lives, how to run |
| `IMPLEMENTATION_PLAN.md` | Milestones M0 to M7 and task checklist |
| `docs/DESIGN_SPEC.md` | Full design spec |
| `docs/tasks/` | Per-task breakdowns (`_TEMPLATE.md`, `M0-spike.md`) |

## Working with an AI assistant

No agent tooling: everything is done in a plain chat by hand. Start each task in a fresh chat with `CLAUDE.md`, `PROJECT_STATE.md`, the task file, and any source files the task names. The assistant writes code and commands; you run them on Windows and paste results back. Details and a suggested first message are in `IMPLEMENTATION_PLAN.md`.
