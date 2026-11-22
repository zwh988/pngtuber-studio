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
- New project from a channel template (name, parent folder and template; the project folder is `<parent>\<name>`), open recent, open folder (native folder picker). The template picker lists the built-in Default and the user's saved templates, each with a one-line summary. "Save as template" on the project page saves the project's intro and outro, voice profile with a copy of its reference clip, voice FX, game audio level, avatar settings and export defaults to `%APPDATA%\PNGtuberStudio\templates\<name>\`; an existing name is replaced only on request. Templates are not applied to an open project.
- Recent projects: up to 10, newest first, stored per user outside any project. Entries whose folder no longer exists are marked missing; the user can remove an entry from the list (the project folder is never touched).
- Shows footage files found in `footage/` (resolution, frame rate, length, audio tracks, status) with a Rescan button. New files are detected on open and on Rescan; missing files are flagged, never removed automatically.
- Voice profile and avatar art show as "not configured" or "path set" until real validation arrives (voice profile with M3, avatar art with M5).
- Relink: a missing footage file is relinked by picking the moved file. It must be inside the project's `footage/` folder and is re-probed; it is refused unless resolution, frame rate and audio track count match and length is within 100 ms.
- A failed save is shown as a banner; edits are never lost silently.
- First run (M7): with no voice model on disk and no project open, the Voice model page opens first: download size and folder, Download with progress, Retry after a failure, Later. Home shows a banner while the model is missing.
- Layout (UI-2): a sidebar (logo, Home, Voice model, Settings, the open project, Recent, New project, Open folder) and pages. Home lists the recent projects; the Project page has a header with the name and "Open editor", four summary cards (footage, timeline, voice, avatar) with status badges, the footage table, and Voice and Avatar cards with their path fields; long help texts are folded away.

### 4.2 Editor (95% of the user's time)

- **Top left:** video player with the avatar drawn on a canvas over it (the preview frame is 16:9, fitted inside the player). While paused, drag the avatar to move it (keys x and y at the playhead) and drag its corner handle to resize it (keys scale); each gesture is one undo step and changes the lane's key within one frame (34 ms) of the playhead, or adds one (keyframes task). Video-lane clips (M8-2) are drawn over the footage in lane order, the avatar between the lanes where its row puts it; while paused, the selected lane clip shows a white dashed outline with corner squares: drag it to move, drag a corner to resize around its centre (one undo step each). An image clip with keys (keyframes task) is drawn at its keyed position, size and opacity at the playhead; a drag keys the keyed properties at the playhead and changes the others. The player runs to the last clip on any lane; past the end of the footage the frame is black under the lanes and the avatar.
- **Top right:** tabs for **Footage** (add a recording to the timeline), **Line bank** (the line list, the selected line's settings, Generate, Reroll and Place at playhead (`M`), and its takes with their size on disk; the disk total, the confirmed permanent Delete take and Delete line and takes, and the read-only list of unreferenced files also live here), **FX** (M8-4: the voice chain, or, while an audio clip is selected, that clip's chain: EQ, compressor, effects and a loudness-levelling switch, with Apply to the selected audio clips and Remove FX; presets, audition and game audio show for the voice only), and **Avatar** (the base motion and placement used wherever a lane has no keys, the expression and reaction tools behind `E` and `R`, and an inspector for the selected keyframe or reaction: for an x, y, size or rotation key the four lanes of that moment together, a typed value or a slider each, a key button for a lane without a key there; easing and strength; Move to playhead; Delete. Slider values can be typed everywhere in this tab).
- **Bottom:** timeline with a ruler and these lanes:
  - Video lanes (M8-2), above the video strip, highest lane on top: recordings dragged from the Footage tab and images (PNG, JPG) or videos dropped from Explorer (images are copied into `images/`; a video from outside `footage/` is copied into `footage/` once, with a message). Drag to move (also to another lane), drag an edge to trim (a still or freeze frame can be any length); clips on one lane never overlap. The lane-name column holds the name, hide (eye; a hidden lane is neither shown nor exported), lock (no edits to its clips) and remove for an empty lane; "+ Video lane" adds one on top (also a drop target). An **Avatar** row sits among the lanes with up and down arrows: lanes above it draw over the avatar (default: on top of every lane). The bar under the timeline sets the selected clip's X, Y, Size and Opacity (%), Full frame, a recording's sound level and mute, Freeze frame, and removes it (also Delete). **Image clips take keys** (keyframes task): the bar shows the values at the playhead, a diamond after each value keys it at the playhead (filled: a key is there; click to remove it), a keyed value has a blue outline and keys at the playhead when changed (greyed out while the playhead is off the clip), and Easing and Strength set the keys at the playhead. The keys show as diamonds along the bottom of the clip block (opacity in the reaction colour); click one to put the playhead on it, drag it to move it within the clip (it always snaps to the clip's start and end, with the magnet also to the playhead, the clip's other keys and other clips' edges; Alt drags freely)
  - Video strip (clips, cut markers, speed badges; freeze frames are labelled "Freeze 0:05.000")
  - Voice lane (placed lines as blocks with waveform; red edge on overflow)
  - Audio lanes (M8-1): music and sound effects dragged from Explorer onto a lane (WAV, MP3, FLAC, OGG, M4A; several files go one after another; a drop on the "+ Audio lane" row makes a new lane; a drop where the lane is taken goes to the next lane with room, or a new one). Blocks with a waveform, the clip level and fade lines. Drag to move (also to another lane), drag an edge to trim; clips on one lane never overlap. The lane-name column holds the name (click to rename), M (mute), S (solo), the lane level in dB and a remove button for an empty lane (never the last). The bar under the timeline sets the selected clip's level and fades, opens its FX (an FX button, "FX on" when the clip has FX; such clips show "FX ·" before their name), and removes it (also Delete)
  - Expression lane (keys as diamonds)
  - Reaction lane (one-shot events as bars)
  - Parameter lanes: one collapsed "Motion keys" row by default; "Lanes" opens one row per lane: bounce, float amplitude, float speed, blink rate, mouth sensitivity, scale, x, y, rotation. Keys and reactions are selected and dragged in time here; values are edited in the Avatar tab. Keyframes task: clicking a key or reaction puts the playhead on it; on the collapsed row the motion keys at one time are one group; Shift-click adds or removes; a drag over empty avatar rows box-selects (Shift adds); dragging any selected item moves the whole selection by the same amount (one undo step), snapping with the magnet to the playhead, clip and line edges and other keys and reactions (Alt: free); Delete removes the selection; previous and next key buttons in the toolbar (`<` `>`). Past the end of the footage a key or reaction keeps its timeline time and shows a small pin
  - Game audio level
- Timeline chrome (UI-2): a lane-name column left of the canvas (the Motion row collapses and expands the per-lane rows), an icon toolbar (zoom out, zoom in, fit, lanes, snap (M8-2: a magnet; on by default and remembered; audio and lane clips snap to the edges of any clip and to the playhead while moved or trimmed, within 8 pixels; Alt drags freely), help), one colour per lane, one selected look for every item, and a white playhead distinct from the red overflow edge. Below the timeline: the selected clip or line bar and the clip table.
- **Status bar:** GPU queue, loudness meter, disk usage of takes.

**Default hotkeys**

| Key | Action |
|---|---|
| Space | Play / pause |
| , and . | Step one frame |
| S | Split at playhead: the selected audio or lane clip, else the footage |
| F | Freeze frame at playhead (2 s): the selected lane recording, else the footage |
| Delete | Ripple-delete selection |
| [ and ] | Set in / out on selection |
| N | New line in bank |
| G | Generate selected line |
| Shift+G | Reroll (new seed, new take) |
| M | Place selected line at playhead |
| E | Add expression key at playhead |
| < and > | Previous / next avatar key (the playhead goes onto it and selects it) |
| R | Drop reaction at playhead |
| Ctrl+Z / Ctrl+Y | Undo / redo |

### 4.3 Export screen
Opened with "Export..." in the editor.
- Output folder (the project's `exports` by default), resolution (1080p), frame rate (match footage), bundle toggles (transparent avatar overlay, raw video link, unload the voice model first), and a test export of the first N seconds, with an estimate of the bundle size.
- Pre-flight checklist: errors block (missing files, no clips, ffmpeg or NVENC not working); warnings (ungenerated lines, orphaned items, overflow, missing avatar art) need "Export anyway".
- Progress bar with the step, time so far and time left, and cancel; then the files written and "Open folder".

### 4.4 Settings
A sidebar page on the project screen (M7). It adds what has no other home and points to the rest:
- **Emotion presets:** exaggeration, pacing (cfg_weight) and avatar expression for each built-in emotion, app-wide (`%APPDATA%\PNGtuberStudio\emotion_presets.json`; the built-in file stays the default). Values only: presets are not added or removed. Reset per row or all. Lines that use a changed preset get a new take on their next Generate; old takes stay.
- **Export defaults** of the open project: resolution (1080p or 720p), frame rate (match, 30, 60) and the bundle switches; one undo step; the export screen starts from them.
- **Keyboard shortcuts:** the read-only map (also `?` or the keyboard icon in the editor).
- **Tools and folders:** whether video export works (ffmpeg and NVENC), and each path the app uses with Open folder.
- **Elsewhere:** voice reference and avatar art folder on the project page; FX presets and game level in the Voice FX tab; takes, disk space and deletes in the Line bank; avatar motion in the Avatar tab; the model download on the Voice model page; channel templates on the project page and New project.

## 5. Data model

**Project folder**

```
MyRack/
  project.json          source of truth (autosaved, atomic writes)
  project.json.bak      rotating backup
  footage/              user places recordings here
  audio/                copies of dropped music and sound effects (M8-1)
  media/audio_fx/       audio clip files rendered through their FX, one per file and chain (M8-4, re-creatable)
  images/               copies of images dropped on the video lanes (M8-2)
  media/
    takes_raw/          raw voice takes (kept until the user deletes them)
    takes_fx/           processed takes (re-creatable)
    envelopes/          mouth envelopes per processed take
    avatar_preview/     downscaled avatar sprites for the preview (re-creatable)
    audio_decoded/      each imported audio file decoded to 48 kHz 16-bit WAV (re-creatable)
  exports/
