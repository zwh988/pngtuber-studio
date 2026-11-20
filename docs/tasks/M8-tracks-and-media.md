# M8: Tracks and media (audio lanes, video lanes, PNG sequences)

> Drafted 2026-11-19, revised the same day after the user's answers: audio (music, sound effects) comes in by **dragging files onto the timeline**, on **multiple audio lanes**; **extra video lanes are required**, not optional; recording audio (from a mic or anything else) is out of scope; a video keeps its own audio as now. To start **after M7 is merged** (`m7-done`). Nothing here is built. The questions under "Decisions" are for the user at the start; the answers go into the decisions log in `PROJECT_STATE.md`. Each part is its own branch and the milestone can stop after any part.

- **Milestone items:** M8-1 to M8-3 (to add to `IMPLEMENTATION_PLAN.md` when the milestone starts).
- **Branches:** `m8-1-audio-lanes`, `m8-2-video-lanes`, then `m8-3` only if decided.
- **Spec sections:** 4.2 (editor lanes), 5 (data model), 7 (audio chain), 9 (editing), 10 (export).
- **Order and size:** M8-1 audio lanes (M) → M8-2 video lanes (L, required) → M8-3 PNG sequences (M to L, optional, decided after M8-2).

## Facts already established (do not re-ask)

- **Not in scope:** recording audio (from a mic or any other input) inside the app (user, 2026-11-19). A video clip keeps its own sound as now: the first audio stream of the file (`[i:a:0]` in `backend/export/editgraph.py`), at the game audio level.
- **Other tracks today:** `Clip.track` exists (default 0). Clips on other tracks are counted (`TimelineState.other_track_clips`), warned about in the editor and the pre-flight (`other_tracks`), and left out of preview and export.
- **Avatar art is still images:** one PNG per expression and eye/mouth state (`backend/avatar/art.py`). The export *writes* a PNG sequence (the optional overlay); nothing reads one.
- **Voice lines already work the way audio clips will:** placed on a lane, played through Web Audio on the audio clock with a drift restart past 120 ms (`voicePlayback.ts`), mixed by the export (`voicetrack.py`). Audio clips reuse that path.
- **Rules that shape this:** footage is never copied or modified (rule 2: audio clips are not footage); every timed item is anchored to (clip_id, source_time) (rule 4); preview equals export (rule 5); schema changes need a migration (rule 6); every edit is undoable (rule 11).
- **Dropping files from Explorer:** a plain browser drop gives the page the file's bytes but not its path. pywebview can report the full path of dropped files to Python (to confirm with a short spike at the start of M8-1); otherwise the page sends the bytes and the backend saves them.

## Decisions (settle at the start)

Settled by the user on 2026-11-19: several audio lanes, not one; extra video lanes are part of M8 (decision 4 is now only about what they do).

**Answers (user, 2026-11-20; also in the `PROJECT_STATE.md` decisions log):**

1. Copy dropped audio files into the project's `audio/` folder.
2. Audio clips are independent of the footage: anchored to a timeline time, never moved or cut by a video edit (the user moves and trims them). A video's own sound always follows its video. Rule 4 in `CLAUDE.md` names the exception.
3. No ducking in M8.
4. Upper video lanes do picture-in-picture in M8-2 (position, scale, opacity per clip, full frame by default). The upper clip's sound plays at a per-clip level (on by default); the main footage's sound continues. Upper-lane clips are independent of footage edits too (timeline time).
5. M8-3 is (b), seen as a video source: the user picks a folder of PNGs and a frame rate, and it goes on a video lane like a video clip.
6. (M8-2, 2026-11-20) Video-lane sources: recordings from the Footage tab (referenced, never copied); from Explorer, images are copied into `images/` and a video from outside `footage/` is copied into `footage/` first, with a message.
7. (M8-2, 2026-11-20, after trying the preview) Drag handles on the preview for the selected lane clip; a snap toggle (clip edges on any lane and the playhead; Alt skips it for one drag); S splits the selected audio or lane clip at the playhead. Audio FX for audio clips is a later part, M8-4, with one FX chain per clip.
8. (M8-2, 2026-11-20) The avatar's layer moves between the video lanes (an Avatar row, default on top). Freeze frame on a lane recording inserts a 2 s hold at the playhead and pushes the rest of that lane later.

