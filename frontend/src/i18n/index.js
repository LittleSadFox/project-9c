import { en } from "./en.js";

const catalog = { en };
let locale = "en";

export function t(key) {
  const table = catalog[locale] || en;
  return table[key] || key;
}

export function setLocale(next) {
  locale = next;
}
