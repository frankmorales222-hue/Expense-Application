import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ExpenseTable from "../components/ExpenseTable";
import SummaryCards from "../components/SummaryCards";
import { useAuth, useToast } from "../context";
import { money, presetRanges, today } from "../format";
import type { ExpenseListItem, NameAmount, Summary } from "../types";

export default function DashboardPage() {
  const { settings } = useAuth();
  const toast = useToast();
  const presets = useMemo(() => presetRanges(), []);
  const [rangeKey, setRangeKey] = useState("ytd");
  const [custom, setCustom] = useState({ from: "", to: today() });
  const [summary, setSummary] = useState<Summary | null>(null);
  const [recent, setRecent] = useState<ExpenseListItem[] | null>(null);
  const currency = settings?.currency ?? "USD";

  const range = rangeKey === "custom"
    ? { from: custom.from || undefined, to: custom.to || undefined }
    : { from: presets.find((p) => p.key === rangeKey)?.from, to: presets.find((p) => p.key === rangeKey)?.to };

  useEffect(() => {
    let alive = true;
    api.summary(range.from, range.to)
      .then((s) => { if (alive) setSummary(s); })
      .catch((e: Error) => toast.error(e.message));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range.from, range.to]);

  useEffect(() => {
    api.listExpenses({ sort: "date_desc" }, 1, 10)
      .then((p) => setRecent(p.items))
      .catch((e: Error) => toast.error(e.message));
  }, [toast]);

  const isEmpty = recent !== null && recent.length === 0;

  return (
    <div className="page">
      <header className="page-head">
        <h1>Dashboard</h1>
        <div className="range">
          <label className="field">
            <span>Period</span>
            <select value={rangeKey} onChange={(e) => setRangeKey(e.target.value)}>
              {presets.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
              <option value="custom">Custom range</option>
            </select>
          </label>
          {rangeKey === "custom" && (
            <>
              <label className="field"><span>From</span>
                <input type="date" value={custom.from} onChange={(e) => setCustom({ ...custom, from: e.target.value })} /></label>
              <label className="field"><span>To</span>
                <input type="date" value={custom.to} onChange={(e) => setCustom({ ...custom, to: e.target.value })} /></label>
            </>
          )}
        </div>
      </header>

      {isEmpty ? (
        <section className="empty">
          <h2>No expenses recorded yet</h2>
          <p>Start with the costs of setting up the business: software, hosting, equipment, registrations.</p>
          <Link className="btn btn-primary" to="/expenses/new">Add your first expense</Link>
        </section>
      ) : (
        <>
          {summary && <SummaryCards summary={summary} approvalRequired={Boolean(settings?.approval_required)} currency={currency} />}

          <div className="two-col">
            <section className="panel">
              <h2>Spending by category</h2>
              {summary && summary.by_category.length > 0
                ? <CategoryBars rows={summary.by_category} total={summary.total_spent} currency={currency} />
                : <p className="muted">No spending in this period.</p>}
            </section>
            <section className="panel">
              <h2>Last 12 months</h2>
              {summary && <MonthlyChart rows={summary.by_month} currency={currency} />}
            </section>
          </div>

          <section className="panel">
            <div className="panel-head">
              <h2>Recent expenses</h2>
              <Link to="/expenses">View all</Link>
            </div>
            {recent && <ExpenseTable items={recent} />}
          </section>
        </>
      )}
    </div>
  );
}

function CategoryBars({ rows, total, currency }: { rows: NameAmount[]; total: number; currency: string }) {
  const max = Math.max(...rows.map((r) => r.amount), 1);
  return (
    <ul className="bars">
      {rows.map((r) => (
        <li key={r.key}>
          <div className="bar-label">
            <span>{r.label}</span>
            <span className="num">{money(r.amount, currency)} <span className="muted">{total ? Math.round((r.amount / total) * 100) : 0}%</span></span>
          </div>
          <div className="bar-track"><div className="bar-fill" style={{ width: `${(r.amount / max) * 100}%` }} /></div>
        </li>
      ))}
    </ul>
  );
}

function MonthlyChart({ rows, currency }: { rows: NameAmount[]; currency: string }) {
  const max = Math.max(...rows.map((r) => r.amount), 1);
  const w = 600, h = 200, pad = 22, bw = (w - pad) / rows.length;
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${h + 26}`} role="img" aria-label="Monthly spending, last 12 months">
      <line x1={0} x2={w} y1={h} y2={h} className="chart-axis" />
      {rows.map((r, i) => {
        const bh = (r.amount / max) * (h - pad);
        const x = i * bw + bw * 0.18;
        return (
          <g key={r.key}>
            <rect x={x} y={h - bh} width={bw * 0.64} height={Math.max(bh, r.amount > 0 ? 2 : 0)} rx={3} className="chart-bar">
              <title>{`${r.label}: ${money(r.amount, currency)} (${r.count})`}</title>
            </rect>
            <text x={x + bw * 0.32} y={h + 18} textAnchor="middle" className="chart-label">{r.label.slice(0, 3)}</text>
          </g>
        );
      })}
    </svg>
  );
}
