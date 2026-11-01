import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ModuleNotice, useModule } from "../modules";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import { useAuth, useToast } from "../context";
import { currencySymbol, formatDate, money, today } from "../format";
import type { Customer, JournalEntry, LedgerAccount } from "../types";
import { TYPE_LABEL, sourceLabel, sourceLink } from "./ChartOfAccountsPage";

export default function JournalPage() {
  const { id } = useParams();
  return id ? <JournalEditor id={id === "new" ? null : id} /> : <JournalList />;
}

function JournalList() {
  const { user } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [source, setSource] = useState<"manual" | "all">("manual");
  const [entries, setEntries] = useState<JournalEntry[] | null>(null);
  const { on } = useModule("advanced_accounting");
  const canEdit = (user?.role === "admin" || user?.role === "approver") && on;

  useEffect(() => {
    setEntries(null);
    api.journal(source).then(setEntries).catch((e: Error) => toast.error(e.message));
  }, [source, toast]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Journal entries</h1>
          <p className="muted">Adjustments your accountant makes by hand: depreciation, owner contributions, loan payments, corrections.
            Everything else is recorded for you from expenses, bills and Banking.</p>
        </div>
        {canEdit && <Link className="btn btn-primary" to="/journal/new">New journal entry</Link>}
      </header>

      <ModuleNotice module="advanced_accounting" />
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={source === "manual"} className={source === "manual" ? "tab active" : "tab"}
          onClick={() => setSource("manual")}>Journal entries</button>
        <button type="button" role="tab" aria-selected={source === "all"} className={source === "all" ? "tab active" : "tab"}
          onClick={() => setSource("all")}>All activity</button>
      </div>

      <section className="panel flush">
        {entries === null ? <div className="empty inner"><p className="muted">Loading…</p></div>
          : entries.length === 0 ? (
            <div className="empty inner"><p>{source === "manual" ? "No journal entries yet." : "Nothing has been recorded yet."}</p></div>
          ) : (
            <div className="table-wrap">
              <table className="ledger">
                <thead><tr><th>Date</th><th>Type</th><th>No.</th><th>Memo</th><th>Accounts</th><th className="num">Amount</th></tr></thead>
                <tbody>
                  {entries.map((e) => {
                    const link = sourceLink(e.source_type, e.source_id, e.id);
                    return (
                      <tr key={e.id} className={link ? "" : "no-link"} onClick={() => link && navigate(link)}>
                        <td className="nowrap">{formatDate(e.entry_date)}</td>
                        <td><span className="tag tag-plain">{sourceLabel(e.source_type)}</span></td>
                        <td>{e.number ?? ""}</td>
                        <td>{e.memo ?? <span className="muted">No memo</span>}</td>
                        <td className="muted">{[...new Set(e.lines.map((l) => l.account_name))].slice(0, 3).join(", ")}
                          {new Set(e.lines.map((l) => l.account_name)).size > 3 ? "…" : ""}</td>
                        <td className="num">{money(e.total)}</td>
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

interface Row { key: number; account_id: string; debit: string; credit: string; description: string; customer_id: string; vendor_name: string }
let nextKey = 1;
const blank = (): Row => ({ key: nextKey++, account_id: "", debit: "", credit: "", description: "", customer_id: "", vendor_name: "" });
const num = (s: string) => Number(s) || 0;
const cents = (n: number) => Math.round(n * 100);
const ORDER = ["asset", "liability", "equity", "income", "expense"] as const;

function JournalEditor({ id }: { id: string | null }) {
  const { user } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const { on } = useModule("advanced_accounting");
  const canEdit = (user?.role === "admin" || user?.role === "approver") && on;
  const [accounts, setAccounts] = useState<LedgerAccount[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [date, setDate] = useState(today());
  const [number, setNumber] = useState("");
  const [memo, setMemo] = useState("");
  const [rows, setRows] = useState<Row[]>([blank(), blank()]);
  const [loaded, setLoaded] = useState(id === null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    api.ledgerAccounts(true).then(setAccounts).catch((e: Error) => toast.error(e.message));
    api.customers().then(setCustomers).catch(() => setCustomers([]));
  }, [toast]);
  useEffect(() => {
    if (!id) return;
    api.getJournal(id).then((e) => {
      setDate(e.entry_date); setNumber(e.number ?? ""); setMemo(e.memo ?? "");
      setRows(e.lines.map((l) => ({
        key: nextKey++, account_id: l.account_id, debit: l.debit ? l.debit.toFixed(2) : "", credit: l.credit ? l.credit.toFixed(2) : "",
        description: l.description ?? "", customer_id: l.customer_id ?? "", vendor_name: l.vendor_name ?? "",
      })));
      setLoaded(true);
    }).catch((e: Error) => toast.error(e.message));
  }, [id, toast]);

  const debits = rows.reduce((s, r) => s + cents(num(r.debit)), 0);
  const credits = rows.reduce((s, r) => s + cents(num(r.credit)), 0);
  const used = rows.filter((r) => r.account_id || r.debit || r.credit || r.description);
  const problems = useMemo(() => {
    const p: string[] = [];
    if (used.length < 2) p.push("A journal entry needs at least two lines.");
    if (used.some((r) => !r.account_id)) p.push("Choose an account on every line.");
    if (used.some((r) => num(r.debit) > 0 && num(r.credit) > 0)) p.push("A line can have a debit or a credit, not both.");
    if (used.some((r) => num(r.debit) <= 0 && num(r.credit) <= 0)) p.push("Every line needs a debit or a credit amount.");
    if (debits !== credits) p.push(`Debits and credits must be equal. They're off by ${money(Math.abs(debits - credits) / 100)}.`);
    return p;
  }, [used, debits, credits]);

  const update = (i: number, patch: Partial<Row>) => setRows(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const grouped = ORDER.map((t) => ({ t, list: accounts.filter((a) => a.type === t && (a.is_active || rows.some((r) => r.account_id === a.id))) }));

  async function save(e: FormEvent) {
    e.preventDefault();
    if (problems.length) { toast.error(problems[0] ?? "Check the entry"); return; }
    const body = {
      entry_date: date, number: number.trim() || null, memo: memo.trim() || null,
      lines: used.map((r) => ({
        account_id: r.account_id, debit: num(r.debit), credit: num(r.credit), description: r.description.trim() || null,
        customer_id: r.customer_id || null, vendor_name: r.vendor_name.trim() || null,
      })),
    };
    setBusy(true);
    try {
      if (id) await api.updateJournal(id, body);
      else await api.createJournal(body);
      toast.success("Journal entry saved");
      navigate("/journal");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the journal entry");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!id) return;
    try {
      await api.deleteJournal(id);
      toast.success("Journal entry deleted");
      navigate("/journal");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete");
    }
  }

  if (!loaded) return <div className="page"><p className="muted">Loading…</p></div>;
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="crumbs"><Link to="/journal">Journal entries</Link></p>
          <h1>{id ? "Journal entry" : "New journal entry"}</h1>
        </div>
      </header>

      <form className="panel form" onSubmit={save}>
        <div className="grid-3">
          <label className="field"><span>Journal date</span>
            <input type="date" value={date} required disabled={!canEdit} onChange={(e) => setDate(e.target.value)} /></label>
          <label className="field"><span>Journal no. (optional)</span>
            <input value={number} maxLength={30} disabled={!canEdit} onChange={(e) => setNumber(e.target.value)} /></label>
        </div>

        <div className="lines">
          <table className="lines-table">
            <thead><tr><th className="ln-num">#</th><th>Account</th><th className="num">Debits</th><th className="num">Credits</th>
              <th>Description</th><th>Customer</th><th><span className="sr-only">Remove</span></th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.key}>
                  <td className="ln-num muted">{i + 1}</td>
                  <td>
                    <select value={r.account_id} disabled={!canEdit} aria-label={`Line ${i + 1} account`}
                      onChange={(e) => update(i, { account_id: e.target.value })}>
                      <option value="">Choose an account</option>
                      {grouped.filter((g) => g.list.length).map((g) => (
                        <optgroup key={g.t} label={TYPE_LABEL[g.t]}>
                          {g.list.map((a) => <option key={a.id} value={a.id}>{a.code ? `${a.code} ` : ""}{a.name}</option>)}
                        </optgroup>
                      ))}
                    </select>
                  </td>
                  <td className="num"><div className="money-input small-money"><span aria-hidden="true">{currencySymbol().trim()}</span>
                    <input inputMode="decimal" value={r.debit} disabled={!canEdit} aria-label={`Line ${i + 1} debit`} placeholder=""
                      onChange={(e) => update(i, { debit: e.target.value.replace(/[^0-9.]/g, ""), credit: e.target.value ? "" : r.credit })}
                      onBlur={() => num(r.debit) > 0 && update(i, { debit: num(r.debit).toFixed(2) })} /></div></td>
                  <td className="num"><div className="money-input small-money"><span aria-hidden="true">{currencySymbol().trim()}</span>
                    <input inputMode="decimal" value={r.credit} disabled={!canEdit} aria-label={`Line ${i + 1} credit`} placeholder=""
                      onChange={(e) => update(i, { credit: e.target.value.replace(/[^0-9.]/g, ""), debit: e.target.value ? "" : r.debit })}
                      onBlur={() => num(r.credit) > 0 && update(i, { credit: num(r.credit).toFixed(2) })} /></div></td>
                  <td><input value={r.description} maxLength={500} disabled={!canEdit} aria-label={`Line ${i + 1} description`}
                    onChange={(e) => update(i, { description: e.target.value })} /></td>
                  <td>
                    <select value={r.customer_id} disabled={!canEdit} aria-label={`Line ${i + 1} customer`}
                      onChange={(e) => update(i, { customer_id: e.target.value })}>
                      <option value="">None</option>
                      {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                  </td>
                  <td className="row-actions">
                    {canEdit && <button type="button" className="icon-btn" aria-label={`Remove line ${i + 1}`}
                      onClick={() => setRows(rows.length > 2 ? rows.filter((_, idx) => idx !== i) : rows.map((x, idx) => (idx === i ? blank() : x)))}>×</button>}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={2}>{canEdit && <button type="button" className="link-button" onClick={() => setRows([...rows, blank()])}>Add line</button>}</td>
                <td className="num lines-total">{money(debits / 100)}</td>
                <td className="num lines-total">{money(credits / 100)}</td>
                <td colSpan={3} className={debits === credits ? "muted" : "overdue-text"}>
                  {debits === credits ? (debits ? "Balanced" : "") : `Out of balance by ${money(Math.abs(debits - credits) / 100)}`}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>

        <label className="field"><span>Memo</span>
          <textarea rows={2} value={memo} maxLength={500} disabled={!canEdit} onChange={(e) => setMemo(e.target.value)} /></label>

        {canEdit && (
          <div className="form-actions">
            {id && <button type="button" className="btn btn-danger" onClick={() => setConfirmDelete(true)}>Delete</button>}
            <span className="spacer" />
            <Link className="btn" to="/journal">Cancel</Link>
            <button type="submit" className="btn btn-primary" disabled={busy || problems.length > 0}>{busy ? "Saving…" : "Save"}</button>
          </div>
        )}
        {canEdit && problems.length > 0 && used.length > 0 && <p className="hint">{problems[0]}</p>}
      </form>

      <ConfirmDialog open={confirmDelete} title="Delete this journal entry?" message="It will be removed from your books. The history is kept."
        confirmLabel="Delete" danger onConfirm={() => { setConfirmDelete(false); void remove(); }} onCancel={() => setConfirmDelete(false)} />
    </div>
  );
}
