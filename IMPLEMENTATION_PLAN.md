# IMPLEMENTATION_PLAN.md

The overarching plan. Behavior and data model live in `docs/DESIGN_SPEC.md`; current reality lives in `PROJECT_STATE.md`. When a milestone item needs more breakdown, create `docs/tasks/<ID>-<slug>.md` from `docs/tasks/_TEMPLATE.md` (example: `docs/tasks/M3-04-take-store.md`).

Sizes: **S** = a few days, **M** = about a week, **L** = one to two weeks of focused work.

## Starting a task in a fresh chat (context pack)

There is no agent tooling: the assistant sees only what you paste, and you run everything yourself. For each task, open a fresh chat and paste:

1. `CLAUDE.md`
2. `PROJECT_STATE.md`
3. The task file (or the milestone section below), plus the spec sections it names
4. Any source files the task says it will edit (the assistant will ask for others by path)

Suggested first message:

> Task: `docs/tasks/<file>.md`. The three files above are pasted below. Follow CLAUDE.md. Work in small steps; I will run commands and paste results back.

If your plan has Projects in claude.ai, you can add `CLAUDE.md` and the design spec as project knowledge so you do not re-paste them. Still paste the current `PROJECT_STATE.md` every time, since it changes.

When the task is done, the assistant outputs the complete updated `PROJECT_STATE.md` and the plan item IDs to tick. Paste the state file over the old one, tick the items yourself, and commit them with the code.

## Suggested order

M0, M1, M3 (with a bare-bones player), M2, M4, M5, M6, M7. The voice loop comes early because it is the riskiest and most valuable part. M2 can be built alongside M3.

Dependencies: M2 needs M1. M3 needs M1. M4 needs M3. M5 needs M2, M3 (envelopes come from takes). M6 needs M2 to M5. M7 last.

---

## M0. Risk spike (S)

Goal: prove the three risky pieces work on the user's machine before building around them.

- [ ] M0-1 Environment: uv project, Python 3.11, CUDA torch, confirm `torch.cuda.is_available()`
- [ ] M0-2 Chatterbox clone test: reference clip, generate 3 lines at different settings; record model load time, per-line latency, peak VRAM
- [ ] M0-3 pywebview shell: FastAPI serves a page that plays a local video through HTTP range requests; confirm smooth seeking
- [ ] M0-4 ffmpeg NVENC: bundled ffmpeg encodes a 10 s clip with `h264_nvenc`; record the working command
- [ ] M0-5 Write findings and go/no-go into `PROJECT_STATE.md`

Done when: all three work on the user's machine and the user has heard one cloned line they would use.

## M1. Project foundation (M)

- [ ] M1-1 Pydantic schema for `project.json` v1 (entities from spec section 5) with `schema_version`
- [ ] M1-2 Project create/open/save: folder layout, atomic writes, autosave, rotating `.bak`
- [ ] M1-3 Footage detection and ffprobe, producing Source entities
- [ ] M1-4 Command layer and undo/redo stack
- [ ] M1-5 Channel template load/apply (default bookend clips, voice profile, FX, avatar, export defaults)
- [ ] M1-6 Project screen UI: new, open, recent, relink missing files
- [ ] M1-7 Tests: round-trip save/load, atomic write failure, migration stub

Done when: create a project, add footage, restart the app, and everything is intact.

## M2. Cut and splice editor (L)

- [ ] M2-1 Time-mapping module (source to timeline and back, including speed) with unit tests
- [ ] M2-2 Timeline canvas component: ruler, zoom/scroll, playhead, lanes framework
- [ ] M2-3 Clip operations with undo: split, ripple-delete, trim, reorder, set speed
- [ ] M2-4 Segment-hopping playback in the player
- [ ] M2-5 Anchoring helpers: re-map anchored items on edit, orphan detection
- [ ] M2-6 Hotkeys: S, Delete, [ and ], frame step, Space

Done when: a rack can be cut to a rough edit and played back with correct timing, and orphan flags appear when anchored moments are cut.

## M3. Line bank and voice (L)

