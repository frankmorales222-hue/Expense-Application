import { useState } from "react";
import { api } from "../api";
import { useAuth, useToast } from "../context";
import { THEMES, applyTheme, type Theme } from "../theme";
import Icon from "./Icon";

/** Small picture of each look: sidebar, a heading bar, a few chart bars. Colors are the looks' own. */
const SWATCH: Record<Theme, { side: string; sideOn: string; bg: string; card: string; head: string; bars: [string, string] }> = {
  classic: { side: "#ffffff", sideOn: "#1e3a8a", bg: "#f8fafc", card: "#ffffff", head: "#0f172a", bars: ["#1e3a8a", "#cbd5e1"] },
  executive: { side: "#0f172a", sideOn: "#fcd34d", bg: "#f8fafc", card: "#ffffff", head: "#0f172a", bars: ["#1e3a8a", "#a16207"] },
  dark: { side: "#020617", sideOn: "#22c55e", bg: "#020617", card: "#0e1223", head: "#f8fafc", bars: ["#22c55e", "#f87171"] },
};

export default function AppearancePanel() {
  const { user, updateUser } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!user) return null;
  const current = user.theme_effective ?? "classic";
  const companyDefault = user.company_default_theme ?? "classic";
  const label = (t: Theme) => THEMES.find((x) => x.key === t)?.label ?? t;

  async function choose(theme: Theme | null) {
    setBusy(true);
    const before = current;
    if (theme) applyTheme(theme);  // show it right away
    try {
      const u = await api.setMyTheme(theme);
      updateUser(u);
      toast.success(theme ? `${label(theme)} look on` : `Back to the company's look (${label(companyDefault)})`);
    } catch (e) {
      applyTheme(before);
      toast.error(e instanceof Error ? e.message : "Could not change the look");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" id="appearance">
      <div className="panel-head"><h2>Appearance</h2>
        {user.theme && user.theme !== companyDefault && (
          <button type="button" className="link-button" disabled={busy} onClick={() => void choose(null)}>
            Use the company's look ({label(companyDefault)})</button>
        )}
      </div>
      <p className="muted" style={{ margin: 0 }}>Choose how F&amp;M Finance looks for you. Everyone in the company can pick their own;
        it follows your login to every company.</p>
      <div className="theme-picks" role="radiogroup" aria-label="Look">
        {THEMES.map((t) => {
          const s = SWATCH[t.key];
          const on = current === t.key;
          return (
            <button key={t.key} type="button" role="radio" aria-checked={on} disabled={busy}
              className={on ? "theme-pick active" : "theme-pick"} onClick={() => { if (!on) void choose(t.key); }}>
              <span className="swatch" aria-hidden="true" style={{ background: s.bg }}>
                <span className="sb" style={{ background: s.side, borderRight: `1px solid ${t.key === "classic" ? "#e2e8f0" : s.side}` }}>
                  <i className="on" style={{ background: s.sideOn }} /><i style={{ background: "#94a3b8" }} /><i style={{ background: "#94a3b8" }} />
                  <i style={{ background: "#94a3b8" }} />
                </span>
                <span className="mn">
                  <i style={{ background: s.card, border: `1px solid ${t.key === "dark" ? "#1f2a3d" : "#e2e8f0"}`, width: "70%" }} />
                  <em>{[14, 20, 16, 24, 19, 26].map((h, i) => (
                    <u key={i} style={{ height: h, background: s.bars[i % 2 === 0 ? 0 : 1] }} />))}</em>
                </span>
              </span>
              <b>{on && <Icon name="check" size={16} />}{t.label}{t.key === companyDefault && <small>· company default</small>}</b>
              <small>{t.blurb}</small>
            </button>
          );
        })}
      </div>
    </section>
  );
}
