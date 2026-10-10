# M0: Risk spike

- **Milestone items:** M0-1 to M0-5 in `IMPLEMENTATION_PLAN.md`
- **Spec sections:** 2, 6, 11
- **Status:** not started

## Goal

Prove on the user's Windows + NVIDIA machine that the three risky pieces work: local cloned-voice generation, local video playback with seeking inside a pywebview window, and NVENC encoding with a bundled ffmpeg. Throwaway scripts are fine, but keep them under `scripts/spike/` so findings can be reused.

## How this task runs

The assistant writes scripts and commands; the user runs them in PowerShell from the repo root and pastes back the output. Work one step at a time and do not move on until the user confirms the previous step.

## Prerequisites (user does these first)

- [ ] **Git** installed, repo cloned to a folder without spaces in the path if possible
- [ ] **NVIDIA driver** current; `nvidia-smi` in PowerShell shows the GPU and driver version
- [ ] **uv** installed (Python manager). The assistant gives the install command
- [ ] **ffmpeg** build with NVENC support downloaded (a Windows "full" build from a known builder such as gyan.dev or BtbN), `ffmpeg.exe` and `ffprobe.exe` placed in `bin/`
- [ ] **Reference voice clip:** a clean WAV, 10 to 20 seconds, quiet room, one speaker, natural delivery
- [ ] **Test video:** any short pool clip (30 to 60 s), kept outside the repo or in a git-ignored folder

## Context pack

- `CLAUDE.md`
- `PROJECT_STATE.md`
- This task file
- No source files exist yet

## Scope

**In:**
- uv project setup, Python 3.11, CUDA torch
- Chatterbox clone test script
- Minimal FastAPI + pywebview page with a range-request video endpoint
- ffmpeg NVENC test command
- Recording findings in `PROJECT_STATE.md`

**Out:**
- Any real app structure, schema, UI polish, or tests beyond a smoke check

## Steps

Each step ends with what to paste back.

1. **Environment (M0-1).** Assistant gives the uv commands to create the project with Python 3.11 and install CUDA-enabled torch for the GPU, plus `scripts/spike/check_cuda.py` that prints `torch.cuda.is_available()`, GPU name, and total VRAM.
   *Paste back:* output of `nvidia-smi` (first 15 lines) and of the script.
2. **Chatterbox (M0-2).** Assistant gives the install command and `scripts/spike/tts_test.py`. The assistant must first check the current Chatterbox usage with the user's installed version (ask for `pip show chatterbox-tts` output and any import error), because the API may have changed. Expected shape: load the model on `cuda`, call generate with text, the reference clip path, `exaggeration`, and `cfg_weight`, save the waveform at the model's sample rate. Generate 3 lines at different settings (for example neutral 0.5/0.5, excited 0.75/0.35, nervous 0.65/0.40). The script logs model load time, per-line time, and peak VRAM, and writes to a git-ignored folder (`scripts/spike/out/`).
   *Paste back:* the script's printed timings and VRAM, plus any traceback. The user also listens to the 3 files and says which settings sounded best.
3. **Player (M0-3).** Assistant gives `scripts/spike/player_spike.py`: a FastAPI app with a video endpoint that supports HTTP Range requests, a page with a `<video>` element, opened in a pywebview window. The user tests seeking to several positions, including near the end.
   *Paste back:* whether it plays, whether seeking is smooth, and any traceback.
4. **NVENC (M0-4).** Assistant gives one ffmpeg command that encodes a 10 s sample with `h264_nvenc`.
   *Paste back:* the last 20 lines of ffmpeg output, or the error.
5. **Findings (M0-5).** Assistant outputs the complete updated `PROJECT_STATE.md` including: versions installed, load/generation times, VRAM use, seek behavior, the working ffmpeg command, how to run each spike script, and a go/no-go. Also lists the plan items to tick.

## Acceptance criteria

- [ ] `torch.cuda.is_available()` is true and the GPU is detected
- [ ] 3 cloned lines generated; the user has listened and judged at least one usable
- [ ] Video plays and seeks smoothly in the pywebview window from a local file
- [ ] NVENC encode succeeds; command recorded
- [ ] `PROJECT_STATE.md` updated with findings and how to run each spike script
- [ ] M0 items ticked in `IMPLEMENTATION_PLAN.md`

## Notes

- If VRAM is tight, record peak usage while the browser window is also open, since that is the real-world case.
- If generation latency per line is much above about 10 s for a short line, note it; it affects how the line bank UI should show progress.
- The assistant cannot see errors until the user pastes them. When something fails, get the full traceback and exact command before suggesting a fix.
