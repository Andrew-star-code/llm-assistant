import { describe, expect, it } from "vitest";

import en from "@/i18n/locales/en.json";
import ru from "@/i18n/locales/ru.json";

function keys(obj: object, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null ? keys(v as object, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

// Формы множественного числа у языков разные (ru: one/few/many, en: one/other) — сравниваем основу.
function normalized(obj: object): string[] {
  const plural = /_(zero|one|two|few|many|other)$/;
  return [...new Set(keys(obj).map((k) => k.replace(plural, "")))].sort();
}

describe("i18n", () => {
  it("в en те же ключи, что в ru", () => {
    expect(normalized(en)).toEqual(normalized(ru));
  });
});
