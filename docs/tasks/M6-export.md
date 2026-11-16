# M6: Export (pre-flight, voice tracks, edit graph, avatar compositor, final render, bundle, export UI)

> Written 2026-11-17 at the start of M6 from `IMPLEMENTATION_PLAN.md` (M6-1 to M6-8), `docs/DESIGN_SPEC.md` sections 7, 8 and 10, `PROJECT_STATE.md` and the M5 code. The plan wins where this file and it disagree. Decisions 1 to 3 were answered by the user on 2026-11-17; the others are recommendations that stand unless the user changes them, and are logged in `PROJECT_STATE.md`.

- **Milestone items:** M6-1 to M6-8.
- **Branch:** `m6-export`.
- **Done when (plan):** the export matches the preview at spot-check timestamps and the bundle contains every asset.

## Facts already established (do not re-ask)

- **Footage:** OBS MKV, H.264 2560x1440, 60 fps, one stereo AAC track at 48 kHz (M0). Bookend clips (`external` sources) have `overlay` off; the default template has none.
- **NVENC:** `h264_nvenc` works with the bundled BtbN 8.1 ffmpeg (`bin/ffmpeg.exe`): 1440p60 to 1080p60 at about 4.5x realtime, `-preset p5 -rc vbr -cq 23 -b:v 0 -pix_fmt yuv420p`, AAC 192k (M0).
- **Voice:** processed takes (`media/takes_fx/<key16>.wav`, 24 kHz mono, limited to -1 dBFS) are what the editor plays; `Session.processed_take_path(take_id, stretch)` renders one on demand. Placements carry `start_ms` and `duration_ms` (the playing length) in `TimelineState`.
- **Mix (spec 7, `audioGraph.ts`):** footage audio times `game_audio_db`, plus the voice bus, through a master limiter at -1 dBFS.
- **Avatar:** the frame track (`backend/avatar/track.py`) is the solver sampled at 30 fps; placement rules are in spec 8 and `frontend/src/avatarTrack.ts` (bottom centre at (x W, y H), height 0.6 H at scale 1, rotation about the anchor, squash). Full-size sprites are about 2095 px high.
- **Speed:** clips play at 0.25x to 8x; the preview keeps the pitch (`preservesPitch`).

## Decisions

