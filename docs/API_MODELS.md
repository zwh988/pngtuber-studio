# API_MODELS.md

Response and request shapes the frontend relies on for the voice features (M3). Source of truth is the Python models (named in each heading); `frontend/src/api.ts` mirrors them. Update this file when a model changes, so nobody has to paste the Python again. The last part, "Core contracts", is a digest of the schema, command stack, time mapping, session, timeline and editor code that M3 chats E and F build on.

Ids are 12-char hex strings; durations are integer ms; errors are HTTP 400 `{"detail": message}`.

## `GET /api/voice`, `POST /api/voice/reference` : `VoiceState` (`backend/voice/profile.py`)
`status` (`no_profile` | `no_reference` | `file_missing` | `unreadable` | `invalid` | `ready`), `ready`, `profile_id`, `name`, `reference_path`, `duration_ms`, `sample_rate`, `hash`, `problems`, `warnings`. api.ts assumes the clip fields can be null and the two lists are string arrays (not yet checked against the Python).

## `GET /api/lines`, `POST /api/lines/edit` : `LineBankState` (`backend/voice/linebank.py`)
`lines: LineItem[]`, `emotions: string[]` (preset names in file order), `can_undo`, `can_redo`, `undo_label`, `redo_label`, `save_error`.

`LineItem`: `id`, `text`, `emotion`, `emotion_known`, `exaggeration` and `cfg_weight` (stored overrides, null = preset), `effective_exaggeration` and `effective_cfg_weight` (null when the emotion is unknown), `allow_overlap`, `active_take_id`, `generated` (has an active take), `take_count`, `placement_count`.

## `POST /api/lines/edit` ops (`backend/project/line_ops.py`, all `extra="forbid"`)
| `op` | fields |
|---|---|
| `add_line` | `text=""`, `emotion="neutral"`, `position?`, `line_id?` |
| `remove_line` | `line_id` |
| `set_line_text` | `line_id`, `text` |
| `set_line_emotion` | `line_id`, `emotion` |
| `set_line_exaggeration` | `line_id`, `value` (float or null = preset) |
| `set_line_cfg_weight` | `line_id`, `value` (float or null = preset) |
| `set_allow_overlap` | `line_id`, `value` |
| `set_active_take` | `line_id`, `take_id` (null clears) |
| `star_take` | `take_id`, `starred=true` |

Slider limits: exaggeration 0.0 to 2.0, cfg_weight 0.0 to 1.0, default emotion `neutral`.

## `GET /api/lines/{line_id}/takes` : `TakeItem[]` (`backend/voice/takes.py`)
`id`, `line_id`, `seed`, `text` (snapshot), `exaggeration`, `cfg_weight`, `duration_ms`, `starred`, `active`, `created` (ISO), `raw_file`, `file_exists`. Oldest first. Audio: `GET /media/take/{id}`.

## `POST /api/takes/delete`, `POST /api/lines/delete` : `TakeDeleteReport`
`removed_take_count`, `removed_line`, `freed_bytes`, `failed_files`, `cleared_active_line_ids`, `cleared_override_placement_ids`.

## `GET /api/storage` : `StorageReport`
`lines: LineStorage[]`, `take_count`, `total_bytes`, `missing_file_count`, `unreferenced: UnreferencedFile[]`, `unreferenced_bytes`.

`LineStorage`: `line_id`, `text`, `take_count`, `size_bytes`, `takes: TakeStorage[]`.
`TakeStorage`: `take_id`, `seed`, `duration_ms`, `size_bytes`, `file_exists`, `starred`, `active`.
`UnreferencedFile`: `path`, `size_bytes`. Files in `media/takes_raw` that no take points at; reported only, the app never deletes them.

## Jobs (`backend/voice/jobs.py`)
`POST /api/voice/generate`, `/reroll`, `/worker/unload` return `JobItem`; `GET /api/voice/jobs` and `POST /api/voice/jobs/cancel` return `JobStatus`.

