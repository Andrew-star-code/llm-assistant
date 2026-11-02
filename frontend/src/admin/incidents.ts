/** Цвета уровней и статусов инцидентов — общие для списка и карточки. */
export const SEVERITY_TONE = {
  low: "muted",
  medium: "warn",
  warning: "warn",
  high: "bad",
  critical: "bad",
} as const;
export const STATUS_TONE = {
  new: "bad",
  in_progress: "warn",
  resolved: "ok",
  false_positive: "muted",
} as const;

export function tone<T extends Record<string, string>>(map: T, key: string): T[keyof T] | "muted" {
  return key in map ? map[key as keyof T] : "muted";
}
