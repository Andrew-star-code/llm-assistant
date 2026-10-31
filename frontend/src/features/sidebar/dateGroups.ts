/**
 * Группы истории по датам (§7.2): Сегодня, Вчера, Последние 7 дней, Последние 30 дней, затем
 * по месяцам текущего года («Сентябрь»), прошлые годы — по году. Считается по дате последнего
 * сообщения в часовом поясе браузера пользователя.
 */

export type DateGroup =
  | { kind: "today" }
  | { kind: "yesterday" }
  | { kind: "week" }
  | { kind: "month" }
  | { kind: "monthOfYear"; month: number }
  | { kind: "year"; year: number };

const DAY = 24 * 60 * 60 * 1000;

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

export function dateGroup(value: string | Date, now: Date = new Date()): DateGroup {
  const date = typeof value === "string" ? new Date(value) : value;
  const days = Math.round((startOfDay(now) - startOfDay(date)) / DAY);
  if (days <= 0) return { kind: "today" };
  if (days === 1) return { kind: "yesterday" };
  if (days < 7) return { kind: "week" };
  if (days < 30) return { kind: "month" };
  if (date.getFullYear() === now.getFullYear())
    return { kind: "monthOfYear", month: date.getMonth() };
  return { kind: "year", year: date.getFullYear() };
}

export function groupKey(group: DateGroup): string {
  if (group.kind === "monthOfYear") return `m${group.month}`;
  if (group.kind === "year") return `y${group.year}`;
  return group.kind;
}

/** Группирует уже отсортированные (свежие сверху) элементы, сохраняя порядок. */
export function groupByDate<T>(
  items: T[],
  dateOf: (item: T) => string | null | undefined,
  now: Date = new Date(),
): { group: DateGroup; items: T[] }[] {
  const result: { group: DateGroup; items: T[] }[] = [];
  for (const item of items) {
    const group = dateGroup(dateOf(item) ?? new Date(0).toISOString(), now);
    const last = result[result.length - 1];
    if (last && groupKey(last.group) === groupKey(group)) last.items.push(item);
    else result.push({ group, items: [item] });
  }
  return result;
}
