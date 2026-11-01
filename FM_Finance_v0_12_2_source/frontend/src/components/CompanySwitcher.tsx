import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth, useToast } from "../context";
import { ROLE_LABEL } from "../format";
import type { CompanyListItem } from "../types";

/** Sidebar control showing the current company and switching between the user's companies. */
export default function CompanySwitcher() {
  const { user } = useAuth();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [companies, setCompanies] = useState<CompanyListItem[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    api.companies().then(setCompanies).catch((e: Error) => toast.error(e.message));
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open, toast]);

  if (!user) return null;
  const canAdd = user.is_platform_admin || user.is_reseller_admin;
  if (!user.company_id && !canAdd) return null;
  // Only one company and no right to add more: just show the name, no menu.
  if (user.company_count <= 1 && !canAdd) {
    return (
      <div className="switcher single">
        <span className="switcher-text"><span className="switcher-label">Company</span>
          <span className="switcher-name">{user.company_name}</span></span>
      </div>
    );
  }

  async function choose(c: CompanyListItem) {
    if (c.is_current) { setOpen(false); return; }
    setBusy(c.id);
    try {
      await api.switchCompany(c.id);
      // A full reload clears every page's data from the previous company.
      window.location.assign("/");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not switch company");
      setBusy(null);
    }
  }

  return (
    <div className="switcher" ref={box}>
      <button type="button" className="switcher-current" aria-haspopup="listbox" aria-expanded={open}
        onClick={() => setOpen((o) => !o)}>
        <span className="switcher-text">
          <span className="switcher-label">Company</span>
          <span className="switcher-name">{user.company_name ?? "No company yet"}</span>
        </span>
        <span className="switcher-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="switcher-menu" role="listbox" aria-label="Your companies">
          {companies === null ? <p className="muted switcher-empty">Loading…</p> :
            companies.length === 0 ? <p className="muted switcher-empty">You don't have a company yet.</p> :
            companies.map((c) => (
              <button key={c.id} type="button" role="option" aria-selected={c.is_current} disabled={busy !== null}
                className={c.is_current ? "switcher-item current" : "switcher-item"} onClick={() => void choose(c)}>
                {c.has_logo
                  ? <img src={`/api/company/${c.id}/logo?v=${c.logo_version}`} alt="" />
                  : <span className="switcher-initial" aria-hidden="true">{c.name.slice(0, 1).toUpperCase()}</span>}
                <span className="switcher-item-text">
                  <span>{c.name}</span>
                  <span className="muted">{ROLE_LABEL[c.role]}{c.reseller_name ? ` · ${c.reseller_name}` : ""}</span>
                </span>
                {c.is_current && <span className="switcher-check" aria-hidden="true">✓</span>}
              </button>
            ))}
          <Link to="/companies" className="switcher-all" onClick={() => setOpen(false)}>
            {canAdd ? "All companies and add a company" : "All companies"}
          </Link>
        </div>
      )}
    </div>
  );
}
