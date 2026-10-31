import { describe, expect, it } from "vitest";

import { activeBranch, latestLeaf, siblings, type Message } from "@/features/chat/tree";
import { dateGroup, groupByDate } from "@/features/sidebar/dateGroups";

function msg(
  id: string,
  parent: string | null,
  role: "user" | "assistant",
  minute: number,
): Message {
  return {
    id,
    parent_id: parent,
    role,
    chat_id: "c",
    content: id,
    reasoning: null,
    status: "completed",
    thinking: false,
    model: null,
    finish_reason: null,
    prompt_tokens: null,
    completion_tokens: null,
    reasoning_tokens: null,
    ttft_ms: null,
    latency_ms: null,
    error: null,
    created_at: new Date(Date.UTC(2026, 9, 31, 10, minute)).toISOString(),
    feedback: null,
  };
}

// u1 → a1, a2 (перегенерация); a2 → u2 → a3
const tree = [
  msg("u1", null, "user", 0),
  msg("a1", "u1", "assistant", 1),
  msg("a2", "u1", "assistant", 2),
  msg("u2", "a2", "user", 3),
  msg("a3", "u2", "assistant", 4),
  msg("u3", "a1", "user", 5),
  msg("a4", "u3", "assistant", 6),
];

describe("дерево сообщений", () => {
  it("строит активную ветку от листа", () => {
    expect(activeBranch(tree, "a3").map((m) => m.id)).toEqual(["u1", "a2", "u2", "a3"]);
    expect(activeBranch(tree, null)).toEqual([]);
  });

  it("находит версии ответа и свежий лист поддерева", () => {
    const a2 = tree[2] as Message;
    expect(siblings(tree, a2).map((m) => m.id)).toEqual(["a1", "a2"]);
    expect(latestLeaf(tree, "a1")).toBe("a4");
    expect(latestLeaf(tree, "a3")).toBe("a3");
  });
});

describe("группы по датам", () => {
  const now = new Date(2026, 9, 31, 12, 0);
  it.each([
    [new Date(2026, 9, 31, 0, 1), "today"],
    [new Date(2026, 9, 30, 23, 59), "yesterday"],
    [new Date(2026, 9, 26), "week"],
    [new Date(2026, 9, 5), "month"],
    [new Date(2026, 7, 15), "monthOfYear"],
    [new Date(2025, 11, 31), "year"],
  ])("%s → %s", (date, kind) => {
    expect(dateGroup(date, now).kind).toBe(kind);
  });

  it("группирует подряд идущие элементы", () => {
    const items = [
      new Date(2026, 9, 31),
      new Date(2026, 9, 31, 1),
      new Date(2026, 9, 30),
      new Date(2026, 7, 1),
    ];
    const groups = groupByDate(items, (d) => d.toISOString(), now);
    expect(groups.map((g) => [g.group.kind, g.items.length])).toEqual([
      ["today", 2],
      ["yesterday", 1],
      ["monthOfYear", 1],
    ]);
  });
});
