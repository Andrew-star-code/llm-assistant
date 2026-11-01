/**
 * Цитаты `[n]` (§10.5) → ссылки `#cite-n`, которые Markdown рисует кнопкой «открыть источник».
 * Меняются только номера существующих источников и только вне кода (блоков и `inline`).
 * Ссылки Markdown `[текст](url)` и сноски `[^1]` не трогаются.
 */
const CITE = /(?<![\\!\]])\[(\d{1,2})\](?![(:])/g;

export function linkCitations(text: string, valid: ReadonlySet<number>): string {
  if (valid.size === 0 || !text.includes("[")) return text;
  return text
    .split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part.replace(CITE, (match: string, n: string) =>
            valid.has(Number(n)) ? `[\\[${n}\\]](#cite-${n})` : match,
          ),
    )
    .join("");
}

export function citationNumber(href: string | undefined): number | null {
  const match = /^#cite-(\d+)$/.exec(href ?? "");
  return match ? Number(match[1]) : null;
}
