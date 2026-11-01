/**
 * Подготовка Markdown от модели к рендеру (§7.5).
 *
 * 1. Делимитеры формул `\(…\)` и `\[…\]` приводятся к `$…$` и `$$…$$` — модели часто пишут их
 *    со слэшами, а remark-math понимает доллары. Внутри кода ничего не трогаем.
 * 2. Во время стрима незакрытый блок кода или формулы закрывается временно, чтобы вёрстка не ломалась.
 */

interface Block {
  code: boolean;
  lines: string[];
}

interface Split {
  blocks: Block[];
  /** Последний блок кода не закрыт (идёт стрим). */
  unclosedFence: boolean;
}

const FENCE = /^\s{0,3}(`{3,}|~{3,})/;

/** Делит текст построчно на блоки кода (``` / ~~~) и обычный текст. */
export function splitFences(markdown: string): Split {
  const blocks: Block[] = [];
  let current: Block = { code: false, lines: [] };
  let fence: string | null = null;
  for (const line of markdown.split("\n")) {
    const match = FENCE.exec(line);
    if (fence === null && match) {
      if (current.lines.length) blocks.push(current);
      current = { code: true, lines: [line] };
      fence = match[1] ?? "```";
      continue;
    }
    if (fence !== null && match && line.trim().startsWith(fence) && /^[`~]+$/.test(line.trim())) {
      current.lines.push(line);
      blocks.push(current);
      current = { code: false, lines: [] };
      fence = null;
      continue;
    }
    current.lines.push(line);
  }
  if (current.lines.length || blocks.length === 0) blocks.push(current);
  return { blocks, unclosedFence: fence !== null };
}

/** В обычном тексте меняет делимитеры формул, не трогая строчный `код`. */
function normalizeText(text: string): string {
  return text
    .split(/(`[^`\n]+`)/g)
    .map((part, index) =>
      index % 2 === 1
        ? part
        : part
            .replace(/\\\[([\s\S]*?)\\\]/g, (_, body: string) => `\n$$\n${body.trim()}\n$$\n`)
            .replace(/\\\(([\s\S]*?)\\\)/g, (_, body: string) => `$${body.trim()}$`)
            // `$$…$$` одной строкой модели подразумевают блочной формулой; remark-math — строчной.
            .replace(
              /^[ \t]*\$\$([^\n$]+?)\$\$[ \t]*$/gm,
              (_, body: string) => `$$\n${body.trim()}\n$$`,
            ),
    )
    .join("");
}

export function normalizeMath(markdown: string): string {
  return splitFences(markdown)
    .blocks.map((block) => {
      const text = block.lines.join("\n");
      return block.code ? text : normalizeText(text);
    })
    .join("\n");
}

/** Закрывает незакрытые блок кода и блочную формулу — только для показа во время стрима. */
export function closeUnfinished(markdown: string): string {
  const { blocks, unclosedFence } = splitFences(markdown);
  if (unclosedFence) return `${markdown}\n\`\`\``;
  const outside = blocks
    .filter((b) => !b.code)
    .map((b) => b.lines.join("\n").replace(/`[^`\n]+`/g, ""))
    .join("\n");
  const displayMath = (outside.match(/\$\$/g) ?? []).length;
  return displayMath % 2 === 1 ? `${markdown}\n$$` : markdown;
}

export function prepareMarkdown(markdown: string, streaming: boolean): string {
  const normalized = normalizeMath(markdown);
  return streaming ? closeUnfinished(normalized) : normalized;
}
