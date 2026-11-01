import { Sparkles } from "lucide-react";

import { SCENARIO_ICONS } from "@/features/scenarios/iconMap";

export function ScenarioIcon({ name, className }: { name: string | null; className?: string }) {
  const Icon = (name && SCENARIO_ICONS[name]) || Sparkles;
  return <Icon className={className} aria-hidden />;
}
