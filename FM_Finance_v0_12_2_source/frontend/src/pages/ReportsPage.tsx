import { useEffect, useMemo, useState } from "react";
import { hasModule, showModule } from "../modules";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth, useToast } from "../context";
import { formatDate, money, toISODate, today } from "../format";
import type { Aging, BalanceSheet, ProfitLoss, ReportSection, SalesByCustomer, TrialBalance } from "../types";
import { TYPE_LABEL } from "./ChartOfAccountsPage";

type Kind = "pl" | "bs" | "tb" | "ar" | "sc";
const KINDS: { key: Kind; label: string }[] = [
  { key: "pl", label: "Profit and loss" },
  { key: "bs", label: "Balance sheet" },
  { key: "ar", label: "A/R aging" },
  { key: "sc", label: "Sales by customer" },
  { key: "tb", label: "Trial balance" },
];
const RANGED: Kind[] = ["pl", "sc"];

function presets(fyStart: number) {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const fyYear = m + 1 >= fyStart ? y : y - 1;
  const fy = new Date(fyYear, fyStart - 1, 1);
  const q = Math.floor(m / 3) * 3;
  return [
    { key: "month", label: "This month", from: toISODate(new Date(y, m, 1)), to: toISODate(new Date(y, m + 1, 0)) },
    { key: "last-month", label: "Last month", from: toISODate(new Date(y, m - 1, 1)), to: toISODate(new Date(y, m, 0)) },
    { key: "quarter", label: "This quarter", from: toISODate(new Date(y, q, 1)), to: toISODate(new Date(y, q + 3, 0)) },
    { key: "ytd", label: "This fiscal year to date", from: toISODate(fy), to: today() },
    { key: "last-year", label: "Last fiscal year", from: toISODate(new Date(fyYear - 1, fyStart - 1, 1)),
      to: toISODate(new Date(fyYear, fyStart - 1, 0)) },
  ];
}

export default function ReportsPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const kinds = KINDS.filter((k) => (k.key === "ar" || k.key === "sc") ? showModule(user, "invoicing")
    : k.key === "tb" ? hasModule(user, "advanced_accounting") : true);
  const wanted = (params.get("r") as Kind) || "pl";
  const kind: Kind = kinds.some((k) => k.key === wanted) ? wanted : "pl";
  const [fyStart, setFyStart] = useState(1);
  const ranges = useMemo(() => presets(fyStart), [fyStart]);
  const [preset, setPreset] = useState("ytd");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState(today());
  const [asOf, setAsOf] = useState(today());
  const [pl, setPl] = useState<ProfitLoss | null>(null);
  const [bs, setBs] = useState<BalanceSheet | null>(null);
  const [tb, setTb] = useState<TrialBalance | null>(null);
  const [ar, setAr] = useState<Aging | null>(null);
  const [sc, setSc] = useState<SalesByCustomer | null>(null);

  useEffect(() => { api.company().then((c) => setFyStart(c.fiscal_year_start_month)).catch(() => undefined); }, []);
  useEffect(() => {
    const p = ranges.find((r) => r.key === preset);
    if (p) { setFrom(p.from); setTo(p.to); }
  }, [preset, ranges]);

  useEffect(() => {
    if (kind === "pl" && from && to) api.profitLoss(from, to).then(setPl).catch((e: Error) => toast.error(e.message));
    if (kind === "bs" && asOf) api.balanceSheet(asOf).then(setBs).catch((e: Error) => toast.error(e.message));
    if (kind === "tb" && asOf) api.trialBalance(asOf).then(setTb).catch((e: Error) => toast.error(e.message));
    if (kind === "ar" && asOf) api.aging(asOf).then(setAr).catch((e: Error) => toast.error(e.message));
    if (kind === "sc" && from && to) api.salesByCustomer(from, to).then(setSc).catch((e: Error) => toast.error(e.message));
  }, [kind, from, to, asOf, toast]);

  return (
    <div className="page report-page">
      <header className="page-head no-print">
        <div>
          <h1>Reports</h1>
          <p className="muted">Built from your books: expenses, bills, approved bank transactions and journal entries.</p>
        </div>
        <button type="button" className="btn" onClick={() => window.print()}>Print or save as PDF</button>
      </header>

      <div className="tabs no-print" role="tablist">
        {kinds.map((k) => (
          <button key={k.key} type="button" role="tab" aria-selected={kind === k.key}
            className={kind === k.key ? "tab active" : "tab"} onClick={() => setParams({ r: k.key })}>{k.label}</button>
        ))}
      </div>

      <div className="toolbar no-print">
        {RANGED.includes(kind) ? (
          <>
            <label className="field"><span>Report period</span>
              <select value={preset} onChange={(e) => setPreset(e.target.value)}>
                {ranges.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
                <option value="custom">Custom dates</option>
              </select></label>
            <label className="field"><span>From</span>
              <input type="date" value={from} onChange={(e) => { setPreset("custom"); setFrom(e.target.value); }} /></label>
            <label className="field"><span>To</span>
              <input type="date" value={to} onChange={(e) => { setPreset("custom"); setTo(e.target.value); }} /></label>
          </>
        ) : (
          <label className="field"><span>As of</span>
            <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
        )}
      </div>

      <section className="panel report">
        <div className="report-title">
          <div className="report-company">{user?.company_name}</div>
          <h2>{KINDS.find((k) => k.key === kind)?.label}</h2>
          <div className="muted">
            {RANGED.includes(kind) ? (from && to ? `${formatDate(from)} – ${formatDate(to)}` : "") : `As of ${formatDate(asOf)}`}
          </div>
        </div>
        {kind === "pl" && pl && <ProfitLossView data={pl} />}
        {kind === "bs" && bs && <BalanceSheetView data={bs} />}
        {kind === "tb" && tb && <TrialBalanceView data={tb} />}
        {kind === "ar" && ar && <AgingView data={ar} />}
        {kind === "sc" && sc && <SalesByCustomerView data={sc} />}
      </section>
    </div>
  );
}

