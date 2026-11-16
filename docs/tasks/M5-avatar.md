# M5: Avatar (manual take trim first, then art, envelopes, solver, lanes, preview)

> Written 2026-11-16 by the M4 wrap-up chat from `IMPLEMENTATION_PLAN.md` (M5-1 to M5-8), `docs/DESIGN_SPEC.md` sections 4.2, 5 and 8 (as pasted by the user), `PROJECT_STATE.md` and the user's real art folder. The plan wins where this file and it disagree. The decisions below are my recommendations: chat A settles them with the user and logs the result in `PROJECT_STATE.md`. Nothing here has been built or run.

- **Milestone items:** M5-1 to M5-8 in `IMPLEMENTATION_PLAN.md`, plus one new item, **M5-0 Manual take trim** (add it to the plan under M5; the user asked for it first because generated takes sometimes have artefacts at the start or end that the automatic silence trim cannot remove).
- **Spec sections:** 4.2 (preview canvas, lanes, hotkeys E and R, status bar), 5 (`Take`, `Keyframe`, `Reaction`, `AvatarSettings`, anchoring rule, folder layout), 7 (processing order, for the trim), 8 (avatar system), 10 (export reuses the solver; M6-4, not built here), 12 (open items).
- **Status:** not started. Branch `m5-avatar`, created after `m4-done` is merged.

## Plan items

- **M5-0** Manual take trim: per-take start and end cut points, applied before the automatic silence trim, undoable, with a trimmer in the take picker (new)
- M5-1 Art loader and validator (folder per expression, state in the file name), fallback with a warning
- M5-2 Envelope extraction per take (about 100 Hz), cached
- M5-3 Solver core: expression, mouth (hysteresis, minimum hold), seeded blink
- M5-4 Solver: bounce, idle float, reactions (shake, hop, pop-in, squish), transform lanes
- M5-5 Generic lane system (keyframes, hold and smooth interpolation) shared with the timeline UI
- M5-6 Canvas renderer in the preview with drag and resize writing keyframes
- M5-7 Expression, parameter and reaction lane UI; optional auto-key from the line emotion
- M5-8 Solver tests: determinism, seek accuracy, hysteresis

**Done when (from the plan):** the live preview looks right and scrubbing to any frame always shows the same state. **Also (M5-0):** trimming a take in the picker changes what plays and the block length within about a second, uses no GPU, and never touches the raw file.

## Goal

The avatar, drawn over the footage, follows the voice: the mouth opens and closes with the loudness of the placed lines, the eyes blink, the expression follows an expression lane, and the avatar bounces, floats and reacts, all computed by one pure Python solver so the preview and the later export show the same frame. Before that, any take can be cut at both ends by hand so generation artefacts never reach the mix.

## How this task runs

Same method as M0 to M4 (see `CLAUDE.md`). Six fresh chats, each getting `CLAUDE.md`, the updated `PROJECT_STATE.md`, this file, `docs/API_MODELS.md`, and only the spec parts and files listed. The user pastes spec parts when asked.

| Chat | Steps (plan items) | Paste these spec parts | Paste these source files |
|---|---|---|---|
| A | S1 decisions; S2 trim pure modules; S3 trim backend (M5-0) | 5, 7, 12 | `schema.py`, `migrations.py`, `voice/takes.py`, `voice/keys.py`, `audio/trim.py`, `audio/chainspec.py`, `audio/processed.py`, `audio/render.py`, `project/line_ops.py`, `project/line_commands.py`, `templates/default_channel.json` |
| B | S4 trim UI (M5-0); S5 art loader (M5-1) | 8, 4.2 (preview), 12 | `LineBank.svelte`, `Editor.svelte` (tab and `syncHistory` pattern), `api.ts`, `voice.ts`, `project/template.py`, `project/summary.py`, `app.py` (media routes), `templates/emotion_presets.json`, `voice/presets.py` |
| C | S6 envelopes (M5-2); S7 solver core (M5-3); S8 solver motion (M5-4); the solver tests (M5-8) | 8, 5 (`Keyframe`, `Reaction`, anchoring rule) | `edl/timemap.py`, `edl/anchoring.py`, `project/timeline.py` (models only), `audio/processed.py`, `voice/peaks.py` (pattern for a per-take cache) |
| D | S9 lane and keyframe backend (M5-5 backend); S10a frame track API and preview sprite cache | 5, 8, 4.2 | `project/commands.py`, `edit_ops.py`, `parking.py`, `placement_commands.py`, `session.py`, `app.py`, `schema.py` |
| E | S10b canvas renderer (M5-6); S11 lane UI (M5-7) | 4.2, 8 | `Player.svelte`, `Timeline.svelte`, `timeline.ts`, `Editor.svelte`, `api.ts`, `format.ts` |
| F | S12 wrap-up, merge, tag `m5-done` | none | `PROJECT_STATE.md`, this file |

