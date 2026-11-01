import { describe, expect, it } from "vitest";

import { greetingKey } from "@/features/home/greeting";

describe("greetingKey", () => {
  it.each([
    [4, "home.greeting.night"],
    [5, "home.greeting.morning"],
    [11, "home.greeting.morning"],
    [12, "home.greeting.day"],
    [18, "home.greeting.evening"],
    [23, "home.greeting.night"],
  ])("%i ч → %s", (hour, expected) => {
    expect(greetingKey(new Date(2026, 9, 31, hour))).toBe(expected);
  });
});
