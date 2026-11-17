export type ProjectSummary = {
  name: string;
  folder: string;
  schema_version: number;
  source_count: number;
  clip_count: number;
  voice_status: string;
  avatar_status: string;
  save_error: string | null;
  problem_count: number;
};

export type RecentItem = {
  name: string;
  folder: string;
  last_opened: string;
  exists: boolean;
};

export type FootageItem = {
  id: string;
  path: string;
  external: boolean;
  exists: boolean;
  width: number;
  height: number;
  fps: number;
  duration_ms: number;
  audio_tracks: number;
};

export type FootageReport = {
  items: FootageItem[];
  added: number;
  errors: string[];
};

/** Shown when the backend cannot be reached at all (M7 S4). */
export const BACKEND_GONE =
  "The app's background service is not answering. Close PNGtuber Studio and start it again; your project was saved after the last change.";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new Error(BACKEND_GONE); // network-level failure: no HTTP answer
  }
  if (!response.ok) {
    let message =
      response.status >= 500
        ? `Something went wrong inside the app (HTTP ${response.status}). The console window shows the details.`
        : `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      // keep the HTTP status message
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

function post<T>(url: string, body?: unknown): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function getProject(): Promise<ProjectSummary | null> {
  return request<ProjectSummary | null>("/api/project");
}

export function newProject(name: string, parent: string): Promise<ProjectSummary> {
  return post<ProjectSummary>("/api/project/new", { name, parent });
}

export function openProject(folder: string): Promise<ProjectSummary> {
  return post<ProjectSummary>("/api/project/open", { folder });
}

export function getRecent(): Promise<RecentItem[]> {
  return request<RecentItem[]>("/api/recent");
}

export function removeRecent(folder: string): Promise<RecentItem[]> {
  return post<RecentItem[]>("/api/recent/remove", { folder });
}

export function getFootage(): Promise<FootageReport> {
  return request<FootageReport>("/api/footage");
}

export function rescanFootage(): Promise<FootageReport> {
  return post<FootageReport>("/api/footage/rescan");
}

export function relinkSource(sourceId: string, path: string): Promise<FootageReport> {
  return post<FootageReport>("/api/footage/relink", { source_id: sourceId, path });
}

export type TimelineSource = {
  id: string;
  external: boolean;
  fps_num: number;
  fps_den: number;
  fps: number;
  width: number;
  height: number;
  duration_ms: number;
  file_missing: boolean;
};

export type TimelineClip = {
  id: string;
  position: number;
  source_id: string;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  in_ms: number;
  out_ms: number;
  speed: number;
  overlay: boolean;
  source: TimelineSource | null;
};

export type TimelineProblem = {
  kind: string;
  owner_id: string;
  missing_id: string;
  message: string;
};

/** A placed line on the voice lane. Times are TIMELINE ms; null when there is nothing to draw. */
export type TimelinePlacement = {
  id: string;
  line_id: string;
  /** Empty when the line no longer exists. */
  line_text: string;
  allow_overlap: boolean;
  /** The take that plays (override, else the line's active take); null when there is none. */
  take_id: string | null;
  duration_ms: number | null;
  start_ms: number | null;
  end_ms: number | null;
  anchor_clip_id: string;
  anchor_source_ms: number;
  /** Its footage was cut away; the placement is parked at a clip edge. */
  orphaned: boolean;
  /** Ms this line's audio runs past the start of the next playing line; 0 when it does not. */
  overflow_ms: number;
  overflow_next_id: string | null;
  /** Ms it could start earlier without touching the previous playing line; set when it overflows. */
  slack_ms: number;
  /** Speed-up of this line's audio (1 to 1.25); `duration_ms` is the length that plays. */
  stretch: number;
  /** The take as recorded, before the stretch. */
  raw_duration_ms: number | null;
  /** The stretch that clears this line's overflow exactly; null when it has none or none can. */
  fit_stretch: number | null;
  /** The playing take's manual cut points as a tag ("" without a cut, M5-0); part of the audio cache key. */
  trim: string;
};

export type TimelineState = {
  clips: TimelineClip[];
  /** Placed lines ordered by start time (unmappable ones last). */
  placements: TimelinePlacement[];
  duration_ms: number;
  other_track_clips: number;
  orphan_count: number;
  problems: TimelineProblem[];
  can_undo: boolean;
  can_redo: boolean;
  undo_label: string | null;
  redo_label: string | null;
  save_error: string | null;
  /** Short hash of the voice chain ("invalid" when it cannot be used). A change means decoded voice audio is stale. */
  fx_version: string;
  /** Level of the footage's own sound in the preview mix, in dB (set in the Voice FX tab). */
  game_audio_db: number;
  /** Avatar lane keys (M5-5), by time; `t_ms` null when the anchor cannot be mapped. */
  keyframes: TimelineKeyframe[];
  reactions: TimelineReaction[];
  avatar: AvatarSettings;
};

export type TimelineKeyframe = {
  id: string;
  lane_id: string;
  value: number | string;
  interpolation: "hold" | "smooth";
  t_ms: number | null;
  anchor_clip_id: string;
  anchor_source_ms: number;
  orphaned: boolean;
};

export type TimelineReaction = {
  id: string;
  type: "shake" | "hop" | "pop_in" | "squish";
  intensity: number;
  duration_ms: number;
  t_ms: number | null;
  anchor_clip_id: string;
  anchor_source_ms: number;
  orphaned: boolean;
};

export type AvatarSettings = {
  art_folder: string | null;
  x: number;
  y: number;
  scale: number;
  rotation_deg: number;
  auto_key_expression: boolean;
  /** Base motion (schema v4): each lane's value where it has no keys. */
  bounce: number;
  float_amp: number;
  float_speed: number;
  /** Direction of the idle float in degrees: 0 up and down, 90 side to side. */
  float_angle_deg: number;
  blink_rate: number;
  mouth_sensitivity: number;
};

export type EditResult = {
  /** What was undone or redone; null when there was nothing to do. */
  label: string | null;
  timeline: TimelineState;
};

export function getTimeline(): Promise<TimelineState> {
  return request<TimelineState>("/api/timeline");
}

export function addClip(sourceId: string, position?: number): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/clips", {
    source_id: sourceId,
    position: position ?? null,
  });
}

export function undoEdit(): Promise<EditResult> {
  return post<EditResult>("/api/timeline/undo");
}

export function redoEdit(): Promise<EditResult> {
  return post<EditResult>("/api/timeline/redo");
}

/** One edit. `source_ms` in a trim is SOURCE time, not timeline time. */
export type EditOp =
  | { op: "add_clip"; source_id: string; position?: number | null }
  | { op: "remove_clip"; clip_id: string }
  | { op: "set_speed"; clip_id: string; speed: number }
  | { op: "reorder_clip"; clip_id: string; new_position: number }
  | { op: "split_clip"; timeline_ms: number; right_clip_id?: string | null }
  | { op: "trim_clip"; clip_id: string; edge: "in" | "out"; source_ms: number }
  | { op: "ripple_delete"; start_ms: number; end_ms: number; right_clip_id?: string | null }
  | { op: "add_placement"; line_id: string; timeline_ms: number; placement_id?: string | null }
  | { op: "move_placement"; placement_id: string; timeline_ms: number }
  | { op: "remove_placement"; placement_id: string }
  // Avatar (M5-5). Times are timeline ms; the backend stores footage anchors.
  | {
      op: "add_keyframe";
      lane_id: string;
      timeline_ms: number;
      value: number | string;
      interpolation?: "hold" | "smooth" | null;
      keyframe_id?: string | null;
    }
  | { op: "key_lane"; lane_id: string; timeline_ms: number; value: number | string; keyframe_id?: string | null }
  | { op: "key_lane_by"; lane_id: string; timeline_ms: number; delta?: number; factor?: number }
  | { op: "move_keyframe"; keyframe_id: string; timeline_ms: number }
  | { op: "set_keyframe_value"; keyframe_id: string; value: number | string }
  | { op: "set_keyframe_interpolation"; keyframe_id: string; interpolation: "hold" | "smooth" }
  | { op: "remove_keyframe"; keyframe_id: string }
  | {
      op: "add_reaction";
      type: string;
      timeline_ms: number;
      intensity?: number;
      duration_ms?: number;
      reaction_id?: string | null;
    }
  | { op: "move_reaction"; reaction_id: string; timeline_ms: number }
  | { op: "set_reaction"; reaction_id: string; type?: string; intensity?: number; duration_ms?: number }
  | { op: "remove_reaction"; reaction_id: string }
  | {
      op: "set_avatar_settings";
      x?: number;
      y?: number;
      scale?: number;
      rotation_deg?: number;
      auto_key_expression?: boolean;
      bounce?: number;
      float_amp?: number;
      float_speed?: number;
      float_angle_deg?: number;
      blink_rate?: number;
      mouth_sensitivity?: number;
    };

export function splitClip(timelineMs: number): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/split", { timeline_ms: timelineMs });
}

export function rippleDelete(startMs: number, endMs: number): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/ripple-delete", { start_ms: startMs, end_ms: endMs });
}

export function trimClip(
  clipId: string,
  edge: "in" | "out",
  sourceMs: number,
): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/trim", {
    clip_id: clipId,
    edge,
    source_ms: sourceMs,
  });
}

export function reorderClip(clipId: string, newPosition: number): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/reorder", {
    clip_id: clipId,
    new_position: newPosition,
  });
}

export function setClipSpeed(clipId: string, speed: number): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/speed", { clip_id: clipId, speed });
}

export function removeClip(clipId: string): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/remove", { clip_id: clipId });
}

/** Put a generated line on the timeline. `timelineMs` is TIMELINE time; the backend anchors it to footage. */
export function placeLine(
  lineId: string,
  timelineMs: number,
  placementId?: string,
): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/place", {
    line_id: lineId,
    timeline_ms: Math.round(timelineMs),
    placement_id: placementId ?? null,
  });
}

/** `timelineMs` is where the START of the placed line goes (TIMELINE time). */
export function setPlacementStretch(placementId: string, stretch: number): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/stretch", {
    placement_id: placementId,
    stretch,
  });
}

export function movePlacement(placementId: string, timelineMs: number): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/move-placement", {
    placement_id: placementId,
    timeline_ms: Math.round(timelineMs),
  });
}

export function removePlacement(placementId: string): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/remove-placement", { placement_id: placementId });
}

/** Lowest and highest sample of each bucket of a take, -1 to 1, left to right. */
export type PeaksReport = {
  take_id: string;
  duration_ms: number;
  sample_rate: number;
  buckets: number;
  lows: number[];
  highs: number[];
};

export function getTakePeaks(takeId: string, buckets = 400): Promise<PeaksReport> {
  return request<PeaksReport>(`/api/takes/${encodeURIComponent(takeId)}/peaks?buckets=${buckets}`);
}

/**
 * `GET /api/avatar/track`: the avatar drawn by the Python solver, sampled at `fps` (M5-6).
 * Frame k is at k * 1000 / fps ms. See docs/API_MODELS.md "Avatar preview".
 */
export type FrameTrack = {
  version: string;
  fps: number;
  duration_ms: number;
  frame_count: number;
  /** Sprite height at scale 1, as a fraction of the frame height. */
  height_fraction: number;
  /** "expression/state" keys, state like "oicm". */
  sprites: string[];
  /** [first frame, index into sprites or -1], each run lasting until the next. */
  sprite_runs: [number, number][];
  x: number[];
  y: number[];
  scale: number[];
  rotation: number[];
  squash: number[];
};

export function getAvatarTrack(): Promise<FrameTrack> {
  return request<FrameTrack>("/api/avatar/track");
}

/** A downscaled sprite of the project's art for a track key "expression/state". */
export function avatarSpriteUrl(key: string): string {
  const cut = key.lastIndexOf("/");
  const expression = key.slice(0, cut);
  const state = key.slice(cut + 1);
  return `/media/avatar/${encodeURIComponent(expression)}/${encodeURIComponent(state)}`;
}

/** Several edits as ONE undo step; all apply or none do. */
export function editBatch(label: string, ops: EditOp[]): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/batch", { label, ops });
}

/** URL a <video> tag can play for a source of the open project (Range supported). */
export function sourceMediaUrl(sourceId: string): string {
  return `/media/source/${encodeURIComponent(sourceId)}`;
}

/** Native file dialog; null when cancelled or not running in the app window. */
export async function pickFile(): Promise<string | null> {
  const result = await window.pywebview?.api?.pick_file?.();
  return result ?? null;
}

/** Native folder dialog; null when cancelled or not running in the app window. */
export async function pickFolder(): Promise<string | null> {
  const result = await window.pywebview?.api?.pick_folder?.();
  return result ?? null;
}

// ---------------------------------------------------------------------------
// Voice (M3): voice profile, line bank, takes, generation jobs.
// Shapes are listed in docs/API_MODELS.md; keep the two in step.
// ---------------------------------------------------------------------------

export type VoiceStatus =
  | "no_profile"
  | "no_reference"
  | "file_missing"
  | "unreadable"
  | "invalid"
  | "ready";

export type VoiceState = {
  status: VoiceStatus;
  ready: boolean;
  profile_id: string | null;
  name: string | null;
  reference_path: string | null;
  duration_ms: number | null;
  sample_rate: number | null;
  hash: string | null;
  problems: string[];
  warnings: string[];
};

export type LineItem = {
  id: string;
  text: string;
  emotion: string;
  /** False when the emotion is no longer in the presets file. */
  emotion_known: boolean;
  /** Stored overrides; null means "use the preset". */
  exaggeration: number | null;
  cfg_weight: number | null;
  /** What generation would use (preset, then override); null when the emotion is unknown. */
  effective_exaggeration: number | null;
  effective_cfg_weight: number | null;
  allow_overlap: boolean;
  active_take_id: string | null;
  generated: boolean;
  take_count: number;
  placement_count: number;
};

export type LineBankState = {
  lines: LineItem[];
  /** Preset names in file order. */
  emotions: string[];
  can_undo: boolean;
  can_redo: boolean;
  undo_label: string | null;
  redo_label: string | null;
  save_error: string | null;
};

export type TakeItem = {
  id: string;
  line_id: string;
  seed: number;
  text: string;
  exaggeration: number;
  cfg_weight: number;
  duration_ms: number;
  starred: boolean;
  active: boolean;
  /** ISO date-time. */
  created: string;
  raw_file: string;
  file_exists: boolean;
  /** Manual cut points in raw take ms (M5-0); null = no cut on that side. */
  trim_start_ms: number | null;
  trim_end_ms: number | null;
};

/** `GET /api/takes/{id}/trim`: what the trimmer shows (raw take ms). */
export type TakeTrimInfo = {
  take_id: string;
  duration_ms: number;
  /** The cut points this report was measured with (stored, or the previewed ones). */
  trim_start_ms: number | null;
  trim_end_ms: number | null;
  stored_start_ms: number | null;
  stored_end_ms: number | null;
  /** Where the automatic silence trim keeps the take, inside the cut points. */
  auto_start_ms: number;
  auto_end_ms: number;
  silent: boolean;
};

/** The stored trim, or (with `preview`) the automatic trim measured inside the given cuts. */
export function getTakeTrim(
  takeId: string,
  preview?: { start_ms: number | null; end_ms: number | null },
): Promise<TakeTrimInfo> {
  let url = `/api/takes/${encodeURIComponent(takeId)}/trim`;
  if (preview !== undefined) {
    const parts = ["preview=1"];
    if (preview.start_ms !== null) parts.push(`start_ms=${Math.round(preview.start_ms)}`);
    if (preview.end_ms !== null) parts.push(`end_ms=${Math.round(preview.end_ms)}`);
    url += `?${parts.join("&")}`;
  }
  return request<TakeTrimInfo>(url);
}

export type TakeDeleteReport = {
  removed_take_count: number;
  removed_line: boolean;
  freed_bytes: number;
  failed_files: string[];
  cleared_active_line_ids: string[];
  cleared_override_placement_ids: string[];
};

export type TakeStorage = {
  take_id: string;
  seed: number;
  duration_ms: number;
  size_bytes: number;
  file_exists: boolean;
  starred: boolean;
  active: boolean;
};

export type LineStorage = {
  line_id: string;
  text: string;
  take_count: number;
  size_bytes: number;
  takes: TakeStorage[];
};

/** A file in media/takes_raw that no take points at. Reported only; the app never deletes it. */
export type UnreferencedFile = {
  path: string;
  size_bytes: number;
};

export type StorageReport = {
  lines: LineStorage[];
  take_count: number;
  total_bytes: number;
  missing_file_count: number;
  unreferenced: UnreferencedFile[];
  unreferenced_bytes: number;
};

export type JobKind = "generate" | "unload";
export type JobState =
  | "queued"
  | "running"
  | "cancelling"
  | "done"
  | "cancelled"
  | "failed"
  | "reused";
export type WorkerState = "stopped" | "loading" | "ready" | "unloaded" | "failed";

export type JobItem = {
  id: string;
  kind: JobKind;
  line_id: string | null;
  reroll: boolean;
  state: JobState;
  /** waiting, loading, generating, storing, unloading or finished. */
  phase: string;
  chunks_done: number;
  chunk_count: number;
  /** True when no GPU time was spent (an existing take was reused). */
  reused: boolean;
  take_id: string | null;
  /** Why a job failed. */
  message: string | null;
};

export type JobStatus = {
  /** Oldest first. */
  jobs: JobItem[];
  /** A job is queued or running. */
  active: boolean;
  worker: WorkerState;
  model_version: string | null;
  worker_message: string | null;
};

/** One line-bank edit; each op carries its `op` tag. A null `value` goes back to the preset. */
export type LineEditOp =
  | { op: "add_line"; text?: string; emotion?: string; position?: number | null; line_id?: string | null }
  | { op: "remove_line"; line_id: string }
  | { op: "set_line_text"; line_id: string; text: string }
  | { op: "set_line_emotion"; line_id: string; emotion: string }
  | { op: "set_line_exaggeration"; line_id: string; value: number | null }
  | { op: "set_line_cfg_weight"; line_id: string; value: number | null }
  | { op: "set_allow_overlap"; line_id: string; value: boolean }
  | { op: "set_active_take"; line_id: string; take_id: string | null }
  | { op: "star_take"; take_id: string; starred?: boolean }
  | { op: "set_take_trim"; take_id: string; start_ms: number | null; end_ms: number | null };

export const EXAGGERATION_MIN = 0;
export const EXAGGERATION_MAX = 2;
export const CFG_WEIGHT_MIN = 0;
export const CFG_WEIGHT_MAX = 1;

export function getVoice(): Promise<VoiceState> {
  return request<VoiceState>("/api/voice");
}

/** `path` is an absolute path of an audio file; the backend validates it and copies it into the project. */
export function setVoiceReference(path: string): Promise<VoiceState> {
  return post<VoiceState>("/api/voice/reference", { path });
}

/** One expression of the avatar art (M5-1): folder `NN_name`, states present as codes. */
export type AvatarExpression = {
  id: string;
  order: number;
  folder: string;
  /** "oicm", "oiom", "cicm", "ciom": eyes open/closed, mouth closed/open. */
  states: string[];
  complete: boolean;
};

/** `GET /api/avatar`, `POST /api/avatar/folder`. */
export type AvatarState = {
  status: "not_configured" | "folder_missing" | "no_art" | "ready";
  /** As stored in the project: relative to it, or an absolute POSIX path. */
  art_folder: string | null;
  resolved_folder: string | null;
  /** Stored as an absolute path: moving the project to another machine breaks it. */
  external: boolean;
  name: string | null;
  expressions: AvatarExpression[];
  default_expression: string | null;
  emotion_map: Record<string, string>;
  warnings: string[];
  problem: string | null;
  can_undo: boolean;
  can_redo: boolean;
  undo_label: string | null;
  redo_label: string | null;
  save_error: string | null;
};

export function getAvatar(): Promise<AvatarState> {
  return request<AvatarState>("/api/avatar");
}

/** Point the project at an art folder on disk (never copied); null clears it. */
export function setAvatarFolder(path: string | null): Promise<AvatarState> {
  return post<AvatarState>("/api/avatar/folder", { path });
}

export function getLines(): Promise<LineBankState> {
  return request<LineBankState>("/api/lines");
}

/** Several ops, or a label, make one undo step; a single op without a label is one step too. */
export function editLines(ops: LineEditOp[], label?: string): Promise<LineBankState> {
  return post<LineBankState>("/api/lines/edit", label === undefined ? { ops } : { label, ops });
}

export function getStorage(): Promise<StorageReport> {
  return request<StorageReport>("/api/storage");
}

export function getTakes(lineId: string): Promise<TakeItem[]> {
  return request<TakeItem[]>(`/api/lines/${encodeURIComponent(lineId)}/takes`);
}

/** State `reused` means an existing take matched the inputs and no GPU time was spent. */
export function generateLine(lineId: string): Promise<JobItem> {
  return post<JobItem>("/api/voice/generate", { line_id: lineId });
}

export function rerollLine(lineId: string): Promise<JobItem> {
  return post<JobItem>("/api/voice/reroll", { line_id: lineId });
}

export function getJobs(): Promise<JobStatus> {
  return request<JobStatus>("/api/voice/jobs");
}

export function cancelJob(jobId: string): Promise<JobStatus> {
  return post<JobStatus>("/api/voice/jobs/cancel", { job_id: jobId });
}

/** Frees the model's VRAM after the jobs before it; the next generation loads the model again. */
export function unloadWorker(): Promise<JobItem> {
  return post<JobItem>("/api/voice/worker/unload");
}

/** Not undoable. Only the user's explicit delete may call this (rule 1). */
export function deleteTake(takeId: string): Promise<TakeDeleteReport> {
  return post<TakeDeleteReport>("/api/takes/delete", { take_id: takeId });
}

/** Deletes the line and all its takes; refused while the line is placed. Not undoable. */
export function deleteLine(lineId: string): Promise<TakeDeleteReport> {
  return post<TakeDeleteReport>("/api/lines/delete", { line_id: lineId });
}

/** URL an <audio> tag can play for a take of the open project (Range supported). */
/** Audio of a take. With a stretch above 1 the backend serves the sped-up copy (made once, then kept). */
export function takeMediaUrl(takeId: string, stretch = 1): string {
  const base = `/media/take/${encodeURIComponent(takeId)}`;
  return stretch === 1 ? base : `${base}?stretch=${stretch}`;
}

/**
 * Processed audio of a take (the voice chain applied, with the placement's stretch): what the
 * editor plays and export writes. `fxVersion` is `TimelineState.fx_version`; it only makes the
 * URL change with the chain (the backend uses the open project's chain, never one from the URL).
 */
export function processedTakeUrl(
  takeId: string,
  stretch: number,
  fxVersion: string,
  trim = "",
): string {
  // `t` (the take's manual trim tag) is ignored by the server, like `v`: it only keeps the
  // browser cache honest after a trim.
  return (
    `/media/take/${encodeURIComponent(takeId)}?processed=1` +
    `&stretch=${stretch}&v=${encodeURIComponent(fxVersion)}` +
    (trim === "" ? "" : `&t=${encodeURIComponent(trim)}`)
  );
}

// ---------------------------------------------------------------------------
// Export (M6): pre-flight, start, progress, cancel. Shapes in docs/API_MODELS.md.
// ---------------------------------------------------------------------------

export type PreflightIssue = {
  severity: "error" | "warning";
  kind: string;
  message: string;
  item_id: string | null;
  t_ms: number | null;
};

export type PreflightReport = {
  ok: boolean;
  error_count: number;
  warning_count: number;
  issues: PreflightIssue[];
};

export type ExportDefaults = {
  folder: string;
  include_overlay: boolean;
  include_raw_links: boolean;
  unload_voice: boolean;
  height: number;
  fps: string;
};

export type ExportFile = { name: string; bytes: number | null; files: number | null };

export type ExportState = "idle" | "running" | "done" | "failed" | "cancelled";

export type ExportStatus = {
  state: ExportState;
  stage: string;
  fraction: number;
  elapsed_s: number;
  eta_s: number | null;
  folder: string | null;
  message: string | null;
  files: ExportFile[];
  video_ms: number | null;
  defaults: ExportDefaults | null;
};

export type ExportRequest = {
  folder: string | null;
  include_overlay: boolean;
  include_raw_links: boolean;
  unload_voice: boolean;
  limit_seconds: number | null;
  accept_warnings: boolean;
};

export function getExportPreflight(): Promise<PreflightReport> {
  return request<PreflightReport>("/api/export/preflight");
}

export function getExportStatus(): Promise<ExportStatus> {
  return request<ExportStatus>("/api/export/status");
}

export function startExport(body: ExportRequest): Promise<ExportStatus> {
  return post<ExportStatus>("/api/export/start", body);
}

export function cancelExport(): Promise<ExportStatus> {
  return post<ExportStatus>("/api/export/cancel");
}

export function openExportFolder(): Promise<{ folder: string }> {
  return post<{ folder: string }>("/api/export/open-folder");
}

// ---- voice model (M7 S3) ----------------------------------------------------

export type ModelState = "missing" | "downloading" | "ready" | "failed";

/** `GET /api/voice/model`: are the voice model's files on disk, and the download. */
export type ModelStatus = {
  state: ModelState;
  repo: string;
  revision: string;
  files_total: number;
  files_present: number;
  bytes_total: number;
  bytes_done: number;
  current_file: string | null;
  cache_dir: string;
  message: string | null;
};

export function getModelStatus(): Promise<ModelStatus> {
  return request<ModelStatus>("/api/voice/model");
}

/** Starts (or retries) the download; does nothing when ready or already running. */
export function startModelDownload(): Promise<ModelStatus> {
  return post<ModelStatus>("/api/voice/model/download");
}
