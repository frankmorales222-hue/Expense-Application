import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useToast } from "../context";
import { formatDate, money, today } from "../format";
import type { Account, Reconciliation, ReconciliationSummary } from "../types";

export default function ReconcilePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [history, setHistory] = useState<ReconciliationSummary[]>([]);
  const [item, setItem] = useState<Reconciliation | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [accountId, setAccountId] = useState("");
  const [statementDate, setStatementDate] = useState(today());
  const [endingBalance, setEndingBalance] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  const loadList = useCallback(async () => {
    try {
      const [accts, rows] = await Promise.all([api.accounts(), api.reconciliations()]);
      const usable = accts.filter((a) => a.is_active);
      setAccounts(usable);
      setHistory(rows);
      setAccountId((current) => current || usable[0]?.id || "");
    } catch (e) { toast.error(e instanceof Error ? e.message : "Could not load reconciliations"); }
  }, [toast]);

  const loadDetail = useCallback(async (reconciliationId: string) => {
    try {
      const row = await api.getReconciliation(reconciliationId);
      setItem(row);
      setSelected(new Set(row.transactions.filter((t) => t.reconciliation_id === row.id).map((t) => t.id)));
    } catch (e) { toast.error(e instanceof Error ? e.message : "Could not load the reconciliation"); }
  }, [toast]);

  useEffect(() => { void loadList(); }, [loadList]);
  useEffect(() => { if (id) void loadDetail(id); else setItem(null); }, [id, loadDetail]);

  const selectedTotal = useMemo(() => item?.transactions.reduce((sum, txn) => selected.has(txn.id) ? sum + txn.amount : sum, 0) ?? 0,
    [item, selected]);
  const cleared = (item?.beginning_balance ?? 0) + selectedTotal;
  const difference = (item?.ending_balance ?? 0) - cleared;

  async function start(e: FormEvent) {
    e.preventDefault();
    const amount = Number(endingBalance);
    if (!accountId || !Number.isFinite(amount)) { toast.error("Choose an account and enter the statement ending balance"); return; }
    setBusy(true);
    try {
      const row = await api.startReconciliation({ account_id: accountId, statement_date: statementDate,
        ending_balance: amount, notes: notes.trim() || null });
      toast.success("Reconciliation started");
      navigate(`/reconcile/${row.id}`);
    } catch (err) { toast.error(err instanceof Error ? err.message : "Could not start the reconciliation"); }
    finally { setBusy(false); }
  }

  async function saveSelection(showToast = true): Promise<Reconciliation | null> {
    if (!item) return null;
    setBusy(true);
    try {
      const row = await api.saveReconciliationSelection(item.id, [...selected]);
      setItem(row);
      setSelected(new Set(row.transactions.filter((t) => t.reconciliation_id === row.id).map((t) => t.id)));
      if (showToast) toast.success("Cleared transactions saved");
      return row;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the cleared transactions");
      return null;
    } finally { setBusy(false); }
  }

  async function complete() {
    if (!item || Math.abs(difference) >= 0.005) return;
    const saved = await saveSelection(false);
    if (!saved || Math.abs(saved.difference) >= 0.005) return;
    setBusy(true);
    try {
      const row = await api.completeReconciliation(item.id);
      setItem(row);
      toast.success("Statement reconciled. Its transactions are now locked.");
      await loadList();
    } catch (err) { toast.error(err instanceof Error ? err.message : "Could not complete the reconciliation"); }
    finally { setBusy(false); }
  }

  async function cancel() {
    if (!item || !window.confirm("Cancel this reconciliation? The transactions will return to an unreconciled state.")) return;
    setBusy(true);
    try {
      await api.cancelReconciliation(item.id);
      toast.success("Reconciliation cancelled");
      navigate("/reconcile");
      await loadList();
    } catch (err) { toast.error(err instanceof Error ? err.message : "Could not cancel the reconciliation"); }
    finally { setBusy(false); }
  }

  async function attach(file: File | undefined) {
    if (!item || !file) return;
    setBusy(true);
    try {
      const row = await api.uploadReconciliationStatement(item.id, file);
      setItem(row);
      toast.success("Bank statement attached");
    } catch (err) { toast.error(err instanceof Error ? err.message : "Could not attach the statement"); }
    finally { setBusy(false); }
  }

  if (id && !item) return <div className="page"><p className="muted">Loading reconciliation…</p></div>;

  if (item) {
    const draft = item.status === "draft";
    return (
      <div className="page">
        <header className="page-head"><div><Link className="back" to="/reconcile">Reconcile</Link>
          <h1>{item.account_name} statement</h1>
          <p className="page-sub">Statement ending {formatDate(item.statement_date)} · {draft ? "In progress" : "Completed"}</p></div>
          <div className="head-actions">{draft && <button className="btn btn-danger-quiet" disabled={busy} onClick={() => void cancel()}>Cancel</button>}
            {draft && <button className="btn" disabled={busy} onClick={() => void saveSelection()}>{busy ? "Saving…" : "Save progress"}</button>}
            {draft && <button className="btn btn-primary" disabled={busy || Math.abs(difference) >= 0.005}
              onClick={() => void complete()}>Finish reconciliation</button>}</div></header>

        <section className="summary-grid reconciliation-summary">
          <div className="summary-card"><span>Beginning balance</span><strong>{money(item.beginning_balance)}</strong></div>
          <div className="summary-card"><span>Statement ending balance</span><strong>{money(item.ending_balance)}</strong></div>
          <div className="summary-card"><span>Cleared balance</span><strong>{money(draft ? cleared : item.cleared_balance)}</strong></div>
          <div className={`summary-card ${Math.abs(draft ? difference : item.difference) < 0.005 ? "balanced" : "attention"}`}>
            <span>Difference</span><strong>{money(draft ? difference : item.difference)}</strong>
            <small>{Math.abs(draft ? difference : item.difference) < 0.005 ? "Ready to finish" : "Keep matching the statement"}</small></div>
        </section>

        <section className="panel statement-panel"><div><h2>Bank statement</h2>
          <p className="muted">Keep the source PDF or image with this completed reconciliation.</p></div>
          <div className="head-actions">{item.statement_filename && <a href={api.reconciliationStatementUrl(item.id)}>{item.statement_filename}</a>}
            <label className="btn file-button">{item.statement_filename ? "Replace" : "Attach statement"}
              <input type="file" accept=".pdf,.jpg,.jpeg,.png" disabled={busy} onChange={(e) => void attach(e.target.files?.[0])} />
            </label></div></section>

        <section className="panel flush"><div className="panel-head"><div><h2>{draft ? "Match statement transactions" : "Reconciled transactions"}</h2>
          <p className="muted">{draft ? "Tick every deposit, payment and transfer shown on this statement." : `${item.transaction_count} locked transactions`}</p></div></div>
          {item.transactions.length === 0 ? <div className="empty inner"><p>No eligible approved transactions through this statement date.</p></div>
            : <div className="table-wrap"><table className="ledger"><thead><tr><th className="check-col">Cleared</th><th>Date</th><th>Description</th><th className="num">Amount</th></tr></thead><tbody>
              {item.transactions.map((txn) => <tr key={txn.id}><td className="check-col"><input type="checkbox" checked={selected.has(txn.id)} disabled={!draft}
                aria-label={`Clear ${txn.description}`} onChange={(e) => setSelected((current) => { const next = new Set(current); if (e.target.checked) next.add(txn.id); else next.delete(txn.id); return next; })} /></td>
                <td>{formatDate(txn.txn_date)}</td><td><strong>{txn.description}</strong>{txn.memo && <div className="muted small">{txn.memo}</div>}</td>
                <td className={`num ${txn.amount < 0 ? "negative" : ""}`}>{money(txn.amount)}</td></tr>)}
            </tbody></table></div>}
        </section>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page-head"><div><h1>Reconcile</h1><p className="page-sub">Match each bank or credit-card statement and lock the completed period.</p></div></header>
      <div className="two-col reconcile-grid">
        <form className="panel form" onSubmit={start}><h2>Start a statement</h2>
          <label className="field"><span>Account</span><select required value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">Choose an account</option>{accounts.map((a) => <option key={a.id} value={a.id}>{a.name}{a.last4 ? ` ··${a.last4}` : ""}</option>)}</select></label>
          <div className="grid-2"><label className="field"><span>Statement ending date</span><input type="date" required value={statementDate} onChange={(e) => setStatementDate(e.target.value)} /></label>
            <label className="field"><span>Ending balance</span><input type="number" step="0.01" required value={endingBalance} onChange={(e) => setEndingBalance(e.target.value)} /></label></div>
          <label className="field"><span>Notes (optional)</span><textarea value={notes} maxLength={1000} onChange={(e) => setNotes(e.target.value)} /></label>
          <div className="form-actions"><span className="spacer" /><button className="btn btn-primary" disabled={busy || !accounts.length}>{busy ? "Starting…" : "Start reconciling"}</button></div>
        </form>
        <section className="panel"><h2>Why reconcile?</h2><p>It proves the app agrees with the bank statement. When the difference reaches zero, finishing locks those transactions so they cannot be accidentally changed.</p>
          <p className="muted">Approve imported transactions before reconciling them. Attach the statement so your accountant can review the evidence later.</p>
          <Link to="/banking">Review bank transactions</Link></section>
      </div>
      <section className="panel flush"><div className="panel-head"><h2>Statement history</h2></div>
        {history.length === 0 ? <div className="empty inner"><p>No reconciliations yet.</p></div> : <div className="table-wrap"><table className="ledger"><thead><tr><th>Account</th><th>Statement date</th><th>Status</th><th className="num">Ending balance</th><th className="num">Difference</th><th>Statement</th></tr></thead><tbody>
          {history.map((row) => <tr key={row.id}><td><Link to={`/reconcile/${row.id}`}>{row.account_name}</Link></td><td>{formatDate(row.statement_date)}</td>
            <td><span className={`tag ${row.status === "completed" ? "tag-green" : "tag-plain"}`}>{row.status === "completed" ? "Reconciled" : "In progress"}</span></td>
            <td className="num">{money(row.ending_balance)}</td><td className="num">{money(row.difference)}</td>
            <td>{row.statement_filename ? <a href={api.reconciliationStatementUrl(row.id)}>Attached</a> : "—"}</td></tr>)}
        </tbody></table></div>}
      </section>
    </div>
  );
}