1. **Frame rate (user).** The output is 1080p at the footage rate (60 fps for the user's recordings: the fps of the first track-0 clip's source that is not external; 30 if none). The avatar stays at 30 fps and is held for two output frames ("on twos").
2. **Which avatar frame shows at time t.** Frame `floor(t * 30 / 1000)` (the frame that started last), in the preview and the export. This is how ffmpeg's `overlay` holds a slower input and how an editor shows a 30 fps PNG sequence, so all three agree. The preview's `frameIndex` changes from nearest to floor (at most 33 ms later than now; not visible).
3. **Transparent overlay (user).** A PNG sequence, optional (off by default): `avatar_overlay/frame_000000.png` and up, one file per avatar frame (30 fps), 1920x1080 RGBA, plus `avatar_overlay/README.txt` giving the frame rate. Mostly transparent frames compress well, but 20 minutes is 36,000 files and several GB; the export screen says so next to the toggle.
4. **Compositing (user asked for the better option): one pass, piped.** Python composites each avatar frame (full-frame RGBA) and writes it to ffmpeg's stdin as raw video at 30 fps; one ffmpeg process reads the footage, the pipe and the mixed voice, and writes the final video. No intermediate avatar video on disk, one encode generation. When the PNG toggle is on, the same composited frames are also saved as PNGs by a small thread pool.
5. **Edited video in the same run.** The edit filter graph (trim, speed, scale to 1080p with letterbox, concat) is built once from the clip list and used straight from the sources. Its output is split: one branch goes under the avatar into `final_1080p.mp4`, the other is encoded as `video_edited.mp4` in the same ffmpeg run (two NVENC sessions, one decode). Re-encoding `video_edited.mp4` for the final would lose quality and take twice as long.
6. **Game audio.** Edited with the video (`atrim`, `atempo` chained for speeds outside 0.5 to 2, so the pitch is kept as in the preview). `video_edited.mp4` keeps the edited footage audio at its original level; the final mix applies `game_audio_db`.
7. **Voice tracks.** Python places every playing placement (not orphaned, with a take) at its timeline start and sums overlaps (rule 10). `voice_processed.wav` uses the processed takes. `voice_raw.wav` uses the raw takes cut to the same kept region and stretched the same way, without EQ, compressor, effects or loudness, so the two tracks line up sample for sample. Both are mono 32-bit float WAV at the takes' rate (24 kHz), so overlaps never clip; ffmpeg resamples to 48 kHz for the mix.
8. **Final mix (in ffmpeg).** `game * game_audio_db` plus voice (mono to both channels), `amix` with `normalize=0`, then `alimiter` at -1 dBFS. AAC 192k, 48 kHz stereo. Video: `h264_nvenc -preset p5 -rc vbr -cq 21 -b:v 0 -pix_fmt yuv420p`, `+faststart` (cq 21 instead of the spike's 23: one generation only, so a little more quality is cheap).
9. **Pre-flight (M6-1).** A pure function returns issues with a severity. **Errors** block the export: no clips, a clip's source file missing, a placed take's raw file missing, an invalid voice chain, an unknown clip effect, ffmpeg or NVENC not available. **Warnings** allow it after the user confirms: a placed line with no take (silent), orphaned placements, keys or reactions (left out), overflow that is not allowed (`allow_overlap` off; the overlap is mixed, rule 10), no usable avatar art (exported without avatar), art warnings (fallback sprites).
10. **Overlay off.** Where a clip has `overlay` off (bookends), no avatar is drawn. This goes into the frame track (sprite index -1 over those spans), so the preview hides it too (rule 5).
11. **Clip effects (rule 13).** A clip effect registry with an ffmpeg filter builder per type; none is registered in v1, and an unknown type is a pre-flight error. The edit graph asks the registry, never a hardcoded list.
12. **Bundle (M6-6).** Default folder `<project>/exports/<YYYY-MM-DD HHMM>/` (the export screen can pick another folder). Contents: `final_1080p.mp4`, `video_edited.mp4`, `voice_processed.wav`, `voice_raw.wav`, `lines/NNN_<mm-ss>_<text slug>.wav` (one processed file per playing placement, in timeline order), `video_raw/<file name>` (an NTFS hard link to each footage file the clips use; when a link is impossible, for example another drive, `video_raw/LINKS.txt` lists the full paths instead), optional `avatar_overlay/`, `project.json` (snapshot), `export.json` (app and ffmpeg version, settings, duration, time taken). Nothing outside the export folder is written; footage is never copied or changed (rule 2).
13. **Progress and cancel (M6-7).** The export runs on a background thread, one at a time. Progress is polled (`GET /api/export/status`), like voice jobs (M3 decision 4), instead of the WebSocket in spec 10; the spec text is updated at the wrap-up. Stages are reported with a fraction from ffmpeg's `-progress pipe:` output. Cancel stops ffmpeg and the compositor; the export folder is renamed with ` (incomplete)`, nothing is deleted.
14. **GPU (rule 7).** Export refuses to start while a voice job runs or waits, and voice generation is refused while an export runs. The existing `ExportSettings.unload_tts_before_export` (off in the template) is the "Unload the voice model first" checkbox; it frees about 3 GB of VRAM before encoding. The other `ExportSettings` fields are used as they are: `height` 1080, `fps` "match" (decision 1), `include_avatar_overlay` (the PNG toggle), `include_raw_video_link`.
15. **Parity (M6-8).** An automated test renders a short synthetic project (ffmpeg `testsrc2` footage, generated sprites) and compares frames of `final_1080p.mp4` at sample times with `video_edited.mp4` plus the compositor's frame for `floor(t * 30)`, within a small error. A shared fixture of poses and expected sprite rectangles is checked by both `pytest` (compositor layout) and `vitest` (`avatarTrack.ts layout`), so the browser and Python place the avatar the same way. The user then compares the preview and the export at three times by eye.

## Steps

1. **S1 Decisions.** This file; log the decisions; branch `m6-export`.
2. **S2 Pre-flight (M6-1).** `backend/export/preflight.py` (pure) and `GET /api/export/preflight`; tests.
3. **S3 Voice tracks (M6-2).** `backend/export/voicetrack.py`: the schedule (pure), the mixer (numpy), the raw-aligned render variant; writes both WAVs and `lines/`; tests.
4. **S4 Edit graph (M6-3).** `backend/export/editgraph.py` (pure): filter graph and argument lists for trim, speed, scale and letterbox, concat, game audio, the clip effect registry; an ffmpeg smoke test on `testsrc2` (skipped without `bin/ffmpeg.exe`).
5. **S5 Compositor (M6-4).** `backend/export/compositor.py`: layout (same maths as `avatarTrack.ts`), Pillow drawing with sprites prepared once at the export height; the overlay-off spans in the frame track; floor frame rule in `avatarTrack.ts`; shared layout fixture tests.
6. **S6 Final render (M6-5).** `backend/export/runner.py`: one ffmpeg run (edited video split to two outputs, avatar pipe, voice, mix), progress parsing, cancel; smoke test on a synthetic project.
7. **S7 Bundle (M6-6).** Folder layout, hard links with the fallback note, PNG sequence writer, `project.json` and `export.json`; tests.
8. **S8 Export API and screen (M6-7).** Start, status, cancel endpoints; the export screen (pre-flight list, folder, PNG toggle, unload toggle, progress, cancel, open folder). **Manual check in the app.**
9. **S9 Parity (M6-8).** The automated parity test; the user's check of preview against export at three times on `Rack 1`.
10. **S10 Wrap-up.** `PROJECT_STATE.md`, ticks, spec sections 10 and 11 (polling instead of WebSocket, one ffmpeg run, frame rule), merge, tag `m6-done`.

## Acceptance checks (user runs these)

- Pre-flight lists the real problems of `Rack 1` (if any) and blocks only on errors.
- Exporting `Rack 1` writes the whole bundle; `final_1080p.mp4` plays with footage, voice, game audio at the set level and the avatar; the mouth matches the voice as in the preview.
- At three times, the preview and the exported frame show the same sprite at the same place.
- `video_raw/` holds hard links (no extra disk use: `fsutil hardlink list <file>` shows both paths), or `LINKS.txt` when on another drive.
- Cancel stops the export within a few seconds and leaves an ` (incomplete)` folder.
- `uv run pytest`, `uv run ruff check .`, `npm run check`, `npm test` pass.

## Risks and open points

- **Compositor speed:** about 36,000 avatar frames for 20 minutes; Pillow resize and rotate of a 650 px sprite plus an 8 MB frame write each. Expected 5 to 15 ms per frame (a few minutes); measure in S5 and S6. If slow: reuse a frame when the pose repeats, or crop the pipe to the avatar's box with per-frame overlay positions.
- **Frame accuracy of the edit graph:** clip boundaries in ms are rounded to frames by ffmpeg; the output can drift by up to a frame at a cut. The parity test checks within one frame.
- **Two NVENC sessions** at once on the laptop GPU (allowed on GeForce, up to 5 since driver 530+); if it fails, encode `video_edited.mp4` in a second run.
- **Disk:** the PNG sequence can be several GB; the bundle size is estimated before the export.
