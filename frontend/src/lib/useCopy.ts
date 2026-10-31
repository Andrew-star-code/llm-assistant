import { useCallback, useEffect, useRef, useState } from "react";

/** Копирование в буфер с коротким подтверждением «Скопировано». */
export function useCopy(timeoutMs = 1500) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const copy = useCallback(
    async (text: string) => {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        setCopied(false);
      }, timeoutMs);
    },
    [timeoutMs],
  );
  return { copied, copy };
}
