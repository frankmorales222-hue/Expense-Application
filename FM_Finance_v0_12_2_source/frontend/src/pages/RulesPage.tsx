import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth, useToast } from "../context";
import type { Choice, CompanyRules, CustomEntity, CustomField, RulesResponse, Term } from "../types";

/** v0.10.0 Company rules: everything a company may want to do its own way, in one place. Owners change it;
 * everyone else sees it read-only. Each tab saves only its own part. */

const TABS = [
  { key: "money", label: "Money and dates" },
  { key: "approvals", label: "Approvals" },
  { key: "terms", label: "Payment terms" },
  { key: "methods", label: "Payment methods" },
  { key: "fields", label: "Custom fields" },
  { key: "invoices", label: "Invoices and email" },
  { key: "banking", label: "Banking and dashboard" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

const ENTITY_LABEL: Record<CustomEntity, string> = {
  customer: "Customers", item: "Products and services", invoice: "Invoices", bill: "Bills", expense: "Expenses",
};
const TYPE_LABEL: Record<CustomField["type"], string> = {
  text: "Text", number: "Number", date: "Date", choice: "List of choices", yes_no: "Yes / no",
};
const LABEL_NAMES: Record<string, string> = {
  invoice_title: "Document title", invoice_no: "Invoice number", invoice_date: "Invoice date", due_date: "Due date",
  terms: "Terms", bill_to: "Bill to", balance_due: "Balance due", total: "Total", payments: "Payments received",
  message: "Message", payment_instructions: "Payment instructions", col_date: "Date column", col_item: "Product column",
  col_description: "Description column", col_qty: "Quantity column", col_rate: "Rate column", col_amount: "Amount column",
  paid_stamp: "Paid stamp", void_stamp: "Void stamp", page: "Page",
};

/** A code made from a name: "Net 45 (EOM)" -> "net_45_eom", unique among existing codes. */
export function makeCode(name: string, taken: string[]): string {
  const base = name.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "").slice(0, 17) || "item";
  let code = base;
  for (let i = 2; taken.includes(code); i++) code = `${base.slice(0, 17)}_${i}`;
  return code;
}

export default function RulesPage() {
  const { user, rules: loaded, setRules } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.key === params.get("tab"))?.key ?? "money") as TabKey;
  const [data, setData] = useState<RulesResponse | null>(loaded);
  const [draft, setDraft] = useState<CompanyRules | null>(loaded?.rules ?? null);
  const [currency, setCurrency] = useState(loaded?.currency ?? "USD");
  const [saving, setSaving] = useState(false);
  const canEdit = user?.company_role === "owner" && (user.permissions?.settings ?? "full") === "full";

  useEffect(() => {
    api.rules().then((r) => { setData(r); setDraft(r.rules); setCurrency(r.currency); })
      .catch((e: Error) => toast.error(e.message));
  }, [toast]);

  const dirty = useMemo(() => !!data && !!draft &&
    (JSON.stringify(data.rules) !== JSON.stringify(draft) || data.currency !== currency), [data, draft, currency]);

  if (!data || !draft) return <div className="page"><p className="muted">Loading…</p></div>;

  const patch = (p: Partial<CompanyRules>) => setDraft((d) => (d ? { ...d, ...p } : d));

  async function save() {
    if (!draft || !data) return;
    setSaving(true);
    try {
      // Send only what changed; the server keeps the rest.
      const changed: Partial<CompanyRules> = {};
      for (const k of Object.keys(draft) as (keyof CompanyRules)[]) {
        if (JSON.stringify(draft[k]) !== JSON.stringify(data.rules[k])) (changed as Record<string, unknown>)[k] = draft[k];
      }
      const r = await api.saveRules(changed, currency !== data.currency ? currency : undefined);
      setData(r); setDraft(r.rules); setCurrency(r.currency); setRules(r);
      toast.success("Rules saved. Every screen uses them now.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the rules");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page rules-page">
      <header className="page-head">
        <div>
          <Link to="/settings" className="back">Settings</Link>
          <h1>Company rules</h1>
          <p className="page-sub">How {user?.company_name} works: its terms, payment methods, approvals, formats and
            the extra details it keeps. Other companies keep their own.</p>
        </div>
        {canEdit && (
          <div className="head-actions">
            {dirty && <button type="button" className="btn" onClick={() => { setDraft(data.rules); setCurrency(data.currency); }}>Undo changes</button>}
            <button type="button" className="btn btn-primary" disabled={!dirty || saving} onClick={() => void save()}>
              {saving ? "Saving…" : "Save rules"}</button>
          </div>
        )}
      </header>
      {!canEdit && <div className="callout">Only the company owner can change these. You can see them here.</div>}

      <div className="tabs rules-tabs" role="tablist" aria-label="Rule groups">
        {TABS.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key}
            className={tab === t.key ? "tab active" : "tab"} onClick={() => setParams({ tab: t.key }, { replace: true })}>
            {t.label}
          </button>
        ))}
      </div>

      <fieldset className="rules-body" disabled={!canEdit}>
        {tab === "money" && <MoneyTab draft={draft} patch={patch} currency={currency} setCurrency={setCurrency} symbols={data.currency_symbols} />}
        {tab === "approvals" && <ApprovalsTab draft={draft} patch={patch} />}
        {tab === "terms" && <TermsTab draft={draft} patch={patch} saved={data.rules.terms} />}
        {tab === "methods" && <MethodsTab draft={draft} patch={patch} saved={data.rules} />}
        {tab === "fields" && <FieldsTab draft={draft} patch={patch} saved={data.rules.custom_fields} />}
        {tab === "invoices" && <InvoicesTab draft={draft} patch={patch} labels={data.labels_default} placeholders={data.email_placeholders} />}
        {tab === "banking" && <BankingTab draft={draft} patch={patch} />}
      </fieldset>
      {canEdit && dirty && (
        <div className="save-bar" role="status">
          <span>You have unsaved changes.</span>
          <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void save()}>{saving ? "Saving…" : "Save rules"}</button>
        </div>
      )}
    </div>
  );
}

