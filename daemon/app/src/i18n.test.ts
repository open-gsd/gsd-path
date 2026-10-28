import { beforeEach, describe, expect, it } from "vitest";
import { en } from "./messages/en";
import { zh } from "./messages/zh";
import {
  applyLanguage, language, resolveLanguage, setLanguage, storedLanguage, t, type LanguageChoice,
} from "./i18n";

// localStorage does not exist in the node test environment; the module reads
// it only inside functions, so a tiny stub stands in.
const store = new Map<string, string>();
const localStorage = {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => store.set(key, value),
  removeItem: (key: string) => store.delete(key),
};
const documentElement = { lang: "" };
Object.defineProperty(globalThis, "localStorage", { value: localStorage, configurable: true });
Object.defineProperty(globalThis, "document", { value: { documentElement }, configurable: true });

describe("resolveLanguage", () => {
  it("keeps an explicit choice over the system languages", () => {
    expect(resolveLanguage("en", ["zh-CN", "zh"])).toBe("en");
    expect(resolveLanguage("zh-CN", ["en-US"])).toBe("zh-CN");
  });
  it("follows a Simplified-Chinese system language", () => {
    for (const tags of [["zh"], ["zh-CN", "en"], ["zh-Hans-CN"], ["zh-SG"], ["zh-hans"]]) {
      expect(resolveLanguage(null, tags)).toBe("zh-CN");
    }
  });
  it("does not claim Traditional Chinese locales", () => {
    expect(resolveLanguage(null, ["zh-TW"])).toBe("en");
    expect(resolveLanguage(null, ["zh-HK", "en"])).toBe("en");
  });
  it("falls back to English for anything unknown", () => {
    expect(resolveLanguage(null, [])).toBe("en");
    expect(resolveLanguage("nonsense", ["fr-FR"])).toBe("en");
  });
});

describe("message tables", () => {
  it("keeps zh-CN at key parity with the English source", () => {
    expect(Object.keys(zh).sort()).toEqual(Object.keys(en).sort());
  });
  it("translates and falls back to English, never to a blank", () => {
    applyLanguage();
    expect(language()).toBe("en");
    expect(t("nav.refresh")).toBe("Refresh");
    setLanguage("zh-CN");
    expect(language()).toBe("zh-CN");
    expect(t("nav.refresh")).toBe("刷新");
    expect(t("board.count", { shown: 2, total: 5 })).toBe("2/5 个项目");
    setLanguage("en");
    expect(t("board.count", { shown: 2, total: 5 })).toBe("2 of 5 projects");
  });
});

describe("the setting", () => {
  beforeEach(() => store.clear());

  it("stores a choice and removes the key for system", () => {
    expect(storedLanguage()).toBe<LanguageChoice>("system");
    setLanguage("zh-CN");
    expect(storedLanguage()).toBe("zh-CN");
    setLanguage("system");
    expect(storedLanguage()).toBe("system");
    expect(localStorage.getItem("gsd-path.language")).toBeNull();
  });
  it("marks the document language for screen readers", () => {
    setLanguage("zh-CN");
    expect(documentElement.lang).toBe("zh-CN");
    setLanguage("system");
    expect(documentElement.lang).toBe("en");
  });
});
