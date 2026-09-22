import { afterEach, describe, expect, it } from "vitest";
import { dictionaryKeys, getLocale, setLocaleSetting, t } from "./index";
import zhCN from "./zh-CN";

// The app's source, as text, so the dictionary can be checked against what is actually rendered.
const SOURCES = import.meta.glob<string>(["../**/*.ts", "../**/*.tsx", "!../**/*.test.ts", "!../i18n/**"], {
  query: "?raw",
  import: "default",
  eager: true,
});

afterEach(() => setLocaleSetting("en"));

describe("t", () => {
  it("returns the English key when there is no translation", () => {
    setLocaleSetting("en");
    expect(t("Nothing here")).toBe("Nothing here");
    expect(t("Hi, {name}", { name: "Sam" })).toBe("Hi, Sam");
  });

  it("translates and keeps placeholders", () => {
    setLocaleSetting("zh-CN");
    expect(getLocale()).toBe("zh-CN");
    expect(t("Feed")).toBe("动态");
    expect(t("Hi, I'm {name}.", { name: "Muse" })).toBe("你好，我是 Muse。");
    expect(t("{n} frames", { n: 3 })).toBe("3 帧");
  });

  it("leaves unknown placeholders alone rather than printing undefined", () => {
    setLocaleSetting("en");
    expect(t("Due in {n} days")).toBe("Due in {n} days");
  });
});

/** Every `t("...")` literal in the app source. */
function sourceKeys(): Set<string> {
  const keys = new Set<string>();
  const re = /\bt\(\s*"((?:[^"\\]|\\.)*)"/g;
  for (const src of Object.values(SOURCES)) {
    for (const m of src.matchAll(re)) keys.add(m[1].replace(/\\"/g, '"'));
  }
  return keys;
}

describe("zh-CN dictionary", () => {
  it("sees the app source", () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(10);
  });

  it("covers every literal string the app translates", () => {
    const missing = [...sourceKeys()].filter((k) => !(k in zhCN)).sort();
    expect(missing, `strings without a 简体中文 translation:\n${missing.join("\n")}`).toEqual([]);
  });

  it("keeps the same placeholders as the English text", () => {
    const vars = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    const broken = dictionaryKeys("zh-CN").filter((k) => JSON.stringify(vars(k)) !== JSON.stringify(vars(zhCN[k])));
    expect(broken, `placeholders differ:\n${broken.join("\n")}`).toEqual([]);
  });

  it("has no empty translations", () => {
    expect(dictionaryKeys("zh-CN").filter((k) => !zhCN[k].trim())).toEqual([]);
  });
});
