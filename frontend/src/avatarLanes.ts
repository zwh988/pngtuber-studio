/** Avatar lanes as the UI shows them (M5-5). Ids, ranges and defaults mirror backend/avatar/lanes.py. */

export interface LaneInfo {
  id: string;
  label: string;
  min: number;
  max: number;
  step: number;
  /** The AvatarSettings field holding this lane's base value. */
  setting: string;
  unit?: string;
}

export const LANE_INFO: LaneInfo[] = [
  { id: "bounce", label: "Bounce", min: 0, max: 3, step: 0.05, setting: "bounce" },
  { id: "float_amp", label: "Float amount", min: 0, max: 3, step: 0.05, setting: "float_amp" },
  { id: "float_speed", label: "Float speed", min: 0, max: 4, step: 0.05, setting: "float_speed" },
  { id: "blink_rate", label: "Blink rate", min: 0, max: 4, step: 0.05, setting: "blink_rate" },
  {
    id: "mouth_sensitivity",
    label: "Mouth sensitivity",
    min: 0.25,
    max: 4,
    step: 0.05,
    setting: "mouth_sensitivity",
  },
  { id: "scale", label: "Scale", min: 0.05, max: 5, step: 0.01, setting: "scale" },
  { id: "x", label: "X", min: -0.5, max: 1.5, step: 0.005, setting: "x" },
  { id: "y", label: "Y", min: -0.5, max: 1.5, step: 0.005, setting: "y" },
  { id: "rotation", label: "Rotation", min: -180, max: 180, step: 1, setting: "rotation_deg", unit: "°" },
];

export const MOTION_LANES: string[] = LANE_INFO.map((lane) => lane.id);

export const REACTION_TYPES = ["shake", "hop", "pop_in", "squish"] as const;

export function laneInfo(id: string): LaneInfo | undefined {
  return LANE_INFO.find((lane) => lane.id === id);
}

export function laneLabel(id: string): string {
  return id === "expression" ? "Expression" : (laneInfo(id)?.label ?? id);
}

export function reactionLabel(type: string): string {
  return type === "pop_in" ? "Pop-in" : type.charAt(0).toUpperCase() + type.slice(1);
}
