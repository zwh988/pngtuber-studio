# M2: Timeline and cut editing

- **Milestone items:** M2 in `IMPLEMENTATION_PLAN.md`. Chat A: M2-1 (S1, S2). Chat B: M2-3 and M2-5 (S3 to S5). Chat C: backend API and media server (S6, S7; no plan id of its own, it supports M2-2 and M2-4). Chat D: M2-2, M2-4, M2-6 and the wrap-up (S8, S9).
- **Spec sections:** 4.2 (editor: player, video strip lane, hotkeys), 5 (Clip row, anchoring rule, conventions), 9 (editing, undo/redo bullet, playback of cuts, speed clips), 11 (media server bullet)
- **Status:** in progress. Chats A to C done (S1 to S7, all user-confirmed and committed). Chat D (S8 editor screen, S9 wrap-up) is next.

## Goal

Footage placed in a project can be put on a timeline and edited: split, ripple-delete, trim, reorder, change speed, with unlimited undo. Time mapping (source time to timeline time and back) and orphan handling are pure, tested modules, because every later milestone (lines, keyframes, reactions, export) builds on them. A first editor screen shows a video player that plays the cut sequence (hopping between segments) and a canvas timeline with the video strip lane, a playhead, and the hotkeys from spec 4.2. Done when: add a recording to the timeline, cut and rearrange it, play it back across the cuts, undo and redo every step, restart the app, and the edit is intact.

## How this task runs

Same method as M0 and M1 (see `CLAUDE.md`): the assistant writes files and commands, the user applies and runs them in PowerShell from the repo root, then pastes results back. One step at a time; do not move on until the user confirms the previous step.

This milestone is larger than M1 (a new editor screen), so it is split across **four fresh chats**. Each chat gets `CLAUDE.md`, a freshly updated `PROJECT_STATE.md`, this file, and only the spec sections and source files listed for it. At the end of each chat the assistant outputs the complete updated `PROJECT_STATE.md`; commit it before starting the next chat.

| Chat | Steps | Paste these spec parts | Paste these source files |
|---|---|---|---|
| A | S1, S2 (decisions, time mapping) | Section 5 (Clip row, anchoring rule, conventions), section 9 "Operations" and "Speed clips" bullets | `backend/project/schema.py` |
| B | S3, S4, S5 (clip commands, orphan logic) | Section 5 anchoring rule, section 9 "Operations" and "Undo/redo" bullets | `schema.py`, `backend/project/commands.py`, `backend/edl/timemap.py` (from chat A) |
| C | S6, S7 (backend API, media server) | Section 9 "Playback of cuts", section 11 "Processes" (media server) and "Frontend" | `backend/app.py`, `backend/project/session.py`, `backend/project/summary.py`, `frontend/src/api.ts`, and only `parse_range` and `iter_file` from `scripts/spike/player_spike.py` |
| D | S8, S9 (editor screen, wrap-up) | Section 4.2 (player, video strip lane, hotkeys), section 9 "Playback of cuts" and "Speed clips" | `frontend/src/App.svelte`, `frontend/src/api.ts`, the new timeline API types from chat C |

Branch: `git switch -c m2-timeline` once at the start of chat A (after `git status` is clean on `main` with `m1-done` tagged). Keep the same branch across all four chats and commit after each confirmed step. Merge and tag (`m2-done`) only after chat D.

## Prerequisites (user does these first)

- [ ] M1 merged to `main`, tagged `m1-done`, pushed; `git status` clean; `uv run pytest` and `uv run ruff check .` pass on `main`
- [ ] A test project with a real recording copied into its `footage/` folder and scanned (the project screen shows it as "ok"). A second, different clip is useful for reorder tests but not required
- [ ] Node.js and the frontend build working (`npm run build` in `frontend/`), needed from chat D (and from chat C for the typed API)
- [ ] `IMPLEMENTATION_PLAN.md` open, so the M2 item ids can be filled in at the top of this file

## Context pack

- `CLAUDE.md`
- `PROJECT_STATE.md` (current)
- This task file
- The spec parts and source files for the current chat (table above)
- Do not paste the whole spec or whole files "just in case"; the assistant asks for a function or section by path when needed

