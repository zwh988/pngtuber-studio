export type ProjectSummary = {
  name: string;
  folder: string;
  schema_version: number;
  source_count: number;
  clip_count: number;
  voice_status: string;
  avatar_status: string;
  save_error: string | null;
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
