# PNGtuber Studio: Design Spec

Source of truth for intended behavior. Sections are numbered so tasks can reference them (for example "spec section 6"). Current implementation status lives in `../PROJECT_STATE.md`.

## 1. Summary

A one-stop local desktop app that turns a recorded pool rack into a finished PNGtuber video. You cut the footage, write voice lines freely, generate them in a cloned voice, key the avatar's expressions and motion on a timeline, and export a 1080p video plus every individual asset. Nothing leaves the PC, and generated voice is never wasted.

**Goals**
- One window for the whole loop: cut, write, generate, place, tune, preview, export.
- Fast spot edits: changing one line or one slider never redoes unrelated work.
- Generated audio is kept (takes) so GPU time is never spent twice on the same result.
- Preview matches export exactly.
- Built to grow: new effects, tracks, and mouth methods plug in without redesign.

**Non-goals (v1):** full video editor (multi-track, transitions, music, color); cloud features or live streaming; vertical or 4K export; captions; A/B take compare.

## 2. Decisions locked

| Area | Decision |
|---|---|
| Platform | Windows, NVIDIA GPU with 6GB+ VRAM |
| Packaging | Python backend (FastAPI) plus web UI in a native pywebview window (WebView2). Offline after first-run model download |
| Footage editing | Cut, splice (join and reorder clips), speed change. Data model is a general edit decision list so effects and tracks can be added later |
| Footage storage | User places recordings in the project's `footage/` folder. App references them by relative path, never copies |
| Voice lines | Written freely into a line bank, generated individually, placed on footage later. Lines can exist unplaced and be reused |
| Generated audio | Every generation is a take, kept until the user deletes it. Same inputs reuse the saved take with no GPU run |
| Line too long | Warning marker with one-click fixes. Per-line allow-overlap toggle silences the warning |
| Voice | Cloned voice via Chatterbox. Reference clip source is open (own voice or acted character); a swappable voice profile makes that a settings change |
| Emotion control | Presets plus per-line sliders (exaggeration, cfg_weight) |
| Avatar | Drawn live over the video. Expression lane, parameter lanes, reaction events, all keyframeable |
| Mouth | Loudness envelope with smoothing (open/closed art). Rhubarb is a possible later provider |
| Game audio | Fixed level (dB slider) |
| Voice bus | 3-band EQ, optional compressor, effects slot, loudness meter and normalize |
| Export | 1080p 16:9 MP4 plus a bundle of individual assets |
| Intro/outro | Saved channel template auto-applies them to new projects; they are ordinary clips, swappable or deletable per project |
| Line bank scope | Per project only |

## 3. User workflow

1. New project from the channel template (default intro/outro, voice profile, FX chain, avatar settings, export settings).
2. Drop the recording into the project's `footage/` folder; the app detects it.
3. Cut and splice: remove dead time, speed up slow parts, reorder if needed.
4. Write lines in the line bank: text, emotion, sliders if needed, generate.
5. Place lines on the footage by dragging or hotkey. Listen in context. Fix overflow with one click, regenerate, or switch takes.
6. Tune the voice: EQ, compression, effects, loudness. Moving a slider reprocesses in about a second with no GPU use.
7. Direct the avatar: key expressions, adjust motion lanes over time, drop reactions.
8. QC in the live preview (footage, game audio, voice, avatar together).
9. Export the finished video plus the asset bundle.

## 4. Screens

### 4.1 Project screen
- New project from the channel template (name plus parent folder; the project folder is `<parent>\<name>`), open recent, open folder (native folder picker).
- Recent projects: up to 10, newest first, stored per user outside any project. Entries whose folder no longer exists are marked missing; the user can remove an entry from the list (the project folder is never touched).
- Shows footage files found in `footage/` (resolution, frame rate, length, audio tracks, status) with a Rescan button. New files are detected on open and on Rescan; missing files are flagged, never removed automatically.
- Voice profile and avatar art show as "not configured" or "path set" until real validation arrives (voice profile with M3, avatar art with M5).
- Relink: a missing footage file is relinked by picking the moved file. It must be inside the project's `footage/` folder and is re-probed; it is refused unless resolution, frame rate and audio track count match and length is within 100 ms.
- A failed save is shown as a banner; edits are never lost silently.

