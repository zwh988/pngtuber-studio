# UI-2: UI/UX overhaul and polish (shared theme, components, every existing screen)

> Written 2026-11-17 after M6, before M7's UI steps. Sources: `docs/DESIGN_SPEC.md` section 4 (screens, layout, hotkeys), `PROJECT_STATE.md` (UI-1 decisions, known issues, "Next up" item 3), `docs/tasks/M7-polish.md` and the frontend as of `m6-done`. Nothing here has been built. The questions under "Decisions" are for the user at the start; the answers go into the decisions log in `PROJECT_STATE.md`.

- **Spec sections:** 4.1 to 4.3 (layout and behaviour stay as written; this task changes how they look and feel).
- **Branch:** `ui-2-overhaul` (from `main` after M7 S1 is settled and logged).
- **Where it sits:** after M7 S1 (decisions), before M7 S3 to S6 (first-run screen, empty states, Settings, hotkey map, templates), so those are built on the new theme. M7 S2 (`install.bat`) does not touch the frontend and can go before or alongside it. M7 S7 (clean install) stays last.
- **Status:** not started.
- **Done when:** every existing screen uses one shared theme and a small set of shared components, UI-1d and UI-1e are done, and every feature that worked at `m6-done` still works.

## Facts already established (do not re-ask)

- **Frontend:** Svelte 5 + TypeScript strict + Vite 6, 13 components (about 6400 lines). The biggest are `Editor.svelte` (1363), `Timeline.svelte` (942), `LineBank.svelte` (684), `App.svelte` (565), `VoiceFx.svelte` (539).
- **The theme today:** colour variables (`--bg`, `--panel`, `--panel-2`, `--line`, `--text`, `--muted`, `--accent`, `--danger`) are defined on `.editor` in `Editor.svelte` and again in `ExportScreen.svelte`. Child components are restyled from the Editor through 6 `:global` blocks (UI-1 decision), so their own files have almost no variables. `App.svelte` (project screen) has none and still has the old light look.
- **Timeline canvas colours are hex literals** inside the draw code of `Timeline.svelte` (ruler, clips, voice blocks, overflow red, keyframe yellow, reaction purple, selection white or orange, and so on: 25+ places).
- **Carry-overs folded in here (M7 decision 6):** UI-1d (lane colours, a clearer selected state), UI-1e (icon buttons, collapsible parameter lanes). The storage-size and clean-up carry-overs stay in M7 S4.
- **Known rough edges:** the side panel has a 320 px minimum, so a narrow window leaves little room for the preview. `npm run check` shows 4 old a11y warnings in `Editor.svelte`. Pane sizes live in a module-level `layout` object, not in `project.json` (keep it that way).
- **Rule 8 (offline):** no CDN fonts, icon fonts or remote CSS. Anything visual is bundled by Vite into `frontend/dist`.
- **Rule 5 (preview equals export):** `AvatarOverlay.svelte` draws solver output with the same layout maths as `backend/export/compositor.py`. Its sprite drawing must not change; only its chrome (hover box, handle) may be restyled.

## Decisions (settled 2026-11-17, see the decisions log in `PROJECT_STATE.md`)

> **Settled:** all six as recommended. One consistent, clean, professional dark theme, with no light theme or switcher. A bundled icon package. The original wording follows for reference.

1. **Direction:** refine the current dark editor look and extend it to every screen, or a new visual direction (colours, density, rounding)? **Recommendation:** refine the dark look; the user already confirmed it in UI-1. A one-page mock of the editor and the project screen comes first, to approve before restyling anything.
2. **Icons:** a bundled icon package (for example `lucide-svelte`, tree-shaken, MIT) or a few hand-picked inline SVGs in one `icons.ts`? **Recommendation:** the package, pinned in `package.json`; only the icons used end up in the build.
3. **Font:** the system UI font (Segoe UI on Windows) or a bundled font file? **Recommendation:** the system font, plus tabular numbers for times and values.
4. **Light theme:** add one, or dark only? **Recommendation:** dark only. The tokens make a light theme possible later (backlog).
5. **Layout changes:** keep spec 4.2's layout (preview top left, tabs top right, timeline across the bottom), or rearrange? **Recommendation:** keep it. Allowed changes: spacing, grouping inside panels, a smaller minimum side panel, collapsible sections.
6. **Smallest window to support:** **Recommendation:** 1280 x 720 without overlapping or clipped controls.

## Steps

