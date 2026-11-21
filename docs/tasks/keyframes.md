# Keyframes: editing, easing, lane-clip keys, keys past the footage

- **Milestone item:** follow-up after M8-2 (`PROJECT_STATE.md`, Next up 2)
- **Spec sections:** 4.2, 5, 8, 9
- **Status:** done (branch `m8-keyframes`, 2026-11-22; user confirmed every step in the app; not merged yet)

## Goal

Avatar keys are easy to change after they are set, keys can ease in or out, video-lane clips can be keyed (x, y, size, opacity) with the preview and the export drawing the same thing, and avatar keys and reactions can sit past the end of the footage.

## How keys work now (found in the code)

- A key is `Keyframe(lane_id, anchor, value, interpolation hold|smooth)`; `smooth` is a smoothstep to the next key (`backend/avatar/lanes.py`).
- Timeline: diamonds on the expression row and one collapsed "Motion keys" row (or one row per lane); click selects, drag sideways moves. Values are not edited on the timeline.
- Avatar tab inspector: the selected key's value (slider), easing, "Move to playhead", Delete.
- Preview drag of the avatar keys x and y (resize: scale) at the playhead through `key_lane_by`. It changes a key only when one sits **exactly** at the playhead's anchor, otherwise it adds a new key; selecting a key does not move the playhead to it.
- Keys and reactions need footage under them (`_anchor_at` refuses a time past the footage).
- Lane clips have one x, y, scale and opacity each (`LaneClip`); preview maths in `frontend/src/videoLanes.ts` (`pipRect`), export in `backend/export/lanes.py` (`pip_rect`, `colorchannelmixer`, `overlay`).

## Scope

**In:** the four parts below. **Out:** curve editor with handles, keys on audio clips, keys on the main footage, captions and other backlog items.

## Steps (each: user checks in the app, then a commit)

1. **Decisions** (below), logged here and in `PROJECT_STATE.md`.
2. **Easing:** wider interpolation set in the lane maths (pure, tested), schema v7 with a migration, the inspector's easing menu.
3. **Key editing fixes** (from the user's answer to decision 1): commands (undoable) plus timeline and inspector UI.
4. **Keys past the footage:** a key or reaction past the last footage clip is stored with a timeline time; solver input, timeline payload, commands and orphan rules updated; tests.
5. **Image-clip keys, data and commands** (decision 5: image clips only): keys on an image `LaneClip`, timed from the clip start; add, move, change, remove; trim, split and freeze keep the keys on the picture; tests.
6. **Lane-clip keys, evaluation:** one pure evaluation in Python and the same in TypeScript, checked against one shared table of cases by pytest and `npm test`.
7. **Lane-clip keys, preview and timeline:** `LaneLayers.svelte` draws the keyed values at the playhead, `LaneHandles.svelte` drags write keys when the clip has keys, diamonds on the clip block, the clip bar edits the key at the playhead.
8. **Lane-clip keys, export:** `lanes.py` animates position, size and opacity; a real-render test compares frames with the evaluation.
9. **Wrap-up:** `PROJECT_STATE.md`, spec 4.2, 5, 8, 9 as built.

## Decisions

| # | Question | Answer |
|---|---|---|
| 1 | What bothers you most when changing a key? | All of: a preview drag adds a key unless the playhead is exactly on one; the playhead is hard to put exactly on a key; stacked x/y/scale keys in the collapsed row; values need the slider; moving keys is fiddly. Fixes: selecting a key moves the playhead onto it; drags and inspector edits change the key within one frame of the playhead; keys at one time on one row are a group; typed values, x/y/scale of the moment together; key drags snap; Shift-click and box select; previous/next key buttons |
| 2 | Easing set | Presets plus strength: Hold, Linear, Ease in, Ease out, Ease in-out, and a strength 0 to 2 (0 linear, 1 normal = default, 2 strong). Strength 1: quadratic in/out, smoothstep in-out (old `smooth`); 2: cubic, smootherstep; blended between. v7 migrates `smooth` to `ease_in_out`, strength 1 |
| 3 | Lane-clip key timing and layout | Timed from the clip start (move with the clip; a start trim keeps keys on the same picture moment; a split shares them); one track per property (x, y, size, opacity), same easing and strength. With keys on a property, preview drags and the clip bar key it at the playhead; without keys, the single clip value as today. Diamonds inside the clip block |
| 4 | Keys and reactions past the footage | Placed or moved past the footage end: a timeline time (no anchor), never moved by footage edits, stays so if the footage grows over it (pin mark). A user move decides again (onto footage: anchored). Never orphaned. Rule 4's exception in `CLAUDE.md` gains these |
| 5 | Which lane clips get keys? | Images only (PNG, JPG: one image clip type) for now; keys on recordings and freeze frames go to the backlog as a future improvement (user) |

## As built

- Steps 2 to 8 landed as one commit each (`git log m8-keyframes`); step 3 was split into 3a (playhead onto keys, edits within one frame, previous/next), 3b (groups, Shift-click, box select, group move and delete, snapping) and 3c (typed values, the moment's x/y/size/rotation together).
- Lane-clip keys are on image clips only (decision 5); the third criterion holds for image clips.
- Schema v7 (easing), v8 (keys and reactions past the footage), v9 (image clip keys).
- Not built: an easing curve drawn between keys on the timeline; multi-select for image clip keys.

## Acceptance criteria

- [x] A selected key's value and time can be changed without hunting for the exact playhead time (per decision 1)
- [x] Easing options work in the preview and the export (solver output)
- [x] A lane clip can fade and move over time; the preview and the export match frame for frame within rounding
- [x] Keys and reactions can be placed past the end of the footage and export there
- [x] Every change is one undo step; old projects open (migration)
- [x] Tests for all pure logic; pytest, ruff, `npm run check`, `npm test`, `npm run build` clean
- [x] `PROJECT_STATE.md` and spec updated