## Scope

**In:**
- **Time mapping** (`backend/edl/timemap.py`, pure): clip spans on the timeline, source anchor to timeline time, timeline time to anchor, total duration, frame snapping, speed handling, all in integer milliseconds
- **Clip commands** on the M1 `CommandStack`: add a source to the timeline as a clip, split at a timeline time, ripple-delete a timeline range, trim a clip's in/out edge, reorder clips, set clip speed (0.25x to 8x), remove a clip. All undoable; drag operations use groups
- **Orphan handling** (pure logic plus its use inside the commands): when an edit removes the footage an anchored item points at, flag it `orphaned` and park it at the nearest edge; undo restores the exact previous anchors and flags. A pure `find_orphans`-style check that the export pre-flight can use later
- **Reference check:** a pure function listing broken references (a clip pointing at a missing source, an anchored item pointing at a missing clip). Reported, not enforced at load (see decisions)
- **Backend API:** timeline state, one endpoint per clip operation (or one generic edit endpoint), undo, redo with labels, all through `Session`'s command stack and saving on every change
- **Media server:** HTTP range endpoint serving a source's video by source id (never by raw path from the browser), reusing the M0 Range logic
- **Editor screen** in the Svelte frontend: `<video>` player that plays the clip sequence by hopping between segments (a seek at each boundary), playback rate from clip speed with pitch preserved, a custom canvas timeline with ruler, the video strip lane (clips, cut markers, speed badges), playhead and selection, drag to trim and reorder (one undo step per drag), and the hotkeys: Space, `,` and `.` frame step, S split, Delete ripple-delete, `[` and `]` set in and out, Ctrl+Z and Ctrl+Y
- pytest suites for every pure module; `ruff` clean; `npm run check` clean

**Out:**
- Line bank, voice lane, takes, GPU anything (M3), voice FX and waveforms (M4), avatar canvas, expression and parameter lanes, reaction lane, game audio lane (M5). The editor shows only the video strip lane; the other lanes arrive with their milestones
- Creating placements, keyframes or reactions (nothing in M2 creates them). Orphan logic is therefore tested with items built directly in unit tests, not through the UI
- Effect registry and zoom, freeze or text effects (rule 13 and the backlog); `Clip.effects` stays an empty list
- Export and the ffmpeg filter graph builder (M6); edited-proxy playback ("later" in spec 9); multi-track editing in the UI (the model keeps `track`, the UI uses track 0 only); WebSocket events (plain HTTP calls are enough); file watcher for `footage/`
- Anything that copies, re-encodes or modifies footage (invariant 2)
- Backlog features listed in `IMPLEMENTATION_PLAN.md`

## Facts already established (do not re-ask)

- Time is integer milliseconds everywhere. Anchors are `(clip_id, source_ms)` in **source** time. At 59.94 fps a frame is 16.683 ms, so frame lookups round to the nearest frame, never floor.
- `Clip` has `id`, `source_id`, `in_ms`, `out_ms` (out > in), `speed` (0.25 to 8.0), `track` (default 0), `overlay` (default true), `effects` (empty list). There is no `start_ms`: the clip list is the sequence. `Project.clips` order is timeline order.
- Template bookends are already clips: intro first, outro last, `overlay=False`, covering the whole source, with `external` sources (absolute path). They carry no anchored items. The default template has no bookends.
- Footage detected by the M1 scan becomes a `Source` only. No clip exists for it until M2 adds one. "Add to timeline" is a new command.
- M1 command contract: validate then mutate; raise `CommandError` before any change; each command records its own undo data (no project snapshots); `apply` can be re-run after `revert` (redo); groups are atomic; undo and redo are refused while a group is open; `on_change` fires once per top-level change. `RemoveSource` is already refused while any clip uses the source.
- `Session` holds one `CommandStack` per open project and saves on every change; a failed save appears as `save_error`. HTTP errors are 400 with `{"detail": message}`.
- The schema validates unique ids per collection but not cross-references.
- M0 results: a hand-written Range endpoint plus `<video>` plays a 4.8 GB 1440p60 OBS MKV with seeks of 17 to 281 ms. The browser sends open-ended `bytes=N-` requests answered with 206. WebView2 plays H.264/AAC in MKV without remuxing.
- Spec says v1 playback hops between segments with a seek at each boundary (a slight hitch is acceptable). Speed clips in the browser use playback rate with pitch preserved.