Chats B to E may ask for more slices with PowerShell commands as usual; the lists above are starting points.

## Prerequisites (user does these first)

- [ ] M4 merged to `main` and tagged `m4-done`; `uv run pytest`, `uv run ruff check .`, `npm run check`, `npm test` and `npm run build` pass on `main`
- [ ] **`avatars/` is not committed.** The art (about 900 KB per image, 4 per expression, 10 expressions) must be in `.gitignore` (rule 9). Check with `git status` and `git check-ignore -v "avatars/nanairo miku/01_smile/01a_smile_oicm.png"`; if it is not ignored, add `avatars/` to `.gitignore` before anything else.
- [ ] List all expression folders and send them to chat A: `Get-ChildItem "avatars\nanairo miku" -Directory | Select-Object -ExpandProperty Name`
- [ ] Say which of those expressions should stand for each emotion preset (the five presets in `templates/emotion_presets.json` each name a default avatar expression, which may not match your folder names); chat A needs the five preset names and their `expression` values: `Get-Content templates\emotion_presets.json -Raw`
- [ ] The test project from M4 with several placed lines; a few of the lines should be ones with artefacts at the start or end, for the trim checks
- [ ] A listening setup you trust (headphones), for the trim and the mouth timing

## Scope

**In:** M5-0 to M5-8. Manual take trim with the trimmer UI. Art loader and validator, avatar settings and folder picker, envelopes, the solver (expression, mouth, blink, bounce, idle float, reactions, transform), keyframe and reaction commands, the lane UI, the preview canvas with drag and resize, auto-key from the line emotion, solver tests.

**Out:** the Python compositor and the avatar in the export (M6-4, which will reuse the solver functions from this milestone); the transparent overlay export (M6-6); Rhubarb or any mouth provider other than the loudness envelope (rule 12); more than two mouth states (the art has only open and closed); per-emotion reference clips; a keyframeable game audio lane (backlog); a global library UI for several avatars beyond choosing a folder (the data model leaves room).

## Facts already established (do not re-ask)