```

**Conventions:** all times are integer milliseconds (anchor times are source time). Ids are 12-character lowercase hex strings. Paths in `project.json` are relative POSIX strings, except `external` sources (template bookend clips that live outside the project folder), which use absolute POSIX paths, and the avatar art folder, which may be absolute (the art usually lives outside the project; the project summary warns that an absolute path breaks when the project moves to another machine).

**Entities**

| Entity | Key fields |
|---|---|
| Source | id, path, external flag, duration_ms, fps (stored as fps_num / fps_den), width, height, audio track count. Project footage uses a relative path; `external` sources (template bookends) use an absolute path |
| Take | id, line id, seed, text snapshot, params used (exaggeration, cfg_weight), voice profile id, model version, raw cache key, raw file, duration_ms, starred, created, manual trim (trim_start_ms, trim_end_ms: cut points in raw take time, null for no cut on that side; the raw file is never changed) |
| Placement | id, line id, anchor (clip id, source_ms), take override, orphaned flag |
| Keyframe | id, lane id, either anchor (clip id, source_ms) or timeline_ms (past the end of the footage, schema v8), value (number, or expression name), interpolation (hold, linear, ease_in, ease_out, ease_in_out; schema v7), ease_strength (0 to 2, default 1), orphaned flag |
| Reaction | id, type, either anchor or timeline_ms (schema v8), intensity, duration_ms, orphaned flag |
| AvatarSettings | art folder (relative or absolute), base placement (x, y as fractions of the frame, scale, rotation_deg), base motion (bounce, float_amp, float_speed, float_angle_deg, blink_rate, mouth_sensitivity), auto-key expression toggle. Each base value is used wherever its lane has no keys |
| Clip | id, source id, in, out, speed, track, overlay on/off, effects list, freeze_ms (M8-2: a freeze frame holds that recording frame, silently, at 1x; its in and out are then a hold range, so anchors, splits and trims work on it unchanged) |
| Line | id, text, emotion, exaggeration override, cfg_weight override, active take id, allow-overlap flag |
| VoiceProfile | id, name, reference clip(s), optional per-emotion reference clips (reserved) |
| FxChain | EQ gains, compressor settings, effects list, loudness target |
| AudioFile | id, path (`audio/<name>`, the copy), original name and size (a drop of the same name and size reuses the copy), duration_ms (of the decoded WAV), sample rate, channels (schema v5) |
| AudioLane | id, name, gain_db (-60 to +12), mute, solo. A project always has at least one ("Audio 1") |
| AudioClip | id, lane id, file id, timeline_ms (a timeline time, not an anchor), in_ms and out_ms (times in the file), gain_db (-60 to +12), fade_in_ms, fade_out_ms (together at most the clip length), fx (schema v10: a ClipFx, or null for none). Clips on one lane never overlap |
| ClipFx | M8-4: the voice FxChain's fields (EQ gains, compressor, effects, loudness target) plus loudness_enabled (default off). A chain that changes nothing plays the file as it is |
| ImageFile | id, path (`images/<name>`, the copy), original name and size (a drop of the same name and size reuses the copy), width, height (schema v6) |
| VideoLane | id, name ("Video 2" up), hidden, locked. `Project.video_lanes` is bottom to top |
| LaneClip | id, lane id, exactly one of source id (a recording) and image id, timeline_ms (not an anchor), in_ms and out_ms (recording times; a still or freeze frame has in 0 and out its length), x and y (centre as fractions of the frame, -1 to 2), scale (0.05 to 4, 1 = fitted to the frame), opacity, gain_db and mute (a recording's own sound), freeze_ms (a freeze frame of the recording), keys (schema v9; image clips only). Clips on one lane never overlap |
| ClipKey | id, prop (x, y, scale or opacity), t_ms (ms from the clip's start; may lie outside the clip after a trim), value (in the property's range), interpolation and ease_strength as for keyframes. A property with keys follows them; one without keeps the clip's own value |
| Project (M8-2) | avatar_below_lane_id: the avatar draws just under that video lane; null = over every lane |
| ChannelTemplate | bookend clips (referenced by absolute path, stored in the project as `external` sources), voice profile, FX chain, avatar defaults, export settings |

**The anchoring rule:** every timed item (placements, keyframes, reactions) is anchored to footage, meaning a clip plus a source time. Timeline time is computed by mapping through the clip list.
- Re-trimming, reordering, or changing speed never makes lines drift.
- If a trim removes the moment an item was anchored to, the item is flagged as orphaned and parked at the nearest edge for the user to resolve.
- Bookend clips (intro/outro) have overlay off and carry no anchored items.
- **Exception (M8, user 2026-11-20):** audio clips on audio lanes and clips on upper video lanes are not anchored. They sit at a timeline time; no video edit (cut, trim, ripple-delete, reorder, speed) moves or cuts them, so they are never orphaned. The user moves and trims them. A video's own sound always follows its video.
- **Exception (keyframes task, user 2026-11-20):** an avatar key or reaction placed or moved past the end of the footage stores that timeline time instead of an anchor. Footage edits never move or orphan it, and it stays there if the footage later grows under it (a pin marks it). Each move decides again: onto footage it is anchored.

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

**Mix:** game audio at a fixed dB level plus the voice bus plus the audio-lane clips (M8-1) plus the video-lane clips' own sound (M8-2), summed with a master limiter to prevent clipping. The status bar meter shows live loudness of the mix.

**Audio-lane clips (M8-1):** a dropped file is copied into `audio/` and decoded once with ffmpeg to `media/audio_decoded/<id>.wav` (48 kHz, 16-bit); the preview, the waveform and the export all read that WAV. A clip plays at clip gain + lane gain (dB); fades are linear in amplitude (0 at the clip start up to full level at fade_in_ms; full level at length - fade_out_ms down to 0 at the clip end); a muted lane, or any lane not soloed while some lane is, is silent; a mono file plays on both channels. The rules live once per side, the same in both: `frontend/src/audioMix.ts` (preview) and `backend/export/audioclips.py` (export). No ducking.

**Audio clip FX (M8-4):** each audio clip may have its own chain: 3-band EQ, compressor and the effect list (the voice chain's stages, same registry), plus loudness levelling to a target with the -1 dBFS limiter, off by default. No silence trim, no stretch. The chain runs on the clip's whole decoded file once and the result is kept in `media/audio_fx/<key>.wav`, the key being a hash of the file and the clip processing spec (what the chain actually does; a chain that does nothing has no spec and plays the file). The cut, fades, clip level and lane level come after it, so moving, trimming or splitting a clip never re-renders and a reverb tail stops at the clip's end. The render keeps the file's rate, channels and length. The preview plays that file (`/media/audioclip/{id}`, rendered on first request) and the export mixes the same file.

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

**Lanes.** Every parameter lane has a base value in the avatar settings, used wherever the lane has no keys. A key's easing describes the segment after it: **hold** (jump at the next key), **linear**, **ease in**, **ease out** or **ease in-out**, with an **ease strength** from 0 (linear) through 1 (normal: quadratic in and out, smoothstep in-out) to 2 (strong: cubic, smootherstep), blended in between and never overshooting (keyframes task, schema v7; the old `smooth` is ease in-out at strength 1). Before the first key and after the last the value holds. New transform keys ease in-out; expression keys always hold. Keys past the footage are evaluated at their timeline time like any other. Tuning constants live in `backend/avatar/tuning.py`.

All randomness comes from a seeded generator keyed to the project seed and event index.

**Expression defaults:** a line's emotion can optionally auto-key its suggested expression at the line's start. Manual keys always win. Auto-keying is a toggle. It adds a key only where the emotion leads to an expression the art has (through `emotion_map`, or a preset expression of that name), so presets that mean neutral add nothing.

## 9. Editing (cut and splice)

- **Operations:** split at playhead, ripple-delete a range, trim clip edges, reorder clips by dragging, set clip speed (0.25x to 8x), add or remove bookend clips.
- **Audio lanes (M8-1):** add, rename, reorder, remove (empty, never the last), level, mute, solo; audio clips add (drop), move (time and lane), trim either edge (the start edge moves the timeline start and the file in-point together), level, fades, split at the playhead (the first part keeps the fade-in, the second the fade-out), remove. Video edits never touch audio clips (section 5). Each is one undo step; a drop of several files is one step.
- **Video lanes (M8-2):** add, rename, hide, lock, reorder, remove (empty); lane clips add (Footage tab drag or Explorer drop), move (time and lane), trim, split at the playhead, place and size (clip bar or preview handles), opacity, sound level and mute, remove; the avatar's layer moves between the lanes. A locked lane refuses edits to its clips.
- **Image clip keys (keyframes task):** moving a clip carries its keys; a start trim keeps each key at the same timeline moment (its clip time moves the other way); keys a trim leaves outside the clip are kept, still shape the curve and come back when the clip is lengthened; a split gives both parts the keys (the right part copies with new ids). Removing a property's last key leaves its value on the clip. The preview (`frontend/src/clipKeys.ts`) and the export (`backend/export/clip_keys.py`) evaluate them the same way, checked against one shared table (`tests/fixtures/clip_key_cases.json`); the export sends ffmpeg the per-frame size, opacity and position (section 10).
- **Freeze frame (M8-2):** on a lane recording, the clip splits at the playhead and a 2 s hold of that frame goes in between; the rest of the clip and later clips on that lane move later, other lanes and the footage do not. On the main footage, the clip splits at the playhead (snapped to its frame grid) and a 2 s hold clip goes in between; everything after it moves later, voice lines, keys and reactions with it, and nothing is orphaned; at a clip's first or last frame the hold goes before or after it. A hold is silent, has no speed and is trimmed like any clip (it may be longer than its recording).
- **Undo/redo:** a command stack over project.json changes, with grouped drag operations.
- **Playback of cuts:** v1 hops between segments (a seek at each boundary, slight hitch possible). Later, a background-rendered low-res edited proxy gives seamless playback, cached by edit hash.
- **Speed clips:** browser playback uses playback rate with pitch preserved; export uses ffmpeg time-scaling (setpts and atempo).
- **Playback past the footage (M8-2):** freeze frames and the time after the last footage clip run on a clock (the video is paused on the frame, or hidden).
- **Scalability hooks:** the clip list supports multiple tracks, and each clip has an `effects` list drawn from a registry. Adding zoom, freeze, or text means registering a new effect type with (a) its parameters, (b) its ffmpeg filter builder, (c) its preview applicator. The editor and export loop do not change.

## 10. Export pipeline

The export screen (section 4.3) starts an export on a background thread; one runs at a time. While it runs, voice generation is refused, and an export does not start while a voice job is queued or running (rule 7). "Unload the voice model first" queues the unload job and waits for it. A test export can stop after the first N seconds.

1. **Pre-flight:** errors block the export: no clips, a missing footage or take file, an imported audio file missing from `audio/` (M8-1), the recording or image of a visible video-lane clip missing (M8-2), an unusable voice chain, an unknown clip effect, ffmpeg or NVENC not working. Warnings need a confirmation ("Export anyway"): a placed line with no take, orphaned placements, keys or reactions, overflow that is not allowed, no usable avatar art, art fallbacks. Each issue can carry a timeline time.
2. **Voice tracks:** every playing placement is placed at its timeline start and overlaps are summed. `voice_processed.wav` uses the processed takes; `voice_raw.wav` uses the raw takes with the same cut, silence trim and stretch but no EQ, compressor, effects or loudness, so the two line up. Both are mono 32-bit float at the takes' rate, as long as the timeline. `lines/` holds one processed file per playing placement (`001_01-05_hello-there.wav`).
2b. **Audio clips (M8-1):** every heard audio clip is cut from its decoded WAV (M8-4: from its FX render when it has FX; pre-flight renders them and reports a failure as an error), given its level and fades (section 7) and summed at its timeline start into `audio_clips.wav`, stereo 32-bit float at 48 kHz, as long as the timeline. Not written when no clip is heard.
3. **Edit graph:** one ffmpeg filter graph from the clip list. Each clip is its own input with input seeking; per clip: speed, the output frame rate, scale into 16:9 with black bars, clip effects from the registry, then padded or cut to exactly its frame count. Game audio keeps its pitch at any speed (`atempo`) and is cut to exactly its sample count; a source with no audio gives silence. A freeze frame reads one frame, clones it to its length and is silent. Totals equal the timeline, so cuts never drift. **Timeline length (M8-2):** the export runs to the last of the footage, the audio clips and the video-lane clips; the edit is padded with black frames and silence up to it, and the voice track, audio clips and avatar run to it too.
3b. **Video lanes (M8-2, `backend/export/lanes.py`):** each visible lane clip is its own input (an image looped, a recording with input seeking, a freeze frame read for one frame), fitted into the frame with the same maths as the preview (`pip_rect` = `pipRect`), opacity applied, shifted to its first output frame and overlaid over its own frames only. Order: the edited footage, the lanes under the avatar (bottom first), the avatar, the lanes over it. A recording's own sound (not muted, not a freeze frame) is delayed to its start at its level and joins the mix before the limiter. Hidden lanes are left out. **Keyed image clips (keyframes task):** Python works out the clip's size, opacity and position for every output frame (the preview's evaluation) and gives them to ffmpeg as per-frame `sendcmd` commands to `scale`, `colorchannelmixer` and `crop` in the clip's own chain; the picture is padded with a transparent border and a frame-sized window is cropped out of it, then overlaid at 0, 0 (commands sent to `overlay` arrive out of step with its frames, so the position never goes there). A real-render test checks every frame.
4. **Final render:** one ffmpeg run (NVENC). Inputs: the avatar frames as raw RGBA from the Python compositor on a pipe at the track's 30 fps, the voice track, the clips. The edited video and game audio are split: one copy is encoded as `video_edited.mp4` (footage audio at its own level); the other gets the avatar overlaid (each avatar frame shows until the next starts: frame `floor(t * 30)`, as in the preview) and the mix: game audio at the project's level plus the voice on both channels plus `audio_clips.wav` (an extra input when it exists) plus the video-lane clips' sound (M8-2), summed without normalising, limited at -1 dBFS. When the overlay is asked for, the avatar stream is also written as the PNG sequence in the same run. Output: 1080p at the footage's frame rate, H.264 (`h264_nvenc`, `-cq 21`), AAC 192k.
5. **Bundle** (a dated folder `YYYY-MM-DD HHMM` in the project's `exports`, or in a chosen folder):
   - `final_1080p.mp4`, `video_edited.mp4`
   - `voice_raw.wav`, `voice_processed.wav`, and `lines/`
   - `audio_clips.wav` (M8-1, when audio clips are heard)
   - `video_raw/`: NTFS hard links to the recordings the timeline uses (no extra disk), or `LINKS.txt` with their paths when a link is impossible (another drive)
   - `avatar_overlay/` (optional): transparent 1920x1080 PNGs, one per avatar frame at 30 fps, plus a README (DaVinci Resolve reads the folder as one clip)
   - `project.json` snapshot, `export.json` (settings, ffmpeg version, counts, time per step, the audio clips with the imported files they use, and the video-lane clips drawn and with sound), `export_ffmpeg.log`, `export_graph.txt`

Progress is polled (`GET /api/export/status`: stage, fraction, elapsed time and time left), with cancel. A cancelled or failed export's folder is renamed with " (incomplete)"; nothing is deleted. Footage is only read. Export speed depends on the GPU's video encoder being free: other recording or streaming programs slow it down.

## 11. Architecture

**Processes**
- **Shell:** pywebview window loading the local backend URL.
- **Backend:** FastAPI with uvicorn on 127.0.0.1. The UI polls for job progress and status (voice jobs, processing, export); there is no WebSocket.
- **GPU worker:** separate process holding Chatterbox, with a job queue and cancel.
- **Background threads in the backend:** processed-take renders (prefetch), envelopes, the export (which runs ffmpeg as a subprocess and draws the avatar on a few threads).
- **Media server:** HTTP range requests for footage and audio so seeking is smooth.

**Frontend:** Svelte + TypeScript with Vite, built to static files and bundled (no Node needed at runtime). The timeline is a custom canvas component.

**Bundled binaries:** ffmpeg and ffprobe with NVENC in `bin/`, from a pinned release-branch build (BtbN GPL 8.1.x). Do not use `master` or 9.0 builds: they need NVENC API 13.1 (driver 610+) and fail on older drivers (verified on driver 581.42).

**Python dependencies:** torch (CUDA), chatterbox-tts, pedalboard, pyloudnorm, numpy, soundfile, Pillow, fastapi, uvicorn, pydantic, pywebview.

**Persistence:** `project.json` is the single source of truth with atomic writes (temp then replace), autosave on change, and a rotating backup. A `schema_version` field supports migrations. The per-user recent-projects list lives at `%APPDATA%\PNGtuberStudio\recent.json`, outside any project.

**Packaging (M7):** `install.bat` runs `scripts\install\install.ps1`: it checks for an NVIDIA GPU with driver 570 or newer (stops with a message otherwise), puts a pinned portable uv in `tools\uv\` and a pinned portable Node in `tools\node\` (SHA-256 checked, no admin rights, no PATH changes), runs `uv sync --frozen` (Python 3.11, CUDA torch from `uv.lock`), builds the frontend, downloads the pinned ffmpeg 8.1 build into `bin\`, checks CUDA and NVENC, and writes `run.bat` and a desktop shortcut. It skips finished steps and logs to `install.log`. The voice model is not downloaded by the installer: the app's first-run page downloads the pinned Chatterbox revision into the Hugging Face cache, and the GPU worker then always runs offline (`HF_HUB_OFFLINE=1`). The app is GPL-3.0-or-later (Pedalboard is GPL); third-party notices are in `THIRD_PARTY_NOTICES.md`. A single exe is deferred because CUDA torch makes it a multi-gigabyte build.

**Per-user data** in `%APPDATA%\PNGtuberStudio\`: `recent.json`, `worker.log`, `emotion_presets.json` (edited presets), `templates\` (saved channel templates).

**Errors:** file errors the user can fix (disk full, a file open in another program, access denied) are turned into plain sentences (`backend/oserrors.py`); every message says what to do next.

## 12. Open items

- Voice source: own voice or acted character.
- Effects slot contents: which effects first (reverb, pitch shift, chorus, others).
- Avatar art naming: resolved in M5 (section 8).
- Avatar tuning is by eye: mouth thresholds, blink gaps, bounce spring, reaction curves, the default position (x 0.85, y 0.75) and size (0.6 of the frame height).
- Mouth timing against the sound: if the mouth looks early or late in the preview (Web Audio output latency), add a fixed offset setting.
- Recording frame rate: resolved in M0. OBS recordings are 2560x1440 at 60 fps (H.264, one mixed stereo AAC track).
- Emotion preset numbers are guesses to tune in M3.
