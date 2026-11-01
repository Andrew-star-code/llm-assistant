import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Card({
  title,
  children,
  className,
  testId,
}: {
  title: ReactNode;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <section
      data-testid={testId}
      className={cn("flex flex-col gap-3 rounded-lg border border-border p-4", className)}
    >
      <h2 className="text-sm font-medium text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

export function Stat({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}
