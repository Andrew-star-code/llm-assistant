import { describe, expect, it } from "vitest";

import en from "@/i18n/locales/en.json";
import ru from "@/i18n/locales/ru.json";

function keys(obj: object, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null ? keys(v as object, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

describe("i18n", () => {
  it("в en те же ключи, что в ru", () => {
    expect(keys(en).sort()).toEqual(keys(ru).sort());
  });
});
