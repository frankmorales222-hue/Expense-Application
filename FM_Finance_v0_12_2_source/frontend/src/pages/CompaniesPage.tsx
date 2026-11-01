import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth, useToast } from "../context";
import { ROLE_LABEL } from "../format";
import type { CompanyListItem, PlanInfo, PlanKey, Reseller } from "../types";

export default function CompaniesPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [companies, setCompanies] = useState<CompanyListItem[]>([]);
  const [resellers, setResellers] = useState<Reseller[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const canAdd = !!user && (user.is_platform_admin || user.is_reseller_admin);

  const load = useCallback(() => {
    api.companies().then(setCompanies).catch((e: Error) => toast.error(e.message));
    if (canAdd) api.resellers().then(setResellers).catch(() => setResellers([]));
  }, [toast, canAdd]);
  useEffect(load, [load]);

  async function open(c: CompanyListItem) {
    setBusy(c.id);
    try {
      await api.switchCompany(c.id);
      window.location.assign("/");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not open the company");
      setBusy(null);
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Companies</h1>
          <p className="muted">Each company has its own books, bank accounts, categories, logo and team.</p>
        </div>
      </header>

      {companies.length === 0 ? (
        <div className="empty"><p>You don't have access to a company yet.{canAdd ? " Add one below." : " Ask an owner to add you."}</p></div>
      ) : (
        <div className="company-grid">
          {companies.map((c) => (
            <article key={c.id} className={c.is_current ? "company-card current" : "company-card"}>
              <div className="company-logo">
                {c.has_logo ? <img src={`/api/company/${c.id}/logo?v=${c.logo_version}`} alt={`${c.name} logo`} />
                  : <span aria-hidden="true">{c.name.slice(0, 1).toUpperCase()}</span>}
              </div>
              <div className="company-info">
                <h2>{c.name}</h2>
                <p className="muted">
                  {ROLE_LABEL[c.role]}{c.via_reseller ? " (through your reseller)" : ""}
                  {c.reseller_name ? <><br />Client of {c.reseller_name}</> : null}
                </p>
              </div>
              {c.is_current ? <span className="tag current-tag">Open now</span> : (
                <button type="button" className="btn" disabled={busy !== null} onClick={() => void open(c)}>
                  {busy === c.id ? "Opening…" : "Open"}
                </button>
              )}
            </article>
          ))}
        </div>
      )}

      {canAdd && <AddCompany resellers={resellers} platformAdmin={!!user?.is_platform_admin} onAdded={load} />}
    </div>
  );
}

function AddCompany({ resellers, platformAdmin, onAdded }: { resellers: Reseller[]; platformAdmin: boolean; onAdded: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [legal, setLegal] = useState("");
  const [resellerId, setResellerId] = useState("");
  const [plan, setPlan] = useState<PlanKey>("plus");
  const [plans, setPlans] = useState<PlanInfo[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.plansCatalog().then((c) => setPlans(c.plans)).catch(() => setPlans([])); }, []);
  // Plans for everyone plus the chosen reseller's own (its plan wins on the same code).
  const offered = (() => {
    const out = new Map<string, PlanInfo>();
    for (const p of plans) {
      if (p.reseller_id === null && !out.has(p.key)) out.set(p.key, p);
      if (p.reseller_id !== null && p.reseller_id === resellerId) out.set(p.key, p);
    }
    return [...out.values()].sort((a, b) => a.sort_order - b.sort_order);
  })();
  useEffect(() => {
    if (offered.length && !offered.some((p) => p.key === plan)) setPlan(offered[0]?.key ?? "plus");
  }, [offered, plan]);
  const active = resellers.filter((r) => r.is_active);
  // Reseller admins always add for their reseller; with one reseller there's nothing to choose.
  const mustPick = !platformAdmin && active.length > 1;

  useEffect(() => {
    const first = active[0];
    if (!platformAdmin && first && !resellerId) setResellerId(first.id);
  }, [platformAdmin, active, resellerId]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const c = await api.createCompany({ name: name.trim(), legal_name: legal.trim() || null, reseller_id: resellerId || null, plan });
      toast.success(`${c.name} added with the default categories. Open it to add its logo, bank accounts and team.`);
      setName(""); setLegal("");
      onAdded();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add the company");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Add a company</h2>
      <form className="inline-form flat" onSubmit={submit}>
        <label className="field grow"><span>Company name</span>
          <input value={name} maxLength={255} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Sunrise Bakery" /></label>
        <label className="field grow"><span>Legal name (optional)</span>
          <input value={legal} maxLength={255} onChange={(e) => setLegal(e.target.value)} placeholder="e.g. Sunrise Bakery LLC" /></label>
        {(platformAdmin || mustPick) && (
          <label className="field"><span>Reseller</span>
            <select value={resellerId} onChange={(e) => setResellerId(e.target.value)}>
              {platformAdmin && <option value="">None (your own client)</option>}
              {active.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select></label>
        )}
        <label className="field"><span>Plan</span>
          <select value={plan} onChange={(e) => setPlan(e.target.value as PlanKey)}>
            {offered.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select></label>
        <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>{busy ? "Adding…" : "Add company"}</button>
      </form>
      <p className="hint">{platformAdmin
        ? "You become the company's owner. For a reseller's client, the reseller's administrators can open it too."
        : "Your reseller's administrators can open this company as owners."} You can change the plan and modules any time in Plans and modules.</p>
    </section>
  );
}
