<script lang="ts">
  import { untrack } from "svelte";
  import type {
    AudioLane,
    PeaksReport,
    TimelineAudioClip,
    TimelineLaneClip,
    VideoLane,
    TimelineClip,
    TimelineKeyframe,
    TimelinePlacement,
    TimelineReaction,
  } from "./api";
  import {
    ADD_ROW_H,
    AUDIO_LANE_H,
    audioEndMs,
    audioLayout,
    audioTrimTarget,
    dragLaneIndex,
    fitsOnLane,
    laneAt,
    laneAudible,
    peakWindow,
    withAudioTrim,
  } from "./audioLanes";
  import { MOTION_LANES, laneLabel } from "./avatarLanes";
  import {
    FOOTAGE_DRAG_TYPE,
    VIDEO_ADD_H,
    VIDEO_LANE_H,
    dragVideoLaneIndex,
    laneEndMs,
    laneTrimTarget,
    videoLaneAt,
    AVATAR_ROW_H,
    avatarSlot,
    movedAvatarLane,
    videoLayout,
    withLaneTrim,
  } from "./videoLanes";
  import { clock } from "./format";
  import { LINE_DRAG_TYPE, dropSlot, peakSpan, trimTarget, withTrim } from "./timeline";
  import { FALLBACK, readTimelineColors, type TimelineColors } from "./timelineTheme";
  import { SNAP_PX, snapEdge, snapMove, snapPoints } from "./snap";
  import { clampShift, keyGroup, keySelection, stepKey, toggleGroup } from "./keyNav";
  import { hiddenClipKeys, keyCurve, visibleClipKeys, type CurveKey } from "./clipKeys";
  import { clampGroupShift, clipsInBox, groupFits, groupMoveOrder } from "./clipGroup";
  import {
    ArrowDown,
    ArrowUp,
    ChevronDown,
    ChevronRight,
    CircleHelp,
    Eye,
    EyeOff,
    Lock,
    LockOpen,
    Magnet,
    Plus,
    X,
    Maximize2,
    Rows3,
    StepBack,
    StepForward,
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
    selectedKeyIds = $bindable([]),
    selectedReactionId = $bindable(null),
    onmovekeys,
    onmovereaction,
    audioLanes = [],
    audioClips = [],
    audioPeaks = {},
    selectedAudioClipId = $bindable(null),
    onmoveaudio,
    ontrimaudio,
    onaudiolane,
    onaddaudiolane,
    onremoveaudiolane,
    videoLanes = [],
    laneClips = [],
    selectedLaneClipId = $bindable(null),
    onmovelane,
    ontrimlane,
    onmoveclipkeys,
    selectedClipKeyIds = $bindable([]),
    selectedClipIds = $bindable([]),
    onmoveclips,
    onvideolane,
    onaddvideolane,
    onremovevideolane,
    onplacefootage,
    avatarBelowLaneId = null,
    onavatarlayer,
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
    /** Several selected keys (Shift-click, box select); counts while it holds `selectedKeyId`. */
    selectedKeyIds?: string[];
    selectedReactionId?: string | null;
    /** Keys or a reaction were dragged sideways: their new TIMELINE times. One call per drag. */
    onmovekeys?: (moves: { id: string; ms: number }[]) => Promise<void>;
    onmovereaction?: (reactionId: string, timelineMs: number) => Promise<void>;
    /** Audio lanes and clips (M8-1). Clips are at TIMELINE times, never anchored to footage. */
    audioLanes?: AudioLane[];
    audioClips?: TimelineAudioClip[];
    /** Waveform peaks by audio file id (the whole file). */
    audioPeaks?: Record<string, PeaksReport>;
    selectedAudioClipId?: string | null;
    /** A clip was dragged: where its start goes and the lane it lands on. One call per drag. */
    onmoveaudio?: (clipId: string, timelineMs: number, laneId: string) => Promise<void>;
    /** A clip edge was dragged to a TIMELINE time. One call per drag. */
    ontrimaudio?: (clipId: string, edge: "start" | "end", timelineMs: number) => Promise<void>;
    /** Lane header edits: name, level, mute, solo. */
    onaudiolane?: (
      laneId: string,
      change: { name?: string; gain_db?: number; mute?: boolean; solo?: boolean },
    ) => Promise<void>;
    onaddaudiolane?: () => Promise<void>;
    onremoveaudiolane?: (laneId: string) => Promise<void>;
    /** Video lanes above the main footage, bottom to top, and their clips (M8-2). */
    videoLanes?: VideoLane[];
    laneClips?: TimelineLaneClip[];
    selectedLaneClipId?: string | null;
    /** A lane clip was dragged: where its start goes and the lane it lands on. */
    onmovelane?: (clipId: string, timelineMs: number, laneId: string) => Promise<void>;
    ontrimlane?: (clipId: string, edge: "start" | "end", timelineMs: number) => Promise<void>;
    /** Keys on an image clip were dragged: each key's new timeline time (keyframes step 7, polish). */
    onmoveclipkeys?: (clipId: string, moves: { id: string; ms: number }[]) => Promise<void>;
    /** Selected keys of the selected image clip (Shift-click, Shift-drag box; keyframes polish). */
    selectedClipKeyIds?: string[];
    /** Several video- and audio-lane clips (box select over empty lane space, Shift-click; polish). */
    selectedClipIds?: string[];
    /** A group of lane clips was dragged: each clip's new start, in an order safe to apply one by one. */
    onmoveclips?: (moves: { kind: "lane" | "audio"; id: string; ms: number }[]) => Promise<void>;
    onvideolane?: (laneId: string, change: { name?: string; hidden?: boolean; locked?: boolean }) => Promise<void>;
    onaddvideolane?: () => Promise<void>;
    onremovevideolane?: (laneId: string) => Promise<void>;
    /** A recording was dragged from the Footage tab onto a video lane (or the add row: newLane). */
    onplacefootage?: (sourceId: string, timelineMs: number, laneId: string | null, newLane: boolean) => Promise<void>;
    /** The video lane the avatar draws just under; null: over every lane. */
    avatarBelowLaneId?: string | null;
    /** Move the avatar's layer: just under `laneId`, or on top with null. */
    onavatarlayer?: (laneId: string | null) => Promise<void>;
  } = $props();

  /** Width of the grab zone at each clip edge, in pixels. */
  const EDGE_PX = 6;
  const RULER_H = 26;
  /** Video lanes (M8-2) under the ruler: the "+ Video lane" row, then the lanes, highest first. */
  const VIDEO_TOP = RULER_H + 4;
  const avatarAt = $derived(avatarSlot(videoLanes, avatarBelowLaneId));
  const video = $derived(videoLayout(VIDEO_TOP, videoLanes.length, avatarAt));
  /** The main footage lane under the video lanes. */
  const LANE_Y = $derived(video.bottom + 4);
  const LANE_H = 60;
  /** The voice lane sits under the video lane. */
  const VOICE_Y = $derived(LANE_Y + LANE_H + 8);
  const VOICE_H = 46;
  /** Audio lanes under the voice lane (M8-1), then the "+ Audio lane" row. */
  const AUDIO_Y = $derived(VOICE_Y + VOICE_H + 6);
  const audio = $derived(audioLayout(AUDIO_Y, audioLanes.length));
  /** Avatar rows under the audio lanes: expression, reactions, then the motion lanes. */
  const EXPR_Y = $derived(audio.bottom + 6);
  const ROW_H = 20;
  const REACT_Y = $derived(EXPR_Y + ROW_H + 3);
  const MOTION_Y = $derived(REACT_Y + ROW_H + 3);
  const KEY_R = 5;
  /** Diamonds of image-clip keys, along the bottom of the clip block. */
  const CLIP_KEY_R = 4;
  /** Collapsed: one row with every motion key. Expanded: one row per motion lane. */
  let lanesOpen = $state(false);
  /** The how-to text under the toolbar (the "?" button). */
  let helpOpen = $state(false);
  /** Snap dragged audio and lane clips to other clip edges and the playhead (Alt: not this drag). */
  const SNAP_KEY = "pngtuber.timeline.snap";
  let snapOn = $state(readSnap());
  function readSnap(): boolean {
    try {
      return localStorage.getItem(SNAP_KEY) !== "off";
    } catch {
      return true;
    }
  }
  function toggleSnap(): void {
    snapOn = !snapOn;
    try {
      localStorage.setItem(SNAP_KEY, snapOn ? "on" : "off");
    } catch {
      // Not remembered: fine.
    }
  }
  /** The times a dragged clip may snap to, or null when snapping is off for this move. */
  function snapTargets(exceptId: string, alt: boolean): number[] | null {
    if (!snapOn || alt) return null;
    return snapPoints(
      [
        ...clips.map((c) => ({ id: c.id, start: c.start_ms, end: c.end_ms })),
        ...placements.map((p) => ({ id: p.id, start: p.start_ms, end: p.end_ms })),
        ...audioClips.map((a) => ({ id: a.id, start: a.timeline_ms, end: a.end_ms })),
        ...laneClips.map((v) => ({ id: v.id, start: v.timeline_ms, end: v.end_ms })),
      ],
      playheadMs,
      exceptId,
    );
  }
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
  /** A key (with the rest of the selection) or a reaction dragged in time; `toMs` is
   * where the grabbed one goes, every other selected key shifts by the same amount. */
  type ItemDrag = {
    mode: "ipress" | "imove";
    kind: "key" | "reaction";
    id: string;
    ids: string[];
    fromMs: number;
    startX: number;
    toMs: number;
  };
  /** A rectangle dragged over empty avatar rows selects the keys inside it. */
  type BoxDrag = { mode: "box"; x0: number; y0: number; x1: number; y1: number; moved: boolean; add: boolean };
  type AudioDrag =
    | { mode: "apress"; clip: TimelineAudioClip; startX: number }
    | { mode: "amove"; clip: TimelineAudioClip; grabDx: number; startMs: number; laneIndex: number }
    | { mode: "atrim"; clip: TimelineAudioClip; edge: "start" | "end"; ms: number };
  type LaneDrag =
    | { mode: "vpress"; clip: TimelineLaneClip; startX: number }
    | { mode: "vmove"; clip: TimelineLaneClip; grabDx: number; startMs: number; laneIndex: number }
    | { mode: "vtrim"; clip: TimelineLaneClip; edge: "start" | "end"; ms: number }
    | { mode: "ckey"; clip: TimelineLaneClip; keyId: string; ids: string[]; startX: number; fromMs: number; deltaMs: number }
    | { mode: "cbox"; clip: TimelineLaneClip; x0: number; y0: number; x1: number; y1: number; moved: boolean; add: boolean; toggleId: string | null }
    | { mode: "gpress"; grabId: string; ids: string[]; startX: number; deltaMs: number; moved: boolean }
    | { mode: "clipbox"; x0: number; y0: number; x1: number; y1: number; moved: boolean; add: boolean };
  type Drag =
    | LaneDrag
    | AudioDrag
    | ItemDrag
    | BoxDrag
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
    | { kind: "drop"; x: number; lane: number | "add" | null; vlane?: number | "add" | null }
    | { kind: "vmove"; clipId: string; startMs: number; laneIndex: number; fits: boolean }
    | { kind: "vtrim"; clip: TimelineLaneClip }
    | { kind: "amove"; clipId: string; startMs: number; laneIndex: number; fits: boolean }
    | { kind: "atrim"; clip: TimelineAudioClip }
    | { kind: "imove"; ids: string[]; deltaMs: number }
    | { kind: "box"; x0: number; y0: number; x1: number; y1: number }
    | { kind: "ckey"; ids: string[]; deltaMs: number }
    | { kind: "gmove"; ids: string[]; deltaMs: number; fits: boolean };

  /** Pointer interaction in progress (not reactive: only the handlers use it). */
  let drag: Drag | null = null;
  /** Clip list with the dragged edge applied, drawn instead of `clips` during a trim drag. */
  let preview = $state<TimelineClip[] | null>(null);
  let dragUi = $state<DragUi | null>(null);

  const viewMs = $derived(viewWidth / pxPerMs);
  /** Audio clips may run past the footage; the view scrolls to their end too. */
  const contentMs = $derived(Math.max(durationMs, audioEndMs(audioClips), laneEndMs(laneClips)));
  const maxScrollMs = $derived(Math.max(0, contentMs - (viewWidth - GUTTER) / pxPerMs));

  /**
   * Where a drop at a window point (CSS px) lands: the TIMELINE time under it and the audio
   * lane under it (null: not over an audio lane, so the first one; `newLane`: the
   * "+ Audio lane" row). Null when the point is not over the timeline canvas.
   */
  /** Previous / next avatar key (`<` and `>`, the toolbar buttons): select it and put the
   * playhead on it, so a preview drag or the inspector edits that key (keyframes decision 1). */
  export function gotoKey(direction: 1 | -1): boolean {
    // The selected image clip's keys when it has some, else the avatar keys.
    const shot = laneClips.find((v) => v.id === selectedLaneClipId);
    if (shot !== undefined && visibleClipKeys(shot).length > 0) {
      const nav = visibleClipKeys(shot).map((k) => ({ id: k.id, lane_id: k.prop, t_ms: shot.timeline_ms + k.t_ms, orphaned: false }));
      const current = shot.keys.find((k) => k.id === selectedClipKeyIds[0]);
      const next = stepKey(nav, playheadMs, direction, current?.prop ?? null);
      if (next === null || next.t_ms === null) return false;
      selectedClipKeyIds = [next.id];
      playheadMs = next.t_ms;
      return true;
    }
    const current = keyframes.find((k) => k.id === selectedKeyId);
    const key = stepKey(keyframes, playheadMs, direction, current?.lane_id ?? null);
    if (key === null || key.t_ms === null) return false;
    selectItem("key", key.id, key.t_ms);
    return true;
  }

  /** Select a key or reaction alone and put the playhead on it. */
  function selectItem(kind: "key" | "reaction", id: string, t: number): void {
    selectedKeyId = kind === "key" ? id : null;
    selectedKeyIds = kind === "key" ? [id] : [];
    selectedReactionId = kind === "reaction" ? id : null;
    selectedPlacementId = null;
    selectedAudioClipId = null;
    selectedLaneClipId = null;
    selectedId = null;
    playheadMs = t;
  }

  export function dropTarget(
    clientX: number,
    clientY: number,
  ): {
    timelineMs: number;
    laneId: string | null;
    newLane: boolean;
    videoLaneId: string | null;
    videoNewLane: boolean;
  } | null {
    if (canvasEl === null) {
      return null;
    }
    const box = canvasEl.getBoundingClientRect();
    if (clientX < box.left || clientX > box.right || clientY < box.top || clientY > box.bottom) {
      return null;
    }
    const lane = laneAt(clientY - box.top, AUDIO_Y, audioLanes.length);
    const vlane = videoLaneAt(clientY - box.top, VIDEO_TOP, videoLanes.length, avatarAt);
    return {
      timelineMs: Math.max(0, Math.round(scrollMs + (clientX - box.left) / pxPerMs)),
      laneId: typeof lane === "number" ? (audioLanes[lane]?.id ?? null) : null,
      newLane: lane === "add",
      videoLaneId: typeof vlane === "number" ? (videoLanes[vlane]?.id ?? null) : null,
      videoNewLane: vlane === "add",
    };
  }

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

  /**
   * The lane-clip group (video- and audio-lane clips): counts only while it holds the
   * selected lane or audio clip, like the key selection (keyframes polish).
   */
  function clipGroup(): string[] {
    const primary = selectedLaneClipId ?? selectedAudioClipId;
    if (primary === null) return [];
    return selectedClipIds.includes(primary) ? selectedClipIds : [primary];
  }

  /** A lane or audio clip where a group drag shows it (moved by the drag's shift). */
  function groupShifted<C extends { id: string; timeline_ms: number; end_ms: number }>(clip: C): C {
    const ui = dragUi;
    if (ui === null || ui.kind !== "gmove" || !ui.ids.includes(clip.id)) return clip;
    return { ...clip, timeline_ms: clip.timeline_ms + ui.deltaMs, end_ms: clip.end_ms + ui.deltaMs };
  }

  /** Select one lane or audio clip as the primary (the clip bar shows it). */
  function setPrimaryClip(id: string | null): void {
    const lane = id !== null && laneClips.some((c) => c.id === id);
    selectedLaneClipId = lane ? id : null;
    selectedAudioClipId = !lane && id !== null && audioClips.some((c) => c.id === id) ? id : null;
  }

  /** Time an item is drawn at (its drag position while it is being dragged). */
  function shownMs(id: string, t: number | null): number | null {
    const ui = dragUi;
    return ui !== null && ui.kind === "imove" && t !== null && ui.ids.includes(id) ? t + ui.deltaMs : t;
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
    if (viewWidth <= 0 || contentMs <= 0) {
      return;
    }
    pxPerMs = clampPx((viewWidth - GUTTER) / contentMs);
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

    // Video lanes (M8-2): the "+ Video lane" row, then the lanes, highest first.
    const uiV = dragUi;
    const addHot = uiV !== null && uiV.kind === "drop" && uiV.vlane === "add";
    ctx.fillStyle = addHot ? c.ghost : c.row;
    ctx.globalAlpha = addHot ? 0.3 : 0.5;
    ctx.fillRect(0, video.addY, viewWidth, VIDEO_ADD_H);
    ctx.globalAlpha = 1;
    if (video.avatarY !== null) {
      // The avatar's layer among the video lanes: lanes above this row cover the avatar.
      ctx.fillStyle = c.expression;
      ctx.globalAlpha = 0.14;
      ctx.fillRect(0, video.avatarY, viewWidth, AVATAR_ROW_H);
      ctx.globalAlpha = 1;
      ctx.font = font(10);
      ctx.fillStyle = c.hint;
      ctx.textBaseline = "middle";
      ctx.fillText("Avatar layer: lanes above this row draw over the avatar", 8, video.avatarY + AVATAR_ROW_H / 2);
      ctx.textBaseline = "top";
    }
    videoLanes.forEach((lane, index) => {
      const y = video.laneY(index);
      ctx.fillStyle = c.row;
      ctx.fillRect(0, y, viewWidth, VIDEO_LANE_H);
      const hot =
        (uiV !== null && uiV.kind === "drop" && uiV.vlane === index) ||
        (uiV !== null && uiV.kind === "vmove" && uiV.laneIndex === index);
      if (hot) {
        ctx.fillStyle = c.ghost;
        ctx.globalAlpha = 0.12;
        ctx.fillRect(0, y, viewWidth, VIDEO_LANE_H);
        ctx.globalAlpha = 1;
      }
    });
    if (videoLanes.length === 0) {
      ctx.font = font(10);
      ctx.fillStyle = c.hint;
      ctx.textBaseline = "middle";
      ctx.fillText(
        "Video lanes: drag a recording from the Footage tab, or images and videos from Explorer, onto this row",
        8,
        video.addY + VIDEO_ADD_H / 2,
      );
      ctx.textBaseline = "top";
    }
    const vIndexOf = new Map(videoLanes.map((lane, index) => [lane.id, index]));
    const uiCk = dragUi !== null && dragUi.kind === "ckey" ? dragUi : null;
    /** A key curve (keyframes polish) between `top` and `bottom`, scaled to its own values. */
    const drawCurve = (keys: CurveKey[], top: number, bottom: number, colour: string): void => {
      if (keys.length < 2) return;
      const pts = keyCurve(keys, Math.max(4, Math.min(32, Math.round((pxPerMs * 1000) / 8))));
      const lo = Math.min(...pts.map((p) => p.v));
      const hi = Math.max(...pts.map((p) => p.v));
      const yOf = (v: number): number => (hi - lo < 1e-9 ? (top + bottom) / 2 : bottom - ((v - lo) / (hi - lo)) * (bottom - top));
      ctx.beginPath();
      pts.forEach((p, i) => (i === 0 ? ctx.moveTo(xOf(p.t), yOf(p.v)) : ctx.lineTo(xOf(p.t), yOf(p.v))));
      ctx.globalAlpha = 0.75;
      ctx.strokeStyle = colour;
      ctx.lineWidth = 1.25;
      ctx.stroke();
      ctx.globalAlpha = 1;
    };
    for (const original of laneClips) {
      const clip = groupShifted(uiV !== null && uiV.kind === "vtrim" && uiV.clip.id === original.id ? uiV.clip : original);
      const index = vIndexOf.get(clip.lane_id);
      const lane = index === undefined ? undefined : videoLanes[index];
      if (index === undefined || lane === undefined) continue;
      const x0 = xOf(clip.timeline_ms);
      const w = Math.max(2, (clip.end_ms - clip.timeline_ms) * pxPerMs);
      if (x0 + w < 0 || x0 > viewWidth) continue;
      const y = video.laneY(index) + 2;
      const h = VIDEO_LANE_H - 4;
      const moving =
        (uiV !== null && uiV.kind === "vmove" && uiV.clipId === clip.id) ||
        (uiV !== null && uiV.kind === "gmove" && !uiV.fits && uiV.ids.includes(clip.id));
      ctx.globalAlpha = moving ? 0.35 : lane.hidden ? 0.35 : 1;
      const picked = clip.id === selectedLaneClipId || clipGroup().includes(clip.id);
      ctx.fillStyle = clip.image_id !== null ? c.clipAlt : clip.freeze_ms !== null ? c.freeze : c.clip;
      if (picked) ctx.filter = "brightness(1.2)";
      ctx.fillRect(x0, y, Math.max(1, w - 1), h);
      ctx.filter = "none";
      if (clip.missing) {
        ctx.strokeStyle = c.missing;
        ctx.lineWidth = 2;
        ctx.strokeRect(x0 + 1, y + 1, Math.max(1, w - 3), h - 2);
      }
      if (clip.keys.length > 0) {
        // The keyed values over the clip, one faint curve per property in the lower half.
        ctx.save();
        ctx.beginPath();
        ctx.rect(x0, y, Math.max(1, w - 1), h);
        ctx.clip();
        for (const prop of ["x", "y", "scale", "opacity"] as const) {
          const keys = clip.keys
            .filter((k) => k.prop === prop)
            .map((k) => ({
              t_ms: clip.timeline_ms + k.t_ms + (uiCk !== null && uiCk.ids.includes(k.id) ? uiCk.deltaMs : 0),
              value: k.value,
              interpolation: k.interpolation,
              strength: k.ease_strength,
            }));
          drawCurve(keys, y + h * 0.45, y + h - 3, prop === "opacity" ? c.reaction : c.motion);
        }
        ctx.restore();
      }
      if (w > 30) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(x0, y, Math.max(1, w - 1), h);
        ctx.clip();
        ctx.fillStyle = c.clipText;
        ctx.textBaseline = "top";
        ctx.font = font(10, 600);
        const pip = clip.scale !== 1 || clip.x !== 0.5 || clip.y !== 0.5 ? "  PiP" : "";
        const fade = clip.opacity < 1 ? `  ${Math.round(clip.opacity * 100)}%` : "";
        const label = clip.freeze_ms !== null ? `Freeze ${clock(clip.freeze_ms)} · ${clip.name}` : clip.name;
        ctx.fillText(`${clip.missing ? `${label} (missing)` : label}${pip}${fade}`, x0 + 4, y + 3);
        ctx.font = font(10);
        ctx.fillStyle = c.clipTextMuted;
        ctx.fillText(clock(clip.end_ms - clip.timeline_ms), x0 + 4, y + 16);
        ctx.restore();
      }
      ctx.globalAlpha = 1;
      if (picked) {
        selectRect(x0, y, Math.max(1, w - 1), h);
      }
      // Keys on an image clip (keyframes step 7): diamonds along the bottom of the block.
      for (const key of visibleClipKeys(clip)) {
        const ms = clip.timeline_ms + key.t_ms + (uiCk !== null && uiCk.ids.includes(key.id) ? uiCk.deltaMs : 0);
        const kx = xOf(ms);
        if (kx < x0 - CLIP_KEY_R || kx > x0 + w + CLIP_KEY_R) continue;
        const ky = y + h - CLIP_KEY_R - 2;
        ctx.beginPath();
        ctx.moveTo(kx, ky - CLIP_KEY_R);
        ctx.lineTo(kx + CLIP_KEY_R, ky);
        ctx.lineTo(kx, ky + CLIP_KEY_R);
        ctx.lineTo(kx - CLIP_KEY_R, ky);
        ctx.closePath();
        ctx.fillStyle = key.prop === "opacity" ? c.reaction : key.interpolation !== "hold" ? c.motion : c.motionHold;
        ctx.fill();
        if (selectedClipKeyIds.includes(key.id)) {
          ctx.strokeStyle = c.selectedRing;
          ctx.lineWidth = 3;
          ctx.stroke();
          ctx.strokeStyle = c.selected;
          ctx.lineWidth = 1.5;
          ctx.stroke();
        } else if (Math.abs(ms - playheadMs) <= 34) {
          ctx.strokeStyle = c.selected;
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      }
      // Keys a trim left outside the clip still shape the motion: a small arrow at that edge.
      const hidden = hiddenClipKeys(clip);
      const ay = y + h - CLIP_KEY_R - 2;
      ctx.fillStyle = c.keyText;
      if (hidden.before > 0 && w > 10) {
        ctx.beginPath();
        ctx.moveTo(x0 + 1, ay);
        ctx.lineTo(x0 + 6, ay - 4);
        ctx.lineTo(x0 + 6, ay + 4);
        ctx.closePath();
        ctx.fill();
      }
      if (hidden.after > 0 && w > 10) {
        const xe = x0 + Math.max(1, w - 1);
        ctx.beginPath();
        ctx.moveTo(xe - 1, ay);
        ctx.lineTo(xe - 6, ay - 4);
        ctx.lineTo(xe - 6, ay + 4);
        ctx.closePath();
        ctx.fill();
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
      ctx.fillStyle = clip.freeze_ms !== null ? c.freeze : tones.get(clip.source_id) === 1 ? c.clipAlt : c.clip;
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
        const name = clip.freeze_ms !== null ? `Freeze ${clock(clip.freeze_ms)} · ${label(clip)}` : label(clip);
        ctx.fillText(missing ? `${name} (missing)` : name, x0 + 6, LANE_Y + 6);
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

    // Audio lanes (M8-1): music and sound effects with their waveform and fades.
    const ui0 = dragUi;
    audioLanes.forEach((lane, index) => {
      const y = audio.laneY(index);
      ctx.fillStyle = c.row;
      ctx.fillRect(0, y, viewWidth, AUDIO_LANE_H);
      const highlight =
        (ui0 !== null && ui0.kind === "drop" && ui0.lane === index) ||
        (ui0 !== null && ui0.kind === "amove" && ui0.laneIndex === index);
      if (highlight) {
        ctx.fillStyle = c.ghost;
        ctx.globalAlpha = 0.12;
        ctx.fillRect(0, y, viewWidth, AUDIO_LANE_H);
        ctx.globalAlpha = 1;
      }
      if (index === 0 && audioClips.length === 0) {
        ctx.font = font(11);
        ctx.fillStyle = c.hint;
        ctx.textBaseline = "middle";
        ctx.fillText("Audio lane: drag music or sound effects here from Explorer", 8, y + AUDIO_LANE_H / 2);
        ctx.textBaseline = "top";
      }
    });
    ctx.fillStyle = ui0 !== null && ui0.kind === "drop" && ui0.lane === "add" ? c.ghost : c.row;
    ctx.globalAlpha = ui0 !== null && ui0.kind === "drop" && ui0.lane === "add" ? 0.3 : 0.5;
    ctx.fillRect(0, audio.addY, viewWidth, ADD_ROW_H);
    ctx.globalAlpha = 1;
    const laneIndexOf = new Map(audioLanes.map((lane, index) => [lane.id, index]));
    for (const original of audioClips) {
      const clip = groupShifted(ui0 !== null && ui0.kind === "atrim" && ui0.clip.id === original.id ? ui0.clip : original);
      const index = laneIndexOf.get(clip.lane_id);
      const lane = index === undefined ? undefined : audioLanes[index];
      if (index === undefined || lane === undefined) continue;
      const x0 = xOf(clip.timeline_ms);
      const w = Math.max(2, (clip.end_ms - clip.timeline_ms) * pxPerMs);
      if (x0 + w < 0 || x0 > viewWidth) continue;
      const y = audio.laneY(index) + 2;
      const h = AUDIO_LANE_H - 4;
      const moving =
        (ui0 !== null && ui0.kind === "amove" && ui0.clipId === clip.id) ||
        (ui0 !== null && ui0.kind === "gmove" && !ui0.fits && ui0.ids.includes(clip.id));
      ctx.globalAlpha = moving ? 0.35 : laneAudible(lane, audioLanes) ? 1 : 0.4;
      const picked = clip.id === selectedAudioClipId || clipGroup().includes(clip.id);
      ctx.fillStyle = c.audio;
      if (picked) ctx.filter = "brightness(1.2)";
      ctx.fillRect(x0, y, Math.max(1, w - 1), h);
      ctx.filter = "none";
      const report = audioPeaks[clip.file_id];
      if (report !== undefined && w > 4) {
        const [from, to] = peakWindow(clip);
        const midY = y + 12 + (h - 14) / 2;
        const half = (h - 14) / 2 - 1;
        ctx.fillStyle = c.wave;
        ctx.globalAlpha *= 0.75;
        const first = Math.max(0, Math.floor(-x0));
        const last = Math.min(Math.ceil(w), Math.ceil(viewWidth - x0));
        for (let col = first; col < last; col += 1) {
          const a = from + ((to - from) * col) / w;
          const b2 = from + ((to - from) * (col + 1)) / w;
          const [low, high] = peakSpan(report.lows, report.highs, a, b2);
          const top = midY - high * half;
          const bottom = midY - low * half;
          ctx.fillRect(x0 + col, top, 1, Math.max(1, bottom - top));
        }
      }
      ctx.globalAlpha = moving ? 0.35 : laneAudible(lane, audioLanes) ? 1 : 0.4;
      // Fades: a line from the clip's bottom corner up to full level.
      ctx.strokeStyle = c.clipText;
      ctx.lineWidth = 1;
      if (clip.fade_in_ms > 0) {
        ctx.beginPath();
        ctx.moveTo(x0, y + h);
        ctx.lineTo(x0 + clip.fade_in_ms * pxPerMs, y);
        ctx.stroke();
      }
      if (clip.fade_out_ms > 0) {
        ctx.beginPath();
        ctx.moveTo(x0 + w - 1 - clip.fade_out_ms * pxPerMs, y);
        ctx.lineTo(x0 + w - 1, y + h);
        ctx.stroke();
      }
      if (w > 30) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(x0, y, Math.max(1, w - 1), h);
        ctx.clip();
        ctx.fillStyle = c.clipText;
        ctx.textBaseline = "top";
        ctx.font = font(10, 600);
        const level = clip.gain_db === 0 ? "" : `  ${clip.gain_db > 0 ? "+" : ""}${clip.gain_db} dB`;
        ctx.fillText(`${clip.fx !== null && clip.fx !== undefined ? "FX · " : ""}${clip.name}${level}`, x0 + 4, y + 3);
        ctx.restore();
      }
      ctx.globalAlpha = 1;
      if (picked) {
        selectRect(x0, y, Math.max(1, w - 1), h);
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
    /** Pin mark: an item past the footage, held at its timeline time (keyframes decision 4). */
    const pin = (px: number, py: number): void => {
      ctx.beginPath();
      ctx.moveTo(px, py);
      ctx.lineTo(px - 3, py + 4);
      ctx.strokeStyle = c.keyText;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(px, py, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = c.keyText;
      ctx.fill();
    };
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
      if (r.pinned) pin(x0 + 1, REACT_Y + 3);
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
    if (lanesOpen) {
      // One row per lane: the lane's value curve under its diamonds (keyframes polish).
      for (const lane of MOTION_LANES) {
        const keys: CurveKey[] = [];
        for (const key of keyframes) {
          if (key.lane_id !== lane || key.orphaned || typeof key.value !== "number") continue;
          const t = shownMs(key.id, key.t_ms);
          if (t !== null) keys.push({ t_ms: t, value: key.value, interpolation: key.interpolation, strength: key.ease_strength });
        }
        const top = motionRowY(lane);
        drawCurve(keys, top + 4, top + ROW_H - 4, c.motion);
      }
    }
    for (const key of keyframes) {
      const t = shownMs(key.id, key.t_ms);
      if (t === null) continue;
      const x = xOf(t);
      if (x < -60 || x > viewWidth + KEY_R) continue;
      const cy = keyRowY(key) + ROW_H / 2;
      const picked = keySelection(selectedKeyId, selectedKeyIds).includes(key.id);
      ctx.beginPath();
      ctx.moveTo(x, cy - KEY_R);
      ctx.lineTo(x + KEY_R, cy);
      ctx.lineTo(x, cy + KEY_R);
      ctx.lineTo(x - KEY_R, cy);
      ctx.closePath();
      ctx.fillStyle =
        key.lane_id === "expression" ? c.expression : key.interpolation !== "hold" ? c.motion : c.motionHold;
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
      if (key.pinned) pin(x + KEY_R - 1, cy - KEY_R + 1);
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
    if (ui !== null && ui.kind === "box") {
      // Selection box over the avatar rows.
      const bx = Math.min(ui.x0, ui.x1);
      const by = Math.min(ui.y0, ui.y1);
      ctx.fillStyle = c.selectedRing;
      ctx.globalAlpha = 0.25;
      ctx.fillRect(bx, by, Math.abs(ui.x1 - ui.x0), Math.abs(ui.y1 - ui.y0));
      ctx.globalAlpha = 1;
      ctx.strokeStyle = c.selected;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(bx + 0.5, by + 0.5, Math.abs(ui.x1 - ui.x0), Math.abs(ui.y1 - ui.y0));
      ctx.setLineDash([]);
    }
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
      const onAudio = ui.lane !== null;
      const onVideo = ui.vlane !== undefined && ui.vlane !== null;
      const top = onVideo ? video.addY : onAudio ? AUDIO_Y - 4 : VOICE_Y - 4;
      const bottom = onVideo ? video.bottom : onAudio ? audio.bottom + 4 : VOICE_Y + VOICE_H + 4;
      ctx.strokeStyle = c.selected;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(Math.round(ui.x), top);
      ctx.lineTo(Math.round(ui.x), bottom);
      ctx.stroke();
    } else if (ui !== null && ui.kind === "vmove") {
      const dragged = laneClips.find((v) => v.id === ui.clipId);
      if (dragged !== undefined) {
        const gx = xOf(ui.startMs);
        const gy = video.laneY(ui.laneIndex) + 2;
        const gw = Math.max(4, (dragged.end_ms - dragged.timeline_ms) * pxPerMs - 1);
        ctx.globalAlpha = 0.7;
        ctx.fillStyle = ui.fits ? c.clip : c.missing;
        ctx.fillRect(gx, gy, gw, VIDEO_LANE_H - 4);
        ctx.globalAlpha = 1;
        ctx.strokeStyle = ui.fits ? c.selected : c.missing;
        ctx.lineWidth = 2;
        ctx.strokeRect(gx, gy, gw, VIDEO_LANE_H - 4);
      }
    } else if (ui !== null && ui.kind === "amove") {
      const dragged = audioClips.find((a) => a.id === ui.clipId);
      if (dragged !== undefined) {
        const gx = xOf(ui.startMs);
        const gy = audio.laneY(ui.laneIndex) + 2;
        const gw = Math.max(4, (dragged.end_ms - dragged.timeline_ms) * pxPerMs - 1);
        ctx.globalAlpha = 0.7;
        ctx.fillStyle = ui.fits ? c.audio : c.missing;
        ctx.fillRect(gx, gy, gw, AUDIO_LANE_H - 4);
        ctx.globalAlpha = 1;
        ctx.strokeStyle = ui.fits ? c.selected : c.missing;
        ctx.lineWidth = 2;
        ctx.strokeRect(gx, gy, gw, AUDIO_LANE_H - 4);
      }
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
      playheadMs = Math.min(Math.max(ms, 0), contentMs);
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
    /** An audio clip under the pointer, and which part: an edge (trim) or the body (move). */
    function hitAudio(x: number, y: number): { clip: TimelineAudioClip; part: "start" | "end" | "body" } | null {
      const lane = laneAt(y, AUDIO_Y, audioLanes.length);
      if (typeof lane !== "number") {
        return null;
      }
      const laneId = audioLanes[lane]?.id;
      for (const clip of audioClips) {
        if (clip.lane_id !== laneId) continue;
        const x0 = xPos(clip.timeline_ms);
        const x1 = xPos(clip.end_ms);
        if (x < x0 || x > x1) continue;
        const grip = Math.min(EDGE_PX, (x1 - x0) / 3);
        return { clip, part: x <= x0 + grip ? "start" : x >= x1 - grip ? "end" : "body" };
      }
      return null;
    }
    /** A clip on a video lane under the pointer: an edge (trim) or the body (move). */
    function hitLaneClip(x: number, y: number): { clip: TimelineLaneClip; part: "start" | "end" | "body" } | null {
      const lane = videoLaneAt(y, VIDEO_TOP, videoLanes.length, avatarAt);
      if (typeof lane !== "number") {
        return null;
      }
      const laneId = videoLanes[lane]?.id;
      for (const clip of laneClips) {
        if (clip.lane_id !== laneId) continue;
        const x0 = xPos(clip.timeline_ms);
        const x1 = xPos(clip.end_ms);
        if (x < x0 || x > x1) continue;
        const grip = Math.min(EDGE_PX, (x1 - x0) / 3);
        return { clip, part: x <= x0 + grip ? "start" : x >= x1 - grip ? "end" : "body" };
      }
      return null;
    }
    /** A key diamond of an image clip under the pointer (the bottom strip of the block). */
    function hitClipKey(x: number, y: number, clip: TimelineLaneClip): string | null {
      const lane = videoLaneAt(y, VIDEO_TOP, videoLanes.length, avatarAt);
      if (typeof lane !== "number" || clip.image_id === null) return null;
      const bottom = video.laneY(lane) + VIDEO_LANE_H - 2;
      if (y < bottom - 2 * CLIP_KEY_R - 4) return null;
      let best: { id: string; gap: number } | null = null;
      for (const key of visibleClipKeys(clip)) {
        const gap = Math.abs(x - xPos(clip.timeline_ms + key.t_ms));
        if (gap <= CLIP_KEY_R + 2 && (best === null || gap < best.gap)) best = { id: key.id, gap };
      }
      return best?.id ?? null;
    }
    /** The y of a press is in the diamond strip along the bottom of a video-lane clip. */
    function inKeyStrip(y: number): boolean {
      const lane = videoLaneAt(y, VIDEO_TOP, videoLanes.length, avatarAt);
      if (typeof lane !== "number") return false;
      return y >= video.laneY(lane) + VIDEO_LANE_H - 2 - 2 * CLIP_KEY_R - 4;
    }
    /**
     * A press on a lane or audio clip, for the group (keyframes polish). Shift toggles the
     * clip in the group (no drag); the body of a clip in a group of several starts a group
     * drag. Returns true when it handled the press; otherwise the clip is now selected alone.
     */
    function pickClip(id: string, part: "start" | "end" | "body", shift: boolean, before: string[], startX: number): boolean {
      if (shift) {
        const next = toggleGroup(before, [id]);
        selectedClipIds = next;
        setPrimaryClip(next.includes(id) ? id : (next[0] ?? null));
        drag = null;
        return true;
      }
      if (part === "body" && before.includes(id) && before.length > 1) {
        selectedClipIds = before;
        const lockedClip = before.some((g) => {
          const v = laneClips.find((c) => c.id === g);
          return v !== undefined && laneLocked(v.lane_id);
        });
        drag = locked || lockedClip ? null : { mode: "gpress", grabId: id, ids: before, startX, deltaMs: 0, moved: false };
        return true;
      }
      selectedClipIds = [id];
      return false;
    }
    function laneLocked(laneId: string): boolean {
      return videoLanes.find((lane) => lane.id === laneId)?.locked ?? false;
    }
    function updateLaneMove(d: Extract<LaneDrag, { mode: "vmove" }>, x: number, y: number, alt: boolean): void {
      const length = d.clip.end_ms - d.clip.timeline_ms;
      d.startMs = snappedStart(d.clip.id, Math.max(0, Math.round(scrollMs + (x - d.grabDx) / pxPerMs)), length, alt);
      d.laneIndex = dragVideoLaneIndex(y, VIDEO_TOP, videoLanes.length, avatarAt);
      const target = videoLanes[d.laneIndex];
      const laneId = target?.id ?? d.clip.lane_id;
      dragUi = {
        kind: "vmove",
        clipId: d.clip.id,
        startMs: d.startMs,
        laneIndex: d.laneIndex,
        fits: !(target?.locked ?? false) && fitsOnLane(laneClips, laneId, d.startMs, d.startMs + length, d.clip.id),
      };
    }
    function snappedStart(clipId: string, startMs: number, length: number, alt: boolean): number {
      const points = snapTargets(clipId, alt);
      return points === null ? startMs : Math.round(snapMove(startMs, length, points, SNAP_PX / pxPerMs));
    }
    function snappedEdge(clipId: string, ms: number, alt: boolean): number {
      const points = snapTargets(clipId, alt);
      return points === null ? ms : snapEdge(ms, points, SNAP_PX / pxPerMs);
    }
    function updateAudioMove(d: Extract<AudioDrag, { mode: "amove" }>, x: number, y: number, alt: boolean): void {
      const length = d.clip.end_ms - d.clip.timeline_ms;
      d.startMs = snappedStart(d.clip.id, Math.max(0, Math.round(scrollMs + (x - d.grabDx) / pxPerMs)), length, alt);
      d.laneIndex = dragLaneIndex(y, AUDIO_Y, audioLanes.length);
      const laneId = audioLanes[d.laneIndex]?.id ?? d.clip.lane_id;
      dragUi = {
        kind: "amove",
        clipId: d.clip.id,
        startMs: d.startMs,
        laneIndex: d.laneIndex,
        fits: fitsOnLane(audioClips, laneId, d.startMs, d.startMs + length, d.clip.id),
      };
    }
    /** Timeline time of a key or reaction (null when it does not map). */
    function itemTime(kind: "key" | "reaction", id: string): number | null {
      const list: { id: string; t_ms: number | null }[] = kind === "key" ? keyframes : reactions;
      return list.find((item) => item.id === id)?.t_ms ?? null;
    }
    /** Where dragged keys snap (magnet on, no Alt): clip and line edges, the playhead, and
     * the other keys and reactions (keyframes decision 1). */
    function itemSnapPoints(ids: string[], alt: boolean): number[] | null {
      const base = snapTargets("", alt);
      if (base === null) return null;
      const others = [...keyframes, ...reactions]
        .filter((item) => !ids.includes(item.id) && item.t_ms !== null)
        .map((item) => item.t_ms as number);
      return [...new Set([...base, ...others])].sort((a, b) => a - b);
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
      const groupBefore = clipGroup().filter((id) => laneClips.some((c) => c.id === id) || audioClips.some((c) => c.id === id));
      const shot = hitLaneClip(x, y);
      if (shot !== null) {
        // A clip on a video lane: select it (and nothing else); drag the body to move it
        // (also to another lane), drag an edge to trim it. Locked lanes only select.
        selectedLaneClipId = shot.clip.id;
        selectedAudioClipId = null;
        selectedId = null;
        selectedPlacementId = null;
        selectedKeyId = null;
        selectedReactionId = null;
        // Key ids are unique to their clip, so this keeps only a selection on this clip.
        const current = selectedClipKeyIds.filter((id) => shot.clip.keys.some((k) => k.id === id));
        const keyId = hitClipKey(x, y, shot.clip);
        if (keyId !== null) {
          // A clip key: the playhead goes onto it (the clip bar then edits it); drag to move it,
          // with the rest of the selection. Shift-click adds or removes it (no drag, no seek).
          if (e.shiftKey) {
            // Released without moving: toggle this key; moved: a box from here.
            selectedClipKeyIds = current;
            drag = { mode: "cbox", clip: shot.clip, x0: x, y0: y, x1: x, y1: y, moved: false, add: true, toggleId: keyId };
            return;
          }
          const ids = current.includes(keyId) ? current : [keyId];
          selectedClipKeyIds = ids;
          const key = shot.clip.keys.find((k) => k.id === keyId);
          const t = shot.clip.timeline_ms + (key?.t_ms ?? 0);
          playheadMs = t;
          drag =
            locked || laneLocked(shot.clip.lane_id)
              ? null
              : { mode: "ckey", clip: shot.clip, keyId, ids, startX: x, fromMs: t, deltaMs: 0 };
          return;
        }
        if (shot.clip.keys.length > 0 && inKeyStrip(y)) {
          // A drag along the diamond strip of an image clip box-selects its keys (Shift adds).
          selectedClipIds = [shot.clip.id];
          selectedClipKeyIds = e.shiftKey ? current : [];
          drag = { mode: "cbox", clip: shot.clip, x0: x, y0: y, x1: x, y1: y, moved: false, add: e.shiftKey, toggleId: null };
          return;
        }
        selectedClipKeyIds = [];
        if (pickClip(shot.clip.id, shot.part, e.shiftKey, groupBefore, x)) return;
        if (locked || laneLocked(shot.clip.lane_id)) {
          drag = null;
        } else if (shot.part === "body") {
          drag = { mode: "vpress", clip: shot.clip, startX: x };
        } else {
          const ms = shot.part === "start" ? shot.clip.timeline_ms : shot.clip.end_ms;
          drag = { mode: "vtrim", clip: shot.clip, edge: shot.part, ms };
          dragUi = { kind: "vtrim", clip: shot.clip };
        }
        return;
      }
      if (videoLaneAt(y, VIDEO_TOP, videoLanes.length, avatarAt) !== null) {
        selectedLaneClipId = null; // empty space in a video lane
      }
      const sound = hitAudio(x, y);
      if (sound !== null) {
        // An audio clip: select it (and nothing else); drag the body to move it (also to
        // another lane), drag an edge to trim it. The playhead stays where it is.
        selectedAudioClipId = sound.clip.id;
        selectedLaneClipId = null;
        selectedId = null;
        selectedPlacementId = null;
        selectedKeyId = null;
        selectedReactionId = null;
        if (pickClip(sound.clip.id, sound.part, e.shiftKey, groupBefore, x)) return;
        if (locked) {
          drag = null;
        } else if (sound.part === "body") {
          drag = { mode: "apress", clip: sound.clip, startX: x };
        } else {
          const ms = sound.part === "start" ? sound.clip.timeline_ms : sound.clip.end_ms;
          drag = { mode: "atrim", clip: sound.clip, edge: sound.part, ms };
          dragUi = { kind: "atrim", clip: sound.clip };
        }
        return;
      }
      if (laneAt(y, AUDIO_Y, audioLanes.length) !== null) {
        selectedAudioClipId = null; // empty space in an audio lane
      }
      if (typeof videoLaneAt(y, VIDEO_TOP, videoLanes.length, avatarAt) === "number" || typeof laneAt(y, AUDIO_Y, audioLanes.length) === "number") {
        // Empty space in a video or audio lane: a click seeks (on release), a drag draws a box
        // that selects the lane clips it touches (Shift adds to the selection).
        if (e.shiftKey) {
          setPrimaryClip(groupBefore[0] ?? null);
          selectedClipIds = groupBefore;
        } else {
          selectedClipIds = [];
        }
        drag = { mode: "clipbox", x0: x, y0: y, x1: x, y1: y, moved: false, add: e.shiftKey };
        return;
      }
      const item = hitItem(x, y);
      if (item !== null) {
        // A key or a reaction: select it (and nothing else) and put the playhead on it, so
        // a preview drag or the inspector edits it (keyframes decision 1); drag sideways to move it.
        // On the collapsed Motion row the keys at that time are one group; Shift-click adds or
        // removes a group; dragging a selected key moves the whole selection.
        let ids = [item.id];
        if (item.kind === "key") {
          const key = keyframes.find((k) => k.id === item.id);
          const group = key === undefined ? [item.id] : keyGroup(keyframes, key, !lanesOpen).map((k) => k.id);
          const current = keySelection(selectedKeyId, selectedKeyIds);
          if (e.shiftKey) {
            const next = toggleGroup(current, group);
            selectItem("key", item.id, playheadMs);
            selectedKeyIds = next;
            selectedKeyId = next.includes(item.id) ? item.id : (next[0] ?? null);
            drag = null;
            return;
          }
          ids = current.includes(item.id) ? current : group;
          selectItem("key", item.id, item.t);
          selectedKeyIds = ids;
        } else {
          selectItem(item.kind, item.id, item.t);
        }
        drag = locked
          ? null
          : { mode: "ipress", kind: item.kind, id: item.id, ids, fromMs: item.t, startX: x, toMs: item.t };
        return;
      }
      if (y >= EXPR_Y) {
        // Empty avatar rows: a click seeks (on release), a drag draws a selection box.
        if (!e.shiftKey) {
          selectedKeyId = null;
          selectedKeyIds = [];
        }
        selectedReactionId = null;
        drag = { mode: "box", x0: x, y0: y, x1: x, y1: y, moved: false, add: e.shiftKey };
        return;
      }
      const placed = hitPlacement(x, y);
      if (placed !== null) {
        // A voice block: select it (and nothing else); the playhead stays where it is.
        selectedPlacementId = placed.id;
        selectedAudioClipId = null;
        selectedLaneClipId = null;
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
        selectedAudioClipId = null;
        selectedLaneClipId = null;
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
        selectedAudioClipId = null;
        selectedLaneClipId = null;
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
        const sound = hitAudio(x, y) ?? hitLaneClip(x, y);
        canvas.style.cursor =
          sound !== null && !locked
            ? sound.part === "body"
              ? "grab"
              : "ew-resize"
            : hitItem(x, y) !== null && !locked
            ? "grab"
            : over === null || locked
              ? "pointer"
              : over.part === "body"
                ? "grab"
                : "ew-resize";
        return;
      }
      if (d.mode === "vpress") {
        if (Math.abs(x - d.startX) > 4) {
          const index = videoLanes.findIndex((lane) => lane.id === d.clip.lane_id);
          const next: LaneDrag = {
            mode: "vmove",
            clip: d.clip,
            grabDx: d.startX - xPos(d.clip.timeline_ms),
            startMs: d.clip.timeline_ms,
            laneIndex: Math.max(0, index),
          };
          drag = next;
          updateLaneMove(next, x, y, e.altKey);
        }
        return;
      }
      if (d.mode === "vmove") {
        updateLaneMove(d, x, y, e.altKey);
        return;
      }
      if (d.mode === "gpress") {
        if (!d.moved && Math.abs(x - d.startX) <= 4) return;
        d.moved = true;
        const all = [...laneClips, ...audioClips];
        const grab = all.find((c) => c.id === d.grabId);
        if (grab === undefined) return;
        const raw = grab.timeline_ms + Math.round((x - d.startX) / pxPerMs);
        const snapped = snappedStart(grab.id, raw, grab.end_ms - grab.timeline_ms, e.altKey);
        d.deltaMs = clampGroupShift(all, d.ids, snapped - grab.timeline_ms);
        dragUi = { kind: "gmove", ids: d.ids, deltaMs: d.deltaMs, fits: groupFits(all, d.ids, d.deltaMs) };
        return;
      }
      if (d.mode === "clipbox") {
        if (!d.moved && Math.hypot(x - d.x0, y - d.y0) <= 4) return;
        d.moved = true;
        d.x1 = x;
        d.y1 = y;
        dragUi = { kind: "box", x0: d.x0, y0: d.y0, x1: x, y1: y };
        return;
      }
      if (d.mode === "ckey") {
        if (Math.abs(x - d.startX) <= 3 && d.deltaMs === 0) return;
        const raw = Math.round(d.fromMs + (x - d.startX) / pxPerMs);
        // The grabbed key snaps, always onto its own clip's start and end (Alt: free); with the
        // magnet on also onto the playhead, other clips' edges and the clip's unselected keys.
        const others = d.clip.keys.filter((k) => !d.ids.includes(k.id)).map((k) => d.clip.timeline_ms + k.t_ms);
        const points = e.altKey
          ? null
          : [d.clip.timeline_ms, d.clip.end_ms, ...(snapOn ? [playheadMs, ...others, ...(snapTargets(d.clip.id, false) ?? [])] : [])];
        const target = points === null ? raw : Math.round(snapEdge(raw, points, SNAP_PX / pxPerMs));
        const times = d.clip.keys.filter((k) => d.ids.includes(k.id)).map((k) => d.clip.timeline_ms + k.t_ms);
        d.deltaMs = clampShift(times, target - d.fromMs, d.clip.timeline_ms, d.clip.end_ms);
        dragUi = { kind: "ckey", ids: d.ids, deltaMs: d.deltaMs };
        return;
      }
      if (d.mode === "cbox") {
        if (!d.moved && Math.hypot(x - d.x0, y - d.y0) <= 4) return;
        d.moved = true;
        d.x1 = x;
        d.y1 = y;
        dragUi = { kind: "box", x0: d.x0, y0: d.y0, x1: x, y1: y };
        return;
      }
      if (d.mode === "vtrim") {
        d.ms = laneTrimTarget(d.clip, d.edge, snappedEdge(d.clip.id, scrollMs + x / pxPerMs, e.altKey), laneClips);
        dragUi = { kind: "vtrim", clip: withLaneTrim(d.clip, d.edge, d.ms) };
        return;
      }
      if (d.mode === "apress") {
        if (Math.abs(x - d.startX) > 4) {
          const index = audioLanes.findIndex((lane) => lane.id === d.clip.lane_id);
          const next: AudioDrag = {
            mode: "amove",
            clip: d.clip,
            grabDx: d.startX - xPos(d.clip.timeline_ms),
            startMs: d.clip.timeline_ms,
            laneIndex: Math.max(0, index),
          };
          drag = next;
          updateAudioMove(next, x, y, e.altKey);
        }
        return;
      }
      if (d.mode === "amove") {
        updateAudioMove(d, x, y, e.altKey);
        return;
      }
      if (d.mode === "atrim") {
        d.ms = audioTrimTarget(d.clip, d.edge, snappedEdge(d.clip.id, scrollMs + x / pxPerMs, e.altKey), audioClips);
        dragUi = { kind: "atrim", clip: withAudioTrim(d.clip, d.edge, d.ms) };
        return;
      }
      if (d.mode === "ipress" || d.mode === "imove") {
        if (d.mode === "ipress" && Math.abs(x - d.startX) <= 4) return;
        d.mode = "imove";
        const raw = Math.round(d.fromMs + (x - d.startX) / pxPerMs);
        const points = itemSnapPoints(d.ids, e.altKey);
        const target = points === null ? raw : Math.round(snapEdge(raw, points, SNAP_PX / pxPerMs));
        const times = d.ids.map((id) => itemTime(d.kind, id)).filter((t): t is number => t !== null);
        // Keys and reactions may sit past the footage (keyframes decision 4), up to the timeline end.
        const delta = clampShift(times, target - d.fromMs, 0, Math.max(0, contentMs - 1));
        d.toMs = d.fromMs + delta;
        dragUi = { kind: "imove", ids: d.ids, deltaMs: delta };
        return;
      }
      if (d.mode === "box") {
        if (!d.moved && Math.hypot(x - d.x0, y - d.y0) <= 4) return;
        d.moved = true;
        d.x1 = x;
        d.y1 = y;
        dragUi = { kind: "box", x0: d.x0, y0: d.y0, x1: x, y1: y };
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
    function up(e: PointerEvent): void {
      const d = drag;
      drag = null;
      if (d === null) {
        return;
      }
      if (d.mode === "box") {
        dragUi = null;
        if (!d.moved) {
          seek(e);
          return;
        }
        const [x0, x1] = [Math.min(d.x0, d.x1), Math.max(d.x0, d.x1)];
        const [y0, y1] = [Math.min(d.y0, d.y1), Math.max(d.y0, d.y1)];
        const inside = keyframes
          .filter((k) => {
            if (k.t_ms === null || k.orphaned) return false;
            const kx = xPos(k.t_ms);
            const ky = keyRowY(k) + ROW_H / 2;
            return kx >= x0 && kx <= x1 && ky >= y0 - KEY_R && ky <= y1 + KEY_R;
          })
          .sort((a, b) => (a.t_ms ?? 0) - (b.t_ms ?? 0))
          .map((k) => k.id);
        const current = d.add ? keySelection(selectedKeyId, selectedKeyIds) : [];
        const next = [...current, ...inside.filter((id) => !current.includes(id))];
        selectedKeyIds = next;
        selectedKeyId = next.includes(selectedKeyId ?? "") ? selectedKeyId : (next[0] ?? null);
        return;
      }
      if (d.mode === "vmove") {
        const lane = videoLanes[d.laneIndex];
        const ui = dragUi;
        const fits = ui !== null && ui.kind === "vmove" && ui.fits;
        const changed = d.startMs !== d.clip.timeline_ms || lane?.id !== d.clip.lane_id;
        if (fits && changed && lane !== undefined && onmovelane !== undefined) {
          void finish(onmovelane(d.clip.id, d.startMs, lane.id));
        } else {
          dragUi = null;
        }
        return;
      }
      if (d.mode === "vtrim") {
        const current = d.edge === "start" ? d.clip.timeline_ms : d.clip.end_ms;
        if (d.ms !== current && ontrimlane !== undefined) {
          void finish(ontrimlane(d.clip.id, d.edge, d.ms));
        } else {
          dragUi = null;
        }
        return;
      }
      if (d.mode === "vpress") {
        return;
      }
      if (d.mode === "gpress") {
        const ui = dragUi;
        if (!d.moved) {
          selectedClipIds = [d.grabId]; // a click on one clip of the group selects it alone
          return;
        }
        const fits = ui !== null && ui.kind === "gmove" && ui.fits;
        if (fits && d.deltaMs !== 0 && onmoveclips !== undefined) {
          const moves = groupMoveOrder([...laneClips, ...audioClips], d.ids, d.deltaMs).map((c) => ({
            kind: laneClips.some((v) => v.id === c.id) ? ("lane" as const) : ("audio" as const),
            id: c.id,
            ms: c.timeline_ms + d.deltaMs,
          }));
          void finish(onmoveclips(moves));
        } else {
          dragUi = null;
        }
        return;
      }
      if (d.mode === "clipbox") {
        dragUi = null;
        if (!d.moved) {
          seek(e);
          return;
        }
        const [y0, y1] = [Math.min(d.y0, d.y1), Math.max(d.y0, d.y1)];
        const lo = scrollMs + Math.min(d.x0, d.x1) / pxPerMs;
        const hi = scrollMs + Math.max(d.x0, d.x1) / pxPerMs;
        const vLanes = new Set(
          videoLanes.filter((_, i) => video.laneY(i) < y1 && y0 < video.laneY(i) + VIDEO_LANE_H).map((l) => l.id),
        );
        const aLanes = new Set(
          audioLanes.filter((_, i) => audio.laneY(i) < y1 && y0 < audio.laneY(i) + AUDIO_LANE_H).map((l) => l.id),
        );
        const inside = [...clipsInBox(laneClips, vLanes, lo, hi), ...clipsInBox(audioClips, aLanes, lo, hi)].map((c) => c.id);
        const next = d.add ? [...selectedClipIds, ...inside.filter((id) => !selectedClipIds.includes(id))] : inside;
        selectedClipIds = next;
        const keep = selectedLaneClipId ?? selectedAudioClipId;
        setPrimaryClip(keep !== null && next.includes(keep) ? keep : (next[0] ?? null));
        if (next.length > 0) {
          selectedId = null;
          selectedPlacementId = null;
          selectedKeyId = null;
          selectedReactionId = null;
        }
        return;
      }
      if (d.mode === "ckey") {
        if (d.deltaMs !== 0 && onmoveclipkeys !== undefined) {
          playheadMs = d.fromMs + d.deltaMs; // the playhead follows the grabbed key
          const moves = d.clip.keys
            .filter((k) => d.ids.includes(k.id))
            .map((k) => ({ id: k.id, ms: d.clip.timeline_ms + k.t_ms + d.deltaMs }));
          void finish(onmoveclipkeys(d.clip.id, moves));
        } else {
          dragUi = null;
        }
        return;
      }
      if (d.mode === "cbox") {
        dragUi = null;
        if (!d.moved) {
          if (d.toggleId !== null) selectedClipKeyIds = toggleGroup(selectedClipKeyIds, [d.toggleId]);
          return;
        }
        const lo = Math.min(d.x0, d.x1);
        const hi = Math.max(d.x0, d.x1);
        const inside = visibleClipKeys(d.clip)
          .filter((k) => {
            const kx = xPos(d.clip.timeline_ms + k.t_ms);
            return kx >= lo - CLIP_KEY_R && kx <= hi + CLIP_KEY_R;
          })
          .map((k) => k.id);
        selectedClipKeyIds = [...selectedClipKeyIds, ...inside.filter((id) => !selectedClipKeyIds.includes(id))];
        return;
      }
      if (d.mode === "amove") {
        const lane = audioLanes[d.laneIndex];
        const ui = dragUi;
        const fits = ui !== null && ui.kind === "amove" && ui.fits;
        const changed = d.startMs !== d.clip.timeline_ms || lane?.id !== d.clip.lane_id;
        if (fits && changed && lane !== undefined && onmoveaudio !== undefined) {
          void finish(onmoveaudio(d.clip.id, d.startMs, lane.id));
        } else {
          dragUi = null;
        }
        return;
      }
      if (d.mode === "atrim") {
        const current = d.edge === "start" ? d.clip.timeline_ms : d.clip.end_ms;
        if (d.ms !== current && ontrimaudio !== undefined) {
          void finish(ontrimaudio(d.clip.id, d.edge, d.ms));
        } else {
          dragUi = null;
        }
        return;
      }
      if (d.mode === "apress") {
        return;
      }
      if (d.mode === "imove") {
        const delta = d.toMs - d.fromMs;
        if (delta !== 0 && d.kind === "key" && onmovekeys !== undefined) {
          playheadMs = d.toMs; // the playhead follows the grabbed key
          const moves = d.ids.flatMap((id) => {
            const t = itemTime("key", id);
            return t === null ? [] : [{ id, ms: t + delta }];
          });
          void finish(onmovekeys(moves));
        } else if (delta !== 0 && d.kind === "reaction" && onmovereaction !== undefined) {
          playheadMs = d.toMs;
          void finish(onmovereaction(d.id, d.toMs));
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
      if (e.dataTransfer !== null && e.dataTransfer.types.includes("Files")) {
        // Audio files from Explorer (M8-1): the app shell sends their paths to the
        // editor after the drop, which asks `dropTarget` where they landed.
        if (locked) {
          return;
        }
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        const top = canvas?.getBoundingClientRect().top ?? 0;
        dragUi = {
          kind: "drop",
          x: dropX(e),
          lane: laneAt(e.clientY - top, AUDIO_Y, audioLanes.length),
          vlane: videoLaneAt(e.clientY - top, VIDEO_TOP, videoLanes.length, avatarAt),
        };
        return;
      }
      if (e.dataTransfer !== null && e.dataTransfer.types.includes(FOOTAGE_DRAG_TYPE)) {
        // A recording from the Footage tab (M8-2): only the video lanes and their add row take it.
        const top = canvas?.getBoundingClientRect().top ?? 0;
        const vlane = videoLaneAt(e.clientY - top, VIDEO_TOP, videoLanes.length, avatarAt);
        if (locked || vlane === null) {
          if (dragUi !== null && dragUi.kind === "drop") dragUi = null;
          return;
        }
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        dragUi = { kind: "drop", x: dropX(e), lane: null, vlane };
        return;
      }
      if (locked || e.dataTransfer === null || !e.dataTransfer.types.includes(LINE_DRAG_TYPE)) {
        return;
      }
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      dragUi = { kind: "drop", x: dropX(e), lane: null };
    }
    function dragleave(): void {
      if (dragUi !== null && dragUi.kind === "drop") {
        dragUi = null;
      }
    }
    function drop(e: DragEvent): void {
      if (e.dataTransfer !== null && e.dataTransfer.types.includes("Files")) {
        e.preventDefault();
        dragUi = null;
        return;
      }
      const sourceId = e.dataTransfer?.getData(FOOTAGE_DRAG_TYPE) ?? "";
      if (sourceId !== "") {
        const top = canvas?.getBoundingClientRect().top ?? 0;
        const vlane = videoLaneAt(e.clientY - top, VIDEO_TOP, videoLanes.length, avatarAt);
        if (locked || vlane === null || onplacefootage === undefined) {
          dragUi = null;
          return;
        }
        e.preventDefault();
        const ms = Math.max(0, Math.round(scrollMs + dropX(e) / pxPerMs));
        const laneId = typeof vlane === "number" ? (videoLanes[vlane]?.id ?? null) : null;
        void finish(onplacefootage(sourceId, ms, laneId, vlane === "add"));
        return;
      }
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
    <IconButton
      icon={Magnet}
      label={snapOn
        ? "Snapping on: audio and lane clips snap to clip edges and the playhead (hold Alt to drag freely)"
        : "Snapping off: click to snap audio and lane clips to clip edges and the playhead"}
      pressed={snapOn}
      onclick={toggleSnap}
    />
    <span class="sep" aria-hidden="true"></span>
    <IconButton icon={StepBack} label="Previous avatar key (<)" onclick={() => gotoKey(-1)} />
    <IconButton icon={StepForward} label="Next avatar key (>)" onclick={() => gotoKey(1)} />
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
      onto the timeline to place it. Drag a recording from the Footage tab, or images and videos
      from Explorer, onto a video lane (or "+ Video lane"); they show over the main footage. Drag music or sound effects from Explorer onto an audio lane
      (or onto "+ Audio lane" for a new lane); drag an audio clip to move it, also up or down to
      another lane, and drag its edge to trim it. With the magnet on, audio and lane clips snap to clip edges and the playhead (hold Alt to drag freely); S splits the selected audio or lane clip at the playhead. Several lane clips: drag over empty space in the video or audio lanes to box-select clips, Shift-click a clip to add or remove it, drag one of them to move them all (each stays on its lane), Delete removes them all. Image clip keys (diamonds along the bottom of the block, with their curves): click one to put the playhead on it, Shift-click to add or remove, drag along the diamond strip to box-select (Shift adds), drag to move the selection, Delete removes it, &lt; and &gt; step through them while the clip is selected; a small arrow at an edge means a trim hid keys beyond it (they still shape the motion). Avatar keys and reactions: click to select (the playhead goes there; on the collapsed Motion row the keys at one time are one group), Shift-click to add or remove, drag over empty avatar rows to box-select, drag sideways to
      move (the whole selection, snapping with the magnet); &lt; and &gt; step between keys. Past the end of the footage a key or reaction keeps its timeline time (pin mark) and no footage edit moves it; moving it onto footage anchors it again. Wheel scrolls, Ctrl+wheel zooms.
    </p>
  {/if}
  <div class="body">
    <div class="heads" style:height="{HEIGHT}px">
      <div class="head ruler num" style:top="0px" style:height="{RULER_H}px">{clock(playheadMs)}</div>
      <div class="head add" style:top="{video.addY}px" style:height="{VIDEO_ADD_H}px">
        <button
          type="button"
          class="addlane"
          title="Add a video lane on top (or drop files or a recording on this row)"
          disabled={locked}
          onclick={() => void onaddvideolane?.()}
        >
          <Plus size={12} strokeWidth={2} aria-hidden="true" /> Video lane
        </button>
      </div>
      {#each videoLanes as lane, i (lane.id)}
        {@const empty = !laneClips.some((v) => v.lane_id === lane.id)}
        <div class="head vlane" class:dim={lane.hidden} style:top="{video.laneY(i)}px" style:height="{VIDEO_LANE_H}px">
          <span class="sw" style:background="var(--lane-clip)"></span>
          <input
            class="lname"
            value={lane.name}
            aria-label="Video lane name"
            title="Rename the lane"
            disabled={locked}
            onkeydown={(e) => {
              if (e.key === "Enter" || e.key === "Escape") {
                if (e.key === "Escape") e.currentTarget.value = lane.name;
                e.currentTarget.blur();
              }
              e.stopPropagation();
            }}
            onchange={(e) => {
              const name = e.currentTarget.value.trim();
              if (name === "" || name === lane.name) {
                e.currentTarget.value = lane.name;
              } else {
                void onvideolane?.(lane.id, { name });
              }
            }}
          />
          <button
            type="button"
            class="toggle"
            title={lane.hidden ? "Show this lane (it is hidden in the preview and the export)" : "Hide this lane"}
            aria-label={lane.hidden ? `Show ${lane.name}` : `Hide ${lane.name}`}
            aria-pressed={lane.hidden}
            disabled={locked}
            onclick={() => void onvideolane?.(lane.id, { hidden: !lane.hidden })}
          >
            {#if lane.hidden}
              <EyeOff size={12} strokeWidth={2} aria-hidden="true" />
            {:else}
              <Eye size={12} strokeWidth={2} aria-hidden="true" />
            {/if}
          </button>
          <button
            type="button"
            class="toggle"
            class:on={lane.locked}
            title={lane.locked ? "Unlock this lane" : "Lock this lane (its clips cannot be edited)"}
            aria-label={lane.locked ? `Unlock ${lane.name}` : `Lock ${lane.name}`}
            aria-pressed={lane.locked}
            disabled={locked}
            onclick={() => void onvideolane?.(lane.id, { locked: !lane.locked })}
          >
            {#if lane.locked}
              <Lock size={12} strokeWidth={2} aria-hidden="true" />
            {:else}
              <LockOpen size={12} strokeWidth={2} aria-hidden="true" />
            {/if}
          </button>
          {#if empty}
            <button
              type="button"
              class="toggle"
              title="Remove this empty lane"
              aria-label="Remove {lane.name}"
              disabled={locked}
              onclick={() => void onremovevideolane?.(lane.id)}
            >
              <X size={12} strokeWidth={2} aria-hidden="true" />
            </button>
          {/if}
        </div>
      {/each}
      {#if video.avatarY !== null}
        <div class="head vlane avatarrow" style:top="{video.avatarY}px" style:height="{AVATAR_ROW_H}px">
          <span class="sw" style:background="var(--lane-expression)"></span>
          <span class="aname">Avatar</span>
          <button
            type="button"
            class="toggle"
            title="Move the avatar up a layer (over the next lane)"
            aria-label="Move the avatar up a layer"
            disabled={locked || avatarAt >= videoLanes.length}
            onclick={() => void onavatarlayer?.(movedAvatarLane(videoLanes, avatarAt, 1))}
          >
            <ArrowUp size={12} strokeWidth={2} aria-hidden="true" />
          </button>
          <button
            type="button"
            class="toggle"
            title="Move the avatar down a layer (under the next lane)"
            aria-label="Move the avatar down a layer"
            disabled={locked || avatarAt <= 0}
            onclick={() => void onavatarlayer?.(movedAvatarLane(videoLanes, avatarAt, -1))}
          >
            <ArrowDown size={12} strokeWidth={2} aria-hidden="true" />
          </button>
        </div>
      {/if}
      <div class="head big" style:top="{LANE_Y}px" style:height="{LANE_H}px">
        <span class="sw" style:background="var(--lane-clip)"></span>Video
      </div>
      <div class="head big" style:top="{VOICE_Y}px" style:height="{VOICE_H}px">
        <span class="sw" style:background="var(--lane-voice)"></span>Voice
      </div>
      {#each audioLanes as lane, i (lane.id)}
        {@const empty = !audioClips.some((a) => a.lane_id === lane.id)}
        <div class="head audio" style:top="{audio.laneY(i)}px" style:height="{AUDIO_LANE_H}px">
          <div class="arow">
            <span class="sw" style:background="var(--lane-audio)"></span>
            <input
              class="lname"
              value={lane.name}
              aria-label="Audio lane name"
              title="Rename the lane"
              disabled={locked}
              onkeydown={(e) => {
                if (e.key === "Enter" || e.key === "Escape") {
                  if (e.key === "Escape") e.currentTarget.value = lane.name;
                  e.currentTarget.blur();
                }
                e.stopPropagation();
              }}
              onchange={(e) => {
                const name = e.currentTarget.value.trim();
                if (name === "" || name === lane.name) {
                  e.currentTarget.value = lane.name;
                } else {
                  void onaudiolane?.(lane.id, { name });
                }
              }}
            />
            {#if audioLanes.length > 1 && empty}
              <button
                type="button"
                class="toggle"
                title="Remove this empty lane"
                aria-label="Remove {lane.name}"
                disabled={locked}
                onclick={() => void onremoveaudiolane?.(lane.id)}
              >
                <X size={12} strokeWidth={2} aria-hidden="true" />
              </button>
            {/if}
          </div>
          <div class="arow">
            <button
              type="button"
              class="ms"
              class:on={lane.mute}
              title={lane.mute ? "Unmute" : "Mute this lane"}
              aria-pressed={lane.mute}
              disabled={locked}
              onclick={() => void onaudiolane?.(lane.id, { mute: !lane.mute })}>M</button
            >
            <button
              type="button"
              class="ms solo"
              class:on={lane.solo}
              title={lane.solo ? "Unsolo" : "Solo: hear only soloed lanes"}
              aria-pressed={lane.solo}
              disabled={locked}
              onclick={() => void onaudiolane?.(lane.id, { solo: !lane.solo })}>S</button
            >
            <input
              class="db num"
              type="number"
              min="-60"
              max="12"
              step="0.5"
              value={lane.gain_db}
              aria-label="{lane.name} level in dB"
              title="Lane level in dB (-60 to +12)"
              disabled={locked}
              onkeydown={(e) => e.stopPropagation()}
              onchange={(e) => {
                const value = e.currentTarget.valueAsNumber;
                if (Number.isFinite(value) && value !== lane.gain_db) {
                  void onaudiolane?.(lane.id, { gain_db: Math.min(12, Math.max(-60, value)) });
                } else {
                  e.currentTarget.value = String(lane.gain_db);
                }
              }}
            />
            <span class="unit">dB</span>
          </div>
        </div>
      {/each}
      <div class="head add" style:top="{audio.addY}px" style:height="{ADD_ROW_H}px">
        <button
          type="button"
          class="addlane"
          title="Add an audio lane (or drop files on this row)"
          disabled={locked}
          onclick={() => void onaddaudiolane?.()}
        >
          <Plus size={12} strokeWidth={2} aria-hidden="true" /> Audio lane
        </button>
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
  .head.audio {
    flex-direction: column;
    align-items: stretch;
    justify-content: center;
    gap: 2px;
    padding: 0 6px 0 8px;
  }
  .arow {
    display: flex;
    align-items: center;
    gap: 4px;
    min-width: 0;
  }
  .head.vlane {
    gap: 3px;
    padding: 0 4px 0 8px;
  }
  .head.dim {
    opacity: 0.55;
  }
  .avatarrow .aname {
    flex: 1;
    font-size: 11px;
    color: var(--text-2);
  }
  .toggle.on {
    color: var(--warning);
  }
  .lname {
    flex: 1;
    min-width: 0;
    height: 17px;
    padding: 0 3px;
    border: 1px solid transparent;
    border-radius: var(--r-sm);
    background: none;
    color: var(--text-1);
    font: inherit;
    font-size: var(--fs-xs);
    font-weight: 600;
  }
  .lname:hover,
  .lname:focus {
    border-color: var(--border-strong);
    background: var(--surface-2);
  }
  .ms {
    width: 18px;
    height: 16px;
    padding: 0;
    border: 1px solid var(--border-strong);
    border-radius: var(--r-sm);
    background: none;
    color: var(--text-2);
    font-size: 10px;
    font-weight: 700;
    line-height: 1;
  }
  .ms.on {
    border-color: var(--warning);
    background: var(--warning);
    color: var(--bg);
  }
  .ms.solo.on {
    border-color: var(--accent);
    background: var(--accent);
  }
  .db {
    width: 44px;
    height: 16px;
    margin-left: auto;
    padding: 0 2px;
    border: 1px solid var(--border-strong);
    border-radius: var(--r-sm);
    background: var(--surface-2);
    color: var(--text-1);
    font-size: 10px;
    text-align: right;
  }
  .unit {
    color: var(--text-3);
    font-size: 10px;
  }
  .addlane {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 0 4px;
    border: none;
    border-radius: var(--r-sm);
    background: none;
    color: var(--text-3);
    font-size: var(--fs-xs);
  }
  .addlane:hover:not(:disabled) {
    background: var(--surface-3);
    color: var(--text-1);
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
