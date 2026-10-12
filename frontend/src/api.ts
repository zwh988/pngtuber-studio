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

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
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

export type TimelineState = {
  clips: TimelineClip[];
  duration_ms: number;
  other_track_clips: number;
  orphan_count: number;
  problems: TimelineProblem[];
  can_undo: boolean;
  can_redo: boolean;
  undo_label: string | null;
  redo_label: string | null;
  save_error: string | null;
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
  | { op: "ripple_delete"; start_ms: number; end_ms: number; right_clip_id?: string | null };

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

/** Several edits as ONE undo step; all apply or none do. */
export function editBatch(label: string, ops: EditOp[]): Promise<TimelineState> {
  return post<TimelineState>("/api/timeline/batch", { label, ops });
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