interface TabProps { draft: CompanyRules; patch: (p: Partial<CompanyRules>) => void }

function Section({ title, hint, children }: { title: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {hint && <p className="muted">{hint}</p>}
      {children}
    </section>
  );
}

// ---------------------------------------------------------------- money and dates
function MoneyTab({ draft, patch, currency, setCurrency, symbols }: TabProps & {
  currency: string; setCurrency: (c: string) => void; symbols: Record<string, string>;
}) {
  const known = Object.keys(symbols);
  const symbol = draft.currency_symbol ?? symbols[currency] ?? `${currency} `;
  const [g, d] = ({ "1,234.56": [",", "."], "1.234,56": [".", ","], "1 234,56": [" ", ","], "1'234.56": ["'", "."] } as const)[draft.number_format];
  const sample = `${symbol}12${g}345${d}67`;
  const date = draft.date_format.replace("YYYY", "2026").replace("MM", "10").replace("DD", "31");
  return (
    <Section title="Money and dates" hint="Used on every screen, report, PDF invoice and email for this company.">
      <div className="grid-3">
        <label className="field"><span>Currency</span>
          <select value={known.includes(currency) ? currency : "__other"} onChange={(e) => e.target.value !== "__other" && setCurrency(e.target.value)}>
            {known.map((c) => <option key={c} value={c}>{c} ({symbols[c]?.trim()})</option>)}
            <option value="__other">Other…</option>
          </select></label>
        {!known.includes(currency) || currency === "" ? (
          <label className="field"><span>Currency code (3 letters)</span>
            <input value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase().replace(/[^A-Z]/g, ""))} /></label>
        ) : <span />}
        <label className="field"><span>Symbol shown</span>
          <input value={draft.currency_symbol ?? ""} maxLength={6} placeholder={(symbols[currency] ?? currency).trim()}
            onChange={(e) => patch({ currency_symbol: e.target.value || null })} /></label>
      </div>
      <div className="grid-3">
        <label className="field"><span>Numbers</span>
          <select value={draft.number_format} onChange={(e) => patch({ number_format: e.target.value as CompanyRules["number_format"] })}>
            <option value="1,234.56">1,234.56</option><option value="1.234,56">1.234,56</option>
            <option value="1 234,56">1 234,56</option><option value="1'234.56">1'234.56</option>
          </select></label>
        <label className="field"><span>Dates</span>
          <select value={draft.date_format} onChange={(e) => patch({ date_format: e.target.value as CompanyRules["date_format"] })}>
            <option value="MM/DD/YYYY">MM/DD/YYYY</option><option value="DD/MM/YYYY">DD/MM/YYYY</option>
            <option value="YYYY-MM-DD">YYYY-MM-DD</option><option value="DD.MM.YYYY">DD.MM.YYYY</option>
          </select></label>
        <div className="static-field"><span>Looks like</span><strong className="num">{sample}</strong><span className="muted">{date}</span></div>
      </div>
      <p className="hint">Changing the currency doesn't convert amounts already entered; it changes how they're shown.</p>
    </Section>
  );
}

