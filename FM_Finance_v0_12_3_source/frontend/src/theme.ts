/** The three looks (v0.9.0). The chosen look is stored with the person's login; the last one used is also kept in
 *  this browser so the sign-in page and start-up already look right. */
export type Theme = "classic" | "executive" | "dark";

export const THEMES: { key: Theme; label: string; blurb: string }[] = [
  { key: "classic", label: "Classic", blurb: "Clean and bright. Navy, with green for paid and red for overdue." },
  { key: "executive", label: "Executive", blurb: "Navy menu with gold accents, like a private bank." },
  { key: "dark", label: "Dark", blurb: "Dark and compact, easy on the eyes for long sessions." },
];

const KEY = "fm-theme";

export function isTheme(v: unknown): v is Theme {
  return v === "classic" || v === "executive" || v === "dark";
}

export function savedTheme(): Theme {
  try {
    const v = window.localStorage.getItem(KEY);
    return isTheme(v) ? v : "classic";
  } catch {
    return "classic";
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    /* private window: the look still applies for this visit */
  }
}
