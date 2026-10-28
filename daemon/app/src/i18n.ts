// Language: follow the OS, or the choice the user made in Settings → App.
// English is the default and the source table; Simplified Chinese is the
// first added table. Pure modules call t() directly; React re-renders ride
// useLanguage() at the App root.
import { useSyncExternalStore } from "react";
import { en } from "./messages/en";
import { zh } from "./messages/zh";

export type Language = "en" | "zh-CN";
export type LanguageChoice = "system" | Language;
const KEY = "gsd-path.language";

export type MessageKey = keyof typeof en;
const TABLES: Record<Language, Partial<Record<MessageKey, string>>> = { en, "zh-CN": zh };

// Simplified-Chinese locale tags: bare zh, Hans, and the Hans-using regions.
// Traditional locales (zh-TW, zh-HK, …) stay English until a table exists.
const HANS_PREFIXES = ["zh-hans"];
const HANS_EXACT = new Set(["zh", "zh-cn", "zh-sg", "zh-my"]);

/** The language to draw for a stored choice and the system languages. */
export const resolveLanguage = (
  choice: string | null,
  systemLanguages: readonly string[],
): Language => {
  if (choice === "en" || choice === "zh-CN") return choice;
  for (const tag of systemLanguages) {
    const name = tag.toLowerCase();
    if (HANS_EXACT.has(name) || HANS_PREFIXES.some((prefix) => name.startsWith(prefix))) {
      return "zh-CN";
    }
  }
  return "en";
};

export const storedLanguage = (): LanguageChoice => {
  const choice = localStorage.getItem(KEY);
  return choice === "en" || choice === "zh-CN" ? choice : "system";
};

// Read in the functions, not at import: the tests have no window.
const systemLanguages = (): string[] => {
  if (typeof navigator === "undefined") return [];
  return [...(navigator.languages ?? []), navigator.language].filter(Boolean);
};

let current: Language = "en";
const listeners = new Set<() => void>();

export function applyLanguage() {
  current = resolveLanguage(localStorage.getItem(KEY), systemLanguages());
  document.documentElement.lang = current;
  listeners.forEach((listener) => listener());
}
export function setLanguage(choice: LanguageChoice) {
  if (choice === "system") localStorage.removeItem(KEY);
  else localStorage.setItem(KEY, choice);
  applyLanguage();
}
/** Call once at start: draw the language and follow a change made in Settings. */
export function watchLanguage() {
  applyLanguage();
  // The tray popover is another window; it follows a change made in Settings.
  addEventListener("storage", (event) => { if (event.key === KEY) applyLanguage(); });
}

export const language = (): Language => current;

/** The message for a key in the current language, falling back to English,
 * then to the key itself — a stale table never renders blank. */
export function t(
  key: MessageKey,
  params?: Record<string, string | number | null | undefined>,
): string {
  let text = TABLES[current][key] ?? en[key] ?? key;
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}

/** The active language as React state: the App root re-renders on change. */
export function useLanguage(): Language {
  return useSyncExternalStore(
    (onChange) => {
      listeners.add(onChange);
      return () => listeners.delete(onChange);
    },
    () => current,
  );
}