// Retained earnings and this year's net income are worked out by the report, not stored in an account.
const CALCULATED = /^0{8}-0{4}-0{4}-0{4}-0{11}[0-9]$/;

function Section({ s, totalLabel, grand }: { s: ReportSection; totalLabel?: string; grand?: boolean }) {
  return (
    <>
      <tr className="report-head"><td colSpan={2}>{s.label}</td></tr>
      {s.rows.length === 0 && <tr className="report-row muted-row"><td>None</td><td className="num" /></tr>}
      {s.rows.map((r) => (
        <tr key={r.account_id} className="report-row">
          <td>{CALCULATED.test(r.account_id) ? <span>{r.name} <span className="muted">(calculated)</span></span>
            : <Link to={`/chart-of-accounts/${r.account_id}`}>{r.code ? `${r.code} ` : ""}{r.name}</Link>}</td>
          <td className="num">{money(r.amount)}</td>
        </tr>
      ))}
      <tr className={grand ? "report-grand" : "report-total"}><td>{totalLabel ?? `Total ${s.label.toLowerCase()}`}</td><td className="num">{money(s.total)}</td></tr>
    </>
  );
}

function Subtotal({ label, value, strong }: { label: string; value: number; strong?: boolean }) {
  return <tr className={strong ? "report-grand" : "report-sub"}><td>{label}</td><td className="num">{money(value)}</td></tr>;
}

function ProfitLossView({ data }: { data: ProfitLoss }) {
  const by: Record<string, ReportSection> = Object.fromEntries(data.sections.map((s) => [s.key, s]));
  const sec = (k: string): ReportSection | null => {
    const s = by[k];
    return s && (s.rows.length > 0 || k === "income" || k === "expenses") ? s : null;
  };
  const income = sec("income"), cogs = sec("cogs"), expenses = sec("expenses");
  const otherIncome = sec("other_income"), otherExpenses = sec("other_expenses");
  return (
    <table className="report-table">
      <thead><tr><th /><th className="num">Total</th></tr></thead>
      <tbody>
        {income && <Section s={income} />}
        {cogs && <Section s={cogs} />}
        {cogs && <Subtotal label="Gross profit" value={data.gross_profit} />}
        {expenses && <Section s={expenses} />}
        <Subtotal label="Net operating income" value={data.net_operating_income} />
        {otherIncome && <Section s={otherIncome} />}
        {otherExpenses && <Section s={otherExpenses} />}
        <Subtotal label="Net income" value={data.net_income} strong />
      </tbody>
    </table>
  );
}

