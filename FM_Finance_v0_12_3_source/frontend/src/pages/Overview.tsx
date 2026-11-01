import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import Icon from "../components/Icon";
import { useAuth, useToast } from "../context";
import { formatDate, money } from "../format";
import { hasModule, showModule } from "../modules";
import type { DashEvent, DashMonth, DashPoint, Dashboard, Txn } from "../types";

/** v0.9.0 dashboard for owners and accountants: cash, the 30-day forecast, what's coming up, profit, invoices,
 *  and the bank transactions waiting for approval. Every color comes from the chosen look (theme tokens). */

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(iso: string): { y: number; m: number; d: number } {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return { y: y ?? 0, m: m ?? 1, d: d ?? 1 };
}
const shortDate = (iso: string) => { const p = parts(iso); return `${MON[p.m - 1]} ${p.d}`; };

function compact(v: number): string {
  const a = Math.abs(v);
  const s = a >= 1_000_000 ? `${(a / 1_000_000).toFixed(a >= 10_000_000 ? 0 : 1)}M` : a >= 1000 ? `${(a / 1000).toFixed(a >= 10_000 ? 0 : 1)}k` : a.toFixed(0);
  return `${v < 0 ? "−" : ""}$${s.replace(/\.0(?=[kM])/, "")}`;
}

function niceTicks(lo: number, hi: number, count = 4): number[] {
  if (hi === lo) { hi = lo + 1; }
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const start = Math.floor(lo / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= hi + step * 0.001; v += step) ticks.push(Math.round(v * 100) / 100);
  if (ticks[ticks.length - 1]! < hi) ticks.push(ticks[ticks.length - 1]! + step);
  return ticks;
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function pct(now: number, before: number): string | null {
  if (!before) return null;
  const p = ((now - before) / Math.abs(before)) * 100;
  return `${p >= 0 ? "+" : "−"}${Math.abs(p).toFixed(Math.abs(p) < 10 ? 1 : 0)}%`;
}

function Spark({ points }: { points: number[] }) {
  if (points.length < 2) return null;
  const w = 72, h = 26, lo = Math.min(...points), hi = Math.max(...points);
  const d = points.map((v, i) => `${(i * (w / (points.length - 1))).toFixed(1)},${(h - 3 - ((v - lo) / (hi - lo || 1)) * (h - 6)).toFixed(1)}`).join(" ");
  const up = points[points.length - 1]! >= points[0]!;
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline points={d} fill="none" stroke={up ? "var(--positive)" : "var(--danger)"} strokeWidth={1.75} strokeLinejoin="round" />
    </svg>
  );
}

