/**
 * Подсветка кода Shiki (§4, §7.5): ядро с JS-движком регулярных выражений (без WASM), языки и
 * темы загружаются лениво из бандла — без CDN и сетевых обращений.
 */
import type { HighlighterCore } from "shiki/core";

const LANGUAGES: Record<string, () => Promise<unknown>> = {
  python: () => import("shiki/langs/python.mjs"),
  javascript: () => import("shiki/langs/javascript.mjs"),
  typescript: () => import("shiki/langs/typescript.mjs"),
  tsx: () => import("shiki/langs/tsx.mjs"),
  jsx: () => import("shiki/langs/jsx.mjs"),
  json: () => import("shiki/langs/json.mjs"),
  yaml: () => import("shiki/langs/yaml.mjs"),
  bash: () => import("shiki/langs/bash.mjs"),
  powershell: () => import("shiki/langs/powershell.mjs"),
  sql: () => import("shiki/langs/sql.mjs"),
  html: () => import("shiki/langs/html.mjs"),
  css: () => import("shiki/langs/css.mjs"),
  xml: () => import("shiki/langs/xml.mjs"),
  markdown: () => import("shiki/langs/markdown.mjs"),
  java: () => import("shiki/langs/java.mjs"),
  csharp: () => import("shiki/langs/csharp.mjs"),
  go: () => import("shiki/langs/go.mjs"),
  rust: () => import("shiki/langs/rust.mjs"),
  cpp: () => import("shiki/langs/cpp.mjs"),
  php: () => import("shiki/langs/php.mjs"),
  dockerfile: () => import("shiki/langs/dockerfile.mjs"),
  latex: () => import("shiki/langs/latex.mjs"),
  "1c": () => import("shiki/langs/1c.mjs"),
};

const ALIASES: Record<string, string> = {
  py: "python",
  js: "javascript",
  ts: "typescript",
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  console: "bash",
  yml: "yaml",
  md: "markdown",
  cs: "csharp",
  "c#": "csharp",
  "c++": "cpp",
  ps1: "powershell",
  tex: "latex",
  bsl: "1c",
  docker: "dockerfile",
  golang: "go",
  rs: "rust",
};

export function resolveLanguage(lang: string | undefined): string | null {
  if (!lang) return null;
  const key = lang.toLowerCase();
  const name = ALIASES[key] ?? key;
  return name in LANGUAGES ? name : null;
}

let highlighter: Promise<HighlighterCore> | null = null;
const loaded = new Set<string>();

async function getHighlighter(): Promise<HighlighterCore> {
  highlighter ??= (async () => {
    const [{ createHighlighterCore }, { createJavaScriptRegexEngine }, light, dark] =
      await Promise.all([
        import("shiki/core"),
        import("shiki/engine/javascript"),
        import("shiki/themes/github-light.mjs"),
        import("shiki/themes/github-dark.mjs"),
      ]);
    return createHighlighterCore({
      themes: [light.default, dark.default],
      langs: [],
      engine: createJavaScriptRegexEngine(),
    });
  })();
  return highlighter;
}

/** HTML подсвеченного кода с цветами обеих тем в CSS-переменных; null — язык не поддержан. */
export async function highlight(code: string, lang: string | undefined): Promise<string | null> {
  const name = resolveLanguage(lang);
  if (!name) return null;
  const hl = await getHighlighter();
  if (!loaded.has(name)) {
    const module = (await LANGUAGES[name]?.()) as {
      default: Parameters<HighlighterCore["loadLanguage"]>[0];
    };
    await hl.loadLanguage(module.default);
    loaded.add(name);
  }
  return hl.codeToHtml(code, {
    lang: name,
    themes: { light: "github-light", dark: "github-dark" },
    defaultColor: false,
  });
}