- **User's art (real files):** `avatars/nanairo miku/` (in the repo folder, to be gitignored), one subfolder per expression named `NN_name` (`01_smile`, `02_cheeky`, `03_confident`, up to `10_...`), each holding four PNGs named `NNx_name_EEMM.png`: `01a_smile_oicm.png`, `01b_smile_oiom.png`, `01c_smile_cicm.png`, `01d_smile_ciom.png`. `oi` open eyes, `ci` closed eyes, `om` open mouth, `cm` closed mouth. **All expressions have all four states. All images are the same canvas, 1179x2095 pixels** (portrait, one full-frame sprite per state, so every sprite shares one origin). About 900 KB each. This replaces the spec's convention `expression_eyes_mouth.png` (spec 8, open item in spec 12): the spec text must be updated.
- **Decoded size matters:** one sprite is about 9.9 MB as a decoded RGBA bitmap, so all 40 decoded at full size would be about 400 MB in the browser. The preview must use downscaled sprites (decision 6).
- **Schema (version 2 now):** `Project` already has `keyframes`, `reactions`, `avatar` (`AvatarSettings`: `art_folder` null, `x` 0.85, `y` 0.75, `scale` 1.0, `rotation_deg` 0.0, `auto_key_expression` true), `seed`. `Keyframe`: id, lane id, anchor (clip id, source_ms), value (number or expression name), interpolation (hold or smooth), orphaned. `Reaction`: id, type, anchor, intensity, duration_ms, orphaned. **No M4 schema change.** `Take` has no trim fields yet.
- **Folder layout (spec 5):** `media/envelopes/` exists for the per-take mouth envelopes.
- **Code to reuse:** `backend/audio/trim.py` (`find_speech_bounds` with -45 dBFS, 10 ms frames, 40 ms before, 80 ms after; `TrimBounds`; length functions `trimmed_duration_ms`, `processed_duration_ms`; the `<raw stem>.trim.json` sidecar, per raw take, invalidated when the take or the trim settings change), `backend/audio/processed.py` (`processed_path`, `ensure_processed`, `trim_bounds_for`, `TrimCache`), `backend/audio/chainspec.py`, `backend/voice/keys.py` (`processed_key`, floats rounded to 4 decimals), `backend/edl/timemap.py` and `anchoring.py` (anchor to timeline time), `backend/project/parking.py` and the M2 "Anchoring and parking API" (orphans), `backend/voice/peaks.py` (the pattern for a derived per-take cache and endpoint), `GET /api/takes/{id}/peaks` and `getTakePeaks` (waveform of the raw take), the `onedited` and `syncHistory()` pattern in `Editor.svelte` (M4: refresh `timeline` after an edit made elsewhere), `AudioGraph` and `VoicePlayback` (M4), `Player.svelte` (video element), `Timeline.svelte` (canvas lanes).
- **Rules in `CLAUDE.md` that bite here:** 1 (takes are never modified or deleted; a trim is metadata), 3 (cache keys: the manual trim must be in the processed key), 4 (anchoring: keyframes and reactions anchor to footage; orphans are flagged, never dropped), 5 (the solver is the single source of truth; renderers only draw; pure function of (project state, time); seeded), 6 (schema bump needs a migration), 8, 11 (every edit undoable), 12 (mouth from the loudness envelope), 13 (registry pattern: reactions can follow it), 14.

## Decisions to settle in chat A (recommendations, not final)

### Part 1: manual take trim (M5-0)

