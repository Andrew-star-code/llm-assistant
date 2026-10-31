import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Providers } from "@/app/providers";
import { THEME_STORAGE_KEY, resolveDark, useThemeStore } from "@/features/theme/store";
import { ThemeToggle } from "@/features/theme/ThemeToggle";

describe("resolveDark", () => {
  it.each([
    ["light", false, false],
    ["light", true, false],
    ["dark", false, true],
    ["system", true, true],
    ["system", false, false],
  ] as const)("%s при системной тёмной=%s → %s", (mode, systemDark, expected) => {
    expect(resolveDark(mode, systemDark)).toBe(expected);
  });
});

describe("ThemeToggle", () => {
  it("переключает тему, применяет класс и сохраняет выбор", async () => {
    useThemeStore.setState({ mode: "system" });
    render(
      <Providers>
        <ThemeToggle />
      </Providers>,
    );

    await userEvent.click(screen.getByRole("radio", { name: "Тёмная" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(screen.getByRole("radio", { name: "Тёмная" })).toHaveAttribute("aria-checked", "true");
    expect(JSON.parse(localStorage.getItem(THEME_STORAGE_KEY) ?? "{}")).toMatchObject({
      state: { mode: "dark" },
    });

    await userEvent.click(screen.getByRole("radio", { name: "Светлая" }));
    expect(document.documentElement).not.toHaveClass("dark");
  });
});
