import { useState } from "react";

import { cn } from "@/lib/utils";

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0))
    .join("")
    .toUpperCase();
}

/** Фото из AD или инициалы, если фото нет или оно не загрузилось. */
export function Avatar({
  name,
  src,
  className,
}: {
  name: string;
  src?: string | null;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <span
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary/15 text-xs font-medium text-primary",
        className,
      )}
    >
      {src && !failed ? (
        <img
          src={src}
          alt=""
          className="size-full object-cover"
          onError={() => {
            setFailed(true);
          }}
        />
      ) : (
        initials(name)
      )}
    </span>
  );
}