### 4.2 Editor (95% of the user's time)

- **Top left:** video player with the avatar drawn on a canvas over it (the preview frame is 16:9, fitted inside the player). While paused, drag the avatar to move it (keys x and y at the playhead) and drag its corner handle to resize it (keys scale); each gesture is one undo step.
- **Top right:** tabs for **Line bank**, **Inspector** (selected line or clip), **Voice FX**, and **Avatar** (the base motion and placement used wherever a lane has no keys, the expression and reaction tools behind `E` and `R`, and an inspector for the selected keyframe or reaction).
- **Bottom:** timeline with a ruler and these lanes:
  - Video strip (clips, cut markers, speed badges)
  - Voice lane (placed lines as blocks with waveform; red edge on overflow)
  - Expression lane (keys as diamonds)
  - Reaction lane (one-shot events as bars)
  - Parameter lanes: one collapsed "Motion keys" row by default; "Lanes" opens one row per lane: bounce, float amplitude, float speed, blink rate, mouth sensitivity, scale, x, y, rotation. Keys and reactions are selected and dragged in time here; values are edited in the Avatar tab
  - Game audio level
- **Status bar:** GPU queue, loudness meter, disk usage of takes.

**Default hotkeys**

| Key | Action |
|---|---|
| Space | Play / pause |
| , and . | Step one frame |
| S | Split clip at playhead |
| Delete | Ripple-delete selection |
| [ and ] | Set in / out on selection |
| N | New line in bank |
| G | Generate selected line |
| Shift+G | Reroll (new seed, new take) |
| M | Place selected line at playhead |
| E | Add expression key at playhead |
| R | Drop reaction at playhead |
| Ctrl+Z / Ctrl+Y | Undo / redo |

### 4.3 Export screen
- Output folder, resolution (1080p), frame rate (match footage), bundle toggles.
- Pre-flight checklist: ungenerated lines, orphaned placements, overflow warnings, missing assets.
- Progress bar with cancel.

### 4.4 Settings
Voice profiles (reference clips), emotion presets, FX chain presets, avatar art mapping, channel template, hotkeys, take storage manager.

## 5. Data model

**Project folder**

```
MyRack/
  project.json          source of truth (autosaved, atomic writes)
  project.json.bak      rotating backup
  footage/              user places recordings here
  media/
    takes_raw/          raw voice takes (kept until the user deletes them)
    takes_fx/           processed takes (re-creatable)
    envelopes/          mouth envelopes per processed take
    avatar_preview/     downscaled avatar sprites for the preview (re-creatable)
  exports/
```

**Conventions:** all times are integer milliseconds (anchor times are source time). Ids are 12-character lowercase hex strings. Paths in `project.json` are relative POSIX strings, except `external` sources (template bookend clips that live outside the project folder), which use absolute POSIX paths, and the avatar art folder, which may be absolute (the art usually lives outside the project; the project summary warns that an absolute path breaks when the project moves to another machine).

**Entities**

| Entity | Key fields |
|---|---|
| Source | id, path, external flag, duration_ms, fps (stored as fps_num / fps_den), width, height, audio track count. Project footage uses a relative path; `external` sources (template bookends) use an absolute path |
| Take | id, line id, seed, text snapshot, params used (exaggeration, cfg_weight), voice profile id, model version, raw cache key, raw file, duration_ms, starred, created, manual trim (trim_start_ms, trim_end_ms: cut points in raw take time, null for no cut on that side; the raw file is never changed) |
| Placement | id, line id, anchor (clip id, source_ms), take override, orphaned flag |
| Keyframe | id, lane id, anchor (clip id, source_ms), value (number, or expression name), interpolation (hold or smooth), orphaned flag |
| Reaction | id, type, anchor, intensity, duration_ms, orphaned flag |
| AvatarSettings | art folder (relative or absolute), base placement (x, y as fractions of the frame, scale, rotation_deg), base motion (bounce, float_amp, float_speed, float_angle_deg, blink_rate, mouth_sensitivity), auto-key expression toggle. Each base value is used wherever its lane has no keys |
| Clip | id, source id, in, out, speed, track, overlay on/off, effects list |
| Line | id, text, emotion, exaggeration override, cfg_weight override, active take id, allow-overlap flag |
| VoiceProfile | id, name, reference clip(s), optional per-emotion reference clips (reserved) |
| FxChain | EQ gains, compressor settings, effects list, loudness target |
| ChannelTemplate | bookend clips (referenced by absolute path, stored in the project as `external` sources), voice profile, FX chain, avatar defaults, export settings |