`JobItem`: `id`, `kind` (`generate` | `unload`), `line_id` (null for unload), `reroll`, `state` (`queued` | `running` | `cancelling` | `done` | `cancelled` | `failed` | `reused`), `phase` (`waiting` | `loading` | `generating` | `storing` | `unloading` | `finished`), `chunks_done`, `chunk_count`, `reused`, `take_id`, `message` (failure reason).

`JobStatus`: `jobs` (oldest first, newest 30 finished kept), `active`, `worker` (`stopped` | `loading` | `ready` | `unloaded` | `failed`), `model_version`, `worker_message`.

## Placements (M3-7, S6a: `backend/project/placement_commands.py`, `backend/project/edit_ops.py`)
Placement ops are part of the timeline `EditOp` union, so they also work inside `POST /api/timeline/batch` and mix with clip ops in one undo step. All are `extra="forbid"`. Times are **timeline** ms; the command turns them into an anchor (clip id plus source time) with `timemap.to_source` on the first apply and reuses that anchor on redo.

| `op` | fields | endpoint (body is the op, returns `TimelineState`) |
|---|---|---|
| `add_placement` | `line_id`, `timeline_ms`, `placement_id?` | `POST /api/timeline/place` |
| `move_placement` | `placement_id`, `timeline_ms` (where the start of the block goes) | `POST /api/timeline/move-placement` |
| `remove_placement` | `placement_id` | `POST /api/timeline/remove-placement` |

Rules: a line must exist and have an active take (error "generate the line first: it has no take yet"); the time must fall on footage (`0 <= t < timeline duration`, else "there is no footage at ..."); a duplicate or malformed `placement_id` is refused; moving an orphaned placement clears `orphaned` and undo brings it back. Remove keeps the line and its takes. Labels: "Place line", "Move placed line", "Remove placed line". Errors are HTTP 400 `{"detail": message}`.

