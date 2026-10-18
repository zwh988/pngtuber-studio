import type { JobItem, JobState, JobStatus, LineItem, TakeDeleteReport, VoiceState } from "./api";

/** Jobs in these states are over; nothing more will change them. */
const FINISHED: readonly JobState[] = ["done", "cancelled", "failed", "reused"];

export function isFinished(job: JobItem): boolean {
  return FINISHED.includes(job.state);
}

/** True while the job still holds or waits for the GPU. */
export function isLive(job: JobItem): boolean {
  return !isFinished(job);
}

/** The newest job for a line (jobs come oldest first); undefined when it has none. */
export function latestJobFor(jobs: JobItem[], lineId: string): JobItem | undefined {
  for (let i = jobs.length - 1; i >= 0; i -= 1) {
    if (jobs[i].line_id === lineId) {
      return jobs[i];
    }
  }
  return undefined;
}

/** The queued or running generate job for a line, if any. */
export function liveJobFor(jobs: JobItem[], lineId: string): JobItem | undefined {
  return jobs.find((j) => j.kind === "generate" && j.line_id === lineId && isLive(j));
}

/** One short line for the UI. */
export function jobText(job: JobItem): string {
  switch (job.state) {
    case "queued":
      return "Queued";
    case "cancelling":
      return "Cancelling...";
    case "reused":
      return "Reused an existing take (no GPU time)";
    case "done":
      return job.kind === "unload" ? "Model unloaded" : "Done";
    case "cancelled":
      return "Cancelled";
    case "failed":
      return job.message === null ? "Failed" : `Failed: ${job.message}`;
    case "running":
      break;
  }
  switch (job.phase) {
    case "loading":
      return "Loading the voice model...";
    case "storing":
      return "Saving the take...";
    case "unloading":
      return "Unloading the model...";
    case "generating":
      return job.chunk_count > 1
        ? `Generating, piece ${Math.min(job.chunks_done + 1, job.chunk_count)} of ${job.chunk_count}`
        : "Generating...";
    default:
      return "Working...";
  }
}

/** 12345678 gives "11.8 MB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`;
}

/** Slider value as shown to the user: two decimals. */
export function show2(value: number): string {
  return value.toFixed(2);
}

/** The value a slider should start from: the stored override, else what generation would use. */
export function sliderValue(override: number | null, effective: number | null, fallback: number): number {
  return override ?? effective ?? fallback;
}

/** True when a line's text is blank (generate would be refused). */
export function isBlank(line: LineItem): boolean {
  return line.text.trim() === "";
}

/** One plain sentence for the voice profile status. */
export function voiceStatusText(voice: VoiceState): string {
  switch (voice.status) {
    case "no_profile":
      return "No voice profile yet. Choose a reference clip to create one.";
    case "no_reference":
      return "No reference clip yet. Choose a recording of the voice to clone.";
    case "file_missing":
      return "The reference clip is missing from the project. Choose it again.";
    case "unreadable":
      return "The reference clip could not be read. Choose another file.";
    case "invalid":
      return "The reference clip cannot be used.";
    case "ready":
      return "Ready to generate.";
  }
}

/** Trim a typed or pasted path and drop the quotes Windows adds with "Copy as path". */
export function cleanPathInput(raw: string): string {
  const trimmed = raw.trim();
  if (trimmed.length >= 2 && trimmed.startsWith('"') && trimmed.endsWith('"')) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

/** A fresh 12-character hex id, the same shape the backend uses. */
export function newLineId(): string {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** "no takes", "1 take" or "3 takes". */
export function takeCountText(count: number): string {
  if (count === 0) {
    return "no takes";
  }
  return count === 1 ? "1 take" : `${count} takes`;
}

/** The voice model's state for the status bar. */
export function workerText(status: JobStatus | null): string {
  if (status === null) {
    return "unknown";
  }
  switch (status.worker) {
    case "stopped":
      return "not loaded yet";
    case "loading":
      return "loading...";
    case "ready":
      return status.model_version === null ? "ready" : `ready (${status.model_version})`;
    case "unloaded":
      return "unloaded";
    case "failed":
      return status.worker_message === null ? "failed" : `failed: ${status.worker_message}`;
  }
}

/** Collapse whitespace the way line text is compared against a take's saved text. */
export function normalizeText(text: string): string {
  return text.trim().replace(/\s+/g, " ");
}

function count(n: number, one: string, many: string): string {
  return n === 1 ? `1 ${one}` : `${n} ${many}`;
}

/** One short paragraph telling the user what a delete did. */
export function deleteReportText(report: TakeDeleteReport): string {
  const takes = count(report.removed_take_count, "take", "takes");
  const parts = [
    report.removed_line ? `Deleted the line and ${takes}.` : `Deleted ${takes}.`,
    `Freed ${formatBytes(report.freed_bytes)}.`,
  ];
  if (report.cleared_active_line_ids.length > 0) {
    parts.push(`${count(report.cleared_active_line_ids.length, "line has", "lines have")} no active take now.`);
  }
  if (report.cleared_override_placement_ids.length > 0) {
    parts.push(
      `${count(report.cleared_override_placement_ids.length, "placement lost its", "placements lost their")} take override.`,
    );
  }
  if (report.failed_files.length > 0) {
    parts.push(
      `${count(report.failed_files.length, "file", "files")} could not be deleted (still open?) and will show as unreferenced.`,
    );
  }
  return parts.join(" ");
}