## Decisions to make in S1 (assistant proposes in 5 lines or fewer each, user decides, log in `PROJECT_STATE.md`)

1. **Sequence model:** confirm that track 0 is a gapless sequence in list order (no start times, ripple everywhere), and that the UI edits track 0 only. Proposal: yes. State what happens to clips on other tracks in the pure functions (proposal: ignored by time mapping in M2, preserved by every command).
2. **Rounding and frame snapping:** timeline time of a source moment = round(clip start + (source_ms minus in_ms) divided by speed). Which values snap to the source frame grid (cut points, trims) and which stay free milliseconds (playhead, anchored items)? Proposal: edits that create or move a cut snap to the nearest frame of that source; anchors never snap.
3. **Orphan parking:** "parked at the nearest edge." Does an orphaned item's stored anchor get rewritten to the nearest surviving clip edge (and `orphaned=True`), or does it keep its old anchor and only get flagged? The schema has no `original_anchor` field. Proposal: rewrite the anchor to the nearest surviving boundary and flag it; the command stores the old anchor for undo; nothing un-orphans automatically except undo; resolving is a later UI action (a re-anchor command in a later milestone). Define "nearest" by timeline distance, ties to the earlier edge.
4. **Insertion point for new clips:** where does "add to timeline" insert? Proposal: before a trailing bookend clip (the last clip when its source is `external` and `overlay` is false), otherwise at the end; and an optional explicit index.
5. **Reference validation:** add a `Project` validator that rejects broken references on load, or a separate pure check reported as warnings? Proposal: separate pure function, called by commands before they apply and by the session after load; never makes an old file unloadable.
6. **Minimum clip length and split edge cases:** proposal: a clip must be at least one source frame long; splitting at a cut point or outside a clip is refused with a clear message; ripple-delete of a range that covers part of a clip trims it, covers a whole clip removes it.
7. **Speed and ripple:** speed changes ripple the following clips (their timeline start moves, their anchors do not). Confirm, and confirm that anchored items inside a sped-up clip keep their source time (so their timeline time scales with the clip).

## Steps

Each step ends with what to paste back and a commit point (`git status`, `git add`, `git commit -m "M2-...: ..."` using the plan ids).