1. **Data.** `Take.trim_start_ms: int | None` and `Take.trim_end_ms: int | None` (cut points in **raw take time**; `None` means no manual cut on that side; start less than end, both inside the take, at least about 200 ms kept). Schema version 3 with a registered migration `2: _v2_to_v3` adding both as `None` to every take (rule 6). The raw file is never touched (rule 1).
2. **Order.** The manual cut is the outermost step: the kept region of the raw take is what everything downstream sees. The automatic silence trim then measures **inside** that region (so a loud click just inside the cut is the user's call, and quiet audio outside the cut is gone). Then stretch, EQ and the rest, unchanged. A region with nothing loud is kept whole (the existing `silent` behaviour).
3. **Edge fades.** A cut can land on a non-zero sample and click. Apply a short fade (proposal 8 ms, raised cosine) at each manual cut edge only, before EQ. It is part of the processing spec, so bump `processing_version` (every processed take is rendered again once: CPU only, accepted).
4. **Cache key.** The processed key includes the manual cut points (the raw key does not; rule 3). The `<raw stem>.trim.json` sidecar is valid only for the same cut points (store them in it, or measure again when they differ). Changing a trim changes only that take's processed file; the old file is cleaned up by the existing clean-up.
5. **Lengths.** `trimmed_duration_ms` and `processed_duration_ms` use the manual region, so the block length, overflow and Tighten maths in the timeline follow automatically. Existing placed blocks of a trimmed take shift where the speech now starts, as they did when the automatic trim arrived (say so in the release note).
6. **Command.** A new line-bank op `set_take_trim` (take id, start or `None`, end or `None`) through the existing line edit path, one undo step per committed trim, undo and redo restore it (rule 11). After it the editor refreshes the timeline (`syncHistory()`), which also changes the processed key and so the audio that plays.
7. **UI.** In the take picker (Line bank), a Trim button on a take opens a small trimmer: the raw waveform (existing peaks endpoint), two draggable handles, millisecond fields, a shaded area for what the automatic trim also removes, Reset, and Play that plays the processed result through the normal processed route after Apply (rule 5: no separate preview renderer). Apply commits.
8. **Out of the trimmer.** No fades editing, no inner cuts, no time editing of the raw file, no automatic detection beyond what exists.

### Part 2: avatar

1. **Art convention (replaces the spec text).** One folder per expression `NN_name`, files `NNx_name_EEMM.png`. Parse each file name with `^(\d{2})([a-z])_(.+)_(oi|ci)(om|cm)\.png$`; the expression id is the folder name without the number prefix (`smile`), the order is the number, the state is (eyes, mouth) from the suffix, the letter `a` to `d` is ignored. A file whose name part does not match its folder, an unknown suffix, or a duplicate state is a warning, not a crash. Case-insensitive on Windows paths, spaces allowed (`nanairo miku`).
2. **Where the art lives and how a project points to it.** In a shared `avatars/<avatar name>/` folder (so several avatars can coexist; gitignored), referenced from the project by `AvatarSettings.art_folder`. Because the art is not inside the project folder, store it like the template's `external` sources: an absolute POSIX path (rule 2: never copied or modified; documented in spec 5), shown as a problem in the project summary when the folder is missing. The channel template carries the default. A native folder picker sets it (`pickFolder` exists). Alternative to weigh: copy the art into the project (about 36 MB per project, portable, but duplicates); not recommended.
3. **Optional `avatar.json` inside the art folder.** `default_expression` (the expression used when nothing else says; default: the first by number), `emotion_map` (emotion preset name to expression id; overrides the preset's own `expression`). It belongs with the art so it follows the avatar to other projects (spec 4.4 "avatar art mapping"). Not required: with none, the preset's expression name is used and an expression the art lacks falls back to the default expression with a warning.
4. **Validation and fallback.** The loader checks every expression for the four states. A missing state falls back to the same expression with the nearest state (closed-eyes to open-eyes, open-mouth to closed-mouth), then to the default expression, and says so in a warning list. An expression named by a keyframe or a preset that does not exist falls back the same way. Pure parser and mapper (no file access) plus a thin scanner; tests use a temporary tree.
5. **Frame placement.** Sprites are full-frame portrait canvases (1179x2095), so position, scale and rotation apply to the whole sprite about one anchor. Proposal: anchor at the sprite's bottom centre; `x` and `y` are fractions of the frame (the bottom centre sits at x, y); `scale` 1.0 means the sprite's height equals a fixed fraction of the frame height (a named constant, tuned with a mock frame, since a native 2095 px sprite is far taller than a 1080p frame). The template defaults (x 0.85, y 0.75, scale 1.0) were guesses and will be retuned.
6. **Preview sprites.** The browser never loads the full-size PNGs. The backend makes downscaled copies on demand (proposal: height about 1000 px) into a re-creatable cache (`media/avatar_preview/`, key = file hash and size, cleaned like `takes_fx`), served by a route that only serves files the loader found (no path from the URL). Only the current expression's four sprites are decoded at once, others on demand. The export compositor (M6) uses the originals.
7. **Envelope.** About 100 Hz (10 ms hop, 20 ms window RMS in dBFS) of the **processed** take (what plays; the take is already loudness-normalised, so one absolute threshold range works), stored under `media/envelopes/` keyed by the processed key (a chain, stretch or trim change re-keys it; rule 3). Pure maths plus a cache like the peaks endpoint; CPU only; computed lazily and prefetched for placed takes.
8. **Solver is a pure function of the timeline time.** Inputs: avatar settings, the lane keyframes mapped to timeline time (anchoring), reactions mapped the same way, the placements with their envelopes (placed on the timeline), the project seed. Output per time `t`: sprite (expression, eyes, mouth), x, y, scale, rotation. To keep it a pure function of `t` despite hysteresis, minimum hold, blink and bounce being stateful: precompute per input version (a hash of everything that matters) the **mouth segments** (open and closed intervals from the envelope with hysteresis and minimum hold of 60 to 80 ms), the **blink times** (seeded intervals, about 120 ms closed, scaled by the blink-rate lane) and the **bounce track** (spring response to the envelope, sampled), then answer `query(t)` by lookup and interpolation. A test proves `query(t)` in any order equals stepping forward (seek accuracy).
9. **Mouth sensitivity.** The sensitivity lane scales the open and close thresholds. Proposal for the starting thresholds (dBFS, guesses to tune by eye): open about -32, close about -38; sensitivity multiplies in dB. No intermediate mouth shapes exist in the art.
10. **Reactions.** Registered in a reaction registry like clip effects (rule 13): `shake` (damped oscillation), `hop`, `pop-in` (scale with overshoot), `squish`; each a closed-form offset of (x, y, scale, rotation) over `duration_ms` scaled by `intensity`. Anchored like keyframes.
11. **Lanes.** Ten lanes with fixed ids, ranges and defaults: `expression` (enum, hold), `bounce`, `float_amp`, `float_speed`, `blink_rate`, `mouth_sensitivity`, `scale`, `x`, `y`, `rotation` (numbers, hold or smooth). The base values come from `AvatarSettings` (x, y, scale, rotation) and lane defaults (a small dict in `AvatarSettings`; schema version 4 with a migration if added). Pure lane evaluation in Python (hold, smooth); the UI asks the backend for the sampled curve to draw instead of reimplementing it, unless chat E finds that too slow (then a TypeScript copy is tested against shared fixtures).
12. **Auto-key.** With `auto_key_expression` on, each placement start gives a virtual expression key from the line's emotion (mapped as in decision 3). The expression at `t` is the latest key at or before `t`, manual or virtual; at the same time a manual key wins. Nothing is written to `project.json` for virtual keys. Toggle in the avatar settings.
13. **How the preview gets solver output.** The solver stays in Python (rule 5). The backend serves a sampled **frame track** for the timeline at the preview frame rate (proposal 30 fps, quantised numbers, run-length sprite changes) keyed by an `avatar_version` hash, rebuilt after any edit that changes it (debounced); the browser canvas draws the nearest sample for the video playhead and never computes motion. While dragging the avatar the canvas shows the dragged pose locally; the commit writes keyframes and refreshes the track. The export (M6) calls the same solver at the export frame rate.
14. **Drag and resize.** Dragging writes `x` and `y` keyframes at the playhead, resizing writes `scale`, one undo step per gesture (grouped, as for clip drags). Interpolation for new transform keys: smooth (proposal); expression keys are always hold.
15. **Commands.** `AddKeyframe`, `MoveKeyframe`, `SetKeyframeValue`, `SetKeyframeInterpolation`, `RemoveKeyframe`, `AddReaction`, `MoveReaction`, `SetReaction` (intensity, duration, type), `RemoveReaction`, `SetAvatarSettings`; all undoable, anchored by (clip id, source_ms), orphaned and parked through the existing anchoring and parking code when a cut removes the footage (rule 4). Hotkeys from the spec: `E` adds an expression key at the playhead, `R` drops a reaction.
16. **Audio and picture alignment.** The mouth follows the video playhead. The M4 playback routes the footage through Web Audio, which may delay sound against picture by the output latency; if the mouth then looks early or late, add a fixed offset setting later (not in M5).

## Steps

Each step ends with what to paste back and a commit point (`git status`, `git add`, `git commit -m "M5-n: ..."`).

1. **S1 Decisions (chat A).** Settle and log the decisions above (the user answers the questions in "Prerequisites" first); create branch `m5-avatar`; add M5-0 to `IMPLEMENTATION_PLAN.md`.
2. **S2 Trim pure modules (chat A; M5-0).** Extend `audio/trim.py` for a manual region (clamp, validate, measure inside it, sidecar with the cut points), the fade length and the processing spec entry, `processed_key` with the cut points, length functions on the manual region; tests (`pytest tests/test_audio_trim.py` and the key tests).
3. **S3 Trim backend (chat A; M5-0).** `Take` fields, schema 3 and migration, `set_take_trim` op, processed render applies the cut and the fades, `trim_bounds_for` and `build_timeline` use it, the take list returns the fields, clean-up still correct; tests; run the whole `pytest`.
4. **S4 Trim UI (chat B; M5-0).** The trimmer in the take picker, Apply, Reset, timeline refresh after the edit, undo and redo; manual checks with a take that has an artefact. Tick M5-0.
5. **S5 Art loader (chat B; M5-1).** Pure parser, mapper and fallback; scanner; `AvatarSettings.art_folder` set from a folder picker; `GET /api/avatar` (expressions, states, warnings); project summary shows the real avatar status; `avatar.json` support; tests on a temporary tree and a check against the user's real folder.
6. **S6 Envelopes (chat C; M5-2).** Pure envelope maths, cache under `media/envelopes/`, endpoint and prefetch; tests with synthetic signals.
7. **S7 Solver core (chat C; M5-3).** Expression, mouth segments with hysteresis and minimum hold, seeded blink; `query(t)`; tests.
8. **S8 Solver motion (chat C; M5-4, M5-8).** Bounce, idle float, reactions, transform lanes; determinism, seek accuracy and hysteresis tests. Tick M5-3, M5-4, M5-8 when the user's `pytest` passes.
9. **S9 Lanes and commands (chat D; M5-5).** Keyframe and reaction commands, lane definitions and evaluation, anchoring and orphaning tests, `SetAvatarSettings`, auto-key virtual keys.
10. **S10a Frame track and preview sprites (chat D; M5-6 backend).** The sampled frame track endpoint with `avatar_version`, the downscaled sprite cache and route.
11. **S10b Canvas renderer (chat E; M5-6).** Overlay canvas in `Player.svelte`, nearest-sample drawing, sprite loading on demand, drag and resize writing keyframes in one undo step.
12. **S11 Lane UI (chat E; M5-5 UI, M5-7).** Expression, parameter and reaction lanes in `Timeline.svelte` (collapsible parameter lanes), keyframe selection and Inspector, hotkeys `E` and `R`, auto-key toggle. Tick M5-5, M5-6, M5-7.
13. **S12 Wrap-up (chat F).** End-of-task checklist from `CLAUDE.md`: complete `PROJECT_STATE.md`, plan ticks, replacement text for the spec sections that changed (section 8 art convention, section 5 `Take` row and the avatar path rule, section 7 processing order, section 12 open items), commit message, merge to `main`, tag `m5-done`.

## Acceptance checks (user runs these)

- Trim: a take with an artefact at the start or end is cut in the trimmer; Play after Apply has no artefact and no click at the cut; the block on the timeline becomes shorter; undo restores the old length and sound; the raw WAV in `media/takes_raw/` is byte-identical (rule 1); `uv run pytest` and `uv run ruff check .` pass; the old projects open (migration).
- Art: the project screen shows `nanairo miku` with ten expressions and no warnings; removing one PNG makes a warning and a fallback, not a crash.
- Preview: the avatar draws over the video at the template position; the mouth follows a placed line; blinks happen at believable intervals; pressing `E` adds an expression key and the expression changes at that time; `R` drops a reaction that plays once; dragging moves the avatar and one Ctrl+Z undoes the whole drag.
- Scrubbing to the same time twice, and playing then scrubbing back, show the same frame (the plan's "done when").
- A cut that removes footage under a keyframe or reaction flags it as orphaned instead of deleting it.

## Risks and open points

- **Memory:** full-size sprites would take about 400 MB decoded; the downscaled preview cache is required, not optional.
- **Portrait sprite on a landscape frame:** scale and anchor semantics (decision 5) need a mock frame with the user's art early, before the renderer is built on them.
- **Preview latency:** the frame track is rebuilt after edits; a dragged avatar must not wait for it (decision 13).
- **Mouth thresholds, blink timing, reaction curves and bounce spring are all guesses** to tune by eye; keep them as named constants in one module.
- **Schema bumps:** version 3 (trim) lands in S3 and version 4 (lane defaults, if needed) in S9; each needs a migration and a test that old projects load.
- **Art path portability:** an absolute `art_folder` breaks if a project is moved to another machine, like template bookends; the project summary must say so clearly.
