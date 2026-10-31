export type GreetingKey =
  "home.greeting.morning" | "home.greeting.day" | "home.greeting.evening" | "home.greeting.night";

/** Ключ приветствия по местному времени: утро 5–11, день 12–17, вечер 18–22, ночь — остальное. */
export function greetingKey(now: Date): GreetingKey {
  const hour = now.getHours();
  if (hour >= 5 && hour < 12) return "home.greeting.morning";
  if (hour >= 12 && hour < 18) return "home.greeting.day";
  if (hour >= 18 && hour < 23) return "home.greeting.evening";
  return "home.greeting.night";
}