`TimelineState.placements: TimelinePlacement[]` (`backend/project/timeline.py`), ordered by `start_ms` (unmappable ones last): `id`, `line_id`, `line_text` (empty if the line is gone), `allow_overlap`, `take_id` (override, else the line's active take, null if neither exists), `duration_ms` (null without a take), `start_ms` and `end_ms` (timeline time; null when the anchor cannot be mapped, `end_ms` also null without a take), `anchor_clip_id`, `anchor_source_ms`, `orphaned`. Overflow flags are not in it yet (S8).

`GET /api/takes/{take_id}/peaks?buckets=400` : `PeaksReport` (`backend/voice/peaks.py`): `take_id`, `duration_ms`, `sample_rate`, `buckets`, `lows` and `highs` (lowest and highest sample of each bucket, -1 to 1, left to right, `buckets` values each). `buckets` must be 8 to 4000 (else 400); 404 for an unknown take or a missing file. Computed on demand, cached in memory by file, size and mtime, never stored in `project.json`.

---

# Core contracts (digest for M3 chat E onward)

Written from the source files pasted in M3 chat E (2026-10-17). Source of truth is still the code; this is what a chat needs so the files need not be pasted again. If you change one of these modules, update the matching section.

## Schema (`backend/project/schema.py`, `SCHEMA_VERSION = 1`)
- Base `_Model`: `extra="forbid"`, `validate_assignment=True`, `protected_namespaces=()`. Types: `EntityId` (12 lowercase hex), `Ms` (int >= 0), `PositiveMs`, `RelPath` (relative POSIX, no `..`). `new_id()` makes an id.
- `Anchor(clip_id, source_ms)`: source time, not timeline time.
- `Clip`: `id, source_id, in_ms, out_ms, speed (0.25..8), track (0 = the timeline), overlay, effects`. `out_ms > in_ms`.
- `Line`: `id, text, emotion, exaggeration|None, cfg_weight|None, active_take_id|None, allow_overlap`.
- `Take`: `id, line_id, seed, text, exaggeration, cfg_weight, voice_profile_id, model_version, raw_key, raw_file (RelPath), duration_ms, starred, created`.
- **`Placement`: `id, line_id, anchor: Anchor, take_override_id|None, orphaned: bool`.** Nothing else yet; `stretch` arrives in S8 (schema v2).
- `Keyframe` and `Reaction` also carry `anchor` and `orphaned`.
- `Project`: `schema_version, name, seed, sources, clips, lines, takes, placements, keyframes, reactions, voice_profiles, fx_chain, game_audio_db, avatar, export`. A validator rejects duplicate ids inside each collection.

## Commands and undo (`backend/project/commands.py`)
- `Command` has `label` (property), `apply(project)` and `revert(project)`. `apply` validates first and raises `CommandError` before changing anything, records what it needs to undo, and may be called again after `revert` (that is redo). Commands copy objects they store (`model_copy(deep=True)`) so the project never aliases them.
- `CommandStack(project, on_change=None)`: `execute(cmd)`, `group(label)` (context manager: one undo step, rolls back on error, nested groups merge), `undo()`, `redo()` (both return the label or None, refused inside a group), `clear()`, properties `can_undo, can_redo, undo_label, redo_label, in_group, project`. `on_change` runs after every recorded step; `Session` uses it to save.
- If a revert or a redo-apply raises `CommandError`, the commands already done are re-applied and the error is re-raised, the step stays on its stack.
- Other command modules: `clip_commands.py` (`AddClip, RemoveClip, SetSpeed, ReorderClip`), `placement_commands.py` (`AddPlacement, RemovePlacement, MovePlacement`), `cut_commands.py` (`SplitClip, TrimClip, RippleDelete`), `parking.py`, `line_commands.py` (has `NoChange`, skipped by `Session._execute_unless_no_change`), `voice_commands.py`.

## Time mapping (`backend/edl/timemap.py`, pure, integer ms, round half up)
- The timeline is track 0 of `Project.clips`, gapless, in list order. A clip's timeline length is `round((out - in) / speed)`.
- `clip_spans(clips) -> list[ClipSpan(clip_id, index, start_ms, end_ms, in_ms, out_ms, speed, duration_ms)]`; `timeline_duration(clips)`; `clip_duration_ms(clip)`.
- `to_timeline(clips, anchor, *, spans=None) -> int | None`: `start + round((source_ms - in) / speed)`; None when the clip is not on track 0 or `source_ms` is outside `[in, out]` (`source_ms == out` is accepted and maps to the clip end). Pass `spans` to avoid recomputing.
- `to_source(clips, timeline_ms, *, spans=None) -> Anchor | None`: None outside `[0, duration)`; at a boundary the time belongs to the clip that starts there; result clamped to `out - 1`.
- Frame helpers: `ms_to_frame, frame_to_ms, snap_to_frame` (cut points snap to the source frame grid; playheads and anchors never snap).

## Timeline state and edit ops
- `build_timeline(project, *, can_undo, can_redo, undo_label, redo_label, missing_source_ids) -> TimelineState` (`backend/project/timeline.py`, pure). `TimelineState`, `TimelineClip`, `TimelineSource`, `TimelineProblem`, `EditResult` are mirrored in `api.ts`. `TimelineState` now carries `placements` (S6a, see "Placements").
- `edit_ops.py`: ops tagged by `op` (`add_clip, remove_clip, set_speed, reorder_clip, split_clip, trim_clip, ripple_delete, add_placement, move_placement, remove_placement`), all `extra="forbid"`; `EditOp` is a discriminated union; `EditBatch(label, ops)`; `build_command(op) -> Command`. `line_ops.py` does the same for line edits (`LineEditOp`, `build_line_command(op, known_emotions=...)`).

## Session (`backend/project/session.py`)
One `Session` holds the open project. Pattern for every mutating method: `with self._lock:` then `_, stack = self._require_open()`, build commands, `stack.execute(...)` (a single op without a label) or `with stack.group(label or "...")` (several ops or a label), turn `CommandError` and `ValueError` into `SessionError`, return fresh state. `app.py` maps `SessionError` to HTTP 400 `{"detail": message}`. The lock is re-entrant because `_on_change` saves the project (`save_project`) after every recorded step and sets `_save_error`.
- Lifecycle: `current, new_project, open_project`; footage: `footage, rescan_footage, relink_source, source_path(source_id)`.
- Timeline: `timeline(), add_clip, undo() / redo() -> EditResult, edit(ops, label=None) -> TimelineState` (placement ops go through `edit` too; `Session` itself did not change in S6a).
- Lines and takes: `lines(), edit_lines(ops, label=None), takes(line_id), reuse_take, add_take, delete_take, delete_line, plan_generation, storage(), project_key()`; **`take_path(take_id) -> Path | None`** (disk path of a take, used by the media endpoint; the natural base for a waveform-peaks endpoint).
- Voice: `voice(), set_voice_reference(path)`. Presets load lazily from `templates/emotion_presets.json`.
- Opening a project calls `stack.clear()` after the footage scan, so undo history starts empty.

## Frontend contracts
- `api.ts`: `request<T>(url, init)` throws `Error(detail)` on non-OK; `post<T>(url, body?)` sends JSON. One exported function per endpoint. Edit endpoints for the timeline return `TimelineState`; `editLines` returns `LineBankState`; `undoEdit` / `redoEdit` return `EditResult`. `takeMediaUrl(takeId)` and `sourceMediaUrl(sourceId)` give playable URLs.
- `timeline.ts` (display and playback only; backend `timemap` is the truth): `clipIndexAt, toSource(clip, timelineMs), stepFrame, trimTarget, withTrim, dropSlot, peakSpan(lows, highs, from, to)` (min and max peak between two fractions of a take, one waveform pixel column). No frontend `toTimeline` is needed: the backend sends each placement's `start_ms`.
- `Timeline.svelte`: props `clips, durationMs, playheadMs (bindable), selectedId (bindable), placements, peaks (Record<take id, PeaksReport>), selectedPlacementId (bindable), locked, label, ontrim, onreorder, onplace, onmoveplacement`. One `<canvas>`, constants `RULER_H=26, LANE_Y=32, LANE_H=60, VOICE_Y=100, VOICE_H=46, HEIGHT=156, EDGE_PX=6, GUTTER=40, PLACEHOLDER_MS=1000`. The voice lane is drawn after the cut markers: blocks from `placement.start_ms`, width from `duration_ms` (`placementWidth`), waveform columns from `peaks`, orange outline when orphaned, white when selected, grey with "(no take)" without audio. Internal state: `pxPerMs`, `scrollMs`, `xPos(ms)`; `draw()` is called from an `$effect` and redraws on any state it reads. Pointer handling is in one `$effect` (`down, move, up, cancel, wheel`) with `hit(x, y)` for clips (video lane only) and `hitPlacement(x, y)` for voice blocks; drag modes `scrub`, `press`, `trim`, `move`; `selectedId` is a clip id and `selectedPlacementId` a placement id, never both. Clicking a block selects it and leaves the playhead alone; a click anywhere at or below the video lane that is not a block clears the placement selection. Pressing a block and moving more than 4 px starts a `pmove` drag (ghost block and a marker; the start is clamped to `0..duration-1`, no snapping); one `onmoveplacement(id, startMs)` call on release, so one undo step. A line dragged from the bank (HTML5 drag, data type `LINE_DRAG_TYPE` from `timeline.ts`) shows a drop marker and calls `onplace(lineId, timelineMs)` on drop; the block starts where it is dropped.
- `Editor.svelte`: owns `timeline, playheadMs, selectedId, selectedPlacementId, peaks, busy, error, notice, tab ("footage" | "lines" | "storage"), lineReload, lineBank, jobs, storage`. `edit(action)` runs a call that returns `TimelineState`; `history(...)` runs undo or redo and bumps `lineReload`; `syncHistory()` refreshes only the undo and redo fields after a line edit. Hotkeys are one `onKeyDown` with a `switch (e.key)`, ignored while typing (`isTyping`), `canEdit = !busy && !e.repeat`. Handled: Space, `,` `.`, G / Shift+G (`lineBank.generateSelected(shift)`), N, **M** (`placeSelected` calls `placeAt(lineId, playhead)`, the same function a drop uses: `placeLine(lineId, ms, newLineId())`, then selects the new block and bumps `lineReload`). `movePlacementByDrag(id, ms)` wraps `movePlacement` for block drags, S, Delete (removes the selected placed line, else the selected clip), `[`, `]`, Ctrl+Z, Ctrl+Y. An `$effect` fetches `getTakePeaks` once per placed take into `peaks`. `LineBank` takes `reloadToken, onedited, jobs, onjobchange` and exports `generateSelected(reroll)`, `addLine()` and `selectedLineId()` (S6b); the selected line id is internal state (`selectedId`, set by clicking a row). Rows are draggable (`startDrag` selects the line and sets `LINE_DRAG_TYPE`).
- Editor layout (UI-1): `Editor.svelte` is `position: fixed; inset: 0`, a flex column: header, messages, `.workspace`, status bar. `.workspace` holds `.top` (preview left with `Player`, a vertical divider, `.side` with the Footage / Line bank / Storage tabs) and, under a horizontal divider, `.bottom` (the `Timeline`, clip bar, shortcuts `<details>`, clip table; scrolls). Pane sizes are `sideW` and `topH` (px), kept in the module-level `layout` object so they survive leaving the editor within one app session (not in `project.json`); clamped to `SIDE_MIN=320` / `TOP_MIN=180` and to the window; dividers are focusable separators (pointer drag, arrow keys, Shift for big steps). Dark theme: CSS variables `--bg --panel --panel-2 --line --text --muted --accent --danger` on `.editor` with `color-scheme: dark`; child components are themed with `:global` descendant selectors (`.error`, `.missing`, `.bad` use `--danger`; `.side :global(.bank)` is one column; `.preview :global(.player/video)` lose their max-width and get a max-height from `--top-h`), so their files are unchanged. New panels (Inspector, Voice FX) go in the `.side` tab strip.
- `Player.svelte`: props `clips, durationMs, playheadMs (bindable)`; one `<video>` hopping between clips; exports `toggle()` and `pause()`; writes `playheadMs` itself while playing and recognises its own writes (`selfPlayhead`), so an outside change pauses and re-cues. Voice playback (S7) must hook into this clock.
- Placement edits share the one undo stack with clip and line edits, so after any placement edit the editor must reload the timeline (placements) and the line bank (`placement_count`, via `lineReload`).

## Spec excerpts for S6 (`docs/DESIGN_SPEC.md`, sections 4.2 and 5)
- Timeline lanes, top to bottom: video strip, **voice lane (placed lines as blocks with waveform; red edge on overflow)**, expression lane, parameter lanes (collapsible), reaction lane, game audio level. Status bar: GPU queue, loudness meter, disk usage of takes.
- Hotkeys: **M places the selected line at the playhead**; E adds an expression key; R drops a reaction; N, G, Shift+G as above.
- Entity row: `Placement`: id, line id, anchor (clip id, source_ms), take override, orphaned flag.
- Anchoring rule: every timed item is anchored to a clip plus a source time, and timeline time is computed by mapping through the clip list. Re-trimming, reordering or changing speed never makes lines drift. If a trim removes the moment an item was anchored to, the item is flagged orphaned and parked at the nearest edge for the user to resolve. Bookend clips (overlay off) carry no anchored items.