**The anchoring rule:** every timed item (placements, keyframes, reactions) is anchored to footage, meaning a clip plus a source time. Timeline time is computed by mapping through the clip list.
- Re-trimming, reordering, or changing speed never makes lines drift.
- If a trim removes the moment an item was anchored to, the item is flagged as orphaned and parked at the nearest edge for the user to resolve.
- Bookend clips (intro/outro) have overlay off and carry no anchored items.

## 6. Voice system

**Per line:** text, emotion preset, and two override sliders.
- **Exaggeration:** how dramatic the delivery is.
- **cfg_weight (pacing):** guidance strength. Lower values give slower, more deliberate delivery. Higher exaggeration tends to speed speech up, so presets pair higher exaggeration with lower cfg_weight. This is not a literal speed control; actual speed changes use time-stretching (section 6, overflow fixes).

**Starting presets (guesses, tune by ear):**

| Preset | Exaggeration | cfg_weight | Default avatar expression |
|---|---|---|---|
| neutral | 0.50 | 0.50 | neutral |
| excited | 0.75 | 0.35 | excited |
| confident | 0.55 | 0.50 | smug |
| nervous | 0.65 | 0.40 | worried |
| disappointed | 0.40 | 0.55 | sad |

**Take lifecycle**
- **Generate:** raw cache key = hash of text, voice profile (including reference clip hash), exaggeration, cfg_weight, seed, and model version. If a take with that key exists it plays immediately with no GPU run.
- **Reroll:** same text, new seed, new take. Chatterbox is stochastic, so rerolls are how to fish for a better read.
- **Keep everything:** takes are never auto-deleted. Star favorites, pick the active take, delete manually from the storage manager (shows size per line).
- **Long text:** lines over the model's comfortable length are split at sentence boundaries, generated in pieces, and joined with short crossfades.
- **Queue:** one GPU job at a time, with cancel. The model stays loaded between jobs. An option unloads it to free VRAM before export.

**Too-long line detection.** A placed line overflows if its processed duration runs past the next placement's start. The line shows a warning with one-click fixes:
1. **Tighten:** time-stretch the existing audio up to about 8 percent (no regeneration).
2. **Nudge earlier:** move the start up to the available slack.
3. **Regenerate:** new take with a lower cfg_weight or edited text.

The per-line **allow overlap** toggle clears the warning when overlap is intended. Overlapping lines are mixed together at export.

## 7. Audio chain

**Voice processing (CPU, fast, derived from the raw take):**

