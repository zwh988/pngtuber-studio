export type ProjectSummary = {
  name: string;
  folder: string;
  schema_version: number;
  source_count: number;
  clip_count: number;
  voice_status: string;
  avatar_status: string;
};

export type RecentItem = {
  name: string;
  folder: string;
  last_opened: string;
  exists: boolean;
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

function post<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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

/** Native folder dialog; null when cancelled or not running in the app window. */
export async function pickFolder(): Promise<string | null> {
  const result = await window.pywebview?.api?.pick_folder?.();
  return result ?? null;
}
