<script lang="ts">
  import { untrack } from "svelte";
  import type {
    PeaksReport,
    TimelineClip,
    TimelineKeyframe,
    TimelinePlacement,
    TimelineReaction,
  } from "./api";
  import { MOTION_LANES, laneLabel } from "./avatarLanes";
  import { clock } from "./format";
  import { LINE_DRAG_TYPE, dropSlot, peakSpan, trimTarget, withTrim } from "./timeline";
  import { FALLBACK, readTimelineColors, type TimelineColors } from "./timelineTheme";
  import {
    ChevronDown,
    ChevronRight,
    CircleHelp,
    Maximize2,
    Rows3,
    ZoomIn,
    ZoomOut,
  } from "@lucide/svelte";
  import IconButton from "./ui/IconButton.svelte";

  let {
    clips,
    durationMs,
    playheadMs = $bindable(0),
    selectedId = $bindable(null),
    placements = [],
    peaks = {},
    selectedPlacementId = $bindable(null),
    locked = false,
    label,
    ontrim,
    onreorder,
    onplace,
    onmoveplacement,
    keyframes = [],
    reactions = [],
    selectedKeyId = $bindable(null),
    selectedReactionId = $bindable(null),
    onmovekey,
    onmovereaction,
  }: {
    clips: TimelineClip[];
    durationMs: number;
    playheadMs?: number;
    selectedId?: string | null;
    /** Placed lines for the voice lane. */
    placements?: TimelinePlacement[];
    /** Waveform peaks by take id; a block without an entry is drawn plain. */
    peaks?: Record<string, PeaksReport>;
    selectedPlacementId?: string | null;
    /** True while an edit is in flight: drags that would edit are ignored. */
    locked?: boolean;
    label: (clip: TimelineClip) => string;
    /** One call per drag, on release. `sourceMs` is SOURCE time. Resolves when the edit is done. */
    ontrim: (clipId: string, edge: "in" | "out", sourceMs: number) => Promise<void>;
    /** One call per drag, on release. `newPosition` is the clip's position after the move. */
    onreorder: (clipId: string, newPosition: number) => Promise<void>;
    /** A line was dropped from the bank. `timelineMs` is TIMELINE time. Resolves when the edit is done. */
    onplace: (lineId: string, timelineMs: number) => Promise<void>;
    /** A voice block was dragged. `timelineMs` is where its START goes (TIMELINE time). */
    onmoveplacement: (placementId: string, timelineMs: number) => Promise<void>;
    /** Avatar lane keys and reactions (M5-5, M5-7), times already mapped by the backend. */
    keyframes?: TimelineKeyframe[];
    reactions?: TimelineReaction[];
    selectedKeyId?: string | null;
    selectedReactionId?: string | null;
    /** A key or reaction was dragged sideways: its new TIMELINE time. One call per drag. */
    onmovekey?: (keyframeId: string, timelineMs: number) => Promise<void>;
    onmovereaction?: (reactionId: string, timelineMs: number) => Promise<void>;
  } = $props();

  /** Width of the grab zone at each clip edge, in pixels. */
  const EDGE_PX = 6;
  const RULER_H = 26;
  const LANE_Y = 32;
  const LANE_H = 60;
  /** The voice lane sits under the video lane. */
  const VOICE_Y = LANE_Y + LANE_H + 8;
  const VOICE_H = 46;
  /** Avatar rows under the voice lane: expression, reactions, then the motion lanes. */
  const EXPR_Y = VOICE_Y + VOICE_H + 6;
  const ROW_H = 20;
  const REACT_Y = EXPR_Y + ROW_H + 3;
  const MOTION_Y = REACT_Y + ROW_H + 3;
  const KEY_R = 5;
  /** Collapsed: one row with every motion key. Expanded: one row per motion lane. */
  let lanesOpen = $state(false);
  /** The how-to text under the toolbar (the "?" button). */
  let helpOpen = $state(false);
  const motionRows = $derived(lanesOpen ? MOTION_LANES.length : 1);
  const HEIGHT = $derived(MOTION_Y + motionRows * (ROW_H + 2) + 8);
  /** Width given to a placed line that has no take yet, in ms. */
  const PLACEHOLDER_MS = 1000;
  /** Empty space kept to the right of the last clip, in pixels. */
  const GUTTER = 40;
  const MIN_PX = 0.0005;
  const MAX_PX = 2;
  const STEPS = [
    10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000,
    600000,
  ];

  let canvasEl = $state<HTMLCanvasElement | null>(null);
  /** Canvas colours from the theme tokens (timelineTheme.ts), read once the canvas exists. */
  let colors = $state<TimelineColors>(FALLBACK);
  let viewWidth = $state(0);
  /** Zoom: pixels per millisecond. */
  let pxPerMs = $state(0.1);
  /** Timeline time at the left edge of the view (ms). */
  let scrollMs = $state(0);
  let fitted = false;

  type Hit = { clip: TimelineClip; part: "in" | "out" | "body" };
  type TrimDrag = { mode: "trim"; clip: TimelineClip; edge: "in" | "out"; sourceMs: number };
  type MoveDrag = { mode: "move"; clip: TimelineClip; grabDx: number; slot: number };
  type PlacementDrag = {
    mode: "pmove";
    placement: TimelinePlacement;
    grabDx: number;
    startMs: number;
  };
  type ItemDrag = {
    mode: "ipress" | "imove";
    kind: "key" | "reaction";
    id: string;
    fromMs: number;
    startX: number;
    toMs: number;
  };
  type Drag =
    | ItemDrag
    | { mode: "scrub" }
    | { mode: "press"; clip: TimelineClip; startX: number }
    | { mode: "ppress"; placement: TimelinePlacement; startX: number }
    | TrimDrag
    | MoveDrag
    | PlacementDrag;
  type DragUi =
    | { kind: "trim"; x: number }
    | { kind: "move"; clipId: string; ghostX: number; slotMs: number }
    | { kind: "pmove"; ghostX: number; width: number }
    | { kind: "drop"; x: number }
    | { kind: "imove"; id: string; ms: number };

  /** Pointer interaction in progress (not reactive: only the handlers use it). */
  let drag: Drag | null = null;
  /** Clip list with the dragged edge applied, drawn instead of `clips` during a trim drag. */
  let preview = $state<TimelineClip[] | null>(null);
  let dragUi = $state<DragUi | null>(null);

  const viewMs = $derived(viewWidth / pxPerMs);
  const maxScrollMs = $derived(Math.max(0, durationMs - (viewWidth - GUTTER) / pxPerMs));

  function xPos(ms: number): number {
    return (ms - scrollMs) * pxPerMs;
  }

  /** Row (y) of a motion key: its own lane when the lanes are open, the summary row otherwise. */
  function motionRowY(laneId: string): number {
    const index = lanesOpen ? Math.max(0, MOTION_LANES.indexOf(laneId)) : 0;
    return MOTION_Y + index * (ROW_H + 2);
  }

  function keyRowY(key: TimelineKeyframe): number {
    return key.lane_id === "expression" ? EXPR_Y : motionRowY(key.lane_id);
  }

  /** Time an item is drawn at (its drag position while it is being dragged). */
  function shownMs(id: string, t: number | null): number | null {
    const ui = dragUi;
    return ui !== null && ui.kind === "imove" && ui.id === id ? ui.ms : t;
  }

  function placementWidth(p: TimelinePlacement): number {
    return Math.max(3, (p.duration_ms ?? PLACEHOLDER_MS) * pxPerMs);
  }

  function clampPx(px: number): number {
    return Math.min(Math.max(px, MIN_PX), MAX_PX);
  }

  function setScroll(ms: number): void {
    scrollMs = Math.min(Math.max(ms, 0), maxScrollMs);
  }

  function fit(): void {
    if (viewWidth <= 0 || durationMs <= 0) {
      return;
    }
    pxPerMs = clampPx((viewWidth - GUTTER) / durationMs);
    scrollMs = 0;
  }

  /** Zoom by `factor`, keeping the time under view-x `x` where it is. */
  function zoomAt(factor: number, x: number): void {
    const anchorMs = scrollMs + x / pxPerMs;
    pxPerMs = clampPx(pxPerMs * factor);
    setScroll(anchorMs - x / pxPerMs);
  }

  function rulerLabel(t: number, step: number): string {
    const m = Math.floor(t / 60000);
    const s = String(Math.floor((t % 60000) / 1000)).padStart(2, "0");
    if (step >= 1000) {
      return `${m}:${s}`;
    }
    return `${m}:${s}.${String(t % 1000).padStart(3, "0")}`;
  }

  function draw(): void {
    const canvas = canvasEl;
    if (canvas === null || viewWidth <= 0) {
      return;
    }
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(viewWidth * dpr);
    canvas.height = Math.round(HEIGHT * dpr);
    const ctx = canvas.getContext("2d");
    if (ctx === null) {
      return;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const xOf = (ms: number): number => (ms - scrollMs) * pxPerMs;
    const c = colors;
    const font = (px: number, weight = 400): string => `${weight} ${px}px ${c.font}`;
    /** One selected look for every item: a white outline inside an accent ring. */
    const selectRect = (x: number, y: number, w: number, h: number): void => {
      ctx.lineWidth = 2;
      ctx.strokeStyle = c.selectedRing;
      ctx.strokeRect(x - 1, y - 1, w + 2, h + 2);
      ctx.strokeStyle = c.selected;
      ctx.strokeRect(x + 1, y + 1, Math.max(1, w - 2), Math.max(1, h - 2));
    };

    ctx.fillStyle = c.background;
    ctx.fillRect(0, 0, viewWidth, HEIGHT);

    // Ruler
    ctx.fillStyle = c.ruler;
    ctx.fillRect(0, 0, viewWidth, RULER_H);
    ctx.fillStyle = c.rowLine;
    ctx.fillRect(0, RULER_H - 1, viewWidth, 1);
    const step = STEPS.find((s) => s * pxPerMs >= 90) ?? STEPS[STEPS.length - 1] ?? 1000;
    const minor = step / 5;
    ctx.font = font(11);
    ctx.textBaseline = "top";
    ctx.lineWidth = 1;
    const endMs = scrollMs + viewMs;
    for (let t = Math.floor(scrollMs / minor) * minor; t <= endMs; t += minor) {
      const x = Math.round(xOf(t)) + 0.5;
      const major = t % step === 0;
      ctx.strokeStyle = major ? c.rulerMajor : c.rulerMinor;
      ctx.beginPath();
      ctx.moveTo(x, RULER_H);
      ctx.lineTo(x, RULER_H - (major ? 10 : 5));
      ctx.stroke();
      if (major && t >= 0) {
        ctx.fillStyle = c.rulerText;
        ctx.fillText(rulerLabel(t, step), x + 3, 4);
      }
    }

    // Video strip lane
    const shown = preview ?? clips;
    // Clips alternate between two tones by source, so cuts between recordings stand out.
    const tones = new Map<string, number>();
    for (const clip of clips) {
      if (!tones.has(clip.source_id)) {
        tones.set(clip.source_id, tones.size % 2);
      }
    }
    for (const clip of shown) {
      const x0 = xOf(clip.start_ms);
      const w = Math.max(1, clip.duration_ms * pxPerMs);
      if (x0 + w < 0 || x0 > viewWidth) {
        continue;
      }
      const missing = clip.source?.file_missing ?? true;
      ctx.globalAlpha = dragUi?.kind === "move" && dragUi.clipId === clip.id ? 0.35 : 1;
      const selected = clip.id === selectedId;
      ctx.fillStyle = tones.get(clip.source_id) === 1 ? c.clipAlt : c.clip;
      if (selected) {
        ctx.filter = "brightness(1.2)";
      }
      ctx.fillRect(x0, LANE_Y, Math.max(1, w - 1), LANE_H);
      ctx.filter = "none";
      if (missing) {
        ctx.strokeStyle = c.missing;
        ctx.lineWidth = 2;
        ctx.strokeRect(x0 + 1, LANE_Y + 1, Math.max(1, w - 3), LANE_H - 2);
      }
      if (selected) {
        selectRect(x0, LANE_Y, Math.max(1, w - 1), LANE_H);
      }
      if (w > 30) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(x0, LANE_Y, w - 1, LANE_H);
        ctx.clip();
        ctx.fillStyle = c.clipText;
        ctx.textBaseline = "top";
        ctx.font = font(11, 600);
        ctx.fillText(missing ? `${label(clip)} (missing)` : label(clip), x0 + 6, LANE_Y + 6);
        ctx.font = font(11);
        ctx.fillStyle = c.clipTextMuted;
        ctx.fillText(clock(clip.duration_ms), x0 + 6, LANE_Y + 22);
        ctx.restore();
      }
      if (clip.speed !== 1 && w > 40) {
        const text = `${clip.speed}x`;
        const tw = ctx.measureText(text).width;
        ctx.fillStyle = c.speedBadge;
        ctx.fillRect(x0 + w - tw - 14, LANE_Y + 4, tw + 10, 16);
        ctx.fillStyle = c.speedText;
        ctx.textBaseline = "top";
        ctx.fillText(text, x0 + w - tw - 9, LANE_Y + 6);
      }
    }

    ctx.globalAlpha = 1;

    // Cut markers between clips
    ctx.strokeStyle = c.cut;
    ctx.lineWidth = 1.5;
    for (let i = 1; i < shown.length; i += 1) {
      const clip = shown[i];
      if (clip === undefined) {
        continue;
      }
      const x = Math.round(xOf(clip.start_ms));
      if (x < -2 || x > viewWidth + 2) {
        continue;
      }
      ctx.beginPath();
      ctx.moveTo(x, LANE_Y - 4);
      ctx.lineTo(x, LANE_Y + LANE_H + 4);
      ctx.stroke();
    }

    // Voice lane: placed lines as blocks with their waveform
    ctx.fillStyle = c.row;
    ctx.fillRect(0, VOICE_Y, viewWidth, VOICE_H);
    if (placements.length === 0) {
      ctx.font = font(11);
      ctx.fillStyle = c.hint;
      ctx.textBaseline = "middle";
      ctx.fillText(
        "Voice lane: select a line in the bank, move the playhead, press M",
        8,
        VOICE_Y + VOICE_H / 2,
      );
      ctx.textBaseline = "top";
    }
    for (const p of placements) {
      if (p.start_ms === null) {
        continue;
      }
      const x0 = xOf(p.start_ms);
      const w = placementWidth(p);
      if (x0 + w < 0 || x0 > viewWidth) {
        continue;
      }
      const picked = p.id === selectedPlacementId;
      const noAudio = p.take_id === null;
      ctx.fillStyle = noAudio ? c.voiceEmpty : c.voice;
      if (picked) {
        ctx.filter = "brightness(1.2)";
      }
      ctx.fillRect(x0, VOICE_Y + 2, Math.max(1, w - 1), VOICE_H - 4);
      ctx.filter = "none";
      const report = p.take_id === null ? undefined : peaks[p.take_id];
      if (report !== undefined && w > 4) {
        const midY = VOICE_Y + 14 + (VOICE_H - 18) / 2;
        const half = (VOICE_H - 18) / 2 - 1;
        ctx.fillStyle = c.wave;
        ctx.globalAlpha = 0.8;
        const first = Math.max(0, Math.floor(-x0));
        const last = Math.min(Math.ceil(w), Math.ceil(viewWidth - x0));
        for (let col = first; col < last; col += 1) {
          const [low, high] = peakSpan(report.lows, report.highs, col / w, (col + 1) / w);
          const top = midY - high * half;
          const bottom = midY - low * half;
          ctx.fillRect(x0 + col, top, 1, Math.max(1, bottom - top));
        }
        ctx.globalAlpha = 1;
      }
      if (w > 30) {
        const text = p.line_text === "" ? "(line gone)" : p.line_text;
        ctx.save();
        ctx.beginPath();
        ctx.rect(x0, VOICE_Y, Math.max(1, w - 1), VOICE_H);
        ctx.clip();
        ctx.fillStyle = c.clipText;
        ctx.textBaseline = "top";
        ctx.font = font(10, 600);
        ctx.fillText(noAudio ? `${text} (no take)` : text, x0 + 4, VOICE_Y + 4);
        ctx.restore();
      }
      if (p.overflow_ms > 0 && !p.allow_overlap) {
        // Runs into the next line: red edge at the end of the block.
        ctx.fillStyle = c.overflow;
        ctx.fillRect(x0 + Math.max(1, w - 1) - 4, VOICE_Y + 2, 4, VOICE_H - 4);
      }
      if (p.orphaned) {
        ctx.strokeStyle = c.orphan;
        ctx.lineWidth = 2;
        ctx.strokeRect(x0 + 1, VOICE_Y + 3, Math.max(1, w - 3), VOICE_H - 6);
      }
      if (picked) {
        selectRect(x0, VOICE_Y + 2, Math.max(1, w - 1), VOICE_H - 4);
      }
    }

    // Avatar rows: expression keys, reactions, motion keys (M5-5, M5-7). Their names are in
    // the lane header column next to the canvas; an empty row says how to add to it.
    const row = (y: number, hint: string | null): void => {
      ctx.fillStyle = c.row;
      ctx.fillRect(0, y, viewWidth, ROW_H);
      if (hint !== null) {
        ctx.fillStyle = c.hint;
        ctx.font = font(10);
        ctx.textBaseline = "middle";
        ctx.fillText(hint, 6, y + ROW_H / 2);
      }
    };
    const exprKeys = keyframes.some((k) => k.lane_id === "expression" && k.t_ms !== null);
    row(EXPR_Y, exprKeys ? null : "No expression keys: press E to key one at the playhead");
    row(REACT_Y, reactions.length > 0 ? null : "No reactions: press R to drop one at the playhead");
    if (lanesOpen) {
      MOTION_LANES.forEach((lane) => row(motionRowY(lane), null));
    } else {
      row(MOTION_Y, null);
    }
    for (const r of reactions) {
      const t = shownMs(r.id, r.t_ms);
      if (t === null) continue;
      const x0 = xOf(t);
      const w = Math.max(4, r.duration_ms * pxPerMs);
      if (x0 + w < 0 || x0 > viewWidth) continue;
      const pickedReaction = r.id === selectedReactionId;
      ctx.fillStyle = c.reaction;
      if (pickedReaction) {
        ctx.filter = "brightness(1.2)";
      }
      ctx.fillRect(x0, REACT_Y + 3, w, ROW_H - 6);
      ctx.filter = "none";
      if (r.orphaned) {
        ctx.strokeStyle = c.orphan;
        ctx.lineWidth = 2;
        ctx.strokeRect(x0, REACT_Y + 3, w, ROW_H - 6);
      }
      if (pickedReaction) {
        selectRect(x0, REACT_Y + 3, w, ROW_H - 6);
      }
      if (w > 24) {
        ctx.fillStyle = c.clipText;
        ctx.font = font(10, 600);
        ctx.textBaseline = "middle";
        ctx.fillText(r.type.replace("_", "-"), x0 + 3, REACT_Y + ROW_H / 2);
      }
    }
    for (const key of keyframes) {
      const t = shownMs(key.id, key.t_ms);
      if (t === null) continue;
      const x = xOf(t);
      if (x < -60 || x > viewWidth + KEY_R) continue;
      const cy = keyRowY(key) + ROW_H / 2;
      const picked = key.id === selectedKeyId;
      ctx.beginPath();
      ctx.moveTo(x, cy - KEY_R);
      ctx.lineTo(x + KEY_R, cy);
      ctx.lineTo(x, cy + KEY_R);
      ctx.lineTo(x - KEY_R, cy);
      ctx.closePath();
      ctx.fillStyle =
        key.lane_id === "expression" ? c.expression : key.interpolation === "smooth" ? c.motion : c.motionHold;
      ctx.fill();
      if (picked) {
        ctx.strokeStyle = c.selectedRing;
        ctx.lineWidth = 4;
        ctx.stroke();
      }
      if (key.orphaned || picked) {
        ctx.strokeStyle = key.orphaned ? c.orphan : c.selected;
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      const text =
        key.lane_id === "expression"
          ? String(key.value)
          : lanesOpen
            ? String(Math.round(Number(key.value) * 100) / 100)
            : `${laneLabel(key.lane_id)} ${Math.round(Number(key.value) * 100) / 100}`;
      ctx.fillStyle = key.lane_id === "expression" ? c.expression : c.keyText;
      ctx.font = font(10);
      ctx.textBaseline = "middle";
      ctx.fillText(text, x + KEY_R + 3, cy);
    }
    ctx.textBaseline = "top";
    ctx.font = font(11);

    // Drag feedback: a dashed line at the pointer while trimming; a ghost and a drop marker
    // while reordering.
    const ui = dragUi;
    if (ui !== null && ui.kind === "trim") {
      ctx.strokeStyle = c.selected;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(Math.round(ui.x) + 0.5, RULER_H);
      ctx.lineTo(Math.round(ui.x) + 0.5, HEIGHT);
      ctx.stroke();
      ctx.setLineDash([]);
    } else if (ui !== null && ui.kind === "move") {
      const dragged = clips.find((c) => c.id === ui.clipId);
      if (dragged !== undefined) {
        ctx.globalAlpha = 0.7;
        ctx.fillStyle = c.ghost;
        ctx.fillRect(ui.ghostX, LANE_Y + 6, Math.max(4, dragged.duration_ms * pxPerMs - 1), LANE_H - 12);
        ctx.globalAlpha = 1;
      }
      const slotX = Math.round(xOf(ui.slotMs));
      ctx.strokeStyle = c.ghost;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(slotX, LANE_Y - 6);
      ctx.lineTo(slotX, LANE_Y + LANE_H + 6);
      ctx.stroke();
    } else if (ui !== null && ui.kind === "pmove") {
      ctx.globalAlpha = 0.7;
      ctx.fillStyle = c.voice;
      ctx.fillRect(ui.ghostX, VOICE_Y + 2, Math.max(4, ui.width - 1), VOICE_H - 4);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = c.selected;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(Math.round(ui.ghostX), VOICE_Y - 4);
      ctx.lineTo(Math.round(ui.ghostX), VOICE_Y + VOICE_H + 4);
      ctx.stroke();
    } else if (ui !== null && ui.kind === "drop") {
      ctx.strokeStyle = c.selected;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(Math.round(ui.x), VOICE_Y - 4);
      ctx.lineTo(Math.round(ui.x), VOICE_Y + VOICE_H + 4);
      ctx.stroke();
    }

    // Playhead
    const px = xOf(playheadMs);
    if (px >= -6 && px <= viewWidth + 6) {
      ctx.strokeStyle = c.playhead;
      ctx.fillStyle = c.playhead;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(px, 0);
      ctx.lineTo(px, HEIGHT);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(px - 6, 0);
      ctx.lineTo(px + 6, 0);
      ctx.lineTo(px, 9);
      ctx.closePath();
      ctx.fill();
    }
  }

  // Read the theme colours once the canvas is in the page.
  $effect(() => {
    const canvas = canvasEl;
    if (canvas !== null) {
      colors = readTimelineColors(getComputedStyle(canvas));
    }
  });

  // Redraw whenever anything it reads changes.
  $effect(() => {
    draw();
  });

  // Fit the whole timeline into view the first time there is a width.
  $effect(() => {
    if (!fitted && viewWidth > 0 && durationMs > 0) {
      fitted = true;
      untrack(fit);
    }
  });

  // Keep the scroll position valid after a zoom, resize or edit.
  $effect(() => {
    const max = maxScrollMs;
    untrack(() => {
      if (scrollMs > max) {
        scrollMs = max;
      }
    });
  });

  // Follow the playhead when it leaves the view (playback, seeking from elsewhere).
  $effect(() => {
    const ms = playheadMs;
    untrack(() => {
      if (viewWidth <= 0) {
        return;
      }
      const x = (ms - scrollMs) * pxPerMs;
      if (x < 0 || x > viewWidth - GUTTER / 2) {
        setScroll(ms - viewMs * 0.1);
      }
    });
  });

  // Pointer (click or drag to seek) and wheel (scroll, Ctrl+wheel to zoom). Plain listeners:
  // the wheel one must not be passive so the window itself does not zoom.
  $effect(() => {
    const canvas = canvasEl;
    if (canvas === null) {
      return;
    }
    function seek(e: PointerEvent): void {
      if (canvas === null) {
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const x = Math.min(Math.max(e.clientX - rect.left, 0), viewWidth);
      const ms = Math.round(scrollMs + x / pxPerMs);
      playheadMs = Math.min(Math.max(ms, 0), durationMs);
    }
    function pointerXY(e: PointerEvent): { x: number; y: number } {
      const rect = canvas?.getBoundingClientRect();
      return { x: e.clientX - (rect?.left ?? 0), y: e.clientY - (rect?.top ?? 0) };
    }
    function hit(x: number, y: number): Hit | null {
      if (y < LANE_Y || y > LANE_Y + LANE_H) {
        return null;
      }
      for (const clip of clips) {
        const x0 = xPos(clip.start_ms);
        const x1 = xPos(clip.end_ms);
        if (x < x0 || x > x1) {
          continue;
        }
        const grip = Math.min(EDGE_PX, (x1 - x0) / 3);
        if (x <= x0 + grip) {
          return { clip, part: "in" };
        }
        if (x >= x1 - grip) {
          return { clip, part: "out" };
        }
        return { clip, part: "body" };
      }
      return null;
    }
    function hitPlacement(x: number, y: number): TimelinePlacement | null {
      if (y < VOICE_Y || y > VOICE_Y + VOICE_H) {
        return null;
      }
      for (let i = placements.length - 1; i >= 0; i -= 1) {
        const p = placements[i];
        if (p === undefined || p.start_ms === null) {
          continue;
        }
        const x0 = xPos(p.start_ms);
        if (x >= x0 && x <= x0 + placementWidth(p)) {
          return p;
        }
      }
      return null;
    }
    /** A key diamond or a reaction bar under the pointer (keys win: they are small). */
    function hitItem(x: number, y: number): { kind: "key" | "reaction"; id: string; t: number } | null {
      for (let i = keyframes.length - 1; i >= 0; i -= 1) {
        const key = keyframes[i];
        if (key === undefined || key.t_ms === null) continue;
        const top = keyRowY(key);
        if (y < top || y > top + ROW_H) continue;
        if (Math.abs(x - xPos(key.t_ms)) <= KEY_R + 3) {
          return { kind: "key", id: key.id, t: key.t_ms };
        }
      }
      if (y >= REACT_Y && y <= REACT_Y + ROW_H) {
        for (let i = reactions.length - 1; i >= 0; i -= 1) {
          const r = reactions[i];
          if (r === undefined || r.t_ms === null) continue;
          const x0 = xPos(r.t_ms);
          if (x >= x0 - 2 && x <= x0 + Math.max(4, r.duration_ms * pxPerMs)) {
            return { kind: "reaction", id: r.id, t: r.t_ms };
          }
        }
      }
      return null;
    }
    function updateMove(d: MoveDrag, x: number): void {
      d.slot = dropSlot(clips, d.clip.id, scrollMs + x / pxPerMs);
      const others = clips.filter((c) => c.id !== d.clip.id);
      dragUi = {
        kind: "move",
        clipId: d.clip.id,
        ghostX: x - d.grabDx,
        slotMs: others[d.slot]?.start_ms ?? durationMs,
      };
    }
    function updatePlacementMove(d: PlacementDrag, x: number): void {
      const start = Math.round(scrollMs + (x - d.grabDx) / pxPerMs);
      d.startMs = Math.min(Math.max(start, 0), Math.max(0, durationMs - 1));
      dragUi = { kind: "pmove", ghostX: xPos(d.startMs), width: placementWidth(d.placement) };
    }
    /** Keep the drag picture until the backend answered, so the timeline does not flicker back. */
    async function finish(job: Promise<void>): Promise<void> {
      try {
        await job;
      } finally {
        preview = null;
        dragUi = null;
      }
    }
    function down(e: PointerEvent): void {
      if (e.button !== 0 || canvas === null) {
        return;
      }
      try {
        canvas.setPointerCapture(e.pointerId);
      } catch {
        // not a live pointer (synthetic event): the drag still works inside the canvas
      }
      const { x, y } = pointerXY(e);
      const item = hitItem(x, y);
      if (item !== null) {
        // A key or a reaction: select it (and nothing else); drag sideways to move it.
        selectedKeyId = item.kind === "key" ? item.id : null;
        selectedReactionId = item.kind === "reaction" ? item.id : null;
        selectedPlacementId = null;
        selectedId = null;
        drag = locked
          ? null
          : { mode: "ipress", kind: item.kind, id: item.id, fromMs: item.t, startX: x, toMs: item.t };
        return;
      }
      if (y >= EXPR_Y) {
        selectedKeyId = null;
        selectedReactionId = null;
      }
      const placed = hitPlacement(x, y);
      if (placed !== null) {
        // A voice block: select it (and nothing else); the playhead stays where it is.
        selectedPlacementId = placed.id;
        selectedId = null;
        selectedKeyId = null;
        selectedReactionId = null;
        drag = locked ? null : { mode: "ppress", placement: placed, startX: x };
        return;
      }
      if (y >= LANE_Y) {
        selectedPlacementId = null;
      }
      const target = hit(x, y);
      if (target !== null && !locked && target.part !== "body") {
        // Grab a clip edge: trim.
        selectedId = target.clip.id;
        const edge = target.part;
        drag = {
          mode: "trim",
          clip: target.clip,
          edge,
          sourceMs: edge === "in" ? target.clip.in_ms : target.clip.out_ms,
        };
        dragUi = { kind: "trim", x };
        return;
      }
      seek(e);
      if (target !== null) {
        selectedId = target.clip.id;
        drag = locked ? { mode: "scrub" } : { mode: "press", clip: target.clip, startX: x };
      } else {
        if (y >= LANE_Y && y <= LANE_Y + LANE_H) {
          selectedId = null; // empty space in the video lane
        }
        drag = { mode: "scrub" };
      }
    }
    function move(e: PointerEvent): void {
      if (canvas === null) {
        return;
      }
      const { x, y } = pointerXY(e);
      const d = drag;
      if (d === null) {
        const over = hit(x, y);
        canvas.style.cursor =
          hitItem(x, y) !== null && !locked
            ? "grab"
            : over === null || locked
              ? "pointer"
              : over.part === "body"
                ? "grab"
                : "ew-resize";
        return;
      }
      if (d.mode === "ipress" || d.mode === "imove") {
        if (d.mode === "ipress" && Math.abs(x - d.startX) <= 4) return;
        d.mode = "imove";
        const ms = Math.round(d.fromMs + (x - d.startX) / pxPerMs);
        d.toMs = Math.min(Math.max(ms, 0), Math.max(0, durationMs - 1));
        dragUi = { kind: "imove", id: d.id, ms: d.toMs };
        return;
      }
      if (d.mode === "scrub") {
        seek(e);
      } else if (d.mode === "trim") {
        d.sourceMs = trimTarget(d.clip, d.edge, scrollMs + x / pxPerMs);
        preview = withTrim(clips, d.clip.id, d.edge, d.sourceMs);
        dragUi = { kind: "trim", x };
      } else if (d.mode === "press") {
        if (Math.abs(x - d.startX) > 4) {
          const next: MoveDrag = {
            mode: "move",
            clip: d.clip,
            grabDx: d.startX - xPos(d.clip.start_ms),
            slot: d.clip.position,
          };
          drag = next;
          updateMove(next, x);
        }
      } else if (d.mode === "ppress") {
        const start = d.placement.start_ms;
        if (start !== null && Math.abs(x - d.startX) > 4) {
          const next: PlacementDrag = {
            mode: "pmove",
            placement: d.placement,
            grabDx: d.startX - xPos(start),
            startMs: start,
          };
          drag = next;
          updatePlacementMove(next, x);
        }
      } else if (d.mode === "pmove") {
        updatePlacementMove(d, x);
      } else if (d.mode === "move") {
        updateMove(d, x);
      }
    }
    function up(): void {
      const d = drag;
      drag = null;
      if (d === null) {
        return;
      }
      if (d.mode === "imove") {
        const handler = d.kind === "key" ? onmovekey : onmovereaction;
        if (d.toMs !== d.fromMs && handler !== undefined) {
          void finish(handler(d.id, d.toMs));
        } else {
          dragUi = null;
        }
        return;
      }
      if (d.mode === "trim") {
        const current = d.edge === "in" ? d.clip.in_ms : d.clip.out_ms;
        if (d.sourceMs !== current) {
          void finish(ontrim(d.clip.id, d.edge, d.sourceMs));
        } else {
          preview = null;
          dragUi = null;
        }
      } else if (d.mode === "move") {
        if (d.slot !== d.clip.position) {
          void finish(onreorder(d.clip.id, d.slot));
        } else {
          dragUi = null;
        }
      } else if (d.mode === "pmove") {
        if (d.startMs !== d.placement.start_ms) {
          void finish(onmoveplacement(d.placement.id, d.startMs));
        } else {
          dragUi = null;
        }
      }
    }
    function dropX(e: DragEvent): number {
      return e.clientX - (canvas?.getBoundingClientRect().left ?? 0);
    }
    function dragover(e: DragEvent): void {
      if (locked || e.dataTransfer === null || !e.dataTransfer.types.includes(LINE_DRAG_TYPE)) {
        return;
      }
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      dragUi = { kind: "drop", x: dropX(e) };
    }
    function dragleave(): void {
      if (dragUi !== null && dragUi.kind === "drop") {
        dragUi = null;
      }
    }
    function drop(e: DragEvent): void {
      const lineId = e.dataTransfer?.getData(LINE_DRAG_TYPE) ?? "";
      if (locked || lineId === "") {
        dragUi = null;
        return;
      }
      e.preventDefault();
      const ms = Math.round(scrollMs + dropX(e) / pxPerMs);
      void finish(onplace(lineId, Math.max(0, ms)));
    }
    function cancel(): void {
      drag = null;
      preview = null;
      dragUi = null;
    }
    function wheel(e: WheelEvent): void {
      if (canvas === null) {
        return;
      }
      e.preventDefault();
      if (e.ctrlKey) {
        const x = e.clientX - canvas.getBoundingClientRect().left;
        zoomAt(Math.exp(-e.deltaY * 0.0015), x);
      } else {
        setScroll(scrollMs + (e.deltaX !== 0 ? e.deltaX : e.deltaY) / pxPerMs);
      }
    }
    canvas.addEventListener("pointerdown", down);
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", cancel);
    canvas.addEventListener("wheel", wheel, { passive: false });
    canvas.addEventListener("dragover", dragover);
    canvas.addEventListener("dragleave", dragleave);
    canvas.addEventListener("drop", drop);
    return () => {
      canvas.removeEventListener("dragover", dragover);
      canvas.removeEventListener("dragleave", dragleave);
      canvas.removeEventListener("drop", drop);
      canvas.removeEventListener("pointerdown", down);
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up);
      canvas.removeEventListener("pointercancel", cancel);
      canvas.removeEventListener("wheel", wheel);
    };
  });
</script>

<div class="timeline">
  <div class="bar">
    <IconButton icon={ZoomOut} label="Zoom out (Ctrl+wheel)" onclick={() => zoomAt(1 / 1.5, viewWidth / 2)} />
    <IconButton icon={ZoomIn} label="Zoom in (Ctrl+wheel)" onclick={() => zoomAt(1.5, viewWidth / 2)} />
    <IconButton icon={Maximize2} label="Fit the whole timeline" onclick={fit} />
    <span class="sep" aria-hidden="true"></span>
    <IconButton
      icon={Rows3}
      label={lanesOpen ? "Show the motion keys in one row" : "Show one row per motion lane"}
      pressed={lanesOpen}
      onclick={() => (lanesOpen = !lanesOpen)}
    />
    <span class="spacer"></span>
    <IconButton
      icon={CircleHelp}
      label="How the timeline works"
      pressed={helpOpen}
      onclick={() => (helpOpen = !helpOpen)}
    />
  </div>
  {#if helpOpen}
    <p class="help">
      Click the ruler to seek, click a clip to select it, drag its edge to trim, drag it sideways to
      reorder. Click a voice block to select it and drag it to move it; drag a line from the bank
      onto the timeline to place it. Avatar keys and reactions: click to select, drag sideways to
      move. Wheel scrolls, Ctrl+wheel zooms.
    </p>
  {/if}
  <div class="body">
    <div class="heads" style:height="{HEIGHT}px">
      <div class="head ruler num" style:top="0px" style:height="{RULER_H}px">{clock(playheadMs)}</div>
      <div class="head big" style:top="{LANE_Y}px" style:height="{LANE_H}px">
        <span class="sw" style:background="var(--lane-clip)"></span>Video
      </div>
      <div class="head big" style:top="{VOICE_Y}px" style:height="{VOICE_H}px">
        <span class="sw" style:background="var(--lane-voice)"></span>Voice
      </div>
      <div class="head" style:top="{EXPR_Y}px" style:height="{ROW_H}px">
        <span class="sw" style:background="var(--lane-expression)"></span>Expression
        <span class="kbd k">E</span>
      </div>
      <div class="head" style:top="{REACT_Y}px" style:height="{ROW_H}px">
        <span class="sw" style:background="var(--lane-reaction)"></span>Reactions
        <span class="kbd k">R</span>
      </div>
      {#if lanesOpen}
        {#each MOTION_LANES as lane, i (lane)}
          <div class="head sub" style:top="{motionRowY(lane)}px" style:height="{ROW_H}px">
            {#if i === 0}
              <button
                type="button"
                class="toggle"
                aria-expanded="true"
                aria-label="Collapse the motion lanes into one row"
                title="Collapse the motion lanes into one row"
                onclick={() => (lanesOpen = false)}
              >
                <ChevronDown size={12} strokeWidth={2} aria-hidden="true" />
              </button>
            {/if}
            <span class="ellipsis">{laneLabel(lane)}</span>
          </div>
        {/each}
      {:else}
        <div class="head" style:top="{MOTION_Y}px" style:height="{ROW_H}px">
          <button
            type="button"
            class="toggle"
            aria-expanded="false"
            aria-label="Show one row per motion lane"
            title="Show one row per motion lane"
            onclick={() => (lanesOpen = true)}
          >
            <ChevronRight size={12} strokeWidth={2} aria-hidden="true" />
          </button>
          <span class="sw" style:background="var(--lane-motion)"></span>Motion keys
        </div>
      {/if}
    </div>
    <div class="view" bind:clientWidth={viewWidth}>
      <canvas bind:this={canvasEl} style:width="{viewWidth}px" style:height="{HEIGHT}px"></canvas>
    </div>
  </div>
  {#if maxScrollMs > 0}
    <input
      class="scroll"
      type="range"
      aria-label="Scroll the timeline"
      min="0"
      max={maxScrollMs}
      step="1"
      value={scrollMs}
      oninput={(e) => setScroll(e.currentTarget.valueAsNumber)}
    />
  {/if}
</div>

<style>
  .timeline {
    width: 100%;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 2px;
    margin-bottom: 6px;
  }
  .sep {
    width: 1px;
    height: 18px;
    margin: 0 6px;
    background: var(--border-strong);
  }
  .spacer {
    flex: 1;
  }
  .help {
    margin: 0 0 8px;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    background: var(--surface-2);
    color: var(--text-2);
    font-size: var(--fs-sm);
  }
  .body {
    display: flex;
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    overflow: hidden;
  }
  .heads {
    position: relative;
    flex: none;
    width: 128px;
    border-right: 1px solid var(--border);
    background: var(--surface-1);
  }
  .head {
    position: absolute;
    left: 0;
    right: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 8px;
    box-sizing: border-box;
    color: var(--text-2);
    font-size: var(--fs-xs);
    white-space: nowrap;
  }
  .head.big {
    font-size: var(--fs-sm);
    font-weight: 600;
  }
  .head.ruler {
    color: var(--text-1);
    font-size: var(--fs-xs);
    font-weight: 600;
    border-bottom: 1px solid var(--border);
  }
  .head.sub {
    padding-left: 26px;
    color: var(--text-3);
  }
  .head.sub .toggle {
    position: absolute;
    left: 6px;
  }
  .sw {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: 2px;
  }
  .k {
    margin-left: auto;
  }
  .ellipsis {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    padding: 0;
    border: none;
    border-radius: var(--r-sm);
    background: none;
    color: var(--text-2);
  }
  .toggle:hover {
    background: var(--surface-3);
    color: var(--text-1);
  }
  .view {
    flex: 1;
    min-width: 0;
  }
  canvas {
    display: block;
    cursor: pointer;
    touch-action: none;
  }
  .scroll {
    display: block;
    width: 100%;
    margin: 6px 0 0;
  }
</style>
