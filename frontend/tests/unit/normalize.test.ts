import { describe, expect, it } from "vitest";

import { closeUnfinished, normalizeMath, prepareMarkdown } from "@/features/markdown/normalize";

describe("normalizeMath", () => {
  it("приводит \\( \\) и \\[ \\] к долларам", () => {
    expect(normalizeMath("Сила \\( F = ma \\) и")).toBe("Сила $F = ma$ и");
    expect(normalizeMath("До\n\\[\nE = mc^2\n\\]\nПосле")).toBe("До\n\n$$\nE = mc^2\n$$\n\nПосле");
  });

  it("делает блочной формулу $$…$$, записанную одной строкой", () => {
    expect(normalizeMath("Сумма:\n\n$$\\sum x$$\n\nконец")).toBe(
      "Сумма:\n\n$$\n\\sum x\n$$\n\nконец",
    );
    expect(normalizeMath("в тексте $$a$$ остаётся")).toBe("в тексте $$a$$ остаётся");
  });

  it("не трогает доллары и формулы внутри кода", () => {
    const md = "Текст \\(x\\)\n```latex\n\\(y\\) и \\[z\\]\n```\nи `\\(w\\)` строчно";
    expect(normalizeMath(md)).toBe(
      "Текст $x$\n```latex\n\\(y\\) и \\[z\\]\n```\nи `\\(w\\)` строчно",
    );
  });

  it("сохраняет текст без формул как есть", () => {
    const md = "# Заголовок\n\n- пункт\n\n```py\nprint(1)\n```\n";
    expect(normalizeMath(md)).toBe(md);
  });
});

describe("closeUnfinished", () => {
  it("закрывает незакрытый блок кода", () => {
    expect(closeUnfinished("Код:\n```python\nprint(1)")).toBe("Код:\n```python\nprint(1)\n```");
  });

  it("закрывает незакрытую блочную формулу, но не трогает закрытые", () => {
    expect(closeUnfinished("Формула\n$$\nx^2")).toBe("Формула\n$$\nx^2\n$$");
    expect(closeUnfinished("$$a$$ и `$$` в коде")).toBe("$$a$$ и `$$` в коде");
  });

  it("готовит текст к рендеру только во время стрима", () => {
    expect(prepareMarkdown("\\[x", true)).toBe("\\[x");
    expect(prepareMarkdown("\\[x\\]", true)).toBe("\n$$\nx\n$$\n");
    expect(prepareMarkdown("```js\nlet a", false)).toBe("```js\nlet a");
  });
});
