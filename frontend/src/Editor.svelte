<script module lang="ts">
  /** Pane sizes in px; they survive leaving and re-entering the editor during one app session. */
  const layout = { sideW: 520, topH: 360 };
</script>

<script lang="ts">
  import { onDestroy, tick, untrack } from "svelte";
  import {
    addClip,
    cancelJob,
    editBatch,
    getAvatarTrack,
    getFootage,
    getJobs,
    getStorage,
    getAudioPeaks,
    getTakePeaks,
    getTimeline,
    importAudio,
    importLaneMedia,
    movePlacement,
    placeLine,
    redoEdit,
    removeClip,
    removePlacement,
    reorderClip,
    setClipSpeed,
    setPlacementStretch,
    splitClip,
    trimClip,
    undoEdit,
    type EditOp,
    type EditResult,
    type FootageItem,
    type FrameTrack,
    type JobStatus,
    type PeaksReport,
    type StorageReport,
    type TimelineState,
  } from "./api";
  import { AudioClipPlayback } from "./audioClipPlayback";
  import { audioEndMs, audioPeakBuckets } from "./audioLanes";
  import { FOOTAGE_DRAG_TYPE, avatarSlot, laneEndMs } from "./videoLanes";
  import { clock } from "./format";
  import { lufsText } from "./loudness";
  import AvatarOverlay from "./AvatarOverlay.svelte";
  import LaneHandles, { type LaneDraft } from "./LaneHandles.svelte";
  import LaneLayers from "./LaneLayers.svelte";
  import AvatarPanel from "./AvatarPanel.svelte";
  import LineBank from "./LineBank.svelte";
  import VoiceFx from "./VoiceFx.svelte";
  import { AudioGraph } from "./audioGraph";
  import Player from "./Player.svelte";
  import ShortcutsDialog from "./ShortcutsDialog.svelte";
  import Timeline from "./Timeline.svelte";
  import { STRETCH_MAX, STRETCH_MIN, STRETCH_WARN, stretchText, tightenTarget } from "./stretch";
  import { clipIndexAt, stepFrame } from "./timeline";
  import { formatBytes, isLive, jobText, newLineId, workerText } from "./voice";
  import { VoicePlayback } from "./voicePlayback";
  import {
    ArrowLeft,
    Cpu,
    Snowflake,
    Gauge,
    HardDrive,
    Keyboard,
    Mic,
    Plus,
    Redo2,
    Trash2,
    Undo2,
    Upload,
    X,
  } from "@lucide/svelte";
  import Banner from "./ui/Banner.svelte";
  import Button from "./ui/Button.svelte";
  import IconButton from "./ui/IconButton.svelte";

  let {
    onclose,
    onexport,
    projectName = null,
  }: { onclose: () => void; onexport: () => void; projectName?: string | null } = $props();

  let timeline = $state<TimelineState | null>(null);
  let sources = $state<FootageItem[]>([]);
  let error = $state<string | null>(null);
  let notice = $state<string | null>(null);
  let busy = $state(false);
  /** Playhead on the timeline, in ms. The player moves it while playing. */
  let playheadMs = $state(0);
  /** Selected clip id (click a clip on the timeline). */
  let selectedId = $state<string | null>(null);
  /** Selected placed line (click a block on the voice lane). Never set together with `selectedId`. */
  let selectedPlacementId = $state<string | null>(null);
  /** Waveform peaks by take id, loaded once per take (a take's audio never changes). */
  let peaks = $state<Record<string, PeaksReport>>({});
  const peaksRequested = new Set<string>();
  /** Waveforms of imported audio files by file id (M8-1). */
  let audioPeaks = $state<Record<string, PeaksReport>>({});
  const audioPeaksRequested = new Set<string>();
  let selectedAudioClipId = $state<string | null>(null);
  /** Selected clip on a video lane (M8-2). */
  let selectedLaneClipId = $state<string | null>(null);
  /** The selected lane clip's position and size while it is dragged in the preview. */
  let laneDraft = $state<LaneDraft | null>(null);
  let player = $state<ReturnType<typeof Player> | null>(null);
  /** True while the player plays (bound from `Player`). */
  let playing = $state(false);
  /** The avatar frame track from the Python solver (M5-6); refetched after every change. */
  let avatarTrack = $state<FrameTrack | null>(null);
  let avatarError = $state<string | null>(null);
  /** Bumped after anything that may change the avatar; the track is refetched shortly after. */
  let avatarToken = $state(0);
  /** The shared Web Audio graph: game bus (the video), voice bus, master limiter, loudness meter. */
  const graph = new AudioGraph();
  /** Plays the processed placed takes in time with the video, on the graph's voice bus. */
  const voice = new VoicePlayback((text) => {
    error = text;
  }, graph);
  /** Plays the music and sound effects of the audio lanes on the graph's music bus (M8-1). */
  const sounds = new AudioClipPlayback((text) => {
    error = text;
  }, graph);
  /** Momentary loudness of the master bus, as status bar text. */
  let meterText = $state("silent");
  /** Playback began but the playhead has not moved yet; the voice starts on the first real advance. */
  let voiceArmed = false;
  let voiceArmedMs = 0;
  /** Which tab of the footage / line bank panel is showing. */
  let tab = $state<"footage" | "lines" | "fx" | "avatar">("footage");
  /** Selected avatar key or reaction (click in the timeline's avatar rows). */
  let selectedKeyId = $state<string | null>(null);
  let selectedReactionId = $state<string | null>(null);
  let avatarPanel = $state<ReturnType<typeof AvatarPanel> | null>(null);
  /** Bumped after an undo or redo so the line bank reloads. */
  let lineReload = $state(0);
  let lineBank = $state<ReturnType<typeof LineBank> | null>(null);
  let timelineView = $state<ReturnType<typeof Timeline> | null>(null);
  /** The voice job list; refreshed every 500 ms while a job is queued or running. */
  let jobs = $state<JobStatus | null>(null);
  let pollTimer: number | undefined;
  /** Disk usage of the takes; refreshed when takes are made or deleted. */
  let storage = $state<StorageReport | null>(null);

  const liveJobs = $derived(jobs === null ? [] : jobs.jobs.filter(isLive));
  const lastJob = $derived.by(() => {
    const finished = jobs === null ? [] : jobs.jobs.filter((j) => !isLive(j));
    return finished[finished.length - 1];
  });

  const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 8];

  /** The selected clip; null when nothing is selected or the clip is gone (after an edit or undo). */
  const selectedClip = $derived(timeline?.clips.find((c) => c.id === selectedId) ?? null);
  const selectedPlacement = $derived(
    timeline?.placements.find((p) => p.id === selectedPlacementId) ?? null,
  );

  const selectedAudioClip = $derived(
    timeline?.audio_clips.find((a) => a.id === selectedAudioClipId) ?? null,
  );
  /** Video lanes drawn under and over the avatar (its layer, M8-2), each bottom to top. */
  const avatarLayer = $derived(
    timeline === null ? 0 : avatarSlot(timeline.video_lanes, timeline.avatar_below_lane_id),
  );
  const lanesUnderAvatar = $derived(timeline?.video_lanes.slice(0, avatarLayer) ?? []);
  const lanesOverAvatar = $derived(timeline?.video_lanes.slice(avatarLayer) ?? []);
  const selectedLaneClip = $derived(
    timeline?.lane_clips.find((v) => v.id === selectedLaneClipId) ?? null,
  );

  /** Index of the clip under the playhead (highlighted in the table). */
  const activeIndex = $derived(timeline === null ? -1 : clipIndexAt(timeline.clips, playheadMs));

  function message(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  function fileName(path: string): string {
    return path.split(/[\\/]/).pop() ?? path;
  }

  function sourceName(sourceId: string): string {
    const item = sources.find((s) => s.id === sourceId);
    return item === undefined ? sourceId : fileName(item.path);
  }

  async function load(): Promise<void> {
    try {
      const [state, footage] = await Promise.all([getTimeline(), getFootage()]);
      timeline = state;
      sources = footage.items;
      avatarToken += 1;
    } catch (err) {
      error = message(err);
    }
  }

  /** Reload the Footage tab (a video dropped from Explorer was copied into footage/, M8-2). */
  async function refreshFootage(): Promise<void> {
    try {
      sources = (await getFootage()).items;
    } catch {
      // the list stays as it was
    }
  }

  /** Run an edit that returns the new timeline; the screen always redraws from it. */
  async function edit(action: () => Promise<TimelineState>): Promise<void> {
    busy = true;
    error = null;
    notice = null;
    try {
      timeline = await action();
      avatarToken += 1;
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  /**
   * Audio files dropped from Explorer (M8-1). The app shell sends their full paths and
   * the drop point; a drop that is not on the timeline is ignored (the page refused it).
   */
  async function importDropped(info: { x: number; y: number; paths: string[] }): Promise<void> {
    const target = timelineView?.dropTarget(info.x, info.y) ?? null;
    if (target === null || busy) {
      return;
    }
    // Audio files go to the audio lanes; images and videos (anything else) to the video
    // lanes (M8-2). Each uses the lane under the drop point when it is the right kind.
    const isAudio = (path: string): boolean => /\.(wav|mp3|flac|ogg|m4a)$/i.test(path);
    const sounds = info.paths.filter(isAudio);
    const pictures = info.paths.filter((path) => !isAudio(path));
    busy = true;
    error = null;
    notice = null;
    const placed: string[] = [];
    const errors: string[] = [];
    try {
      if (sounds.length > 0) {
        const result = await importAudio(sounds, target.laneId, target.timelineMs, target.newLane);
        timeline = result.timeline;
        const last = result.imported[result.imported.length - 1];
        if (last !== undefined) {
          selectedAudioClipId = last.clip_id;
          selectedLaneClipId = null;
          selectedId = null;
          selectedPlacementId = null;
        }
        for (const item of result.imported) {
          placed.push(
            `${item.name} on ${item.lane_name} at ${clock(item.timeline_ms)}${item.reused ? " (already in the project)" : ""}`,
          );
        }
        errors.push(...result.errors);
      }
      if (pictures.length > 0) {
        const result = await importLaneMedia(pictures, target.videoLaneId, target.timelineMs, target.videoNewLane);
        timeline = result.timeline;
        const last = result.imported[result.imported.length - 1];
        if (last !== undefined) {
          selectedLaneClipId = last.clip_id;
          selectedAudioClipId = null;
          selectedId = null;
          selectedPlacementId = null;
        }
        for (const item of result.imported) {
          placed.push(
            `${item.name} on ${item.lane_name} at ${clock(item.timeline_ms)}` +
              (item.copied_to_footage ? " (copied into the footage folder)" : ""),
          );
        }
        errors.push(...result.errors);
        if (result.imported.some((item) => item.copied_to_footage)) {
          void refreshFootage();
        }
      }
      if (placed.length > 0) {
        notice = `Placed ${placed.join("; ")}`;
      }
      if (errors.length > 0) {
        error = errors.join(" ");
      }
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  /** A recording dragged from the Footage tab onto a video lane (or the add row: a new lane). */
  async function placeFootage(sourceId: string, timelineMs: number, laneId: string | null, newLane: boolean): Promise<void> {
    const ops: EditOp[] = [];
    let lane = laneId;
    if (newLane || lane === null) {
      lane = newLineId();
      ops.push({ op: "add_video_lane", lane_id: lane });
    }
    const clipId = newLineId();
    ops.push({ op: "add_lane_clip", lane_id: lane, timeline_ms: Math.round(timelineMs), source_id: sourceId, clip_id: clipId });
    await laneEdit("Add recording to a video lane", ops);
    if (error === null) {
      selectedLaneClipId = clipId;
      selectedAudioClipId = null;
      selectedId = null;
      selectedPlacementId = null;
    }
  }

  // Files dragged from Explorer: only the timeline accepts them (it cancels its own
  // dragover); everywhere else the drop is refused, so WebView2 never opens the file.
  $effect(() => {
    const hook = window as unknown as Record<string, unknown>;
    hook.__pngtuberFilesDropped = (info: { x: number; y: number; paths: string[] }) => {
      void importDropped(info);
    };
    function refuse(e: DragEvent): void {
      if (e.dataTransfer !== null && e.dataTransfer.types.includes("Files") && !e.defaultPrevented) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "none";
      }
    }
    window.addEventListener("dragover", refuse);
    window.addEventListener("drop", refuse);
    return () => {
      delete hook.__pngtuberFilesDropped;
      window.removeEventListener("dragover", refuse);
      window.removeEventListener("drop", refuse);
    };
  });

  async function history(
    action: () => Promise<EditResult>,
    verb: string,
    nothing: string,
  ): Promise<void> {
    busy = true;
    error = null;
    notice = null;
    try {
      const result = await action();
      timeline = result.timeline;
      lineReload += 1;
      avatarToken += 1;
      notice = result.label === null ? nothing : `${verb}: ${result.label}`;
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  function speedChoices(current: number): number[] {
    return SPEEDS.includes(current) ? SPEEDS : [...SPEEDS, current].sort((a, b) => a - b);
  }

  /** A trim drag ended: one edit, one undo step. */
  async function trimByDrag(clipId: string, edge: "in" | "out", sourceMs: number): Promise<void> {
    player?.pause();
    await edit(() => trimClip(clipId, edge, sourceMs));
  }

  /** A reorder drag ended: one edit, one undo step. */
  async function reorderByDrag(clipId: string, newPosition: number): Promise<void> {
    player?.pause();
    await edit(() => reorderClip(clipId, newPosition));
  }

  /**
   * A line edit went onto the shared undo stack. Refresh only the undo and redo fields,
   * so the player and the timeline are not redrawn.
   */
  async function syncHistory(): Promise<void> {
    try {
      const state = await getTimeline();
      if (timeline !== null) {
        timeline.can_undo = state.can_undo;
        timeline.can_redo = state.can_redo;
        timeline.undo_label = state.undo_label;
        timeline.redo_label = state.redo_label;
        timeline.save_error = state.save_error;
        // Line edits and finished jobs change what a placement plays (active take, length,
        // allow overlap), so refresh the placements too.
        timeline.placements = state.placements;
        // Voice FX edits change the chain version and the game level: refresh both so the voice
        // drops its decoded audio and the game bus follows (undo and redo replace the whole
        // timeline, which carries them too).
        timeline.fx_version = state.fx_version;
        timeline.game_audio_db = state.game_audio_db;
        timeline.keyframes = state.keyframes;
        timeline.reactions = state.reactions;
        timeline.avatar = state.avatar;
      }
      avatarToken += 1;
    } catch (err) {
      error = message(err);
    }
  }

  // Refetch the avatar track a moment after the last change (a burst of edits fetches once).
  let avatarTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    void avatarToken;
    clearTimeout(avatarTimer);
    avatarTimer = setTimeout(() => {
      void (async () => {
        try {
          const next = await getAvatarTrack();
          if (avatarTrack === null || avatarTrack.version !== next.version) {
            avatarTrack = next;
          }
          avatarError = null;
        } catch (err) {
          avatarError = `The avatar could not be computed: ${message(err)}`;
        }
      })();
    }, 250);
    return () => clearTimeout(avatarTimer);
  });

  /** An avatar drag or resize ended: one labelled batch, one undo step. */
  async function commitAvatar(label: string, ops: EditOp[]): Promise<boolean> {
    error = null;
    try {
      timeline = await editBatch(label, ops);
      avatarToken += 1;
      notice = label;
      return true;
    } catch (err) {
      error = message(err);
      return false;
    }
  }

  async function refreshStorage(): Promise<void> {
    try {
      storage = await getStorage();
    } catch (err) {
      error = message(err);
    }
  }

  /** Takes were deleted: reload the lines, the undo state and the disk usage. */
  function takesDeleted(): void {
    lineReload += 1;
    void syncHistory();
    void refreshStorage();
  }

  /** Fetch the job list; keeps polling while a job is active and reloads the lines when one ends. */
  async function refreshJobs(): Promise<void> {
    window.clearTimeout(pollTimer);
    const before = jobs === null ? [] : jobs.jobs.filter(isLive).map((j) => j.id);
    try {
      const next = await getJobs();
      jobs = next;
      const ended = before.some((id) => {
        const job = next.jobs.find((j) => j.id === id);
        return job === undefined || !isLive(job);
      });
      if (ended) {
        lineReload += 1;
        void syncHistory();
        void refreshStorage();
      }
      if (next.active) {
        pollTimer = window.setTimeout(() => void refreshJobs(), 500);
      }
    } catch (err) {
      error = message(err);
      if (jobs !== null && jobs.active) {
        pollTimer = window.setTimeout(() => void refreshJobs(), 2000);
      }
    }
  }

  /** A job was started or cancelled: refresh the list, then the lines (a reused take finishes at once). */
  async function jobsChanged(): Promise<void> {
    await refreshJobs();
    lineReload += 1;
    void syncHistory();
    void refreshStorage();
  }

  async function cancelFirstJob(): Promise<void> {
    const job = liveJobs[0];
    if (job === undefined) {
      return;
    }
    try {
      jobs = await cancelJob(job.id);
    } catch (err) {
      error = message(err);
    }
    await jobsChanged();
  }

  onDestroy(() => {
    window.clearTimeout(pollTimer);
    voice.dispose();
    sounds.dispose();
    graph.dispose();
  });

  /** Keep the voice engine's placement list current (it loads new takes and re-plans while playing). */
  $effect(() => {
    const list = timeline?.placements ?? [];
    untrack(() => voice.setPlacements(list));
  });

  /** Keep the audio-clip player's clips and lanes current (edits, mute, solo, undo). */
  $effect(() => {
    const clips = timeline?.audio_clips ?? [];
    const lanes = timeline?.audio_lanes ?? [];
    untrack(() => sounds.setClips(clips, lanes));
  });

  /** A voice chain change (or undo of one) drops the decoded voice audio and loads the new files. */
  $effect(() => {
    const version = timeline?.fx_version ?? "";
    untrack(() => voice.setFxVersion(version));
  });

  /** The footage level of the mix. */
  $effect(() => {
    const db = timeline?.game_audio_db ?? 0;
    untrack(() => graph.setGameDb(db));
  });

  /** Read the loudness meter ten times a second. */
  $effect(() => {
    const timer = window.setInterval(() => {
      const lufs = graph.momentaryLufs();
      meterText = lufs === null ? "silent" : lufsText(lufs);
    }, 100);
    return () => window.clearInterval(timer);
  });

  /**
   * Voice and the audio clips follow the player. When playback begins the voice waits for the playhead to actually
   * move (the video may still be seeking), then starts there; after that every playhead change
   * is checked for drift. Pause, an edit or the end of the timeline sets `playing` to false.
   */
  $effect(() => {
    const isPlaying = playing;
    const ms = playheadMs;
    untrack(() => {
      if (!isPlaying) {
        voiceArmed = false;
        voice.stop();
        sounds.stop();
      } else if (voice.running) {
        voice.sync(ms);
        sounds.sync(ms);
      } else if (!voiceArmed) {
        voiceArmed = true;
        voiceArmedMs = ms;
      } else if (ms !== voiceArmedMs) {
        voice.start(ms);
        sounds.start(ms);
      }
    });
  });

  /** Hotkey N: show the line bank and add a line. */
  function newLine(): void {
    tab = "lines";
    void tick().then(() => lineBank?.addLine());
  }

  function undo(): void {
    void history(undoEdit, "Undid", "Nothing to undo");
  }

  function redo(): void {
    void history(redoEdit, "Redid", "Nothing to redo");
  }

  function stepBy(direction: 1 | -1): void {
    if (timeline === null) {
      return;
    }
    player?.pause();
    playheadMs = stepFrame(timeline.clips, playheadMs, direction);
  }

  /** F: hold the frame at the playhead of the selected lane recording for 2 s, then select the hold. */
  function freezeAtPlayhead(): void {
    const shot = selectedLaneClip;
    if (shot === null) {
      freezeFootageAtPlayhead();
      return;
    }
    if (shot.source_id === null || shot.freeze_ms !== null) {
      notice = "Only a recording can be frozen: a still or a freeze frame already holds one picture.";
      return;
    }
    const holdId = newLineId();
    const atStart = playheadMs - shot.timeline_ms < 40;
    void laneEdit("Freeze frame", [
      { op: "freeze_lane_clip", clip_id: shot.id, timeline_ms: playheadMs, freeze_clip_id: holdId },
    ]).then(() => {
      // At the clip's very start the hold keeps the clip's id.
      selectedLaneClipId = atStart ? shot.id : holdId;
    });
  }

  /** F with no lane clip selected: hold the main footage's frame at the playhead for 2 s. */
  function freezeFootageAtPlayhead(): void {
    if (timeline === null) return;
    const at = playheadMs;
    const clip = timeline.clips[clipIndexAt(timeline.clips, at)];
    if (clip === undefined || at >= timeline.duration_ms) {
      notice = "Put the playhead on the footage to freeze a frame.";
      return;
    }
    if (clip.freeze_ms !== null) {
      notice = "That is already a freeze frame: trim it to make it longer or shorter.";
      return;
    }
    const holdId = newLineId();
    player?.pause();
    void edit(() =>
      editBatch("Freeze frame", [{ op: "freeze_clip", timeline_ms: at, freeze_clip_id: holdId }]),
    ).then(() => {
      selectedId = holdId;
    });
  }

  /** S: split the selected audio or video-lane clip at the playhead, else the main footage. */
  function splitAtPlayhead(): void {
    const at = playheadMs;
    player?.pause();
    if (selectedAudioClip !== null) {
      const op: EditOp = { op: "split_audio_clip", clip_id: selectedAudioClip.id, timeline_ms: at };
      void audioEdit("Split audio clip", [op]);
    } else if (selectedLaneClip !== null) {
      const op: EditOp = { op: "split_lane_clip", clip_id: selectedLaneClip.id, timeline_ms: at };
      void laneEdit("Split clip on a video lane", [op]);
    } else {
      void edit(() => splitClip(at));
    }
  }

  /** Fetch the waveform of every placed take that has none yet. A failure leaves a plain block. */
  $effect(() => {
    for (const placement of timeline?.placements ?? []) {
      const takeId = placement.take_id;
      if (takeId === null || peaksRequested.has(takeId)) {
        continue;
      }
      peaksRequested.add(takeId);
      getTakePeaks(takeId)
        .then((report) => {
          peaks[takeId] = report;
        })
        .catch(() => undefined);
    }
  });

  /** Fetch the waveform of every imported audio file on the timeline that has none yet. */
  $effect(() => {
    for (const clip of timeline?.audio_clips ?? []) {
      const fileId = clip.file_id;
      if (audioPeaksRequested.has(fileId)) {
        continue;
      }
      audioPeaksRequested.add(fileId);
      getAudioPeaks(fileId, audioPeakBuckets(clip.file_duration_ms))
        .then((report) => {
          audioPeaks[fileId] = report;
        })
        .catch(() => undefined);
    }
  });

  /** One video lane or lane clip edit, as one undo step (M8-2). */
  async function laneEdit(label: string, ops: EditOp[]): Promise<void> {
    player?.pause();
    await edit(() => editBatch(label, ops));
  }

  /** One audio lane or clip edit, as one undo step (M8-1). */
  async function audioEdit(label: string, ops: EditOp[]): Promise<void> {
    player?.pause();
    await edit(() => editBatch(label, ops));
  }

  /** Place a line so that it starts at a timeline time, then select the new block. */
  async function placeAt(lineId: string, timelineMs: number): Promise<void> {
    const placementId = newLineId();
    player?.pause();
    await edit(() => placeLine(lineId, Math.round(timelineMs), placementId));
    if (error === null) {
      selectedPlacementId = placementId;
      selectedId = null;
      lineReload += 1;
    }
  }

  /** Hotkey M: put the line selected in the bank at the playhead. */
  function placeSelected(): void {
    const lineId = lineBank?.selectedLineId() ?? null;
    if (lineId === null) {
      error = "Select a line in the line bank first.";
      return;
    }
    void placeAt(lineId, playheadMs);
  }

  /** A voice block was dragged to a new start time (one undo step). */
  async function movePlacementByDrag(placementId: string, timelineMs: number): Promise<void> {
    player?.pause();
    await edit(() => movePlacement(placementId, timelineMs));
  }

  /** Nudge earlier: move a block up by the overflow, or by the slack when that is less. */
  function nudgeEarlier(placementId: string): void {
    const placed = timeline?.placements.find((p) => p.id === placementId);
    if (placed === undefined || placed.start_ms === null) {
      return;
    }
    const amount = Math.min(placed.overflow_ms, placed.slack_ms);
    if (amount <= 0) {
      return;
    }
    player?.pause();
    void edit(() => movePlacement(placementId, (placed.start_ms ?? 0) - amount));
  }

  /** Tighten and the speed slider: set how much faster a placed line plays (one undo step). */
  function setStretch(placementId: string, stretch: number): void {
    const placed = timeline?.placements.find((p) => p.id === placementId);
    if (placed === undefined || Math.abs(placed.stretch - stretch) < 0.0005) {
      return;
    }
    player?.pause();
    void edit(() => setPlacementStretch(placementId, stretch));
  }

  function removePlaced(placementId: string): void {
    player?.pause();
    void edit(() => removePlacement(placementId)).then(() => {
      if (error === null) {
        selectedPlacementId = null;
        lineReload += 1;
      }
    });
  }

  /** Delete: remove the selected placed line, or else the selected clip. */
  function removeSelected(): void {
    const shot = selectedLaneClip;
    if (shot !== null) {
      void laneEdit("Remove clip from a video lane", [{ op: "remove_lane_clip", clip_id: shot.id }]).then(() => {
        if (error === null) {
          selectedLaneClipId = null;
        }
      });
      return;
    }
    const sound = selectedAudioClip;
    if (sound !== null) {
      void audioEdit("Remove audio clip", [{ op: "remove_audio_clip", clip_id: sound.id }]).then(() => {
        if (error === null) {
          selectedAudioClipId = null;
        }
      });
      return;
    }
    if (selectedKeyId !== null || selectedReactionId !== null) {
      void avatarPanel?.deleteSelected();
      return;
    }
    const placed = selectedPlacement;
    if (placed !== null) {
      removePlaced(placed.id);
      return;
    }
    const clip = selectedClip;
    if (clip === null) {
      error = "Select a clip first (click it on the timeline).";
      return;
    }
    player?.pause();
    void edit(() => removeClip(clip.id));
  }

  /** `[` and `]`: cut the selected clip's in or out edge at the playhead (in SOURCE time). */
  function setEdge(edge: "in" | "out"): void {
    const clip = selectedClip;
    if (clip === null) {
      error = "Select a clip first (click it on the timeline).";
      return;
    }
    if (playheadMs < clip.start_ms || playheadMs > clip.end_ms) {
      error = "Move the playhead inside the selected clip first.";
      return;
    }
    const sourceMs = Math.round(clip.in_ms + (playheadMs - clip.start_ms) * clip.speed);
    player?.pause();
    void edit(() => trimClip(clip.id, edge, sourceMs)).then(() => {
      // Cutting the in edge at the playhead makes that frame the clip's first frame.
      if (edge === "in" && error === null) {
        playheadMs = clip.start_ms;
      }
    });
  }

  /** The keyboard shortcuts dialog ("?" or the header button, M7 S5). */
  let showShortcuts = $state(false);

  function isTyping(target: EventTarget | null): boolean {
    return (
      target instanceof Element &&
      target.closest("input:not([type=range]), textarea, select, [contenteditable]") !== null
    );
  }

  function onKeyDown(e: KeyboardEvent): void {
    if (timeline === null || isTyping(e.target)) {
      return;
    }
    if (e.ctrlKey || e.metaKey) {
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) {
        e.preventDefault();
        if (!busy) {
          undo();
        }
      } else if (key === "y" || (key === "z" && e.shiftKey)) {
        e.preventDefault();
        if (!busy) {
          redo();
        }
      }
      return;
    }
    if (e.altKey) {
      return;
    }
    const canEdit = !busy && !e.repeat;
    switch (e.key) {
      case "?":
        e.preventDefault();
        showShortcuts = !showShortcuts;
        break;
      case " ":
        e.preventDefault();
        if (!e.repeat) {
          player?.toggle();
        }
        break;
      case ",":
        e.preventDefault();
        stepBy(-1);
        break;
      case "<":
      case ">":
        e.preventDefault();
        player?.pause();
        timelineView?.gotoKey(e.key === ">" ? 1 : -1);
        break;
      case ".":
        e.preventDefault();
        stepBy(1);
        break;
      case "g":
      case "G":
        e.preventDefault();
        if (canEdit) {
          tab = "lines";
          void lineBank?.generateSelected(e.shiftKey);
        }
        break;
      case "n":
      case "N":
        e.preventDefault();
        if (canEdit) {
          newLine();
        }
        break;
      case "m":
      case "M":
        e.preventDefault();
        if (canEdit) {
          placeSelected();
        }
        break;
      case "s":
      case "S":
        e.preventDefault();
        if (canEdit) {
          splitAtPlayhead();
        }
        break;
      case "f":
      case "F":
        e.preventDefault();
        if (canEdit && !e.ctrlKey) {
          freezeAtPlayhead();
        }
        break;
      case "e":
      case "E":
        e.preventDefault();
        if (canEdit) {
          player?.pause();
          void avatarPanel?.addExpressionKey();
        }
        break;
      case "r":
      case "R":
        e.preventDefault();
        if (canEdit && !e.ctrlKey) {
          void avatarPanel?.dropReaction();
        }
        break;
      case "Delete":
        e.preventDefault();
        if (canEdit) {
          removeSelected();
        }
        break;
      case "[":
        e.preventDefault();
        if (canEdit) {
          setEdge("in");
        }
        break;
      case "]":
        e.preventDefault();
        if (canEdit) {
          setEdge("out");
        }
        break;
      default:
        break;
    }
  }

  /** Space on a focused button would click it on key release; the hotkey already handled it. */
  function onKeyUp(e: KeyboardEvent): void {
    if (e.key === " " && !isTyping(e.target)) {
      e.preventDefault();
    }
  }

  const SIDE_MIN = 320;
  const TOP_MIN = 180;
  let sideW = $state(layout.sideW);
  let topH = $state(layout.topH);
  let divider: { axis: "v" | "h"; startPos: number; startSize: number } | null = null;

  function clampSide(px: number): number {
    return Math.min(Math.max(px, SIDE_MIN), Math.max(SIDE_MIN, window.innerWidth - 360));
  }

  function clampTop(px: number): number {
    return Math.min(Math.max(px, TOP_MIN), Math.max(TOP_MIN, window.innerHeight - 320));
  }

  function startDivider(e: PointerEvent, axis: "v" | "h"): void {
    e.preventDefault();
    if (e.currentTarget instanceof HTMLElement) {
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    divider = {
      axis,
      startPos: axis === "v" ? e.clientX : e.clientY,
      startSize: axis === "v" ? sideW : topH,
    };
  }

  function moveDivider(e: PointerEvent): void {
    if (divider === null) {
      return;
    }
    if (divider.axis === "v") {
      // The side panel is on the right: dragging left makes it wider.
      sideW = clampSide(divider.startSize - (e.clientX - divider.startPos));
    } else {
      topH = clampTop(divider.startSize + (e.clientY - divider.startPos));
    }
  }

  function endDivider(): void {
    if (divider !== null) {
      layout.sideW = sideW;
      layout.topH = topH;
      divider = null;
    }
  }

  /** Arrow keys resize a focused divider (Shift for bigger steps). */
  function nudgeDivider(e: KeyboardEvent, axis: "v" | "h"): void {
    const step = e.shiftKey ? 80 : 24;
    if (axis === "v" && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
      sideW = clampSide(sideW + (e.key === "ArrowLeft" ? step : -step));
    } else if (axis === "h" && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      topH = clampTop(topH + (e.key === "ArrowDown" ? step : -step));
    } else {
      return;
    }
    e.preventDefault();
    layout.sideW = sideW;
    layout.topH = topH;
  }

  void load();
  void refreshJobs();
  void refreshStorage();
</script>

<svelte:window onkeydown={onKeyDown} onkeyup={onKeyUp} />

<div class="editor">
  <header>
    <IconButton icon={ArrowLeft} label="Back to project" onclick={onclose} />
    <h2>{projectName ?? "Editor"}</h2>
    {#if projectName !== null}<span class="crumb">/ Editor</span>{/if}
    <span class="sep" aria-hidden="true"></span>
    <IconButton
      icon={Undo2}
      label={timeline?.undo_label ? `Undo: ${timeline.undo_label} (Ctrl+Z)` : "Undo (Ctrl+Z)"}
      disabled={busy || timeline === null || !timeline.can_undo}
      onclick={undo}
    />
    <IconButton
      icon={Redo2}
      label={timeline?.redo_label ? `Redo: ${timeline.redo_label} (Ctrl+Y)` : "Redo (Ctrl+Y)"}
      disabled={busy || timeline === null || !timeline.can_redo}
      onclick={redo}
    />
    <div class="spacer"></div>
    <IconButton icon={Keyboard} label="Keyboard shortcuts (?)" onclick={() => (showShortcuts = true)} />
    <Button variant="primary" icon={Upload} disabled={busy || timeline === null} onclick={onexport}>
      Export
    </Button>
  </header>

  {#if error !== null}
    <div class="msg"><Banner kind="error">{error}</Banner></div>
  {/if}
  {#if notice !== null}
    <div class="msg"><Banner kind="info">{notice}</Banner></div>
  {/if}
  {#if timeline !== null && timeline.save_error !== null}
    <div class="msg">
      <Banner kind="error">Could not save the project: {timeline.save_error}</Banner>
    </div>
  {/if}

  {#if timeline === null}
    <p class="msg">Loading...</p>
  {:else}
    <div class="workspace">
      <div class="top" style:height="{topH}px" style:--top-h="{topH}px">
        <div class="preview">
          {#if timeline.clips.length > 0}
            <Player
              bind:this={player}
              clips={timeline.clips}
              durationMs={timeline.duration_ms}
              endMs={Math.max(audioEndMs(timeline.audio_clips), laneEndMs(timeline.lane_clips))}
              bind:playheadMs
              bind:playing
              {graph}
              onstep={stepBy}
            >
              {#snippet overlay()}
                <LaneLayers
                  clips={timeline?.lane_clips ?? []}
                  lanes={lanesUnderAvatar}
                  {playheadMs}
                  {playing}
                  {graph}
                  draft={laneDraft}
                />
                <AvatarOverlay
                  track={avatarTrack}
                  {playheadMs}
                  editable={!playing && !busy}
                  oncommit={commitAvatar}
                />
                <LaneLayers
                  clips={timeline?.lane_clips ?? []}
                  lanes={lanesOverAvatar}
                  {playheadMs}
                  {playing}
                  {graph}
                  draft={laneDraft}
                />
                <LaneHandles
                  clips={timeline?.lane_clips ?? []}
                  lanes={timeline?.video_lanes ?? []}
                  selectedId={selectedLaneClipId}
                  {playheadMs}
                  editable={!playing && !busy}
                  bind:draft={laneDraft}
                  oncommit={(clipId, change) =>
                    laneEdit("Move or resize a clip on a video lane", [{ op: "set_lane_clip", clip_id: clipId, ...change }])}
                />
              {/snippet}
            </Player>
            {#if avatarError !== null}<p class="error">{avatarError}</p>{/if}
          {:else}
            <div class="empty-stage">
              <p>The timeline is empty.</p>
              <p class="hint">Add a recording from the Footage tab.</p>
            </div>
          {/if}
        </div>
        <!-- A focusable separator is a widget in ARIA (it has a value and takes arrow keys), but
             Svelte's a11y rules list "separator" as non-interactive, so these two warnings are expected. -->
        <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
        <div
          class="divider v"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the side panel"
          aria-valuenow={sideW}
          aria-valuemin={SIDE_MIN}
          tabindex="0"
          onpointerdown={(e) => startDivider(e, "v")}
          onpointermove={moveDivider}
          onpointerup={endDivider}
          onpointercancel={endDivider}
          onkeydown={(e) => nudgeDivider(e, "v")}
        ></div>
        <div class="side" style:width="{sideW}px">
          <div class="tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "footage"}
              class:on={tab === "footage"}
              onclick={() => (tab = "footage")}
            >
              Footage
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "lines"}
              class:on={tab === "lines"}
              onclick={() => {
                tab = "lines";
                void refreshStorage();
              }}
            >
              Line bank
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "fx"}
              class:on={tab === "fx"}
              onclick={() => (tab = "fx")}
            >
              Voice FX
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "avatar"}
              class:on={tab === "avatar"}
              onclick={() => (tab = "avatar")}
            >
              Avatar
            </button>
          </div>
          <div class="pane">
            <div hidden={tab !== "footage"}>
              {#if sources.length === 0}
                <p class="empty">No footage in this project yet. Go back to the project screen and Rescan.</p>
              {:else}
                <ul class="sources">
                  {#each sources as item (item.id)}
                    <li
                      class:missing={!item.exists}
                      draggable={item.exists}
                      title={item.exists ? "Drag onto a video lane to show it over the main footage" : undefined}
                      ondragstart={(e) => {
                        if (e.dataTransfer !== null) {
                          e.dataTransfer.setData(FOOTAGE_DRAG_TYPE, item.id);
                          e.dataTransfer.effectAllowed = "copy";
                        }
                      }}
                    >
                      <span class="name">{fileName(item.path)}</span>
                      <span class="meta num">{clock(item.duration_ms)}</span>
                      <Button
                        size="sm"
                        icon={Plus}
                        title={item.exists ? "Add this recording to the end of the timeline" : "The file is missing"}
                        disabled={busy || !item.exists}
                        onclick={() => edit(() => addClip(item.id))}
                      >
                        Add
                      </Button>
                    </li>
                  {/each}
                </ul>
              {/if}
            </div>
            <div hidden={tab !== "lines"}>
              <LineBank
                bind:this={lineBank}
                reloadToken={lineReload}
                onedited={() => void syncHistory()}
                {jobs}
                onjobchange={() => void jobsChanged()}
                fxVersion={timeline?.fx_version ?? ""}
                {storage}
                ondeleted={takesDeleted}
                onplace={placeSelected}
                placeDisabled={busy}
              />
            </div>
            <div hidden={tab !== "avatar"}>
              {#if timeline !== null}
                <AvatarPanel
                  bind:this={avatarPanel}
                  avatar={timeline.avatar}
                  keyframes={timeline.keyframes}
                  reactions={timeline.reactions}
                  {playheadMs}
                  {busy}
                  bind:selectedKeyId
                  bind:selectedReactionId
                  oncommit={commitAvatar}
                />
              {/if}
            </div>
            <div hidden={tab !== "fx"}>
              <VoiceFx
                active={tab === "fx"}
                reloadToken={lineReload}
                placements={timeline?.placements ?? []}
                {selectedPlacementId}
                onedited={() => void syncHistory()}
              />
            </div>
          </div>
        </div>
      </div>

      <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
      <div
        class="divider h"
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize the preview and the timeline"
        aria-valuenow={topH}
        aria-valuemin={TOP_MIN}
        tabindex="0"
        onpointerdown={(e) => startDivider(e, "h")}
        onpointermove={moveDivider}
        onpointerup={endDivider}
        onpointercancel={endDivider}
        onkeydown={(e) => nudgeDivider(e, "h")}
      ></div>

      <div class="bottom">
        {#if timeline.clips.length > 0}
          <Timeline
            bind:this={timelineView}
            clips={timeline.clips}
            durationMs={timeline.duration_ms}
            bind:playheadMs
            bind:selectedId
            bind:selectedPlacementId
            placements={timeline.placements}
            {peaks}
            locked={busy}
            label={(clip) => sourceName(clip.source_id)}
            ontrim={trimByDrag}
            onreorder={reorderByDrag}
            onplace={placeAt}
            onmoveplacement={movePlacementByDrag}
            keyframes={timeline.keyframes}
            reactions={timeline.reactions}
            bind:selectedKeyId
            bind:selectedReactionId
            onmovekey={async (id, ms) => {
              await commitAvatar("Move key", [{ op: "move_keyframe", keyframe_id: id, timeline_ms: ms }]);
            }}
            onmovereaction={async (id, ms) => {
              await commitAvatar("Move reaction", [{ op: "move_reaction", reaction_id: id, timeline_ms: ms }]);
            }}
            audioLanes={timeline.audio_lanes}
            audioClips={timeline.audio_clips}
            {audioPeaks}
            bind:selectedAudioClipId
            videoLanes={timeline.video_lanes}
            laneClips={timeline.lane_clips}
            bind:selectedLaneClipId
            onmovelane={(id, ms, laneId) =>
              laneEdit("Move clip on a video lane", [{ op: "move_lane_clip", clip_id: id, timeline_ms: ms, lane_id: laneId }])}
            ontrimlane={(id, edge, ms) =>
              laneEdit("Trim clip on a video lane", [{ op: "trim_lane_clip", clip_id: id, edge, timeline_ms: ms }])}
            onvideolane={(laneId, change) =>
              laneEdit(change.name !== undefined ? "Rename video lane" : "Change video lane", [
                { op: "set_video_lane", lane_id: laneId, ...change },
              ])}
            onaddvideolane={() => laneEdit("Add video lane", [{ op: "add_video_lane" }])}
            onremovevideolane={(laneId) => laneEdit("Remove video lane", [{ op: "remove_video_lane", lane_id: laneId }])}
            onplacefootage={placeFootage}
            avatarBelowLaneId={timeline.avatar_below_lane_id}
            onavatarlayer={(laneId) => laneEdit("Move the avatar between the video lanes", [{ op: "set_avatar_layer", lane_id: laneId }])}
            onmoveaudio={(id, ms, laneId) =>
              audioEdit("Move audio clip", [{ op: "move_audio_clip", clip_id: id, timeline_ms: ms, lane_id: laneId }])}
            ontrimaudio={(id, edge, ms) =>
              audioEdit("Trim audio clip", [{ op: "trim_audio_clip", clip_id: id, edge, timeline_ms: ms }])}
            onaudiolane={(laneId, change) =>
              audioEdit(change.name !== undefined ? "Rename audio lane" : "Change audio lane", [
                { op: "set_audio_lane", lane_id: laneId, ...change },
              ])}
            onaddaudiolane={() => audioEdit("Add audio lane", [{ op: "add_audio_lane" }])}
            onremoveaudiolane={(laneId) => audioEdit("Remove audio lane", [{ op: "remove_audio_lane", lane_id: laneId }])}
          />
          <div class="clipbar">
            {#if selectedClip !== null}
              {@const clip = selectedClip}
              <strong>{clip.freeze_ms !== null ? "Freeze frame" : "Clip"} {clip.position + 1}: {sourceName(clip.source_id)}</strong>
              {#if clip.freeze_ms !== null}
                <span class="hint num">holds the frame at {clock(clip.freeze_ms)}; trim it to change its length</span>
              {:else}
              <Button
                size="sm"
                icon={Snowflake}
                disabled={busy || playheadMs < clip.start_ms || playheadMs >= clip.end_ms}
                title="Hold the frame at the playhead for 2 s; everything after it moves later (F)"
                onclick={freezeFootageAtPlayhead}
              >
                Freeze frame
              </Button>
              <label class="inline">
                Speed
                <select
                  value={String(clip.speed)}
                  disabled={busy}
                  onchange={(e) => {
                    const speed = Number(e.currentTarget.value);
                    e.currentTarget.blur();
                    void edit(() => setClipSpeed(clip.id, speed));
                  }}
                >
                  {#each speedChoices(clip.speed) as speed}
                    <option value={String(speed)}>{speed}x</option>
                  {/each}
                </select>
              </label>
              {/if}
              <Button size="sm" variant="danger" icon={Trash2} disabled={busy} onclick={removeSelected}>
                Remove clip
              </Button>
            {:else if selectedPlacement === null && selectedAudioClip === null && selectedLaneClip === null}
              <span class="hint">No clip selected. Click a clip on the timeline.</span>
            {/if}
            {#if selectedLaneClip !== null}
              {@const shot = selectedLaneClip}
              {@const pct = (value: number) => Math.round(value * 1000) / 10}
              {@const setShot = (label: string, change: Partial<Record<"x" | "y" | "scale" | "opacity" | "gain_db", number>> & { mute?: boolean }) =>
                void laneEdit(label, [{ op: "set_lane_clip", clip_id: shot.id, ...change }])}
              <strong>{shot.image_id !== null ? "Still" : shot.freeze_ms !== null ? "Freeze frame" : "Clip"}: {shot.name}</strong>
              <span class="hint num">{clock(shot.timeline_ms)} to {clock(shot.end_ms)}</span>
              {#if shot.missing}
                <span class="error">The file is missing.</span>
              {/if}
              {#each [["X", "x", -100, 200], ["Y", "y", -100, 200], ["Size", "scale", 5, 400], ["Opacity", "opacity", 0, 100]] as const as [title, key, lo, hi] (key)}
                <label class="inline">
                  {title}
                  <input
                    class="num small"
                    type="number"
                    min={lo}
                    max={hi}
                    step="1"
                    value={pct(shot[key])}
                    disabled={busy}
                    onkeydown={(e) => e.stopPropagation()}
                    onchange={(e) => {
                      const raw = e.currentTarget.valueAsNumber;
                      if (!Number.isFinite(raw)) {
                        e.currentTarget.value = String(pct(shot[key]));
                        return;
                      }
                      const value = Math.min(hi, Math.max(lo, raw)) / 100;
                      if (Math.abs(value - shot[key]) > 0.0005) {
                        setShot(key === "opacity" ? "Change clip opacity" : "Place clip on a video lane", { [key]: value });
                      }
                    }}
                  />
                  %
                </label>
              {/each}
              <Button
                size="sm"
                disabled={busy || (shot.x === 0.5 && shot.y === 0.5 && shot.scale === 1)}
                title="Back to full frame, centred"
                onclick={() => setShot("Place clip on a video lane", { x: 0.5, y: 0.5, scale: 1 })}
              >
                Full frame
              </Button>
              {#if shot.source_id !== null && shot.freeze_ms === null}
                <Button
                  size="sm"
                  icon={Snowflake}
                  disabled={busy || playheadMs < shot.timeline_ms || playheadMs >= shot.end_ms}
                  title="Hold the frame at the playhead for 2 s; the rest of the clip and later clips on this lane move later (F)"
                  onclick={freezeAtPlayhead}
                >
                  Freeze frame
                </Button>
                <label class="inline">
                  Sound
                  <input
                    class="num small"
                    type="number"
                    min="-60"
                    max="12"
                    step="0.5"
                    value={shot.gain_db}
                    disabled={busy || shot.mute}
                    onkeydown={(e) => e.stopPropagation()}
                    onchange={(e) => {
                      const value = Math.min(12, Math.max(-60, e.currentTarget.valueAsNumber));
                      if (Number.isFinite(value) && value !== shot.gain_db) {
                        setShot("Change clip sound level", { gain_db: value });
                      } else {
                        e.currentTarget.value = String(shot.gain_db);
                      }
                    }}
                  />
                  dB
                </label>
                <label class="inline">
                  <input type="checkbox" checked={shot.mute} disabled={busy} onchange={(e) => setShot("Mute clip sound", { mute: e.currentTarget.checked })} />
                  Mute
                </label>
              {/if}
              <Button size="sm" variant="danger" icon={Trash2} disabled={busy} onclick={removeSelected}>
                Remove from lane
              </Button>
            {/if}
            {#if selectedAudioClip !== null}
              {@const sound = selectedAudioClip}
              {@const length = sound.end_ms - sound.timeline_ms}
              <strong>Audio: {sound.name}</strong>
              <span class="hint num">{clock(sound.timeline_ms)} to {clock(sound.end_ms)}</span>
              <label class="inline">
                Level
                <input
                  class="num small"
                  type="number"
                  min="-60"
                  max="12"
                  step="0.5"
                  value={sound.gain_db}
                  disabled={busy}
                  onkeydown={(e) => e.stopPropagation()}
                  onchange={(e) => {
                    const value = Math.min(12, Math.max(-60, e.currentTarget.valueAsNumber));
                    if (Number.isFinite(value) && value !== sound.gain_db) {
                      void audioEdit("Change audio clip level", [{ op: "set_audio_clip", clip_id: sound.id, gain_db: value }]);
                    } else {
                      e.currentTarget.value = String(sound.gain_db);
                    }
                  }}
                />
                dB
              </label>
              <label class="inline">
                Fade in
                <input
                  class="num small"
                  type="number"
                  min="0"
                  max={(length - sound.fade_out_ms) / 1000}
                  step="0.1"
                  value={sound.fade_in_ms / 1000}
                  disabled={busy}
                  onkeydown={(e) => e.stopPropagation()}
                  onchange={(e) => {
                    const ms = Math.round(Math.max(0, e.currentTarget.valueAsNumber) * 1000);
                    if (Number.isFinite(ms) && ms !== sound.fade_in_ms) {
                      void audioEdit("Change fade in", [
                        { op: "set_audio_clip", clip_id: sound.id, fade_in_ms: Math.min(ms, length - sound.fade_out_ms) },
                      ]);
                    } else {
                      e.currentTarget.value = String(sound.fade_in_ms / 1000);
                    }
                  }}
                />
                s
              </label>
              <label class="inline">
                Fade out
                <input
                  class="num small"
                  type="number"
                  min="0"
                  max={(length - sound.fade_in_ms) / 1000}
                  step="0.1"
                  value={sound.fade_out_ms / 1000}
                  disabled={busy}
                  onkeydown={(e) => e.stopPropagation()}
                  onchange={(e) => {
                    const ms = Math.round(Math.max(0, e.currentTarget.valueAsNumber) * 1000);
                    if (Number.isFinite(ms) && ms !== sound.fade_out_ms) {
                      void audioEdit("Change fade out", [
                        { op: "set_audio_clip", clip_id: sound.id, fade_out_ms: Math.min(ms, length - sound.fade_in_ms) },
                      ]);
                    } else {
                      e.currentTarget.value = String(sound.fade_out_ms / 1000);
                    }
                  }}
                />
                s
              </label>
              <Button size="sm" variant="danger" icon={Trash2} disabled={busy} onclick={removeSelected}>
                Remove audio clip
              </Button>
            {/if}
            {#if selectedPlacement !== null}
              {@const placed = selectedPlacement}
              <strong>Placed line: {placed.line_text === "" ? "(line gone)" : placed.line_text}</strong>
              {#if placed.orphaned}
                <span class="hint">Its footage was cut away; it is parked at a clip edge.</span>
              {/if}
              {#if placed.take_id === null}
                <span class="hint">This line has no take to play.</span>
              {/if}
              {#if placed.overflow_ms > 0 && !placed.allow_overlap}
                <span class="error">
                  Runs {(placed.overflow_ms / 1000).toFixed(2)} s into the next line.
                  Tick "Allow overlap" for this line in the Line bank if that is intended.
                </span>
                {@const tighten = tightenTarget(placed.fit_stretch, placed.stretch)}
                {#if tighten !== null}
                  <Button size="sm" disabled={busy} onclick={() => setStretch(placed.id, tighten)}>
                    Tighten {stretchText(tighten)}
                    {placed.fit_stretch !== null && placed.fit_stretch > tighten + 0.0005
                      ? `(clearing it needs ${stretchText(placed.fit_stretch)}: use the slider)`
                      : ""}
                  </Button>
                {/if}
                {#if placed.fit_stretch !== null && placed.fit_stretch > STRETCH_MAX}
                  <span class="hint">Even {stretchText(STRETCH_MAX)} would not clear it: also nudge or shorten the line.</span>
                {/if}
                {#if placed.slack_ms > 0}
                  <Button size="sm" disabled={busy} onclick={() => nudgeEarlier(placed.id)}>
                    Nudge earlier {(Math.min(placed.overflow_ms, placed.slack_ms) / 1000).toFixed(2)} s
                    {placed.slack_ms < placed.overflow_ms ? "(not enough room to clear it)" : ""}
                  </Button>
                {:else}
                  <span class="hint">No room to nudge earlier: the previous line ends where this one starts.</span>
                {/if}
              {/if}
              {#if placed.take_id !== null}
                <label class="stretch">
                  Speed up
                  <input
                    type="range"
                    min={STRETCH_MIN}
                    max={STRETCH_MAX}
                    step="0.01"
                    value={placed.stretch}
                    disabled={busy}
                    onchange={(event) => setStretch(placed.id, event.currentTarget.valueAsNumber)}
                  />
                  <span class="num">{placed.stretch === 1 ? "as recorded" : stretchText(placed.stretch)}</span>
                </label>
                {#if placed.stretch > STRETCH_WARN}
                  <span class="hint">Above +15% the voice may sound unnatural.</span>
                {/if}
              {/if}
              <Button size="sm" variant="danger" icon={Trash2} disabled={busy} onclick={removeSelected}>
                Remove placed line
              </Button>
            {/if}
          </div>
          <details class="keys">
            <summary>Shortcuts</summary>
            <p>
              Space play/pause, , and . step a frame, S split at playhead (the selected audio or lane clip, else the footage), F freeze frame at the playhead (the selected lane recording, else the footage), N new voice line, G generate, Shift+G reroll, M place the selected line at the playhead, E add an expression key at the playhead (Avatar tab picks which), R drop a reaction at the playhead, Delete remove the selected clip, placed line, key or reaction,
              [ and ] cut the selected clip's in/out at the playhead, Ctrl+Z / Ctrl+Y undo / redo.
              Drag a clip's edge to trim it, drag a clip sideways to reorder, drag a voice block to move it, drag a line from the bank onto the timeline to place it; each drag is one undo step.
              Drag the thin bars between the panels to resize them (arrow keys work when a bar is focused).
            </p>
          </details>
        {/if}

        <h3>Clips <span class="count num">{timeline.clips.length} · {clock(timeline.duration_ms)}</span></h3>
        {#if timeline.other_track_clips > 0}
          <p class="hint">{timeline.other_track_clips} clip(s) on other tracks are not shown.</p>
        {/if}
        {#if timeline.orphan_count > 0}
          <p class="error">{timeline.orphan_count} item(s) lost their footage (orphaned).</p>
        {/if}
        {#each timeline.problems as problem}
          <p class="error">{problem.message}</p>
        {/each}
        {#if timeline.clips.length > 0}
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Source</th>
                <th>Timeline</th>
                <th>Length</th>
                <th>Source in..out</th>
                <th>Speed</th>
              </tr>
            </thead>
            <tbody>
              {#each timeline.clips as clip, i (clip.id)}
                <tr
                  class:missing={clip.source?.file_missing ?? true}
                  class:selected={clip.id === selectedId}
                  class:active={i === activeIndex}
                >
                  <td class="num">{clip.position + 1}</td>
                  <td class="file">
                    <button type="button" class="pick" onclick={() => {
                        selectedId = clip.id;
                        selectedPlacementId = null;
                        selectedAudioClipId = null;
                        playheadMs = clip.start_ms;
                      }}>
                      {sourceName(clip.source_id)}
                    </button>
                  </td>
                  <td class="num">{clock(clip.start_ms)} to {clock(clip.end_ms)}</td>
                  <td class="num">{clock(clip.duration_ms)}</td>
                  <td class="num">{clock(clip.in_ms)} to {clock(clip.out_ms)}</td>
                  <td class="num">{clip.speed}x</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>
    </div>

    <footer class="statusbar">
      <span class="seg" title="Voice model">
        <Mic size={14} strokeWidth={1.75} aria-hidden="true" />Voice model: {workerText(jobs)}
      </span>
      <span class="seg" class:busy-seg={liveJobs.length > 0} title="GPU queue">
        <Cpu size={14} strokeWidth={1.75} aria-hidden="true" />
        {#if liveJobs.length === 0}
          GPU idle
        {:else}
          {jobText(liveJobs[0])}{#if liveJobs.length > 1} (+{liveJobs.length - 1} waiting){/if}
        {/if}
      </span>
      {#if liveJobs.length > 0}
        <Button size="sm" variant="danger" icon={X} onclick={() => void cancelFirstJob()}>Cancel</Button>
      {:else if lastJob !== undefined}
        <span class="seg">Last job: {jobText(lastJob)}</span>
      {/if}
      {#if storage !== null}
        <span class="seg num" title="Takes on disk">
          <HardDrive size={14} strokeWidth={1.75} aria-hidden="true" />Takes {formatBytes(
            storage.total_bytes,
          )} ({storage.take_count})
        </span>
        {#if storage.missing_file_count > 0}
          <span class="seg error">{storage.missing_file_count} take file(s) missing</span>
        {/if}
      {/if}
      <span
        class="seg meter num"
        title="Momentary loudness (400 ms, K-weighted) of the preview mix. An approximation; the export is measured with pyloudnorm."
      >
        <Gauge size={14} strokeWidth={1.75} aria-hidden="true" />Mix {meterText}
      </span>
    </footer>
  {/if}
</div>

<ShortcutsDialog bind:open={showShortcuts} />

<style>
  .editor {
    position: fixed;
    inset: 0;
    display: flex;
    flex-direction: column;
    background: var(--bg);
    color: var(--text);
  }
  header {
    flex: none;
    display: flex;
    align-items: center;
    gap: 6px;
    height: 44px;
    padding: 0 10px;
    border-bottom: 1px solid var(--border);
    background: var(--surface-1);
  }
  header h2 {
    margin: 0 0 0 4px;
    font-size: var(--fs-lg);
    font-weight: 600;
  }
  .crumb {
    color: var(--text-3);
  }
  .sep {
    width: 1px;
    height: 18px;
    margin: 0 4px;
    background: var(--border-strong);
  }
  .spacer {
    flex: 1;
  }
  .msg {
    flex: none;
    margin: 0;
    padding: 6px 10px 0;
  }
  .workspace {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .top {
    flex: none;
    min-height: 0;
    max-height: 65%;
    display: flex;
  }
  .preview {
    flex: 1;
    min-width: 0;
    padding: 10px 12px;
    overflow: auto;
  }
  .empty-stage {
    display: grid;
    place-content: center;
    gap: 4px;
    height: 100%;
    min-height: 120px;
    border: 1px dashed var(--border-strong);
    border-radius: var(--r-md);
    text-align: center;
  }
  .empty-stage p {
    margin: 0;
  }
  .preview :global(.player) {
    max-width: none;
  }
  .preview :global(video) {
    max-height: calc(var(--top-h) - 5.5rem);
  }
  .side {
    flex: none;
    max-width: 70%;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border-left: 1px solid var(--line);
  }
  .pane {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 12px;
  }
  .empty {
    margin: 0;
    padding: 16px 4px;
    color: var(--text-2);
  }
  .side :global(.bank) {
    grid-template-columns: minmax(0, 1fr);
  }
  .divider {
    flex: none;
    background: var(--border);
    touch-action: none;
  }
  .divider:hover,
  .divider:focus-visible {
    background: var(--accent);
    outline: none;
  }
  .divider.v {
    width: 6px;
    cursor: col-resize;
  }
  .divider.h {
    height: 6px;
    cursor: row-resize;
  }
  .bottom {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 8px 12px 16px;
    background: var(--surface-1);
  }
  .bottom h3 {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin: 16px 0 0;
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .bottom h3 .count {
    color: var(--text-2);
    font-size: var(--fs-sm);
    font-weight: 500;
    letter-spacing: 0;
    text-transform: none;
  }
  .sources {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .sources li {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 0;
    border-bottom: 1px solid var(--border);
  }
  .sources li.missing .name {
    color: var(--danger);
  }
  .sources .name {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .meta {
    color: var(--muted);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 0.5rem;
  }
  th,
  td {
    text-align: left;
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
  }
  th {
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  tr.missing td.file {
    color: var(--danger);
  }
  td.file {
    overflow-wrap: anywhere;
  }
  tr.active td {
    background: var(--accent-soft);
  }
  tr.selected td {
    background: var(--accent-strong-soft);
  }
  .clipbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 12px;
    margin-top: 8px;
    min-height: 32px;
    padding: 4px 10px;
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    background: var(--surface-2);
  }
  .inline {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--text-2);
  }
  .inline input.small {
    width: 64px;
  }
  .keys {
    margin-top: 8px;
    font-size: var(--fs-sm);
    color: var(--muted);
  }
  .keys summary {
    cursor: pointer;
  }
  .keys p {
    margin: 0.4rem 0 0;
  }
  .pick {
    background: none;
    border: none;
    border-radius: var(--r-sm);
    padding: 0;
    margin: 0;
    color: inherit;
    font: inherit;
    text-align: left;
    text-decoration: underline;
    text-decoration-color: var(--text-3);
    text-underline-offset: 2px;
    cursor: pointer;
  }
  .pick:hover {
    background: none;
    text-decoration-color: currentColor;
  }
  .statusbar {
    flex: none;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 16px;
    min-height: 28px;
    padding: 2px 12px;
    border-top: 1px solid var(--border);
    background: var(--surface-1);
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .seg {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .busy-seg {
    color: var(--accent-hover);
  }
  .meter {
    margin-left: auto;
  }
  .tabs {
    flex: none;
    display: flex;
    gap: 2px;
    padding: 0 8px;
    border-bottom: 1px solid var(--border);
    overflow-x: auto;
  }
  .tabs button {
    margin: 0 0 -1px;
    padding: 10px 10px 9px;
    white-space: nowrap;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    background: none;
    color: var(--text-2);
    font: 500 var(--fs-md) var(--font);
    cursor: pointer;
  }
  .tabs button:hover {
    background: none;
    color: var(--text-1);
  }
  .tabs button.on {
    border-bottom-color: var(--accent);
    color: var(--text-1);
  }
  .hint {
    color: var(--muted);
  }
  .stretch {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
  }
</style>