function BalanceSheetView({ data }: { data: BalanceSheet }) {
  return (
    <>
      <table className="report-table">
        <thead><tr><th /><th className="num">Total</th></tr></thead>
        <tbody>
          {data.sections.map((s) => (
            <SectionWithGrand key={s.key} s={s} data={data} />
          ))}
        </tbody>
      </table>
      {!data.balanced && (
        <p className="field-error">Assets don't equal liabilities plus equity. Check Settings → Books for entries that need attention.</p>
      )}
    </>
  );
}

function SectionWithGrand({ s, data }: { s: ReportSection; data: BalanceSheet }) {
  return (
    <>
      <Section s={s} grand={s.key === "assets"} />
      {s.key === "equity" ? <Subtotal label="Total liabilities and equity" value={data.total_liabilities_and_equity} strong /> : null}
    </>
  );
}

function TrialBalanceView({ data }: { data: TrialBalance }) {
  return (
    <table className="report-table">
      <thead><tr><th>Account</th><th>Type</th><th className="num">Debit</th><th className="num">Credit</th></tr></thead>
      <tbody>
        {data.rows.map((r) => (
          <tr key={r.account_id} className="report-row">
            <td><Link to={`/chart-of-accounts/${r.account_id}`}>{r.code ? `${r.code} ` : ""}{r.name}</Link></td>
            <td className="muted">{TYPE_LABEL[r.type]}</td>
            <td className="num">{r.debit ? money(r.debit) : ""}</td>
            <td className="num">{r.credit ? money(r.credit) : ""}</td>
          </tr>
        ))}
        <tr className="report-grand"><td colSpan={2}>Total</td>
          <td className="num">{money(data.total_debit)}</td><td className="num">{money(data.total_credit)}</td></tr>
      </tbody>
    </table>
  );
}

function AgingView({ data }: { data: Aging }) {
  const cols: [keyof Aging["totals"], string][] = [["current", "Current"], ["d1_30", "1–30"], ["d31_60", "31–60"],
    ["d61_90", "61–90"], ["d91_plus", "91 and over"], ["total", "Total"]];
  if (data.rows.length === 0) return <p className="muted center">Nobody owes you anything on this date.</p>;
  return (
    <table className="report-table aging-table">
      <thead><tr><th>Customer</th>{cols.map(([k, l]) => <th key={k} className="num">{l}</th>)}</tr></thead>
      <tbody>
        {data.rows.map((r) => (
          <tr key={r.customer_id} className="report-row">
            <td><Link to={`/customers/${r.customer_id}`}>{r.customer_name}</Link></td>
            {cols.map(([k]) => <td key={k} className={k === "total" ? "num strong" : "num"}>{Number(r[k]) ? money(Number(r[k])) : ""}</td>)}
          </tr>
        ))}
        <tr className="report-grand"><td>Total</td>{cols.map(([k]) => <td key={k} className="num">{money(Number(data.totals[k]))}</td>)}</tr>
      </tbody>
    </table>
  );
}

function SalesByCustomerView({ data }: { data: SalesByCustomer }) {
  if (data.rows.length === 0) return <p className="muted center">No income in this period.</p>;
  return (
    <table className="report-table">
      <thead><tr><th>Customer</th><th className="num">Total</th></tr></thead>
      <tbody>
        {data.rows.map((r) => (
          <tr key={r.customer_id ?? "none"} className="report-row">
            <td>{r.customer_id ? <Link to={`/customers/${r.customer_id}`}>{r.customer_name}</Link> :
              <span className="muted">{r.customer_name} (deposits not tagged with a customer)</span>}</td>
            <td className="num">{money(r.amount)}</td>
          </tr>
        ))}
        <tr className="report-grand"><td>Total income</td><td className="num">{money(data.total)}</td></tr>
      </tbody>
    </table>
  );
}
