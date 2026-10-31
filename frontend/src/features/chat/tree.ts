import type { Schemas } from "@/api/client";

export type Message = Schemas["MessageOut"];

/** Активная ветка: от листа вверх по parent_id, в порядке диалога (§8.6). */
export function activeBranch(messages: Message[], leafId: string | null | undefined): Message[] {
  const byId = new Map(messages.map((m) => [m.id, m]));
  const chain: Message[] = [];
  let current = leafId ? byId.get(leafId) : undefined;
  while (current) {
    chain.push(current);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return chain.reverse();
}

/** Версии ответа — сообщения с тем же родителем, в порядке создания. */
export function siblings(messages: Message[], message: Message): Message[] {
  return messages
    .filter((m) => m.parent_id === message.parent_id && m.role === message.role)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

/** Самый свежий лист поддерева: при переключении версии продолжаем её последнюю ветку. */
export function latestLeaf(messages: Message[], rootId: string): string {
  let current = rootId;
  for (;;) {
    const children = messages
      .filter((m) => m.parent_id === current)
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    const next = children[0];
    if (!next) return current;
    current = next.id;
  }
}
