import {
  BookOpen,
  Briefcase,
  Calculator,
  FileSignature,
  FileText,
  GraduationCap,
  LifeBuoy,
  Megaphone,
  Scale,
  Shield,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";

// Иконки карточек сценариев — тот же набор, что `ICONS` в backend/app/modules/scenarios/service.py.
export const SCENARIO_ICONS: Record<string, LucideIcon> = {
  "file-signature": FileSignature,
  "life-buoy": LifeBuoy,
  scale: Scale,
  briefcase: Briefcase,
  users: Users,
  calculator: Calculator,
  "book-open": BookOpen,
  megaphone: Megaphone,
  shield: Shield,
  "graduation-cap": GraduationCap,
  "file-text": FileText,
  sparkles: Sparkles,
};
