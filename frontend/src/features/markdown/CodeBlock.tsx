import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { highlight } from "@/features/markdown/highlight";
import { useCopy } from "@/lib/useCopy";

/** Блок кода: подпись языка, «Копировать», подсветка Shiki, горизонтальная прокрутка (§7.5). */
export function CodeBlock({
  code,
  lang,
  streaming,
}: {
  code: string;
  lang?: string;
  streaming: boolean;
}) {
  const { t } = useTranslation();
  const [html, setHtml] = useState<string | null>(null);
  const { copied, copy } = useCopy();

  useEffect(() => {
    // Во время стрима код меняется на каждом чанке — подсвечиваем, когда ответ готов.
    if (streaming) return;
    let cancelled = false;
    highlight(code, lang)
      .then((result) => {
        if (!cancelled) setHtml(result);
      })
      .catch(() => {
        if (!cancelled) setHtml(null);
      });
    return () => {
      cancelled = true;
    };
  }, [code, lang, streaming]);

  return (
    <div
      className="code-block my-3 overflow-hidden rounded-lg border border-border"
      data-testid="code-block"
    >
      <div className="flex items-center justify-between bg-muted px-3 py-1 text-xs text-muted-foreground">
        <span>{lang || t("markdown.code")}</span>
        <button
          type="button"
          onClick={() => {
            void copy(code);
          }}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-background hover:text-foreground"
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? t("markdown.copied") : t("markdown.copy")}
        </button>
      </div>
      {html && !streaming ? (
        // HTML строит Shiki из текста кода с экранированием — пользовательской разметки в нём нет.
        <div
          className="overflow-x-auto text-sm [&_pre]:p-3"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <pre className="overflow-x-auto p-3 text-sm">
          <code>{code}</code>
        </pre>
      )}
    </div>
  );
}