// ---------------------------------------------------------------- approvals
function ApprovalsTab({ draft, patch }: TabProps) {
  return (
    <Section title="Expense approvals" hint={<>Whether expenses need an owner or accountant to approve them. Each category can
      set its own amount in <Link to="/settings">Settings › Categories</Link>.</>}>
      <label className="switch">
        <input type="checkbox" checked={draft.approvals_required} onChange={(e) => patch({ approvals_required: e.target.checked })} />
        <span>{draft.approvals_required ? "Expenses need approval" : "Expenses are approved when saved"}</span>
      </label>
      {draft.approvals_required && (
        <label className="field narrow-field"><span>From this amount (unless the category says otherwise)</span>
          <input inputMode="decimal" value={String(draft.approval_threshold)}
            onChange={(e) => patch({ approval_threshold: e.target.value.replace(/[^0-9.]/g, "") })} /></label>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------- payment terms
function TermsTab({ draft, patch, saved }: TabProps & { saved: Term[] }) {
  const savedCodes = saved.map((t) => t.code);
  const setTerm = (i: number, p: Partial<Term>) => patch({ terms: draft.terms.map((t, j) => (j === i ? { ...t, ...p } : t)) });
  function add() {
    const name = "New term";
    patch({ terms: [...draft.terms, { code: makeCode(name, draft.terms.map((t) => t.code)), name, kind: "days", days: 30, day: null, active: true }] });
  }
  const active = draft.terms.filter((t) => t.active);
  return (
    <>
      <Section title="Payment terms" hint="When invoices and bills are due. Terms already used can be turned off but not deleted, so old records still read correctly.">
        <div className="table-wrap">
          <table className="ledger rules-table">
            <thead><tr><th>Name</th><th>Due</th><th className="num">Days</th><th>Active</th><th><span className="sr-only">Remove</span></th></tr></thead>
            <tbody>
              {draft.terms.map((t, i) => (
                <tr key={t.code}>
                  <td><input className="cell-input" value={t.name} maxLength={40} aria-label="Term name"
                    onChange={(e) => setTerm(i, savedCodes.includes(t.code) ? { name: e.target.value }
                      : { name: e.target.value, code: makeCode(e.target.value, draft.terms.filter((_, j) => j !== i).map((x) => x.code)) })} />
                    <small className="muted code-hint">{t.code}</small></td>
                  <td><select className="cell-input" value={t.kind} aria-label="How the due date is worked out"
                    onChange={(e) => setTerm(i, { kind: e.target.value as Term["kind"], day: e.target.value === "day_of_next_month" ? (t.day ?? 10) : null })}>
                    <option value="days">Days after the date</option>
                    <option value="end_of_month">End of the month, plus days</option>
                    <option value="day_of_next_month">A day of next month</option>
                  </select></td>
                  <td className="num">{t.kind === "day_of_next_month"
                    ? <input className="cell-input num-input" inputMode="numeric" value={t.day ?? ""} aria-label="Day of the month"
                        onChange={(e) => setTerm(i, { day: Math.min(31, Math.max(1, Number(e.target.value) || 1)) })} />
                    : <input className="cell-input num-input" inputMode="numeric" value={t.days} aria-label="Days"
                        onChange={(e) => setTerm(i, { days: Math.min(365, Math.max(0, Number(e.target.value) || 0)) })} />}</td>
                  <td><input type="checkbox" checked={t.active} aria-label={`${t.name} active`} onChange={(e) => setTerm(i, { active: e.target.checked })} /></td>
                  <td>{!savedCodes.includes(t.code) && (
                    <button type="button" className="link-button danger" onClick={() => patch({ terms: draft.terms.filter((_, j) => j !== i) })}>Remove</button>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button type="button" className="btn btn-small" onClick={add}>Add a term</button>
      </Section>
      <Section title="Defaults">
        <div className="grid-2">
          <label className="field"><span>New invoices (when the customer has none)</span>
            <select value={draft.default_terms ?? ""} onChange={(e) => patch({ default_terms: e.target.value || null })}>
              <option value="">Net 30 (built in)</option>
              {active.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
            </select></label>
          <label className="field"><span>New bills</span>
            <select value={draft.bill_default_terms ?? ""} onChange={(e) => patch({ bill_default_terms: e.target.value || null })}>
              <option value="">Net 30 (built in)</option>
              {active.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
            </select></label>
        </div>
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- payment methods
function MethodsTab({ draft, patch, saved }: TabProps & { saved: CompanyRules }) {
  return (
    <div className="two-col">
      <ChoiceList title="Paying for expenses" hint="How the business pays (on the expense form)."
        items={draft.expense_methods} savedCodes={saved.expense_methods.map((c) => c.code)}
        onChange={(expense_methods) => patch({ expense_methods })} />
      <ChoiceList title="Receiving payments" hint="How customers pay you (on Receive payment)."
        items={draft.received_methods} savedCodes={saved.received_methods.map((c) => c.code)}
        onChange={(received_methods) => patch({ received_methods })} />
    </div>
  );
}

function ChoiceList({ title, hint, items, savedCodes, onChange }: {
  title: string; hint: string; items: Choice[]; savedCodes: string[]; onChange: (c: Choice[]) => void;
}) {
  const [label, setLabel] = useState("");
  const set = (i: number, p: Partial<Choice>) => onChange(items.map((c, j) => (j === i ? { ...c, ...p } : c)));
  return (
    <Section title={title} hint={hint}>
      <ul className="choice-list">
        {items.map((c, i) => (
          <li key={c.code} className={c.active ? "" : "inactive"}>
            <input className="cell-input" value={c.label} maxLength={60} aria-label="Name" onChange={(e) => set(i, { label: e.target.value })} />
            <label className="check small"><input type="checkbox" checked={c.active} onChange={(e) => set(i, { active: e.target.checked })} />Active</label>
            {!savedCodes.includes(c.code) && <button type="button" className="link-button danger" onClick={() => onChange(items.filter((_, j) => j !== i))}>Remove</button>}
          </li>
        ))}
      </ul>
      <form className="inline-form" onSubmit={(e) => {
        e.preventDefault();
        if (!label.trim()) return;
        onChange([...items, { code: makeCode(label, items.map((c) => c.code)), label: label.trim(), active: true }]);
        setLabel("");
      }}>
        <label className="field grow"><span>Add</span><input value={label} maxLength={60} placeholder="e.g. Zelle" onChange={(e) => setLabel(e.target.value)} /></label>
        <button type="submit" className="btn" disabled={!label.trim()}>Add</button>
      </form>
    </Section>
  );
}

// ---------------------------------------------------------------- custom fields
const BLANK_FIELD: CustomField = { code: "", label: "", entity: "invoice", type: "text", options: [], required: false, print_on_invoice: false, active: true };

function FieldsTab({ draft, patch, saved }: TabProps & { saved: CustomField[] }) {
  const savedCodes = saved.map((f) => f.code);
  const [adding, setAdding] = useState<CustomField>(BLANK_FIELD);
  const [optionsText, setOptionsText] = useState("");
  const setField = (code: string, p: Partial<CustomField>) =>
    patch({ custom_fields: draft.custom_fields.map((f) => (f.code === code ? { ...f, ...p } : f)) });

  function add() {
    if (!adding.label.trim()) return;
    const options = optionsText.split(/[,\n]/).map((o) => o.trim()).filter(Boolean);
    const field = { ...adding, label: adding.label.trim(), options, code: makeCode(adding.label, draft.custom_fields.map((f) => f.code)) };
    patch({ custom_fields: [...draft.custom_fields, field] });
    setAdding({ ...BLANK_FIELD, entity: adding.entity });
    setOptionsText("");
  }

  const printable = adding.entity === "invoice" || adding.entity === "customer";
  return (
    <>
      <Section title="Custom fields" hint="Extra details your company keeps: a PO number on invoices, a license plate on expenses, a region on customers. They show on the form, and invoice and customer fields can print on the PDF.">
        {(Object.keys(ENTITY_LABEL) as CustomEntity[]).map((entity) => {
          const list = draft.custom_fields.filter((f) => f.entity === entity);
          if (!list.length) return null;
          return (
            <div key={entity} className="field-group">
              <h3>{ENTITY_LABEL[entity]}</h3>
              <div className="table-wrap">
                <table className="ledger rules-table">
                  <thead><tr><th>Label</th><th>Type</th><th>Required</th>{(entity === "invoice" || entity === "customer") && <th>On the PDF</th>}<th>Active</th><th><span className="sr-only">Remove</span></th></tr></thead>
                  <tbody>
                    {list.map((f) => (
                      <tr key={f.code} className={f.active ? "" : "inactive"}>
                        <td><input className="cell-input" value={f.label} maxLength={60} aria-label="Label" onChange={(e) => setField(f.code, { label: e.target.value })} />
                          {f.type === "choice" && <small className="muted code-hint">{f.options.join(" · ")}</small>}</td>
                        <td>{TYPE_LABEL[f.type]}</td>
                        <td><input type="checkbox" checked={f.required} aria-label="Required" onChange={(e) => setField(f.code, { required: e.target.checked })} /></td>
                        {(entity === "invoice" || entity === "customer") && <td><input type="checkbox" checked={f.print_on_invoice} aria-label="Print on invoice"
                          onChange={(e) => setField(f.code, { print_on_invoice: e.target.checked })} /></td>}
                        <td><input type="checkbox" checked={f.active} aria-label="Active" onChange={(e) => setField(f.code, { active: e.target.checked })} /></td>
                        <td>{!savedCodes.includes(f.code) && <button type="button" className="link-button danger"
                          onClick={() => patch({ custom_fields: draft.custom_fields.filter((x) => x.code !== f.code) })}>Remove</button>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
        {draft.custom_fields.length === 0 && <p className="empty-note">No custom fields yet.</p>}
      </Section>
      <Section title="Add a field">
        <div className="grid-3">
          <label className="field"><span>On</span>
            <select value={adding.entity} onChange={(e) => setAdding({ ...adding, entity: e.target.value as CustomEntity, print_on_invoice: false })}>
              {(Object.keys(ENTITY_LABEL) as CustomEntity[]).map((k) => <option key={k} value={k}>{ENTITY_LABEL[k]}</option>)}
            </select></label>
          <label className="field"><span>Label</span>
            <input value={adding.label} maxLength={60} placeholder="e.g. PO number" onChange={(e) => setAdding({ ...adding, label: e.target.value })} /></label>
          <label className="field"><span>Type</span>
            <select value={adding.type} onChange={(e) => setAdding({ ...adding, type: e.target.value as CustomField["type"] })}>
              {Object.entries(TYPE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select></label>
        </div>
        {adding.type === "choice" && (
          <label className="field"><span>Choices (separate with commas)</span>
            <input value={optionsText} placeholder="North, South, East, West" onChange={(e) => setOptionsText(e.target.value)} /></label>
        )}
        <div className="inline-checks">
          <label className="check"><input type="checkbox" checked={adding.required} onChange={(e) => setAdding({ ...adding, required: e.target.checked })} />Required</label>
          {printable && <label className="check"><input type="checkbox" checked={adding.print_on_invoice}
            onChange={(e) => setAdding({ ...adding, print_on_invoice: e.target.checked })} />Print on the invoice PDF</label>}
          <span className="spacer" />
          <button type="button" className="btn" disabled={!adding.label.trim() || (adding.type === "choice" && !optionsText.trim())} onClick={add}>Add field</button>
        </div>
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- invoices and email
function InvoicesTab({ draft, patch, labels, placeholders }: TabProps & { labels: Record<string, string>; placeholders: string[] }) {
  const setLabel = (k: string, v: string) => {
    const next = { ...draft.pdf_labels };
    if (v.trim()) next[k] = v; else delete next[k];
    patch({ pdf_labels: next });
  };
  const nextNo = `${draft.invoice_prefix}${draft.next_invoice_number ?? "1001"}`;
  return (
    <>
      <Section title="Numbering">
        <div className="grid-3">
          <label className="field"><span>Prefix</span>
            <input value={draft.invoice_prefix} maxLength={10} placeholder="e.g. FM-" onChange={(e) => patch({ invoice_prefix: e.target.value })} /></label>
          <label className="field"><span>Next number</span>
            <input inputMode="numeric" value={draft.next_invoice_number ?? ""} placeholder="After the last one"
              onChange={(e) => patch({ next_invoice_number: e.target.value ? Math.max(1, Number(e.target.value.replace(/\D/g, ""))) : null })} /></label>
          <div className="static-field"><span>Next invoice</span><strong>{nextNo}</strong></div>
        </div>
      </Section>
      <Section title="Invoice PDF" hint="Rename anything printed on the invoice, for example FACTURA or TAX INVOICE. Leave a box empty to keep the standard wording.">
        <label className="field color-field"><span>Accent color</span>
          <span className="color-row"><input type="color" value={draft.pdf_accent} onChange={(e) => patch({ pdf_accent: e.target.value.toUpperCase() })} />
            <input value={draft.pdf_accent} maxLength={7} aria-label="Accent color code" onChange={(e) => patch({ pdf_accent: e.target.value })} /></span></label>
        <div className="label-grid">
          {Object.entries(labels).map(([k, standard]) => (
            <label key={k} className="field"><span>{LABEL_NAMES[k] ?? k.replace(/_/g, " ")}</span>
              <input value={draft.pdf_labels[k] ?? ""} maxLength={40} placeholder={standard} onChange={(e) => setLabel(k, e.target.value)} /></label>
          ))}
        </div>
      </Section>
      <Section title="Invoice email" hint={<>The message that goes with each invoice. You can still change it before sending. Words in braces are filled in:
        {" "}{placeholders.map((p) => <code key={p} className="ph">{`{${p}}`}</code>)}</>}>
        <label className="field"><span>Subject</span>
          <input value={draft.email_subject} maxLength={200} onChange={(e) => patch({ email_subject: e.target.value })} /></label>
        <label className="field"><span>Message</span>
          <textarea rows={8} value={draft.email_body} maxLength={5000} onChange={(e) => patch({ email_body: e.target.value })} /></label>
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- banking and dashboard
function BankingTab({ draft, patch }: TabProps) {
  return (
    <>
      <Section title="Banking" hint={<>How sure the app must be before <strong>Approve all</strong> takes a suggestion. Your own
        <Link to="/banking/rules"> bank rules</Link> count as 100% sure.</>}>
        <label className="field range-field"><span>Approve all at {draft.auto_approve_confidence}% sure or more</span>
          <input type="range" min={50} max={100} step={5} value={draft.auto_approve_confidence}
            onChange={(e) => patch({ auto_approve_confidence: Number(e.target.value) })} /></label>
      </Section>
      <Section title="Dashboard">
        <div className="grid-2">
          <label className="field"><span>Cash forecast looks ahead</span>
            <select value={draft.forecast_days} onChange={(e) => patch({ forecast_days: Number(e.target.value) as CompanyRules["forecast_days"] })}>
              {[14, 30, 60, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
            </select></label>
          <label className="field"><span>"Coming up" shows the next</span>
            <select value={draft.coming_up_days} onChange={(e) => patch({ coming_up_days: Number(e.target.value) as CompanyRules["coming_up_days"] })}>
              {[7, 14, 30, 60].map((d) => <option key={d} value={d}>{d} days</option>)}
            </select></label>
        </div>
      </Section>
    </>
  );
}
