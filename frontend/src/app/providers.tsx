import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { useThemeEffect } from "@/features/theme/store";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
      }),
  );
  useThemeEffect();
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
