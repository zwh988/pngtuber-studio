# M4: Audio chain (processed takes, Voice FX tab, game audio and mix, loudness meter)

> Reconciled with `IMPLEMENTATION_PLAN.md` (M4-1 to M4-4) and `docs/DESIGN_SPEC.md` (sections 2, 4.2, 5, 6, 7, 10, 11, 12) on 2026-10-27, after M3 chat F. The plan wins where this file and it disagree. The decisions below are my recommendations: chat A settles them with the user and logs them in `PROJECT_STATE.md`.

- **Milestone items:** M4-1 to M4-4 in `IMPLEMENTATION_PLAN.md` (listed below).
- **Spec sections:** 7 (audio chain), 4.2 (Voice FX tab, status bar loudness meter, game audio level lane), 5 (`FxChain`, `Take`, `Placement`, folder layout), 6 (overflow uses the *processed* duration), 10 (export plays the same processed files), 11 (CPU worker pool, media server), 12 (open item: effects slot contents).
- **Status:** not started. Branch `m4-audio`, created after `m3-done` is merged.

## Plan items

- M4-1 Processing pipeline: trim silence, EQ, compressor, effects, loudness normalize; cached by raw key + FX hash
- M4-2 Voice FX tab UI with presets
- M4-3 Game audio level slider and mix model (voice bus + game audio + master limiter) for preview
- M4-4 Loudness meter in the status bar

**Done when (from the plan):** moving a slider changes the audible result within about a second and uses no GPU.

## Goal

Every placed line plays as its *processed take*: raw take, optional Tighten stretch, silence trimmed, EQ, compressor, effects, normalised to the channel's loudness target. The chain lives in the project (copied from the channel template) and is edited in the Voice FX tab. The editor mixes processed voice with the footage's game audio at a fixed dB level through a master limiter and shows the loudness of that mix in the status bar. Processing is CPU only, cached by key, never touches raw takes (rule 1), and never repeats for an existing key (rule 3). What the editor plays is what export will write (spec 7, rule 5).

## How this task runs

Same method as M0 to M3 (see `CLAUDE.md`). Four fresh chats, each getting `CLAUDE.md`, the updated `PROJECT_STATE.md`, this file, `docs/API_MODELS.md`, and only the spec parts and files listed:

| Chat | Steps (plan items) | Paste these spec parts | Paste these source files |
|---|---|---|---|
| A | S1 decisions; S2 pure modules (M4-1 logic, M4-2 presets file and loader) | 7, 5 (`FxChain`, folder layout), 12 | `schema.py`, `backend/voice/keys.py`, `stretch.py`, `stretchrender.py`, `templates/default_channel.json`, `backend/voice/presets.py` (to copy the loader pattern) |
| B | S3 backend (M4-1 render, cache, serving, `SetFxChain`, processed durations in the timeline state, prefetch) | 7, 6 "Too-long line detection", 11 | `session.py`, `app.py`, `edit_ops.py`, `commands.py`, `timeline.py`, `overflow.py`, `takestore.py`, `takes.py`, `stretchrender.py` |
| C | S4 UI (M4-2 Voice FX tab, audition, presets; game audio slider control) | 4.2 | `Editor.svelte`, `api.ts`, `LineBank.svelte` (for the tab and `onedited` pattern) |
| D | S5 mix model and playback (M4-3, M4-4, playback swap), wrap-up | 7 "Mix", 4.2 status bar | `voicePlayback.ts`, `Player.svelte`, `Editor.svelte`, `stretch.ts`, `api.ts` |

## Prerequisites (user does these first)

- [ ] M3 merged to `main`, tagged `m3-done`; `uv run pytest`, `uv run ruff check .`, `npm run check` pass on `main`
- [ ] `uv add pyloudnorm` (Pedalboard is already in `pyproject.toml` as `pedalboard>=0.9.26`; `pyloudnorm` is not yet); check `uv run python -c "import pedalboard, pyloudnorm"`
- [ ] The test project from M3 with several placed lines, some tightened
- [ ] A listening setup you trust (headphones), since the assistant cannot hear anything

## Scope