The original options and recommendations follow for the record.

1. **Where dropped audio files go.** (a) copied into the project's `audio/` folder (the project stays self-contained; the copy is what the project uses), or (b) referenced where they are, by path, relinked like footage when moved. **Recommendation:** (a): music and sound effects are small next to footage, and a project that still plays after the original file is moved or deleted is worth the copy.
2. **What audio clips follow when you cut.** Rule 4 anchors timed items to the footage, so a cut moves them with the picture. (a) anchor like voice lines (a sound effect stays on its moment in the footage; music jumps at a cut), (b) anchor to the timeline (music keeps playing across cuts; an exception to rule 4, written into `CLAUDE.md`), or (c) per clip: a "Stay with footage" switch, on by default for short clips and off for long ones. **Recommendation:** (c), with (a) for anything under 30 s.
3. **Ducking.** Lower audio clips under the voice lines automatically (a fixed level curve computed from the placements, the same in preview and export), per clip on or off? **Recommendation:** yes, off by default, one "duck under voice" switch per clip with a single depth setting in Settings.
4. **Extra video lanes (M8-2, required): how do upper lanes show?** (a) full frame over the lanes below (B-roll, cutaways, title cards with transparency), (b) also position, scale and opacity per clip (picture-in-picture), (c) (a) now and (b) later. A clip on an upper lane: does its own sound play (on by default, with a level), and does the main footage's sound continue under it? **Recommendation:** (c); upper clips' sound on with a level; the main footage's sound continues.
5. **PNG sequences (M8-3, optional): which meaning?** (a) animated avatar sprites (a looping idle or talking loop per expression), or (b) a transparent PNG sequence dropped on a video lane as an overlay (a sticker or effect), which M8-2's lanes make small. **Recommendation:** ask which one is wanted before planning it in detail.

## Steps

### M8-1 Audio lanes by drag and drop (decisions 1 to 3)

**Done 2026-11-20** on `m8-1-audio-lanes` (each step confirmed by the user in the app). As built, differing from the steps below: imported files are their own `AudioFile` entity that clips point to (`file_id`); the clip length is the decoded WAV's; a drop on the "+ Audio lane" row makes a new lane; the lane level and the clip level, fades, mute and solo are in place, no ducking (decision 3); audio past the end of the footage was neither played nor exported (fixed in M8-2); the bundle gains `audio_clips.wav`. Details: `PROJECT_STATE.md` decisions log (2026-11-20) and spec 4.2, 5, 7, 9, 10.

1. **Spike (half a step):** drop a file from Explorer onto the pywebview window and get its full path in Python; if that fails, upload the bytes. Decide the import path from the result. **Done 2026-11-20:** full paths work (`scripts/spike/drop_spike.py`); imports go by path, no upload.
2. **Schema v5:** `audio_lanes: list[AudioLane{id, name, gain_db, mute, solo}]` (one "Audio 1" lane in a new or migrated project) and `audio_clips: list[AudioClip{id, lane_id, file (project-relative), timeline_ms, in_ms, out_ms, gain_db, fade_in_ms, fade_out_ms}]` (decision 2: timeline time, no anchor, so no orphans; decision 3: no duck), migration from v4. Lane commands add, rename, reorder, remove (only when empty), level, mute, solo. Commands add, move, trim, set level and fades, remove (undoable).
3. **Import:** dropping one or more audio files (WAV, MP3, FLAC, OGG, M4A) on the timeline imports each (decision 1), probes it with ffprobe, decodes it once to a cached WAV for preview and peaks, and places it at the drop point. A file whose name and size match an earlier import is reused, not copied again.
4. **Timeline:** audio lanes under the voice lane, each with a name, level, mute and solo in the lane-name column, and "+ Audio lane". Blocks with a waveform (the existing peaks code), drag to move (also up and down between lanes), edge-drag to trim; a drop on empty space below the last lane adds a lane. Clips on one lane do not overlap (a drop that would overlap goes to the next free lane). An inspector (Line bank style) for level and fades.
5. **Preview:** an audio-clip bus in Web Audio, scheduled like the voice lines, with the fades applied as gain automation.
6. **Export:** the clips are mixed into the voice/music track before the final mix and limiter, using the same pure level curve as the preview; each imported file is also listed in `export.json`.
7. **Tests:** migration, commands, audio clips unmoved by cut, ripple-delete and undo (decision 2), the fade curve (pure), the export mix, import reuse.

