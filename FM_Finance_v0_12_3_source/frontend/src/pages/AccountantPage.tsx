import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useToast } from "../context";
import { formatDate, money, today } from "../format";
import type { AuditLogPage, ReconciliationSummary } from "../types";

function yearStart() { return `${today().slice(0, 4)}-01-01`; }
function label(value: string) { return value.replace(/_/g, " ").replace(/\b\w/g, (letter: string) => letter.toUpperCase()); }

export default function AccountantPage() {
  const toast = useToast();
  const [dateFrom, setDateFrom] = useState(yearStart());
  const [dateTo, setDateTo] = useState(today());
  const [entityType, setEntityType] = useState("");
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const [audit, setAudit] = useState<AuditLogPage | null>(null);
  const [reconciliations, setReconciliations] = useState<ReconciliationSummary[]>([]);

  const loadAudit = useCallback((nextPage = page) => {
    api.audit({ entity_type: entityType || undefined, action: action || undefined,
      date_from: dateFrom || undefined, date_to: dateTo || undefined }, nextPage, 25)
      .then(setAudit).catch((e: Error) => toast.error(e.message));
  }, [action, dateFrom, dateTo, entityType, page, toast]);

  useEffect(() => { loadAudit(1); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api.reconciliations().then(setReconciliations).catch((e: Error) => toast.error(e.message)); }, [toast]);

  function search(e: FormEvent) { e.preventDefault(); setPage(1); loadAudit(1); }
  function move(next: number) { setPage(next); loadAudit(next); }
  const completed = reconciliations.filter((row) => row.status === "completed");
  const drafts = reconciliations.filter((row) => row.status === "draft");

  return (
    <div className="page">
      <header className="page-head"><div><h1>Accountant center</h1><p className="page-sub">Review the books, audit changes, and hand over a complete period package.</p></div></header>

      <section className="summary-grid accountant-summary">
        <div className="summary-card"><span>Completed reconciliations</span><strong>{completed.length}</strong><small>{drafts.length ? `${drafts.length} still in progress` : "No statements in progress"}</small></div>
        <div className="summary-card"><span>Audit events in view</span><strong>{audit?.total ?? "—"}</strong><small>Who changed what and when</small></div>
        <div className="summary-card accent"><span>Books review</span><strong>Ready here</strong><small>Reports, statements and documents together</small></div>
      </section>

      <div className="two-col accountant-grid">
        <section className="panel"><h2>Accountant package</h2><p>Download one ZIP with the general ledger, financial statements, bank activity, expenses, invoices, bills, reconciliations, audit history, and available receipts and source documents.</p>
          <div className="grid-2"><label className="field"><span>From</span><input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></label>
            <label className="field"><span>Through</span><input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></label></div>
          <a className={`btn btn-primary ${!dateFrom || !dateTo || dateFrom > dateTo ? "disabled" : ""}`}
            href={api.accountantExportUrl(dateFrom, dateTo)} aria-disabled={!dateFrom || !dateTo || dateFrom > dateTo}>Download accountant ZIP</a>
        </section>
        <section className="panel"><h2>Review shortcuts</h2><div className="accountant-links">
          <Link to="/reports">Financial reports <span>Profit and loss, balance sheet and trial balance</span></Link>
          <Link to="/reconcile">Bank reconciliation <span>Statements and completed periods</span></Link>
          <Link to="/journal">Journal entries <span>Adjustments and supporting entries</span></Link>
          <Link to="/owner-funds">Owner funds <span>Loans and reimbursements still owed</span></Link>
        </div></section>
      </div>

      <section className="panel flush"><div className="panel-head"><div><h2>Reconciliation status</h2><p className="muted">The most recent statement work for every account.</p></div><Link to="/reconcile">Open all</Link></div>
        {reconciliations.length === 0 ? <div className="empty inner"><p>No statements reconciled yet.</p></div> : <div className="table-wrap"><table className="ledger"><thead><tr><th>Account</th><th>Statement date</th><th>Status</th><th className="num">Ending balance</th><th>Completed by</th></tr></thead><tbody>
          {reconciliations.slice(0, 8).map((row) => <tr key={row.id}><td><Link to={`/reconcile/${row.id}`}>{row.account_name}</Link></td><td>{formatDate(row.statement_date)}</td>
            <td>{row.status === "completed" ? "Reconciled" : "In progress"}</td><td className="num">{money(row.ending_balance)}</td><td>{row.completed_by_name ?? "—"}</td></tr>)}
        </tbody></table></div>}
      </section>

      <section className="panel flush"><div className="panel-head"><div><h2>Audit history</h2><p className="muted">A searchable record of changes made in the company.</p></div></div>
        <form className="audit-filters" onSubmit={search}><label className="field"><span>Record type</span><input value={entityType} placeholder="e.g. expense" onChange={(e) => setEntityType(e.target.value)} /></label>
          <label className="field"><span>Action</span><input value={action} placeholder="e.g. updated" onChange={(e) => setAction(e.target.value)} /></label>
          <button className="btn" type="submit">Search</button></form>
        {!audit ? <div className="empty inner"><p className="muted">Loading…</p></div> : audit.items.length === 0 ? <div className="empty inner"><p>No matching activity.</p></div>
          : <div className="table-wrap"><table className="ledger"><thead><tr><th>When</th><th>Person</th><th>Record</th><th>Action</th><th>Details</th></tr></thead><tbody>
            {audit.items.map((row) => <tr key={row.id}><td>{new Date(row.created_at).toLocaleString()}</td><td>{row.user_name ?? "System"}<div className="muted small">{row.user_email}</div></td>
              <td>{label(row.entity_type)}</td><td>{label(row.action)}</td><td className="small audit-details">{row.changes ? Object.entries(row.changes).slice(0, 4).map(([key, value]) => `${label(key)}: ${String(value)}`).join(" · ") : "—"}</td></tr>)}
          </tbody></table></div>}
        {audit && audit.total > audit.page_size && <div className="pagination"><button className="btn" disabled={page <= 1} onClick={() => move(page - 1)}>Previous</button>
          <span>Page {page} of {Math.ceil(audit.total / audit.page_size)}</span><button className="btn" disabled={page * audit.page_size >= audit.total} onClick={() => move(page + 1)}>Next</button></div>}
      </section>
    </div>
  );
}
