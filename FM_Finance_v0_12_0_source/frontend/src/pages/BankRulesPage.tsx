import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import { useAuth, useToast } from "../context";
import { currencySymbol, money } from "../format";
import type { Account, BankRule, BankRuleInput, Category, Customer } from "../types";

/** v0.10.0: the company's own rules for bank transactions, checked before the app's own suggestions. */

const MATCH_LABEL: Record<BankRuleInput["match_type"], string> = {
  contains: "contains", starts_with: "starts with", equals: "is exactly", not_contains: "doesn't contain",
};
const DIRECTION_LABEL: Record<BankRuleInput["direction"], string> = {
  any: "Money in or out", out: "Money out", in: "Money in",
};

const BLANK: BankRuleInput = {
  name: "", priority: 100, is_active: true, match_type: "contains", match_text: "", direction: "out",
  amount_min: null, amount_max: null, account_id: null, category_id: null, vendor_name: null, customer_id: null,
  memo: null, auto_approve: false,
};

export default function BankRulesPage() {
  const toast = useToast();
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "approver";
  const [rules, setRules] = useState<BankRule[] | null>(null);
  const [cats, setCats] = useState<Category[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [editing, setEditing] = useState<BankRule | "new" | null>(null);
  const [removing, setRemoving] = useState<BankRule | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(() => {
    api.bankRules().then(setRules).catch((e: Error) => toast.error(e.message));
  }, [toast]);
  useEffect(() => {
    load();
    api.categories().then(setCats).catch(() => setCats([]));
    api.accounts().then(setAccounts).catch(() => setAccounts([]));
    api.customers().then(setCustomers).catch(() => setCustomers([]));
  }, [load]);

  async function run() {
    setRunning(true);
    try {
      const r = await api.applyBankRules();
      toast.success(r.matched === 0 ? "No waiting transactions match your rules."
        : `${r.matched} matched${r.approved ? `, ${r.approved} approved automatically` : ""}.`);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not run the rules");
    } finally {
      setRunning(false);
    }
  }

  const waiting = (rules ?? []).reduce((s, r) => s + (r.is_active ? r.would_match : 0), 0);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <Link to="/banking" className="back">Banking</Link>
          <h1>Bank rules</h1>
          <p className="page-sub">Tell the app how to handle transactions you see every month. Your rules come before its own
            suggestions, top to bottom; the first one that fits wins.</p>
        </div>
        {canEdit && (
          <div className="head-actions">
            <button type="button" className="btn" disabled={running || waiting === 0} onClick={() => void run()}>
              {running ? "Running…" : `Run on waiting${waiting ? ` (${waiting})` : ""}`}</button>
            <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>New rule</button>
          </div>
        )}
      </header>

      {editing && (
        <RuleForm rule={editing === "new" ? null : editing} cats={cats} accounts={accounts} customers={customers}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />
      )}

      <section className="panel flush">
        {rules === null ? <p className="muted padded">Loading…</p> : rules.length === 0 ? (
          <div className="empty inner">
            <p><strong>No rules yet.</strong></p>
            <p className="muted">Example: when the description contains <em>ADP</em> and money goes out, put it in Payroll and approve it.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="ledger bank-rules">
              <thead><tr><th className="num">#</th><th>Rule</th><th>When</th><th>Then</th><th className="num">Used</th><th className="num">Waiting</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id} className={r.is_active ? "" : "inactive"}>
                    <td className="num muted">{r.priority}</td>
                    <td><strong>{r.name}</strong>{!r.is_active && <span className="tag tag-plain">Off</span>}</td>
                    <td className="small">
                      Description {MATCH_LABEL[r.match_type]} <q>{r.match_text}</q>
                      <div className="muted">{DIRECTION_LABEL[r.direction]}
                        {r.amount_min !== null && ` · from ${money(r.amount_min)}`}{r.amount_max !== null && ` · up to ${money(r.amount_max)}`}
                        {r.account_name && ` · ${r.account_name}`}</div>
                    </td>
                    <td className="small">
                      {[r.category_name, r.vendor_name && `Payee ${r.vendor_name}`, r.customer_name && `Customer ${r.customer_name}`].filter(Boolean).join(" · ")}
                      {r.auto_approve && <div><span className="chip">Approves automatically</span></div>}
                    </td>
                    <td className="num">{r.times_used}</td>
                    <td className="num">{r.would_match || "—"}</td>
                    <td className="row-actions">{canEdit && <>
                      <button type="button" className="link-button" onClick={() => setEditing(r)}>Edit</button>
                      <button type="button" className="link-button danger" onClick={() => setRemoving(r)}>Delete</button>
                    </>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <ConfirmDialog open={removing !== null} title={`Delete the rule "${removing?.name ?? ""}"?`} confirmLabel="Delete rule" danger
        message="Transactions it already handled stay as they are."
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          if (!removing) return;
          api.deleteBankRule(removing.id).then(() => { toast.success("Rule deleted"); load(); })
            .catch((e: Error) => toast.error(e.message)).finally(() => setRemoving(null));
        }} />
    </div>
  );
}

function RuleForm({ rule, cats, accounts, customers, onClose, onSaved }: {
  rule: BankRule | null; cats: Category[]; accounts: Account[]; customers: Customer[]; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [f, setF] = useState<BankRuleInput>(() => (rule ? { ...BLANK, ...rule } : BLANK));
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof BankRuleInput>(k: K, v: BankRuleInput[K]) => setF((x) => ({ ...x, [k]: v }));
  const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(/[^0-9.]/g, "")));
  const sym = currencySymbol().trim();

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const body = { ...f, name: f.name.trim() || f.match_text.trim() };
      if (rule) await api.updateBankRule(rule.id, body); else await api.createBankRule(body);
      toast.success(rule ? "Rule saved" : "Rule added. New transactions will use it.");
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the rule");
    } finally {
      setBusy(false);
    }
  }

  const ready = f.match_text.trim() && (f.category_id || f.vendor_name?.trim() || f.customer_id);
  return (
    <section className="panel rule-form">
      <h2>{rule ? `Edit ${rule.name}` : "New bank rule"}</h2>
      <form onSubmit={save} className="stack-form">
        <fieldset>
          <legend>When a transaction</legend>
          <div className="grid-3">
            <label className="field"><span>Description</span>
              <select value={f.match_type} onChange={(e) => set("match_type", e.target.value as BankRuleInput["match_type"])}>
                {Object.entries(MATCH_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select></label>
            <label className="field span-2"><span>Text</span>
              <input value={f.match_text} maxLength={200} required placeholder="e.g. ADP PAYROLL" onChange={(e) => set("match_text", e.target.value)} /></label>
          </div>
          <div className="grid-4">
            <label className="field"><span>Direction</span>
              <select value={f.direction} onChange={(e) => set("direction", e.target.value as BankRuleInput["direction"])}>
                {Object.entries(DIRECTION_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select></label>
            <label className="field"><span>Amount from</span>
              <div className="money-input"><span>{sym}</span><input inputMode="decimal" value={f.amount_min ?? ""} onChange={(e) => set("amount_min", num(e.target.value))} /></div></label>
            <label className="field"><span>Amount up to</span>
              <div className="money-input"><span>{sym}</span><input inputMode="decimal" value={f.amount_max ?? ""} onChange={(e) => set("amount_max", num(e.target.value))} /></div></label>
            <label className="field"><span>In account</span>
              <select value={f.account_id ?? ""} onChange={(e) => set("account_id", e.target.value || null)}>
                <option value="">Any account</option>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select></label>
          </div>
        </fieldset>
        <fieldset>
          <legend>Then</legend>
          <div className="grid-3">
            <label className="field"><span>Category</span>
              <select value={f.category_id ?? ""} onChange={(e) => set("category_id", e.target.value || null)}>
                <option value="">Don't set</option>
                {cats.filter((c) => c.is_active || c.id === f.category_id).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select></label>
            <label className="field"><span>Payee</span>
              <input value={f.vendor_name ?? ""} maxLength={255} placeholder="e.g. ADP" onChange={(e) => set("vendor_name", e.target.value || null)} /></label>
            <label className="field"><span>Customer (money in)</span>
              <select value={f.customer_id ?? ""} onChange={(e) => set("customer_id", e.target.value || null)}>
                <option value="">Don't set</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select></label>
          </div>
          <label className="field"><span>Memo (optional)</span>
            <input value={f.memo ?? ""} maxLength={500} onChange={(e) => set("memo", e.target.value || null)} /></label>
          <label className="check"><input type="checkbox" checked={f.auto_approve} onChange={(e) => set("auto_approve", e.target.checked)} />
            Approve it automatically (it goes straight to the books)</label>
        </fieldset>
        <div className="grid-3">
          <label className="field"><span>Rule name</span>
            <input value={f.name} maxLength={100} placeholder={f.match_text || "e.g. Payroll"} onChange={(e) => set("name", e.target.value)} /></label>
          <label className="field"><span>Order (lower runs first)</span>
            <input inputMode="numeric" value={f.priority} onChange={(e) => set("priority", Math.max(1, Number(e.target.value) || 1))} /></label>
          <label className="switch"><input type="checkbox" checked={f.is_active} onChange={(e) => set("is_active", e.target.checked)} />
            <span>{f.is_active ? "On" : "Off"}</span></label>
        </div>
        <div className="form-actions">
          <span className="spacer" />
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !ready}>{busy ? "Saving…" : "Save rule"}</button>
        </div>
        {!ready && f.match_text.trim() && <p className="hint">Choose a category, payee or customer for the rule to set.</p>}
      </form>
    </section>
  );
}