1. **S1 Decisions and audit.** Settle the questions above and log them. The user takes a screenshot of each screen and state (project screen empty and with a project, editor with each tab, timeline with every lane open, export screen before, during and after an export). Produce a short audit list: inconsistencies, cramped or unclear spots, controls that need icons, missing hover, focus and disabled states. Write and approve the mock (decision 1). **Manual check.**
2. **S2 Shared theme.** A new `frontend/src/theme.css` imported once in `main.ts`: colour, spacing, radius, font and shadow tokens on `:root`, plus base styles (body, buttons, inputs, focus ring, scrollbars). Remove the duplicated variables from `Editor.svelte` and `ExportScreen.svelte`. Nothing should look different yet, apart from the project screen turning dark. **Manual check.**
3. **S3 Shared components.** Keep the set small: `Button` (primary, secondary, danger, ghost; with an optional icon), `IconButton` (with a tooltip and an `aria-label`), `Section` (a collapsible titled group for panels), `Banner` (info, warning, error; M7 S4 reuses it for its messages). Move each `:global` restyle out of `Editor.svelte` into the component it styles. **Manual check.**
4. **S4 Project screen** (`App.svelte`): restyled on the theme and components. Recent list, footage table, voice profile and avatar sections, relink, save-failure banner.
5. **S5 Editor panels:** Line bank, inspector, take picker and `TakeTrimmer`, Voice FX (`VoiceFx`, `FxSlider`), Avatar (`AvatarPanel`, `ParamSlider`), Storage (`StorageList`), the tab strip, the header and the status bar. Icon buttons where a text button is a repeated action (play, star, delete, reroll, key-here). Clear hover, focus, disabled and selected states. Lower the side panel's minimum width if decision 6 needs it. Fix the 4 a11y warnings. **Manual check.**
6. **S6 Timeline** (`Timeline.svelte`, UI-1d, UI-1e): every canvas colour comes from one table in a new `frontend/src/timelineTheme.ts` (read once from the CSS tokens, so the canvas and the panels match). Each lane gets its own colour, and one consistent selected state (outline plus a brighter fill) covers clips, blocks, keys and reactions. Lane headers become collapsible, with icon buttons. Leave hit testing, drag and zoom logic alone. **Manual check.**
7. **S7 Export screen and the whole app at the smallest size** (`ExportScreen.svelte`): restyled. Then every screen at 1280 x 720 and at full screen. **Manual check.**
8. **S8 Regression pass and wrap-up.** Run the regression list below, then update `PROJECT_STATE.md` (repo map, UI decisions, the UI-1 known issue closed) and spec 4 only where the look is described. Merge, then tag `ui-2-done`.

## Acceptance checks (user runs these)

- No colour literals in `.svelte` style blocks or in `Timeline.svelte` draw code. Colours come only from `theme.css` and `timelineTheme.ts`. Check with: `Get-ChildItem frontend\src -Filter *.svelte | Select-String -Pattern '#[0-9a-fA-F]{3,8}\b'` (a few deliberate exceptions, such as sprite-checker backgrounds, are listed in the decisions log).
- No `:global` restyles left in `Editor.svelte`, other than layout.
- The project screen, editor and export screen share one look, and nothing is clipped or overlapping at 1280 x 720.
- Every icon-only button has a tooltip and an `aria-label`. Keyboard focus is visible everywhere. The hotkeys from spec 4.2 work as before.
- **Regression list** (each one worked at `m6-done`): create a project and open a recent one; rescan and relink; add, trim, split, reorder, speed and ripple-delete clips; undo and redo; write, generate, reroll and cancel a line; pick, star and trim a take; place, move and Tighten a line, and see the overflow edge; change a Voice FX preset and the game audio level; key an expression (E) and a reaction (R), drag the avatar and its handle; open the lanes and drag a key; delete a take in Storage; a test export of 10 s.
- `npm run check` reports 0 errors and 0 warnings. `npm test` and `npm run build` pass. `uv run pytest` is unchanged, since there are no backend changes.

## Out of scope (do not touch)

- Backend code, API shapes, `project.json` schema, commands and the undo stack.
- New features and the M7 screens: first-run, Settings, hotkey map, template picker and the empty-state audit (M7 S3 to S6 build them on this theme).
- Rebindable hotkeys, a light theme, saved pane sizes, an animation pass.
- How the avatar is drawn (rule 5), and the timeline's time maths, hit testing and drag logic.

## Risks and open points

- **`Timeline.svelte` is large and hand-drawn.** Change colours and lane headers only, in small commits, and run the drag checks after each one.
- **Removing `:global` blocks can drop a style without any error.** Compare screenshots before and after S3.
- **Scope creep:** "polish" never ends. Anything not in the S1 audit list goes to the backlog in `IMPLEMENTATION_PLAN.md`.
- **The icon package adds a dependency.** Pin the version, commit `package-lock.json`, and check it is bundled (rule 8).

