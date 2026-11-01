import { useCallback, useEffect, useState } from "react";
import { ModuleNotice, useModule } from "../modules";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useToast } from "../context";
import { formatDate, money } from "../format";
import type { BillPage, BillStatus } from "../types";

const STATUS: Record<BillStatus, string> = { open: "Open", partial: "Partly paid", paid: "Paid", overdue: "Overdue" };
const TABS = [
  { key: "unpaid", label: "Unpaid" },
  { key: "paid", label: "Paid" },
  { key: "all", label: "All" },
] as const;

export default function BillsPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [show, setShow] = useState<"unpaid" | "paid" | "all">("unpaid");
  const [search, setSearch] = useState("");
  const { on } = useModule("bills");
  const [data, setData] = useState<BillPage | null>(null);

  const load = useCallback(() => {
    api.bills(show, search.trim() || undefined).then(setData).catch((e: Error) => toast.error(e.message));
  }, [show, search, toast]);
  useEffect(() => { const t = window.setTimeout(load, 200); return () => window.clearTimeout(t); }, [load]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Bills</h1>
          <p className="muted">What you owe vendors. Enter a bill when it arrives, then record the payment when you pay it.</p>
        </div>
        {on && <Link className="btn btn-primary" to="/bills/new">Enter a bill</Link>}
      </header>

      <ModuleNotice module="bills" />

      {data && (
        <div className="figures">
          <div className="figure figure-lead"><span className="figure-label">Unpaid</span>
            <span className="figure-value">{money(data.total_open)}</span></div>
          <div className="figure"><span className="figure-label">Overdue</span>
            <span className={data.total_overdue > 0 ? "figure-value overdue-text" : "figure-value"}>{money(data.total_overdue)}</span></div>
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
          <input type="search" placeholder="Search vendor, bill number or memo" value={search}
            onChange={(e) => setSearch(e.target.value)} /></label>
      </div>

      <section className="panel flush">
        {!data || data.items.length === 0 ? (
          <div className="empty inner"><p>{show === "unpaid" ? "No unpaid bills." : "No bills here."}</p></div>
        ) : (
          <div className="table-wrap">
            <table className="ledger">
              <thead><tr><th>Vendor</th><th>Bill no.</th><th>Bill date</th><th>Due</th><th>Status</th>
                <th className="num">Total</th><th className="num">Open balance</th></tr></thead>
              <tbody>
                {data.items.map((b) => (
                  <tr key={b.id} onClick={() => navigate(`/bills/${b.id}`)}>
                    <td><strong>{b.vendor_name}</strong>{b.attachment_count > 0 && <span className="tag">file</span>}</td>
                    <td>{b.bill_number ?? <span className="muted">None</span>}</td>
                    <td className="nowrap">{formatDate(b.bill_date)}</td>
                    <td className="nowrap">{formatDate(b.due_date)}</td>
                    <td><span className={`badge badge-bill-${b.status}`}>{STATUS[b.status]}</span></td>
                    <td className="num">{money(b.total)}</td>
                    <td className="num"><strong>{money(b.balance)}</strong></td>
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