### M8-2 Video lanes (required; decision 4)

**Done 2026-11-20** on `m8-2-video-lanes` (each step confirmed by the user in the app). As built, differing from the steps below: lane clips are **not anchored** (decision 4: timeline times, a separate `lane_clips` list with `video_lanes`, not `Clip.track`), so the `other_tracks` warning stays for old track > 0 clips; picture-in-picture (x, y, scale, opacity) was built from the start; the preview draws each lane recording in its own `<video>` re-seeked on drift, not by segment hopping; the avatar's layer moves between the lanes (an Avatar row, default on top). Added on the way (decisions 7 and 8): split of audio and lane clips (S), a snap toggle, drag handles on the preview, freeze frames on lane recordings and on the main footage (F), and the timeline, preview, avatar and export running to the last clip on any lane (black past the footage). Export: `backend/export/lanes.py`. Details: `PROJECT_STATE.md` decisions log (2026-11-20) and spec 4.2, 5, 7, 9, 10.

1. **Model:** the main lane stays track 0, the cut-and-splice sequence everything is anchored to (rule 4). Upper lanes (track 1, 2, ...) hold clips from recordings or image files placed at a time on the main lane (anchored like the other items), with in/out, and per decision 4 their own sound level. `Clip.track` exists; upper-lane clips get an anchor instead of a sequence position. Schema change with migration; the `other_tracks` warning goes away.
2. **Timeline:** one row per video lane above the main lane, "+ Video lane", drag footage or images from the Footage tab or Explorer onto a lane, move and trim like audio clips; lane eye (hide) and lock.
3. **Preview:** a second `<video>` (and an `<img>` for stills) drawn over the main picture while an upper clip is active, kept in sync by the same segment hopping as the main player; the avatar stays on top.
4. **Export:** the edit graph builds each upper lane as its own timed stream and `overlay`s it on the main picture with `enable` over its time range (full frame now; position, scale and opacity per decision 4 later); upper clips' sound joins the mix at its level.
5. **Tests:** anchoring of upper clips through cuts and ripple-deletes (orphans parked, never dropped), the overlay filters, the preview's active-clip lookup (pure), migration.

### M8-3 PNG sequences (only if decision 5 is chosen)

- **(a) Animated avatar sprites:** art layout gains optional frame folders per state (for example `01a_neutral_oiom/0001.png ...` plus a frame rate in `avatar.json`); the solver picks the frame from time (pure, rule 5); the frame track and the compositor handle many more images. Size M to L.
- **(b) Overlay sequence:** a clip on an M8-2 video lane whose source is a folder of PNGs, read with ffmpeg's `image2` input in the export and as a frame strip in the preview.

## Acceptance checks

- M8-1: dragging a music file and two sound effects onto two audio lanes places them at the drop points; they play in the preview and the export at the same times and levels, with fades, lane mute and solo; cutting the footage never moves them (decision 2); undo removes each step; old projects open unchanged (migration).
- M8-2: a cutaway clip on video lane 2 and a still image on video lane 3 show over the main picture in the preview and the export at the same times, with the avatar on top; a cut on the main lane moves or parks them as rule 4 says.
- `uv run pytest`, `uv run ruff check .`, `npm run check`, `npm test` pass; `PROJECT_STATE.md` and the spec sections updated.

## Risks

- **Preview sync:** long music under many cuts is the case to test (the voice lines' drift restart covers short items well).
- **Drop path:** if pywebview cannot hand over file paths, large files go through an upload; fine for music and sound effects, which is all M8-1 accepts.
- **Scope creep:** no EQ or effects on audio clips beyond level, fades and ducking; no recording inside the app; video lanes do full-frame overlays first (decision 4).
- **Preview cost of video lanes:** two or three `<video>` elements decoding at once on a laptop GPU; test with 1440p60 OBS files early in M8-2.