## S1 audit (2026-11-17)

The agent drove the real frontend in a browser at 1280 x 760, against a hard-linked copy of `Rack 1` (`scripts/spike/out/ui_audit/`, git-ignored). It covered: the empty project screen, the project screen with a project open, the editor with each tab (Footage, Line bank with a line selected, Storage, Voice FX, Avatar), the timeline with the lanes open and a voice block selected, and the export screen before an export. Not covered: the export screen during and after an export, and `TakeTrimmer` (open it in S5).

**Cross-cutting**
- C1 Three unrelated button styles: native light buttons on the project screen, small grey ones in the editor, large ones on the export screen.
- C2 No type scale. Headings are a different size on each screen, and help text ranges from tiny to body size.
- C3 Native checkboxes, selects and number inputs are unstyled. A select shows light-on-dark in the Voice FX tab.
- C4 No shared focus ring, and hover, disabled and selected states differ per component.
- C5 4 a11y warnings: the two pane dividers (`Editor.svelte` lines 780 and 906) are focusable `div`s with key handlers.

**Project screen (`App.svelte`)**
- P1 Still light with browser defaults. It does not look like the same app as the editor.
- P2 One long page: the open project, Footage, Voice, Avatar, then Recent, New and Open below the fold. Proposal: a Home state (the recent list as the main content, with New and Open as actions) and a Project state (a header with the name and a primary "Open editor" button, then Footage, Voice and Avatar as cards).
- P3 Statuses are plain words ("path set", red "missing"). Use status badges (ok, warning, missing) and show Relink next to the badge.
- P4 Long help paragraphs (art folder naming, "the art stays in its own folder") are always visible. Collapse them behind a help line.

**Editor shell (`Editor.svelte`, `Player.svelte`)**
- E1 The header says "Editor", not the project name. Back, Undo and Redo are text buttons; make them icon buttons with tooltips. Make Export the one primary button.
- E2 Player: a "Play" text button, a plain scrub bar, and "Clip 1 of 1 (1x)" floating under it. Use an icon play/pause, frame-step buttons, and tabular-number time.
- E3 Status bar: fine content, flat text. Use compact segments with icons (voice model, GPU queue, takes on disk, loudness).

**Side panel tabs**
- T1 Tab strip: the selected tab is only a lighter box. Use one tab style with a clear accent underline.
- T2 Line bank: each take row wraps onto two or three lines ("3.3 s, seed ..., exaggeration 0.75, pacing 0.05") with up to four text buttons. Use a one-line row: icon buttons (play, trim, star, use), the details as muted small text, and Active as a badge. "Hotkey N." next to Add line becomes a keyboard chip or tooltip.
- T3 Voice FX: presets as small buttons (use a segmented control); each slider takes two rows (label and value above, slider below). Use a compact row: label left, value right, slider under, with tighter spacing.
- T4 Avatar: the ◆ key-here buttons are tiny grey squares with no visible meaning. Use an icon button ("Key at playhead") with a tooltip. Sliders as in T3.
- T5 Storage: a repeated grey "Delete take" on every row. Use a trash icon button that keeps the inline confirm, and group each line as a card.
- T6 Each tab keeps its own scroll position (the Avatar tab opened half-scrolled). Keep that, but give section headers that stay readable.

**Timeline (`Timeline.svelte`)**
- L1 The toolbar's "Zoom out", "Zoom in", "Fit" and "▸ Lanes" wrap onto two lines, and a long help sentence takes the rest of the row. Use icon buttons, with the help behind a "?" tooltip.
- L2 Lane names are tiny dim text drawn inside the canvas, with no header column. Add a fixed lane header column (name, collapse toggle) (UI-1e).
- L3 Colours: a blue clip and a green voice block. The selected voice block only gets a thin white outline. Give one consistent selected state for clips, blocks, keys and reactions, and a colour per lane (UI-1d).
- L4 The playhead red and the overflow red are the same colour; separate them.
- L5 Empty Expression and Reactions rows give no hint of how to add something (E and R).
- L6 At 760 px high the open lanes are cut off below Blink rate, and the pane scrolls on its own. The lane header column must scroll with the rows.

**Export screen (`ExportScreen.svelte`)**
- X1 Dark, but with its own button and heading sizes. Content hugs the left edge with an empty right half. Use a centred column, or two columns: options left, pre-flight right.
- X2 Pre-flight is a line of text. Use a status list with icons, and errors and warnings as badges.
