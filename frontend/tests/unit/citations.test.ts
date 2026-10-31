import { describe, expect, it } from "vitest";

import { citationNumber, linkCitations } from "@/features/markdown/citations";

describe("Цитаты [n]", () => {
  const valid = new Set([1, 2]);

  it("превращает номера источников в ссылки", () => {
    expect(linkCitations("Срок 10 дней [1], оплата [2].", valid)).toBe(
      "Срок 10 дней [\\[1\\]](#cite-1), оплата [\\[2\\]](#cite-2).",
    );
  });

  it("не трогает несуществующие номера, код, ссылки и сноски", () => {
    expect(linkCitations("Пункт [7]", valid)).toBe("Пункт [7]");
    expect(linkCitations("`arr[1]` и\n```\nx = a[2]\n```", valid)).toBe(
      "`arr[1]` и\n```\nx = a[2]\n```",
    );
    expect(linkCitations("[1](http://x) и [^1] и ![1](img)", valid)).toBe(
      "[1](http://x) и [^1] и ![1](img)",
    );
    expect(linkCitations("[1]: http://def", valid)).toBe("[1]: http://def");
  });

  it("распознаёт ссылку цитаты", () => {
    expect(citationNumber("#cite-3")).toBe(3);
    expect(citationNumber("https://x")).toBeNull();
  });
});
