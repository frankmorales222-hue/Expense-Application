import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth, useToast } from "../context";
import { formatDate, money } from "../format";
import type { CompanyPlan, ModuleKey, PlanEditInput, PlanInfo, PlanKey, PlansCatalog, Reseller } from "../types";
import { THEMES, type Theme } from "../theme";

interface Draft { plan: PlanKey | "custom"; modules: ModuleKey[]; user_limit: string }

const toDraft = (c: CompanyPlan): Draft => ({
  plan: (c.plan as PlanKey | "custom" | null) ?? "custom", modules: c.modules, user_limit: c.user_limit ? String(c.user_limit) : "",
});

export default function PlansPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [catalog, setCatalog] = useState<PlansCatalog | null>(null);
  const [rows, setRows] = useState<CompanyPlan[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const load = useCallback(() => {
    api.companyPlans().then((r) => { setRows(r); setDrafts(Object.fromEntries(r.map((c) => [c.id, toDraft(c)]))); })
      .catch((e: Error) => toast.error(e.message));
  }, [toast]);
  const loadCatalog = useCallback(() => { api.plansCatalog(true).then(setCatalog).catch(() => undefined); }, []);
  useEffect(() => { loadCatalog(); load(); }, [load, loadCatalog]);

  /** Plans a company can be put on: everyone's plans, and its own reseller's (which win on the same code). */
  const plansFor = useCallback((c: CompanyPlan, current?: string | null): PlanInfo[] => {
    const out = new Map<string, PlanInfo>();
    for (const p of catalog?.plans ?? []) {
      if (!p.is_active && p.key !== current) continue;
      if (p.reseller_id === null && !out.has(p.key)) out.set(p.key, p);
      if (p.reseller_id !== null && p.reseller_name === c.reseller_name) out.set(p.key, p);
    }
    return [...out.values()].sort((a, b) => a.sort_order - b.sort_order);
  }, [catalog]);

  function choosePlan(id: string, plan: PlanKey | "custom") {
    setDrafts((d) => {
      const cur = d[id];
      const company = rows?.find((x) => x.id === id);
      if (!cur || !company) return d;
      const p = plansFor(company).find((x) => x.key === plan);
      return { ...d, [id]: p ? { plan, modules: [...p.modules], user_limit: p.user_limit ? String(p.user_limit) : "" } : { ...cur, plan } };
    });
  }

  function toggle(id: string, key: ModuleKey) {
    setDrafts((d) => {
      const cur = d[id];
      if (!cur) return d;
      const modules = cur.modules.includes(key) ? cur.modules.filter((m) => m !== key) : [...cur.modules, key];
      return { ...d, [id]: { ...cur, modules, plan: "custom" } };
    });
  }

  async function save(c: CompanyPlan) {
    const d = drafts[c.id];
    if (!d) return;
    const limit = d.user_limit.trim() ? Number(d.user_limit) : null;
    if (limit !== null && !(limit >= 1)) { toast.error("The user limit must be 1 or more (or empty for unlimited)"); return; }
    setBusy(c.id);
    try {
      const out = await api.setCompanyPlan(c.id, { plan: d.plan, modules: d.modules, user_limit: limit });
      setRows((r) => (r ?? []).map((x) => (x.id === c.id ? out : x)));
      setDrafts((all) => ({ ...all, [c.id]: toDraft(out) }));
      toast.success(`${c.name}: ${out.plan_label}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the plan");
    } finally {
      setBusy(null);
    }
  }

  async function setLook(c: CompanyPlan, theme: Theme) {
    try {
      const out = await api.setCompanyTheme(c.id, theme);
      setRows((r) => (r ?? []).map((x) => (x.id === c.id ? out : x)));
      toast.success(`${c.name}: ${THEMES.find((x) => x.key === theme)?.label} look by default`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not change the look");
    }
  }

  const q = search.trim().toLowerCase();
  const list = (rows ?? []).filter((c) => !q || c.name.toLowerCase().includes(q) || (c.reseller_name ?? "").toLowerCase().includes(q));
  const modules = catalog?.modules ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Plans and modules</h1>
          <p className="muted">
            {user?.is_platform_admin ? "Every company in F&M Finance. " : "Your clients. "}
            Tick the modules each client pays for. Core (dashboard, expenses, banking, chart of accounts, profit and loss,
            balance sheet, closing date, history, export, settings) is in every plan. Turning a module off keeps its records
            readable; nothing is deleted. Only names and plans are shown here, never a company's books. The default look is what people in the company see until they pick their own in Settings.
          </p>
        </div>
      </header>

      {catalog && <PlanCatalog catalog={catalog} isPlatform={!!user?.is_platform_admin} onChanged={() => { loadCatalog(); load(); }} />}

      <div className="toolbar">
        <label className="field grow"><span className="sr-only">Search</span>
          <input type="search" placeholder="Search company or reseller" value={search} onChange={(e) => setSearch(e.target.value)} /></label>
      </div>

      <section className="panel flush">
        {rows && list.length === 0 ? <div className="empty inner"><p>No companies.</p></div> : (
          <div className="table-wrap">
            <table className="ledger plans-table">
              <thead><tr>
                <th>Company</th><th>Plan</th>
                {modules.map((m) => <th key={m.key} className="center" title={m.description}>{m.label}</th>)}
                <th className="num">Users</th><th>Default look</th><th><span className="sr-only">Save</span></th>
              </tr></thead>
              <tbody>
                {list.map((c) => {
                  const d = drafts[c.id];
                  if (!d) return null;
                  const dirty = JSON.stringify(toDraft(c)) !== JSON.stringify({ ...d, modules: modules.map((m) => m.key).filter((k) => d.modules.includes(k)) });
                  return (
                    <tr key={c.id} className={c.is_active ? "" : "inactive"}>
                      <td><strong>{c.name}</strong>
                        <div className="muted small">{c.reseller_name ? `Client of ${c.reseller_name}` : "Direct client"} · since {formatDate(c.created_at)}</div></td>
                      <td>
                        <select value={d.plan} aria-label={`${c.name} plan`} onChange={(e) => choosePlan(c.id, e.target.value as PlanKey | "custom")}>
                          {plansFor(c, c.plan).map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
                          <option value="custom">Custom</option>
                        </select>
                        {c.plan === null && <div className="muted small">Before plans: all modules</div>}
                      </td>
                      {modules.map((m) => (
                        <td key={m.key} className="center">
                          <input type="checkbox" checked={d.modules.includes(m.key)} aria-label={`${c.name}: ${m.label}`}
                            onChange={() => toggle(c.id, m.key)} />
                        </td>
                      ))}
                      <td className="num">
                        <div className="seat-cell">
                          <span className={c.user_limit !== null && c.seats_used >= c.user_limit ? "overdue-text" : "muted"}>{c.seats_used} of</span>
                          <input inputMode="numeric" className="num-input seat-input" value={d.user_limit} placeholder="∞" aria-label={`${c.name} user limit`}
                            onChange={(e) => setDrafts((all) => ({ ...all, [c.id]: { ...d, plan: "custom", user_limit: e.target.value.replace(/[^0-9]/g, "") } }))} />
                        </div>
                      </td>
                      <td>
                        <select value={c.default_theme ?? "classic"} aria-label={`${c.name} default look`}
                          onChange={(e) => void setLook(c, e.target.value as Theme)}>
                          {THEMES.map((th) => <option key={th.key} value={th.key}>{th.label}</option>)}
                        </select>
                      </td>
                      <td className="row-actions">
                        <button type="button" className={dirty ? "btn btn-primary" : "btn"} disabled={!dirty || busy !== null}
                          onClick={() => void save(c)}>{busy === c.id ? "Saving…" : "Save"}</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- v0.10.0 plans are data
const BLANK_PLAN: PlanEditInput = { key: "", label: "", description: null, modules: [], user_limit: null, monthly_price: null,
  is_active: true, sort_order: 10, reseller_id: null };

function PlanCatalog({ catalog, isPlatform, onChanged }: { catalog: PlansCatalog; isPlatform: boolean; onChanged: () => void }) {
  const [editing, setEditing] = useState<PlanInfo | "new" | null>(null);
  const modules = catalog.modules;
  const describe = (p: PlanInfo) => (p.modules.length === modules.length ? "All modules"
    : p.modules.length === 0 ? "Core only" : p.modules.map((m) => modules.find((x) => x.key === m)?.label ?? m).join(", "));
  return (
    <section className="panel plan-editor">
      <div className="panel-head">
        <div>
          <h2>Plans</h2>
          <p className="muted small">{isPlatform ? "Plans for everyone, and plans you make for one reseller." : "Your own plans, next to the standard ones."}
            {" "}The company's Accountant always has the accounting tools and doesn't count as a user.</p>
        </div>
        {editing === null && <button type="button" className="btn" onClick={() => setEditing("new")}>New plan</button>}
      </div>
      {editing !== null && <PlanForm plan={editing === "new" ? null : editing} catalog={catalog} isPlatform={isPlatform}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onChanged(); }} />}
      <div className="table-wrap">
        <table className="ledger">
          <thead><tr><th>Plan</th><th>Modules</th><th className="num">Users</th><th className="num">Price / month</th><th>For</th><th><span className="sr-only">Edit</span></th></tr></thead>
          <tbody>
            {catalog.plans.map((p) => (
              <tr key={p.id ?? p.key} className={p.is_active ? "" : "inactive"}>
                <td><strong>{p.label}</strong>{!p.is_active && <span className="tag tag-plain">Off</span>}
                  {p.description && <div className="small muted">{p.description}</div>}</td>
                <td className="small">{describe(p)}</td>
                <td className="num">{p.user_limit ?? "Unlimited"}</td>
                <td className="num">{p.monthly_price !== null ? money(p.monthly_price) : "—"}</td>
                <td className="small">{p.reseller_name ?? "Everyone"}</td>
                <td className="row-actions">{p.editable && <button type="button" className="link-button" onClick={() => setEditing(p)}>Edit</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PlanForm({ plan, catalog, isPlatform, onClose, onSaved }: {
  plan: PlanInfo | null; catalog: PlansCatalog; isPlatform: boolean; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [f, setF] = useState<PlanEditInput>(() => (plan ? {
    label: plan.label, description: plan.description, modules: [...plan.modules], user_limit: plan.user_limit,
    monthly_price: plan.monthly_price, is_active: plan.is_active, sort_order: plan.sort_order, reseller_id: plan.reseller_id,
  } : BLANK_PLAN));
  const [applyAll, setApplyAll] = useState(false);
  const [resellers, setResellers] = useState<Reseller[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (isPlatform && !plan) api.resellers().then(setResellers).catch(() => setResellers([])); }, [isPlatform, plan]);

  const toggle = (m: ModuleKey) => setF((x) => ({ ...x, modules: x.modules.includes(m) ? x.modules.filter((y) => y !== m) : [...x.modules, m] }));
  const code = (f.key || f.label).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 30);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      if (plan?.id) await api.editPlan(plan.id, f, applyAll);
      else await api.createPlan({ ...f, key: code });
      toast.success(plan ? `${f.label} saved` : `Added the ${f.label} plan`);
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the plan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="role-editor" onSubmit={save}>
      <div className="grid-4">
        <label className="field"><span>Name</span>
          <input value={f.label} maxLength={60} required placeholder="e.g. Nonprofit" onChange={(e) => setF({ ...f, label: e.target.value })} /></label>
        <label className="field"><span>Users</span>
          <input inputMode="numeric" value={f.user_limit ?? ""} placeholder="Unlimited"
            onChange={(e) => setF({ ...f, user_limit: e.target.value ? Math.max(1, Number(e.target.value.replace(/\D/g, ""))) : null })} /></label>
        <label className="field"><span>Price per month (for your records)</span>
          <input inputMode="decimal" value={f.monthly_price ?? ""} placeholder="—"
            onChange={(e) => setF({ ...f, monthly_price: e.target.value ? Number(e.target.value.replace(/[^0-9.]/g, "")) : null })} /></label>
        <label className="field"><span>Order in lists</span>
          <input inputMode="numeric" value={f.sort_order} onChange={(e) => setF({ ...f, sort_order: Math.min(1000, Number(e.target.value.replace(/\D/g, "")) || 0) })} /></label>
      </div>
      <label className="field"><span>Description (optional)</span>
        <input value={f.description ?? ""} maxLength={300} onChange={(e) => setF({ ...f, description: e.target.value || null })} /></label>
      <div className="field"><span>Modules (core is always included)</span>
        <div className="module-checks">
          {catalog.modules.map((m) => (
            <label key={m.key} className="check" title={m.description}>
              <input type="checkbox" checked={f.modules.includes(m.key)} onChange={() => toggle(m.key)} />{m.label}</label>
          ))}
        </div>
      </div>
      <div className="inline-checks">
        {isPlatform && !plan && (
          <label className="field"><span>For</span>
            <select value={f.reseller_id ?? ""} onChange={(e) => setF({ ...f, reseller_id: e.target.value || null })}>
              <option value="">Everyone</option>
              {resellers.map((r) => <option key={r.id} value={r.id}>{r.name} only</option>)}
            </select></label>
        )}
        <label className="switch"><input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />
          <span>{f.is_active ? "Offered" : "Not offered to new companies"}</span></label>
        {plan && <label className="check"><input type="checkbox" checked={applyAll} onChange={(e) => setApplyAll(e.target.checked)} />
          Also update companies already on this plan</label>}
      </div>
      {!plan && f.label && <p className="hint">Code: {code}</p>}
      <div className="form-actions">
        <span className="spacer" />
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={busy || !f.label.trim() || !code}>{busy ? "Saving…" : "Save plan"}</button>
      </div>
    </form>
  );
}
