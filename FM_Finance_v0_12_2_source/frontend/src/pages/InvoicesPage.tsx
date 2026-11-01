import { useCallback, useEffect, useState } from "react";
import { ModuleNotice, useModule } from "../modules";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth, useToast } from "../context";
import { daysLate, formatDate, INVOICE_STATUS_LABEL, money } from "../format";
import type { InvoicePage, InvoiceStatus } from "../types";

const TABS = [
  { key: "unpaid", label: "Unpaid" },
  { key: "paid", label: "Paid" },
  { key: "all", label: "All" },
] as const;

export function InvoiceBadge({ status, due }: { status: InvoiceStatus; due?: string }) {
  const late = status === "overdue" && due ? daysLate(due) : 0;
  return (
    <span className={`badge badge-inv-${status}`}>
      {status === "overdue" && late > 0 ? `Overdue ${late} day${late === 1 ? "" : "s"}` : INVOICE_STATUS_LABEL[status]}
    </span>
  );
}

export default function InvoicesPage() {
  const { user } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const { on } = useModule("invoicing");
  const canEdit = (user?.role === "admin" || user?.role === "approver") && on;
  const [params] = useSearchParams();
  const initial = params.get("tab");
  const [show, setShow] = useState<"unpaid" | "paid" | "all">(initial === "paid" || initial === "all" ? initial : "unpaid");
  const [search, setSearch] = useState("");
  const [data, setData] = useState<InvoicePage | null>(null);

  const load = useCallback(() => {
    api.invoices(show, search.trim() || undefined).then(setData).catch((e: Error) => toast.error(e.message));
  }, [show, search, toast]);
  useEffect(() => { const t = window.setTimeout(load, 200); return () => window.clearTimeout(t); }, [load]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Invoices</h1>
          <p className="muted">What customers owe you. Create an invoice, send it as a PDF by email, and record the payment when it arrives.</p>
        </div>
        {canEdit && (
          <div className="head-actions">
            <Link className="btn" to="/payments/new">Receive payment</Link>
            <Link className="btn btn-primary" to="/invoices/new">Create invoice</Link>
          </div>
        )}
      </header>

      <ModuleNotice module="invoicing" />

      {data && (
        <div className="figures">
          <div className="figure figure-lead"><span className="figure-label">Open invoices ({data.count_open})</span>
            <span className="figure-value">{money(data.total_open)}</span></div>
          <div className="figure"><span className="figure-label">Overdue ({data.count_overdue})</span>
            <span className={data.total_overdue > 0 ? "figure-value overdue-text" : "figure-value"}>{money(data.total_overdue)}</span></div>
          <div className="figure"><span className="figure-label">Paid in the last 30 days</span>
            <span className="figure-value amount-in">{money(data.paid_last_30)}</span></div>
        </div>
      )}

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={show === t.key}
            className={show === t.key ? "tab active" : "tab"} onClick={() => setShow(t.key)}>{t.label}</button>
        ))}
      </div>
      <div className="toolbar">
        <label className="field grow"><span className="sr-only">Search</span>
          <input type="search" placeholder="Search customer, invoice number or memo" value={search}
            onChange={(e) => setSearch(e.target.value)} /></label>
      </div>

      <section className="panel flush">
        {!data || data.items.length === 0 ? (
          <div className="empty inner">
            <p>{show === "unpaid" ? "No unpaid invoices." : "No invoices here."}</p>
            {canEdit && show !== "paid" && <Link className="btn btn-primary" to="/invoices/new">Create your first invoice</Link>}
          </div>
        ) : (
          <div className="table-wrap">
            <table className="ledger">
              <thead><tr><th>Date</th><th>No.</th><th>Customer</th><th>Due</th><th>Status</th>
                <th className="num">Amount</th><th className="num">Open balance</th><th><span className="sr-only">Action</span></th></tr></thead>
              <tbody>
                {data.items.map((i) => (
                  <tr key={i.id} onClick={() => navigate(`/invoices/${i.id}`)}>
                    <td className="nowrap">{formatDate(i.invoice_date)}</td>
                    <td>{i.invoice_number}</td>
                    <td><strong>{i.customer_name}</strong></td>
                    <td className="nowrap">{formatDate(i.due_date)}</td>
                    <td><InvoiceBadge status={i.status} due={i.due_date} /></td>
                    <td className="num">{money(i.total)}</td>
                    <td className="num"><strong>{money(i.balance)}</strong></td>
                    <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                      {canEdit && i.balance > 0 && i.status !== "void" && (
                        <Link className="link-button" to={`/payments/new?customer=${i.customer_id}&invoice=${i.id}`}>Receive payment</Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