// ---------------------------------------------------------------- cash forecast
function ForecastChart({ history, forecast, low }: { history: DashPoint[]; forecast: DashPoint[]; low: DashPoint }) {
  const all = [...history, ...forecast];
  const values = all.map((p) => p.balance);
  const ticks = niceTicks(Math.min(...values), Math.max(...values));
  const lo = ticks[0]!, hi = ticks[ticks.length - 1]!;
  const W = 760, H = 260, L = 52, R = 8, T = 14, B = 226;
  const days = history.length - 1 + forecast.length - 1;  // 60
  const x = (i: number) => L + (i / days) * (W - L - R);
  const y = (v: number) => B - ((v - lo) / (hi - lo || 1)) * (B - T);
  const hx = history.map((p, i) => `${x(i).toFixed(1)},${y(p.balance).toFixed(1)}`).join(" ");
  const off = history.length - 1;
  const fx = forecast.map((p, i) => `${x(off + i).toFixed(1)},${y(p.balance).toFixed(1)}`).join(" ");
  const lowIdx = off + forecast.findIndex((p) => p.date === low.date);
  const labels = [0, 10, 20, 30, 40, 50, 60].filter((i) => i <= days);
  const dateAt = (i: number) => (i <= off ? history[i]!.date : forecast[i - off]!.date);
  const lowX = x(lowIdx);
  const nearToday = lowIdx - off < 10;
  const lowAnchor = nearToday ? "start" : lowX > W - 160 ? "end" : lowX < L + 120 ? "start" : "middle";
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Cash: ${money(history[off]!.balance)} today; lowest expected ${money(low.balance)} on ${formatDate(low.date)}`}>
      <rect className="future" x={x(off)} y={T} width={x(days) - x(off)} height={B - T} />
      {ticks.map((v) => (
        <g key={v}><line className="grid" x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
          <text className="tick" x={L - 8} y={y(v) + 4} textAnchor="end">{compact(v)}</text></g>
      ))}
      <polyline className="actual" points={hx} strokeLinejoin="round" />
      <polyline className="forecast" points={fx} strokeLinejoin="round" />
      <line className="today" x1={x(off)} x2={x(off)} y1={T} y2={B} />
      <text className="label" x={x(off) + 6} y={T + 12}>Today</text>
      <circle cx={x(off)} cy={y(history[off]!.balance)} r={5} fill="var(--chart-in)" stroke="var(--surface)" strokeWidth={2} />
      {lowIdx > off && (
        <g>
          <circle className="low" cx={lowX} cy={y(low.balance)} r={4.5} />
          <text className="lowtext" x={nearToday ? lowX + 10 : lowX} y={nearToday ? Math.min(y(low.balance) + 22, B - 4) : Math.min(y(low.balance) + 20, B - 4)} textAnchor={lowAnchor}>
            Lowest {compact(low.balance)} on {shortDate(low.date)}</text>
        </g>
      )}
      {labels.map((i) => (
        <text key={i} className="tick" x={x(i)} y={H - 8} textAnchor={i === 0 ? "start" : i === days ? "end" : "middle"}>{shortDate(dateAt(i))}</text>
      ))}
      {all.map((p, i) => (
        <rect key={i} className="hit" x={x(i) - (W - L - R) / days / 2} y={T} width={(W - L - R) / days} height={B - T}>
          <title>{`${formatDate(p.date)}: ${money(p.balance)}${i > off ? " expected" : ""}`}</title>
        </rect>
      ))}
    </svg>
  );
}

// ---------------------------------------------------------------- income and expenses by month
function MonthsChart({ months }: { months: DashMonth[] }) {
  const max = Math.max(...months.flatMap((m) => [m.income, m.expenses]), 1);
  const ticks = niceTicks(0, max, 3);
  const top = ticks[ticks.length - 1]!;
  const W = 640, H = 220, L = 44, T = 18, B = 190;
  const step = (W - L) / months.length;
  const bw = Math.min(16, step * 0.32);
  const y = (v: number) => B - (Math.max(v, 0) / top) * (B - T);
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Income and expenses by month, last 12 months">
      {ticks.map((v) => (
        <g key={v}><line className="grid" x1={L} x2={W} y1={y(v)} y2={y(v)} />
          <text className="tick" x={L - 8} y={y(v) + 4} textAnchor="end">{compact(v)}</text></g>
      ))}
      {months.map((m, i) => {
        const cx = L + step * i + step / 2;
        const net = m.income - m.expenses;
        return (
          <g key={m.key}>
            <rect className="in" x={cx - bw - 1} y={y(m.income)} width={bw} height={B - y(m.income)} rx={2}>
              <title>{`${m.label}: income ${money(m.income)}`}</title></rect>
            <rect className="out" x={cx + 1} y={y(m.expenses)} width={bw} height={B - y(m.expenses)} rx={2}>
              <title>{`${m.label}: expenses ${money(m.expenses)}`}</title></rect>
            {(m.income !== 0 || m.expenses !== 0) && (
              <text x={cx} y={y(Math.max(m.income, m.expenses)) - 5} textAnchor="middle" fontSize={11} fontWeight={700}
                fill={net >= 0 ? "var(--positive)" : "var(--danger)"}>{net >= 0 ? "+" : ""}{compact(net)}</text>
            )}
            <text className="tick" x={cx} y={H - 8} textAnchor="middle">{m.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------- pieces
function EventRow({ e }: { e: DashEvent }) {
  const p = parts(e.date);
  const to = e.kind === "invoice" ? `/invoices/${e.id}` : `/bills/${e.id}`;
  const what = e.kind === "invoice"
    ? `Invoice ${e.reference ?? ""}${e.days_late ? " · send a reminder" : " due"}`
    : `Bill${e.reference ? ` ${e.reference}` : ""}${e.days_late ? " · past due" : ""}`;
  return (
    <li>
      {e.days_late > 0
        ? <span className="day late"><small>LATE</small><b>{e.days_late}d</b></span>
        : <span className="day"><small>{MON[p.m - 1]!.toUpperCase()}</small><b>{p.d}</b></span>}
      <Link to={to} className="ev-what"><b>{e.name}</b><small>{what}</small></Link>
      <span className={e.amount > 0 ? "amt-in num" : "amt-out num"}>{e.amount > 0 ? "+" : "−"}{money(Math.abs(e.amount))}</span>
    </li>
  );
}

function suggestion(t: Txn): { text: string; tone: "" | "match" | "ask"; ready: boolean } {
  if (t.is_transfer) return { text: "Transfer between your accounts", tone: "", ready: true };
  if (t.allocation_account_name) return { text: t.allocation_account_name, tone: "match", ready: true };
  if (t.customer_payment_id) return { text: "Payment received on an invoice", tone: "match", ready: true };
  if (t.bill_id) return { text: "Pays a bill", tone: "match", ready: true };
  const cat = t.category_name ?? t.suggested_category_name;
  if (cat) return { text: cat, tone: "", ready: true };
  return { text: t.amount > 0 ? "Who paid this?" : "Choose a category", tone: "ask", ready: false };
}

function ReviewPanel({ count, onChanged }: { count: number; onChanged: () => void }) {
  const toast = useToast();
  const [items, setItems] = useState<Txn[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const load = useCallback(() => {
    api.transactions({ tab: "review", sort: "date_desc" }, 1, 5).then((p) => setItems(p.items)).catch(() => setItems([]));
  }, []);
  useEffect(load, [load, count]);

  async function approve(t: Txn) {
    setBusy(t.id);
    try {
      await api.approveTransaction(t.id);
      toast.success(`Approved: ${t.vendor_name ?? t.customer_name ?? t.description}`);
      onChanged();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not approve");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="dpanel span-7">
      <div className="dpanel-head"><h2>New from the bank</h2>
        <span className="muted">{count === 0 ? "All caught up" : `${count} waiting · approve to add to your books`}</span></div>
      {items && items.length === 0 ? (
        <div className="dash-empty"><Icon name="check" size={22} /><p>Nothing to review. New bank transactions show up here.</p>
          <Link to="/banking">Go to Banking</Link></div>
      ) : (
        <div className="table-wrap">
          <table className="dash-table">
            <thead><tr><th>Transaction</th><th>We suggest</th><th className="num">Amount</th><th><span className="sr-only">Action</span></th></tr></thead>
            <tbody>
              {(items ?? []).map((t) => {
                const s = suggestion(t);
                const name = t.vendor_name ?? t.customer_name ?? t.suggested_vendor_name ?? t.description;
                return (
                  <tr key={t.id}>
                    <td><b style={{ fontWeight: 600 }}>{name}</b><div className="raw">{shortDate(t.txn_date)} · {t.description}</div></td>
                    <td><span className={`sugg ${s.tone}`}>{s.tone === "match" && <Icon name="link" size={13} />}
                      {s.tone === "ask" && <Icon name="alert" size={13} />}{s.text}</span></td>
                    <td className={t.amount > 0 ? "num amt-in" : "num amt-out"}>{t.amount > 0 ? "+" : "−"}{money(Math.abs(t.amount))}</td>
                    <td className="row-actions">
                      {s.ready
                        ? <button type="button" className="btn btn-small" disabled={busy !== null} onClick={() => void approve(t)}>
                            <Icon name="check" size={15} />Approve</button>
                        : <Link className="btn btn-small" to="/banking">Review</Link>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {count > 5 && <p className="hint" style={{ padding: "8px 20px", margin: 0, borderTop: "1px solid var(--line)" }}>
        <Link to="/banking">See all {count} in Banking</Link></p>}
    </section>
  );
}

const STATUS_TEXT: Record<string, string> = { not_sent: "Not sent", sent: "Sent", partial: "Part paid", paid: "Paid", overdue: "Late", void: "Void" };

// ---------------------------------------------------------------- page
export default function Overview() {
  const { user } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [d, setD] = useState<Dashboard | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    api.dashboard().then(setD).catch((e: Error) => toast.error(e.message));
  }, [toast, tick]);

  if (!user) return null;
  const invoicing = showModule(user, "invoicing");
  const canInvoice = hasModule(user, "invoicing");
  const bills = showModule(user, "bills");
  const first = user.name.split(/\s+/)[0] ?? user.name;

  return (
    <div className="page page-wide">
      <header className="page-head welcome">
        <div><h1>{greeting()}, {first}</h1>
          <p className="page-sub">Where {user.company_name} stands today{d ? `, ${formatDate(d.as_of)}` : ""}.</p></div>
        <div className="head-actions">
          {user.role !== "viewer" && <Link className="btn" to="/expenses/new"><Icon name="plusDoc" size={16} />Add expense</Link>}
          {canInvoice && <Link className="btn" to="/payments/new">Receive payment</Link>}
          {canInvoice && <Link className="btn btn-primary" to="/invoices/new"><Icon name="plus" size={16} />Create invoice</Link>}
        </div>
      </header>

      {!d ? <div className="panel muted">Loading your numbers…</div> : (
        <div className="dash">
          <section className="kpis span-12" aria-label="Key numbers">
            <Link to="/banking" className="kpi">
              <span className="kpi-label">Cash in the bank</span>
              <span className="kpi-value">{money(d.cash_total)}</span>
              <span className="kpi-row">
                {d.has_bank_accounts
                  ? <span className={d.cash_total >= d.cash_month_start ? "kpi-note good" : "kpi-note bad"}>
                      <Icon name={d.cash_total >= d.cash_month_start ? "up" : "down"} size={15} />
                      {money(Math.abs(d.cash_total - d.cash_month_start))} this month</span>
                  : <span className="kpi-note">Add a bank account to see cash</span>}
                <Spark points={d.history.map((p) => p.balance)} />
              </span>
            </Link>
            <Link to="/reports" className="kpi">
              <span className="kpi-label">Profit, year to date</span>
              <span className="kpi-value">{money(d.profit_ytd)}</span>
              <span className="kpi-row">
                {pct(d.profit_ytd, d.profit_prior_ytd)
                  ? <span className={d.profit_ytd >= d.profit_prior_ytd ? "kpi-note good" : "kpi-note bad"}>
                      <Icon name={d.profit_ytd >= d.profit_prior_ytd ? "up" : "down"} size={15} />
                      {pct(d.profit_ytd, d.profit_prior_ytd)} vs last year</span>
                  : <span className="kpi-note">Income {money(d.income_ytd)}</span>}
                <Spark points={d.months.map((m) => m.income - m.expenses)} />
              </span>
            </Link>
            <Link to={invoicing ? "/invoices" : "/reports"} className="kpi">
              <span className="kpi-label">Customers owe you</span>
              <span className="kpi-value">{money(d.receivable_total)}</span>
              {d.overdue_total > 0
                ? <span className="kpi-note bad"><Icon name="alert" size={15} />{money(d.overdue_total)} late ({d.overdue_count})</span>
                : <span className="kpi-note">{d.receivable_open_count} open invoice{d.receivable_open_count === 1 ? "" : "s"}</span>}
            </Link>
            <Link to={bills ? "/bills" : "/reports"} className="kpi">
              <span className="kpi-label">You owe vendors</span>
              <span className="kpi-value">{money(d.payable_total)}</span>
              {d.payable_due_14 > 0
                ? <span className={d.payable_overdue > 0 ? "kpi-note bad" : "kpi-note warn"}><Icon name="calendar" size={15} />
                    {money(d.payable_due_14)} due in 14 days</span>
                : <span className="kpi-note">{d.payable_count} unpaid bill{d.payable_count === 1 ? "" : "s"}</span>}
            </Link>
            <Link to="/owner-funds" className="kpi">
              <span className="kpi-label">Owed to owner</span>
              <span className="kpi-value">{money(d.owner_total_owed)}</span>
              <span className="kpi-note">Loans {money(d.owner_loan_balance)} · expenses {money(d.owner_reimbursements)}</span>
            </Link>
          </section>

          {d.accounts.length > 0 && (
            <section className="accts span-12" aria-label="Accounts">
              <div className="acct-card total">
                <span className="l"><Icon name="wallet" size={16} /><span>Total cash</span></span>
                <span className="v">{money(d.cash_total)}</span>
                <span className="s">{d.accounts.filter((a) => a.kind !== "credit_card").length} bank account{d.accounts.filter((a) => a.kind !== "credit_card").length === 1 ? "" : "s"}</span>
              </div>
              {d.accounts.slice(0, 3).map((a) => (
                <Link key={a.id} to="/banking" className="acct-card">
                  <span className="l"><Icon name={a.kind === "credit_card" ? "card" : a.kind === "cash" ? "cash" : "bank"} size={16} />
                    <span>{a.name}{a.last4 ? ` ··${a.last4}` : ""}</span></span>
                  <span className={a.balance < 0 ? "v neg" : "v"}>{money(a.balance)}</span>
                  <span className="s">{a.unreviewed > 0 ? `${a.unreviewed} to review` : a.kind === "credit_card" ? "Credit card, not counted as cash" : "Up to date"}</span>
                </Link>
              ))}
            </section>
          )}

          <section className="dpanel span-8">
            <div className="dpanel-head"><h2>Cash forecast</h2>
              <span className="legend"><span><i className="line" style={{ borderColor: "var(--chart-in)" }} />Actual</span>
                <span><i className="line dash" style={{ borderColor: "var(--chart-forecast)" }} />Expected from open invoices and bills</span></span></div>
            <div className="dpanel-body">
              {d.has_bank_accounts
                ? <ForecastChart history={d.history} forecast={d.forecast} low={d.forecast_low} />
                : <div className="dash-empty"><Icon name="bank" size={22} /><p>Add your bank accounts and import a statement to see your cash
                    and where it's headed over the next 30 days.</p><Link className="btn" to="/banking">Set up banking</Link></div>}
              {d.has_bank_accounts && <p className="hint" style={{ margin: "6px 0 0" }}>Late invoices aren't counted until they're paid. Bills already past due are counted tomorrow.</p>}
            </div>
          </section>

          <section className="dpanel span-4">
            <div className="dpanel-head"><h2>Coming up</h2><span className="muted">Next 14 days</span></div>
            {d.coming_up.length === 0
              ? <div className="dash-empty"><Icon name="calendar" size={22} /><p>No invoices or bills due in the next two weeks.</p></div>
              : <ul className="events">{d.coming_up.slice(0, 6).map((e) => <EventRow key={`${e.kind}-${e.id}`} e={e} />)}</ul>}
          </section>

          <section className={invoicing ? "dpanel span-7" : "dpanel span-12"}>
            <div className="dpanel-head"><h2>Income and expenses</h2>
              <span className="legend"><span><i style={{ background: "var(--chart-in)" }} />Income</span>
                <span><i style={{ background: "var(--chart-out)" }} />Expenses</span>
                <span style={{ color: "var(--positive)", fontWeight: 700 }}>+ Profit</span></span></div>
            <div className="dpanel-body"><MonthsChart months={d.months} /></div>
          </section>

          {invoicing && (
            <section className="dpanel span-5">
              <div className="dpanel-head"><h2>Invoices</h2><Link to="/invoices">View all</Link></div>
              <div className="dpanel-body" style={{ paddingBottom: 6 }}>
                {(() => {
                  const open = d.receivable_total - d.overdue_total, total = d.paid_last_30 + d.receivable_total || 1;
                  return (<>
                    <div className="stackbar" aria-hidden="true">
                      <i style={{ width: `${(d.paid_last_30 / total) * 100}%`, background: "var(--positive)" }} />
                      <i style={{ width: `${(open / total) * 100}%`, background: "var(--chart-open)" }} />
                      <i style={{ width: `${(d.overdue_total / total) * 100}%`, background: "var(--danger)" }} />
                    </div>
                    <div className="stack-legend">
                      <span>Paid, 30 days<b>{money(d.paid_last_30)}</b></span>
                      <span>Open<b>{money(open)}</b></span>
                      <span style={{ textAlign: "right" }}>Late<b style={{ color: d.overdue_total ? "var(--danger)" : undefined }}>{money(d.overdue_total)}</b></span>
                    </div>
                  </>);
                })()}
              </div>
              {d.invoices.length === 0
                ? <div className="dash-empty"><p>No invoices yet.</p>{canInvoice && <Link className="btn" to="/invoices/new">Create your first invoice</Link>}</div>
                : <ul className="inv-list">{d.invoices.map((i) => (
                    <li key={i.id} onClick={() => navigate(`/invoices/${i.id}`)} style={{ cursor: "pointer" }}>
                      <Link to={`/invoices/${i.id}`}><b>{i.invoice_number}</b><small>{i.customer_name}</small></Link>
                      <span className={`badge badge-inv-${i.status}`}>{i.status === "overdue" ? `${i.days_late} days late` : i.status === "paid" ? <><Icon name="check" size={13} />Paid</> : i.status === "sent" || i.status === "not_sent" ? `Due ${shortDate(i.due_date)}` : STATUS_TEXT[i.status] ?? i.status}</span>
                      <span className="num">{money(i.status === "paid" ? i.total : i.balance)}</span>
                    </li>))}</ul>}
            </section>
          )}

          {(user.role === "admin" || user.role === "approver") && <ReviewPanel count={d.review_count} onChanged={() => setTick((n) => n + 1)} />}

          <section className="dpanel span-5">
            <div className="dpanel-head"><h2>This month so far</h2>
              <span className="muted">{shortDate(d.pnl.this_from)}–{parts(d.pnl.this_to).d} vs {MON[parts(d.pnl.last_from).m - 1]}</span></div>
            <div className="table-wrap"><table className="dash-table">
              <thead><tr><th></th><th className="num">This month</th><th className="num">Last month</th></tr></thead>
              <tbody>
                <tr><td>Income</td><td className="num">{money(d.pnl.income_this)}</td><td className="num">{money(d.pnl.income_last)}</td></tr>
                <tr><td>Expenses</td><td className="num">{money(d.pnl.expenses_this)}</td><td className="num">{money(d.pnl.expenses_last)}</td></tr>
                {d.pnl.expense_rows.map((r) => (
                  <tr key={r.name} className="sub"><td>{r.name}</td><td className="num">{money(r.this_month)}</td><td className="num">{money(r.last_month)}</td></tr>
                ))}
                <tr className="total"><td>Profit</td>
                  <td className="num" style={{ color: d.pnl.net_this >= 0 ? "var(--positive)" : "var(--danger)" }}>{money(d.pnl.net_this)}</td>
                  <td className="num">{money(d.pnl.net_last)}</td></tr>
              </tbody>
            </table></div>
          </section>
        </div>
      )}
    </div>
  );
}