**In:** all four plan items. Silence trimming, 3-band EQ, optional compressor, an effects slot with a registry, loudness normalisation with a peak limiter; processed-take cache and serving; `SetFxChain` as an undoable command; processed durations in the timeline state (overflow, blocks and Tighten use them); built-in FX presets; the Voice FX tab with audition; the game audio dB slider; the Web Audio mix (voice bus, game bus, master limiter) and the status bar loudness meter; pytest for every pure module and command, `ruff` and `npm run check` clean.

**Out:** avatar, envelopes, mouth, lanes (M5; the loudness envelope per take is M5-2, built from the processed take); voice tracks and the ffmpeg mix for export (M6-2, which will reuse the render function from this milestone); keyframeable game audio level (backlog); per-line FX overrides; user-saved FX presets (M7-4 "template save" territory; confirm with the user); A/B compare; network access (rule 8).

## Facts already established (do not re-ask)

- **Plan and spec:** processed take = cached by raw key plus FX chain (spec 7); the editor and export play the processed files; step 1 of the chain is trimming leading and trailing silence; the default loudness target is about -16 LUFS; mix = game audio at a fixed dB level plus the voice bus, summed with a master limiter; the meter shows live loudness of the mix; tooling is Pedalboard (EQ, compressor, effects) and pyloudnorm; ffmpeg filters are the fallback. Spec 6: an overflow is judged on the line's **processed** duration.
- **Schema (version 2):** `FxChain` has `eq_bass_db`, `eq_mid_db`, `eq_treble_db`, `compressor` (`enabled`, `threshold_db` -18, `ratio` 3, `attack_ms` 10, `release_ms` 100), `effects: list[EffectSpec]` (`type`, `params`), `loudness_target_lufs` (-16). `Project.fx_chain` and `Project.game_audio_db` (0.0) exist, copied from `templates/default_channel.json` at project creation. `Placement.stretch` (1.0 to 1.25) is per placement. **No schema change is planned**; any change needs migration `MIGRATIONS[2]`, a spec note and a decision-log row.
- **Folder layout (spec 5):** `media/takes_raw/` (kept), `media/takes_fx/` ("processed takes, re-creatable"), `media/envelopes/` (M5).
- **Code from M3:** `backend/voice/keys.py` (`raw_key`, SHA-256 of canonical JSON, floats rounded to 4 decimals); `backend/voice/stretch.py` (`stretched_duration_ms`, `fit_stretch`, `stretched_name`); `backend/voice/stretchrender.py` (`ensure_stretched`, Pedalboard `time_stretch`, atomic write, refuses a result more than about 5 percent off the expected length); `GET /media/take/{id}?stretch=1.083` renders `media/takes_fx/<stem>_x1083.wav` on first request; `TimelinePlacement.duration_ms` is the playing length and drives overflow, block width and Nudge; `VoicePlayback` caches decoded audio per (take, stretch) and plays through its own `AudioContext`; `Player.svelte` has one `<video>` element.
- **Pedalboard** `time_stretch` is confirmed in the app (shortens by the factor, pitch kept).
- **Status bar** (M3 chat D) shows model state, GPU queue, last job, takes size; the loudness meter slot was left for M4.
- Rules in `CLAUDE.md` that bite here: 1, 3, 5, 6, 8, 11, 13, 14. Rule 7 (one GPU job at a time) does not apply to CPU processing, but processing must never block the UI.

## Decisions to settle in chat A (recommendations, not final)