- [ ] M3-1 Voice profile: reference clip import, hashing, settings screen
- [ ] M3-2 Emotion presets file and loader (`templates/`)
- [ ] M3-3 GPU worker process: queue, cancel, warm model, optional unload
- [ ] M3-4 Take store: cache keys, generate/reuse/reroll/star/delete, storage manager with sizes
- [ ] M3-5 Long-text chunking at sentence boundaries with crossfade join
- [ ] M3-6 Line bank UI and inspector: text, emotion, sliders, generate, take picker
- [ ] M3-7 Placement: drag onto timeline and hotkey M; voice lane with waveform blocks
- [ ] M3-8 In-context playback: voice audio synced with the preview
- [ ] M3-9 Overflow detection and fixes: tighten (time-stretch up to about 8%), nudge earlier, regenerate with lower cfg_weight; allow-overlap toggle

Done when: write, generate, place, reroll, close the app, reopen, and play everything with zero regeneration.

## M4. Audio chain (M)

- [ ] M4-1 Processing pipeline: trim silence, EQ, compressor, effects, loudness normalize; cached by raw key + FX hash
- [ ] M4-2 Voice FX tab UI with presets
- [ ] M4-3 Game audio level slider and mix model (voice bus + game audio + master limiter) for preview
- [ ] M4-4 Loudness meter in the status bar

Done when: moving a slider changes the audible result within about a second and uses no GPU.

## M5. Avatar (L)

- [ ] M5-1 Art loader and validator (`expression_eyes_mouth.png`), fallback to neutral with warning
- [ ] M5-2 Envelope extraction per take (about 100 Hz), cached
- [ ] M5-3 Solver core: expression, mouth (hysteresis, min hold), seeded blink
- [ ] M5-4 Solver: bounce, idle float, reactions (shake, hop, pop-in, squish), transform lanes
- [ ] M5-5 Generic lane system (keyframes, hold/smooth interpolation) shared with the timeline UI
- [ ] M5-6 Canvas renderer in the preview with drag/resize writing keyframes
- [ ] M5-7 Expression, parameter, and reaction lane UI; optional auto-key from line emotion
- [ ] M5-8 Solver tests: determinism, seek accuracy, hysteresis

Done when: the live preview looks right and scrubbing to any frame always shows the same state.

## M6. Export (L)

- [ ] M6-1 Pre-flight checks (ungenerated lines, orphans, unresolved overflow, missing files)
- [ ] M6-2 Voice track builder: raw and processed tracks with overlap mixing
- [ ] M6-3 EDL to ffmpeg filter graph, producing `video_edited.mp4`
- [ ] M6-4 Python compositor: avatar layer from solver frame states
- [ ] M6-5 Single-pass final render (NVENC) with mixed audio
- [ ] M6-6 Bundle writer: per-line wavs, hard-linked raw video, optional transparent overlay, project snapshot
- [ ] M6-7 Export UI: output folder, progress, cancel
- [ ] M6-8 Parity spot-check test (preview vs export frames at sample timestamps)

Done when: the export matches the preview at spot-check timestamps and the bundle contains every asset.

## M7. Polish (M)

- [ ] M7-1 Hotkey map and settings screens
- [ ] M7-2 First-run weights downloader plus `install.bat` and `run.bat`
- [ ] M7-3 Error handling, empty states, helpful messages
- [ ] M7-4 Channel template save/apply UI
- [ ] M7-5 Clean-install test on a fresh Windows user account

Done when: a fresh install works from `install.bat` to a finished export.

---

## Backlog (designed for, not in v1)

- Burned-in captions from line text
- A/B compare takes and loop-selected-line playback
- Vertical 9:16 and 4K export
- Zoom, freeze frame, and text overlay effects (via the effects registry)
- Additional video tracks and music
- Global favorites library across projects
- Rhubarb as an alternate mouth provider
- Per-emotion reference clips in voice profiles
- Seamless edited-proxy playback (background-rendered low-res proxy cached by edit hash)
- Keyframeable game audio level

## Risks to watch

| Risk | Mitigation |
|---|---|
| Voice quality varies between runs | Seeds, takes, reroll, starred favorites; clean 10 to 20 s reference clip |
| Hitch at cut boundaries in preview | Accept in v1; proxy playback later |
| Preview and export disagree | Single Python solver; renderers only draw its output; spot-check test |
| VRAM contention (TTS, NVENC, browser) | One GPU job at a time; optional unload before export |
| Timeline UI is the largest frontend piece | Build in M2, reuse the lane component in M5 |
| CUDA torch packaging | `install.bat` first; single exe deferred |
| Data loss | Atomic writes, autosave, rotating backup, schema versioning |
