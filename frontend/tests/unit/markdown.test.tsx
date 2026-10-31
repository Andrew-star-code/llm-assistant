import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Markdown } from "@/features/markdown/Markdown";

describe("Markdown", () => {
  it("рендерит формулы во всех делимитерах (§7.5)", () => {
    const text = "Строчные: \\(a^2\\) и $b^2$.\n\n\\[\nc^2\n\\]\n\n$$d^2$$";
    const { container } = render(<Markdown text={text} />);
    expect(container.querySelectorAll(".katex")).toHaveLength(4);
    expect(container.querySelectorAll(".katex-display")).toHaveLength(2);
    expect(container.textContent).not.toContain("\\(");
  });

  it("показывает блок кода с языком и кнопкой «Копировать»", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<Markdown text={"```python\nprint('hi')\n```"} />);
    const block = screen.getByTestId("code-block");
    expect(block).toHaveTextContent("python");
    await userEvent.click(screen.getByRole("button", { name: "Копировать" }));
    expect(writeText).toHaveBeenCalledWith("print('hi')");
    expect(await screen.findByText("Скопировано")).toBeInTheDocument();
  });

  it("не исполняет HTML из ответа модели и открывает ссылки в новой вкладке", () => {
    const { container } = render(
      <Markdown
        text={
          '<script>window.x=1</script>\n\nТекст <img src=x onerror="alert(1)"> и [сайт](https://example.org)'
        }
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    const link = screen.getByRole("link", { name: "сайт" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("не ломается на незакрытом блоке кода и формуле во время стрима", () => {
    const { container, rerender } = render(<Markdown text={"Код:\n```js\nlet a = 1"} streaming />);
    expect(screen.getByTestId("code-block")).toHaveTextContent("let a = 1");
    rerender(<Markdown text={"Формула:\n$$\nx^2 + "} streaming />);
    expect(container.querySelectorAll(".katex-display")).toHaveLength(1);
  });

  it("рендерит таблицы и чек-листы GFM", () => {
    const { container } = render(
      <Markdown text={"| a | b |\n|---|---|\n| 1 | 2 |\n\n- [x] готово"} />,
    );
    expect(container.querySelector("table")).not.toBeNull();
    expect(container.querySelector('input[type="checkbox"]')).not.toBeNull();
  });
});