1. **Processed key.** `processed_key = sha256(raw_key, stretch, canonical FX chain, processing_version)` in `keys.py`, floats rounded to 4 decimals like `raw_key`. File: `media/takes_fx/<key16>.wav`. This extends rule 3 ("hash(raw key, FX chain)") with stretch and a version number; replacement text is in "Doc changes" below. The M3 stretch-only files (`<stem>_x1083.wav`) become unreferenced (the storage manager lists them) and are no longer served; no data migration.
2. **Order of processing.** raw take, stretch (if the placement has one), trim silence, EQ, compressor, effects, loudness normalise, peak limiter (ceiling about -1 dBFS) so normalising never clips. The FX then act on the audio that actually plays. Trimming after the stretch keeps the thresholds in real time.
3. **Silence trimming and lengths.** Spec 6 judges overflow on the processed duration, so trimming changes block length. Proposal: threshold about -45 dBFS on short frames, keep about 40 ms before and 80 ms after the speech (guesses, tune by ear). **Trim offsets depend only on the raw audio, the stretch and the constants**, not on the FX chain, so they are cached in a re-creatable sidecar `media/takes_fx/<raw stem>.trim.json` (per stretch value) and passed to `build_timeline` as a plain mapping, like `missing_source_ids`. Alternative: add `Take.trim_start_ms` and `trim_end_ms` (schema v3 plus a migration that cannot fill them without audio): not recommended.
4. **Where a placement starts.** After trimming, a block starts where the speech starts, so existing M3 placements shift earlier by the trimmed lead-in (about 0.1 to 0.5 s). Accepted, and said in the release note in `PROJECT_STATE.md`. The anchor (clip, source time) is unchanged.
5. **Length-changing effects.** Effects slot contents are an open spec item. Proposal for M4: `pitch_shift` and `chorus` (length preserving) registered in a voice-effect registry (params, Pedalboard builder, like clip effects, rule 13). **Reverb** only if chat A decides how its tail counts: either clipped to the trimmed length, or a fixed tail included in the processed duration. Without a decision, leave reverb out.
6. **Loudness.** pyloudnorm integrated LUFS of the processed signal before the limiter, one gain per processed take toward `loudness_target_lufs`, then the limiter. Takes under about 400 ms are too short for BS.1770 gating: use an RMS fallback and say so in the Voice FX tab.
7. **Chain edits.** `SetFxChain` replaces the whole `FxChain` in one command (one undo step per committed edit: on slider release or after about 250 ms of rest, not per tick). A chain change bumps a short `fx_version` (hash of the chain) in the timeline state so the browser drops its decoded audio.
8. **Rendering.** Lazily on the first request of `GET /media/take/{id}?processed=1&stretch=...` (uses the open project's chain, never a chain from the URL), plus a background prefetch of every placed take when the chain changes, newest chain first, on a small thread pool (Pedalboard and pyloudnorm release the GIL). A newer chain change cancels the queued older work. Takes the take picker auditions in the line bank stay raw.
9. **Audition in the Voice FX tab.** Plays a selected take through the *current* chain by asking for the processed file, the same path as playback (rule 5). No separate preview renderer.
10. **FX presets.** Built-in `templates/fx_presets.json` (name to `FxChain`) with a pure loader, like the emotion presets; the tab applies one as a `SetFxChain`. Starting set: Clean, Warm, Radio, Podcast (guesses, tune by ear). "Save as preset" is deferred (confirm).
11. **Mix model (M4-3).** One shared `AudioContext` owned by a new `audioGraph.ts`: game bus (the `<video>` element through `createMediaElementSource` and a `GainNode` set from `game_audio_db`, range about -30 to +6 dB), voice bus (`VoicePlayback` connects its sources here instead of `ctx.destination`), master limiter (a `DynamicsCompressorNode` tuned as a limiter; an approximation of the export's Pedalboard limiter, since each voice is already limited at -1 dBFS and the limiter should rarely act), then the meter, then `destination`. Risk to check by ear: routing the video's sound through Web Audio can shift audio-video sync a little. `Player.svelte` swaps `src` on one element, so one `MediaElementSource` is enough.
12. **Meter (M4-4).** K-weighted momentary loudness (400 ms) of the master bus computed in the browser: two `BiquadFilterNode`s (high-pass about 38 Hz, high shelf +4 dB at 1.5 kHz) into an `AnalyserNode`, mean square, `-0.691 + 10 log10(sum)`. A pure function for the maths, tested. An approximation for the preview; export measures with pyloudnorm.
13. **Game audio level storage.** `Project.game_audio_db` set through a `SetGameAudioDb` command (one undo step), shown as a slider in the Voice FX tab or next to the status bar meter (chat C decides with the user). The spec's "Game audio level" lane stays a fixed level (keyframes are backlog).

## Steps

Each step ends with what to paste back and a commit point (`git status`, `git add`, `git commit -m "M4-n: ..."`).

1. **S1 Decisions (chat A).** Settle and log the decisions above; create branch `m4-audio`.
2. **S2 Pure modules (chat A; M4-1 logic, M4-2 data).** `processed_key` (extend `keys.py`), silence detection on a float array (offsets only), chain to plugin-spec builder (a plain list of dicts; no Pedalboard import), loudness gain maths and the short-take fallback rule, voice-effect registry skeleton, `templates/fx_presets.json` and its loader, tests. *Paste back:* `uv run pytest`, `uv run ruff check .`.
3. **S3 Backend (chat B; M4-1).** (a) `uv add pyloudnorm`; render function (Pedalboard plus pyloudnorm, atomic write, lazy import, `StretchError`-style error class) and the cache; (b) serve processed audio, replace the stretch-only route behaviour, trim sidecar; (c) `SetFxChain` and `SetGameAudioDb` ops and endpoints, `fx_version` and processed durations in the timeline state, overflow on them; (d) prefetch on a thread pool. *Paste back:* pytest, and for one real take the processed file's length, measured LUFS and peak, and the time to render.
4. **S4 Voice FX tab (chat C; M4-2).** Tab with EQ sliders, compressor, effects list, loudness target, presets, audition, "processing N of M" state, undo and redo through the existing history buttons; game audio slider.
5. **S5 Mix, meter, playback (chat D; M4-3, M4-4).** `audioGraph.ts`, `VoicePlayback` on the voice bus and keyed by (take, stretch, `fx_version`), video through the game bus, limiter, meter in the status bar. Then the end-of-task checklist, merge, tag `m4-done`.

## Acceptance criteria

- [ ] `uv run pytest`, `uv run ruff check .` and `npm run check` are clean
- [ ] Moving an EQ or compressor slider changes the sound of the auditioned take, and then of every placed line, within about a second per take, and no GPU job runs (status bar queue stays empty, worker log unchanged)
- [ ] Every placed line measures within about 1 LU of the target on its processed file and none clips (the user pastes measured LUFS and peak for two or three takes)
- [ ] Silence at the start and end of a take is gone; block lengths follow the processed length; an overflow is judged on it; Tighten and Nudge still work
- [ ] The same inputs reuse the saved processed file (no re-render; visible by timing or log); raw take files are byte-identical before and after (rule 1)
- [ ] Undo and redo restore the previous chain and the previous sound
- [ ] The game audio slider changes the footage's level in the editor; voice and footage are mixed; no clipping when a loud line overlaps loud game audio
- [ ] The status bar meter moves with the mix and reads close to the target on a steady spoken line
- [ ] Video and voice stay in sync (checked by ear on a cut and after a seek)
- [ ] The editor stays responsive while files render; a newer chain change replaces queued older work
- [ ] Close, reopen, play everything with zero regeneration and no re-processing of unchanged inputs
- [ ] No network access at runtime (rule 8)
- [ ] `PROJECT_STATE.md` updated; M4-1 to M4-4 ticked in `IMPLEMENTATION_PLAN.md`; the doc changes below applied

## Doc changes to apply at the end of M4

- **`CLAUDE.md` rule 3**, replace the second sentence: "Raw take key = hash(text, voice profile id + reference clip hash, exaggeration, cfg_weight, seed, model version). Processed take key = hash(raw key, placement stretch, FX chain, processing version)."
- **`docs/DESIGN_SPEC.md` section 7**, after "cached by raw key plus FX chain": "and the placement's Tighten stretch (and a processing version number)". Add under step 1: "Silence is trimmed after any Tighten stretch; a placed line's block starts where its speech starts."
- **Spec section 6** "Too-long line detection" is already worded in terms of processed duration; keep the M3 replacement text.
- **`IMPLEMENTATION_PLAN.md`:** tick M4-1 to M4-4. (Plan boxes that look stale in the version pasted on 2026-10-27: M2-3, M2-4, M2-6 and M3-1 to M3-9 are unticked although M2 and M3 are done per `PROJECT_STATE.md`; tick them in the M3 merge.)

## Notes

- Pure logic (keys, silence offsets, chain spec, loudness gain, presets, meter maths) has no file, network or audio-library access; Pedalboard and pyloudnorm calls live in one thin render module, imported lazily, so the pure tests run without them (as `stretchrender.py` does).
- The assistant cannot hear anything: loudness and clipping checks must come from numbers the user pastes (measured LUFS and peak, render time), and the sound check from the user's ears. Ask for the exact command that produced a measurement.
- Never commit weights, audio or footage (rule 9). Every schema change needs a migration, a spec note and a decision-log row; none is planned.