1. Manual cut (optional, per take): only the region between the take's start and end cut points is kept
2. Trim leading and trailing silence, measured inside that region
3. Short fade (8 ms raised cosine) where the kept audio starts or ends exactly on a manual cut, so the cut does not click
4. Time stretch (the placement's stretch factor)
5. 3-band EQ (bass, mids, treble)
6. Compressor (optional)
7. Effects slot (reverb, pitch shift, chorus, and similar)
8. Loudness normalize to a target (default around -16 LUFS), then a limiter

The result is the **processed take**, cached by hash(raw key, stretch, processing spec). The processing spec is what the chain actually does (manual cut points, silence trim settings, the active stages, loudness settings), so a setting that does nothing never changes the key, and only a trimmed take gets a new key when its cut changes. Slider changes re-run only this stage. The editor and the export both play the processed files, so what is heard is what is exported.

**Mix:** game audio at a fixed dB level plus the voice bus, summed with a master limiter to prevent clipping. The status bar meter shows live loudness of the mix.

**Tooling:** Pedalboard (Spotify) for EQ, compressor, and effects; pyloudnorm for LUFS. Pedalboard is GPL licensed, which only matters if the app is distributed. Fallback: ffmpeg filters (equalizer, acompressor, loudnorm), which cover everything except high-quality reverb.

## 8. Avatar system

**Art convention.** The art folder holds one folder per expression named `NN_name` (for example `01_neutral`; `NN` orders them). Each holds four PNGs named `NNx_name_EEMM.png`, where `x` is one letter, `EE` is `oi` (eyes open) or `ci` (eyes closed) and `MM` is `om` (mouth open) or `cm` (mouth closed), for example `01a_neutral_oicm.png`. Other files (such as preview videos) are ignored; a PNG that breaks the rule, belongs to another folder or repeats a state is skipped with a warning. A missing state falls back to the nearest state of the same expression (closed eyes to open eyes, open mouth to closed mouth), then to the default expression, with a warning.

An optional `avatar.json` in the art folder sets `default_expression` (otherwise the first by number) and `emotion_map` (emotion preset name to expression id). It lives with the art so it follows the avatar to other projects. An expression named by a key or a preset that the art lacks falls back to the default expression; `neutral` means the default expression without a warning.

**Placement.** The sprite's bottom centre sits at (x times the frame width, y times the frame height); at scale 1 the sprite is 0.6 of the frame height; rotation turns about the bottom centre. The preview draws downscaled copies (about 1000 px high, `media/avatar_preview/`); the export uses the full-size files.

**Solver and drawing are separate.** A Python **avatar solver** is the single source of truth. It takes the project (lanes, reactions, envelopes, seed) and outputs a compact per-frame state: which sprite, plus position, scale, and rotation. Two thin renderers draw that state:
- The browser canvas for live preview.
- A Python compositor for export.

The solver is a pure function of time, so scrubbing is frame-accurate and the preview matches the export. The preview receives the solver's output sampled at 30 fps for the whole timeline (a frame track, rebuilt after each edit) and draws the nearest frame.

**Solver behavior**

| Element | How it works |
|---|---|
| Expression | Step value from the expression lane (hold interpolation) |
| Mouth | Loudness envelope of each processed take (20 ms RMS every 10 ms, dBFS), the loudest placed line at each step. Opens at -32 dBFS, closes below -38 dBFS (hysteresis), minimum hold of 70 ms for both states. Mouth sensitivity s lowers both thresholds by 20 log10(s) dB |
| Blink | Seeded random intervals between a minimum and maximum, scaled by the blink-rate lane. About 120 ms closed |
| Bounce | While speaking, a damped spring chasing the voice level times the bounce lane lifts the avatar (up to 3% of the frame height at bounce 1) |
| Idle float | Slow sinusoidal drift; amplitude and speed lanes; drifts along the float direction setting (0 degrees up and down, 90 side to side) |
| Reactions | One-shots: shake (damped oscillation), hop, pop-in (scale with overshoot), squish. Each has intensity and duration |
| Transform | Position, scale, rotation lanes. Dragging the avatar in the preview writes keyframes |

**Lanes.** Every parameter lane has a base value in the avatar settings, used wherever the lane has no keys. A key's interpolation (hold, or smooth with an ease) describes the segment after it; before the first key and after the last the value holds. New transform keys are smooth; expression keys always hold. Tuning constants live in `backend/avatar/tuning.py`.

All randomness comes from a seeded generator keyed to the project seed and event index.

**Expression defaults:** a line's emotion can optionally auto-key its suggested expression at the line's start. Manual keys always win. Auto-keying is a toggle. It adds a key only where the emotion leads to an expression the art has (through `emotion_map`, or a preset expression of that name), so presets that mean neutral add nothing.

## 9. Editing (cut and splice)

- **Operations:** split at playhead, ripple-delete a range, trim clip edges, reorder clips by dragging, set clip speed (0.25x to 8x), add or remove bookend clips.
- **Undo/redo:** a command stack over project.json changes, with grouped drag operations.
- **Playback of cuts:** v1 hops between segments (a seek at each boundary, slight hitch possible). Later, a background-rendered low-res edited proxy gives seamless playback, cached by edit hash.
- **Speed clips:** browser playback uses playback rate with pitch preserved; export uses ffmpeg time-scaling (setpts and atempo).
- **Scalability hooks:** the clip list supports multiple tracks, and each clip has an `effects` list drawn from a registry. Adding zoom, freeze, or text means registering a new effect type with (a) its parameters, (b) its ffmpeg filter builder, (c) its preview applicator. The editor and export loop do not change.

## 10. Export pipeline

1. **Pre-flight:** check for ungenerated lines, orphaned items, unresolved overflow, and missing files.
2. **Voice tracks:** place raw and processed takes at their mapped timeline times (overlaps mixed). Write `voice_raw.wav` and `voice_processed.wav`.
3. **Edited video:** build one ffmpeg filter graph from the clip list (trim, speed, concat), encoded with NVENC to `video_edited.mp4` (no avatar, no voice).
4. **Final render:** a single pass takes the edited video, the solver's frame states composited into an avatar layer, and the mixed audio, and encodes `final_1080p.mp4` with NVENC.
5. **Bundle** (one folder per export):
   - `final_1080p.mp4`
   - `voice_raw.wav`, `voice_processed.wav`, and `lines/` with per-line processed takes
   - `video_edited.mp4`
   - `video_raw`: an NTFS hard link to the original recording (no extra disk used), or a path note if on another drive
   - `avatar_overlay` (transparent, optional toggle)
   - `project.json` snapshot

Progress streams to the UI over a WebSocket, with cancel support. Export unloads the TTS model first if that option is enabled.

## 11. Architecture

**Processes**
- **Shell:** pywebview window loading the local backend URL.
- **Backend:** FastAPI with uvicorn on 127.0.0.1, WebSocket for events (job progress, status).
- **GPU worker:** separate process holding Chatterbox, with a job queue and cancel.
- **CPU worker pool:** audio FX, envelopes, waveforms, ffmpeg jobs.
- **Media server:** HTTP range requests for footage and audio so seeking is smooth.

**Frontend:** Svelte + TypeScript with Vite, built to static files and bundled (no Node needed at runtime). The timeline is a custom canvas component.

**Bundled binaries:** ffmpeg and ffprobe with NVENC in `bin/`, from a pinned release-branch build (BtbN GPL 8.1.x). Do not use `master` or 9.0 builds: they need NVENC API 13.1 (driver 610+) and fail on older drivers (verified on driver 581.42).

**Python dependencies:** torch (CUDA), chatterbox-tts, pedalboard, pyloudnorm, numpy, soundfile, opencv or Pillow, fastapi, uvicorn, pydantic, pywebview.

**Persistence:** `project.json` is the single source of truth with atomic writes (temp then replace), autosave on change, and a rotating backup. A `schema_version` field supports migrations. The per-user recent-projects list lives at `%APPDATA%\PNGtuberStudio\recent.json`, outside any project.

**Packaging:** start with `install.bat` (uv creates the environment, installs CUDA torch, downloads model weights) and `run.bat`. A single exe is deferred because CUDA torch makes it a multi-gigabyte build.

## 12. Open items

- Voice source: own voice or acted character.
- Effects slot contents: which effects first (reverb, pitch shift, chorus, others).
- Avatar art naming: resolved in M5 (section 8).
- Avatar tuning is by eye: mouth thresholds, blink gaps, bounce spring, reaction curves, the default position (x 0.85, y 0.75) and size (0.6 of the frame height).
- Mouth timing against the sound: if the mouth looks early or late in the preview (Web Audio output latency), add a fixed offset setting.
- Recording frame rate: resolved in M0. OBS recordings are 2560x1440 at 60 fps (H.264, one mixed stereo AAC track).
- Emotion preset numbers are guesses to tune in M3.
