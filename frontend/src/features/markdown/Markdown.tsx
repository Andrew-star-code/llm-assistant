import "katex/dist/katex.min.css";
import "@/features/markdown/markdown.css";

import { memo, type ComponentProps, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { citationNumber, linkCitations } from "@/features/markdown/citations";
import { CodeBlock } from "@/features/markdown/CodeBlock";
import { prepareMarkdown } from "@/features/markdown/normalize";

// HTML из ответа модели не исполняется (§7.5, §15): react-markdown не рендерит сырой HTML,
// а rehype-sanitize чистит дерево. Классы math-* нужны rehype-katex, language-* — блокам кода.
const schema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: [
      ...(defaultSchema.attributes?.code ?? []),
      ["className", /^language-./, "math-inline", "math-display"],
    ],
    span: [...(defaultSchema.attributes?.span ?? []), ["className", "math", "math-inline"]],
    div: [...(defaultSchema.attributes?.div ?? []), ["className", "math", "math-display"]],
  },
};

type CodeProps = ComponentProps<"code"> & { node?: unknown };

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  return "";
}

const NO_CITATIONS: ReadonlySet<number> = new Set();

interface MarkdownProps {
  text: string;
  streaming?: boolean;
  /** Номера источников ответа: `[n]` становится кнопкой, открывающей источник. */
  citations?: ReadonlySet<number>;
  onCite?: (index: number) => void;
}

function MarkdownImpl({
  text,
  streaming = false,
  citations = NO_CITATIONS,
  onCite,
}: MarkdownProps) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeSanitize, schema], rehypeKatex]}
        components={{
          a: ({ node, href, children, ...props }) => {
            const cite = citationNumber(href);
            if (cite !== null) {
              return (
                <button
                  type="button"
                  className="citation"
                  data-testid="citation"
                  onClick={() => onCite?.(cite)}
                >
                  {cite}
                </button>
              );
            }
            return (
              <a href={href} {...props} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          },
          pre: ({ children }) => <>{children}</>,
          code: ({ className, children, node, ...props }: CodeProps) => {
            const match = /language-([\w#+-]+)/.exec(className ?? "");
            const content = textOf(children).replace(/\n$/, "");
            const isBlock = Boolean(match) || content.includes("\n");
            if (!isBlock) {
              return (
                <code className="rounded bg-muted px-1 py-0.5 text-[0.9em]" {...props}>
                  {children}
                </code>
              );
            }
            return <CodeBlock code={content} lang={match?.[1]} streaming={streaming} />;
          },
        }}
      >
        {linkCitations(prepareMarkdown(text, streaming), citations)}
      </ReactMarkdown>
    </div>
  );
}

export const Markdown = memo(MarkdownImpl);
