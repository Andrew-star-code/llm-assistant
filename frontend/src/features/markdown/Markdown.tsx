import "katex/dist/katex.min.css";
import "@/features/markdown/markdown.css";

import { memo, type ComponentProps, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

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

function MarkdownImpl({ text, streaming = false }: { text: string; streaming?: boolean }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeSanitize, schema], rehypeKatex]}
        components={{
          a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
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
        {prepareMarkdown(text, streaming)}
      </ReactMarkdown>
    </div>
  );
}

export const Markdown = memo(MarkdownImpl);
