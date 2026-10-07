/** Light / dark appearance, remembered per browser. */
export type Theme = "light" | "dark";

const KEY = "bom:theme";

export function storedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* storage blocked - the choice just isn't remembered */
  }
}