1. **S1 Decisions.** Assistant reads the pasted spec parts and `schema.py`, lists decisions 1 to 7 with one-line proposals (and any it thinks are missing), user decides. *Paste back:* your choices. No code yet.
2. **S2 Time mapping.** Assistant gives `backend/edl/timemap.py` (and `backend/edl/__init__.py`): `clip_spans(clips)` returning each clip's timeline start and end, `timeline_duration`, `to_timeline(clips, anchor)`, `to_source(clips, timeline_ms)` returning an anchor or `None`, `snap_to_frame(ms, fps_num, fps_den)`, all pure, with `tests/test_timemap.py`: single clip, several clips, speeds 0.25 and 8, trims, reordering keeping anchors attached, 60 and 59.94 fps rounding, round trips, boundaries, empty list. *Paste back:* `uv run pytest` and `uv run ruff check .` output.
3. **S3 Clip commands, part 1.** Assistant gives (in `backend/project/commands.py` or a new `backend/project/clip_commands.py`, the assistant states which and why) `AddClip`, `RemoveClip`, `SetSpeed`, `ReorderClip`, with undo data and tests. *Paste back:* `uv run pytest` and `uv run ruff check .`.
4. **S4 Clip commands, part 2.** `SplitClip`, `TrimClip` (in or out edge), `RippleDelete(range)`, with tests including groups (a split plus a trim reverts as one undo) and edge cases from decision 6. *Paste back:* `uv run pytest` and `uv run ruff check .`.
5. **S5 Orphans and reference check.** Assistant gives the pure orphan functions and `check_references`, wires orphan flagging and parking into the trim, split, delete and reorder commands (so undo restores anchors and flags exactly), with tests that build placements, keyframes and reactions directly: trim past an anchor, delete a whole clip, reorder (no orphans), undo and redo. *Paste back:* `uv run pytest` and `uv run ruff check .`.
6. **S6 Backend API.** Assistant extends `Session` and `app.py`: timeline state (clip spans, duration, per-clip source info), edit endpoints, `undo` and `redo` (returning the label and new state), and tests with `TestClient`. Work in sub-rounds: (a) read-only timeline state, (b) add clip and undo/redo, (c) the remaining operations and groups. *Paste back:* each sub-round's pytest output.
7. **S7 Media server.** Assistant gives a Range endpoint (for example `GET /media/source/{source_id}`) built from the M0 `parse_range` and `iter_file`: path comes from the project's source list, never from the request; handles spaces in Windows paths, `external` sources, missing files (404), and multi-GB files. Pure Range parsing is tested. *Paste back:* pytest output, and a browser check: open the URL in the app window and confirm playback with seeking.
8. **S8 Editor screen.** Work in sub-rounds, building on the existing Svelte app: (a) a basic editor view and a way to open it from the project screen, plus the typed API; (b) the `<video>` player playing one clip with correct start and end; (c) segment hopping across clips and playback rate for speed; (d) the canvas timeline: ruler, clip blocks, cut markers, speed badges, playhead, click to seek, zoom and scroll; (e) selection and the hotkeys; (f) drag trim and reorder with grouped undo. *Paste back:* for each sub-round, what you see in the window and any console error or traceback.
9. **S9 Tests and wrap-up.** Assistant checks the test list against the plan, runs the end-of-task checklist: complete updated `PROJECT_STATE.md` (repo map, command API additions, endpoints, decisions from S1, known issues), plan items to tick, replacement text for any spec section whose behavior changed, suggested commit message and merge and tag commands (`m2-done`). *Paste back:* final `uv run pytest`, `uv run ruff check .`, `npm run check` output, and the manual acceptance run below.

## Acceptance criteria

- [ ] `uv run pytest` passes; `uv run ruff check .` is clean; `npm run check` is clean
- [ ] Time mapping round-trips (source to timeline to source) across trims, reorders and speeds, at 60 and 59.94 fps, with tests
- [ ] Every edit (add, split, ripple-delete, trim, reorder, speed, remove) undoes and redoes through the command stack; a drag undoes as one step
- [ ] Trimming or deleting past an anchored item flags it `orphaned` and parks it at the nearest edge; undo restores the original anchor and flag (unit-tested; no UI for creating these items yet)
- [ ] Reordering clips never changes an anchored item's source time or clip id
- [ ] Footage is never modified or copied; the media endpoint serves only sources that belong to the open project
- [ ] Manual run: add a recording to the timeline, split with S, delete a segment with Delete, drag to reorder and trim, set one clip to 2x and play across the cuts with sound, step frames with `,` and `.`, Ctrl+Z and Ctrl+Y through every step, close the app, reopen the project, and the edit is intact
- [ ] Playback hops between segments without stopping on a wrong frame (a brief hitch is acceptable per spec)
- [ ] `PROJECT_STATE.md` updated; M2 items ticked in `IMPLEMENTATION_PLAN.md`

## Notes

- Pure logic (time mapping, orphan handling, reference check, clip command bookkeeping, Range parsing) has no file or network access, per `CLAUDE.md`. I/O lives in thin wrappers (`Session`, the media endpoint).
- Every schema change needs a migration. M2 should not need one; if the assistant wants a new field (for example an orphan "original anchor"), it must say so, add a migration, and list it for a spec update.
- The M1 `AutosaveTracker` is unused because the session saves on every change. A drag that fires many commands should be one group (one save). If saving per change still feels slow during drags, say so and the debounce gets wired then.
- `RelinkSource` is path-only; relinking goes through `Session.relink_source`, which re-probes. Clip commands must not assume a source's metadata changed.
- Verify playback decisions with the real 1440p60 recording, not only short test clips; the M0 seek numbers came from a 4.8 GB file.
- The assistant cannot see errors until the user pastes them; get the full traceback, the exact command, and (for the editor) the browser console output before suggesting a fix.
