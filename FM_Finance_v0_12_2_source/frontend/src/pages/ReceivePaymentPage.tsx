import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ModuleNotice, useModule } from "../modules";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useToast } from "../context";
import { formatDate, methodOptions, money, today, currencySymbol } from "../format";
import type { Account, Customer, InvoiceListItem, PaymentMethodIn, PeerTxn } from "../types";

const r2 = (n: number) => Math.round(n * 100) / 100;

export default function ReceivePaymentPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const params = new URLSearchParams(useLocation().search);
  const fromInvoice = params.get("invoice");
  const fromTxn = params.get("transaction");

  const { on } = useModule("invoicing");
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [customerId, setCustomerId] = useState(params.get("customer") ?? "");
  const [date, setDate] = useState(params.get("date") ?? today());
  const [method, setMethod] = useState<PaymentMethodIn | "">(() => methodOptions("received")[0]?.code ?? "");
  const [reference, setReference] = useState("");
  const [accountId, setAccountId] = useState(params.get("account") ?? "");
  const [amount, setAmount] = useState(params.get("amount") ?? "");
  const [memo, setMemo] = useState("");
  const [open, setOpen] = useState<InvoiceListItem[] | null>(null);
  const [applied, setApplied] = useState<Record<string, string>>({});
  const [candidates, setCandidates] = useState<PeerTxn[]>([]);
  const [match, setMatch] = useState(fromTxn ?? "");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.customers().then(setCustomers).catch((e: Error) => toast.error(e.message));
    api.accounts().then((a) => {
      const active = a.filter((x) => x.is_active);
      setAccounts(active);
      setAccountId((cur) => cur || active.find((x) => x.kind === "checking")?.id || active[0]?.id || "");
    }).catch((e: Error) => toast.error(e.message));
  }, [toast]);

  // Open invoices for the customer, oldest first. The invoice we came from (or the deposit amount) is applied.
  useEffect(() => {
    if (!customerId) { setOpen(null); setApplied({}); return; }
    api.invoices("unpaid", undefined, customerId).then((p) => {
      const list = [...p.items].sort((a, b) => a.due_date.localeCompare(b.due_date));
      setOpen(list);
      const start: Record<string, string> = {};
      const target = list.find((i) => i.id === fromInvoice);
      if (target) {
        start[target.id] = target.balance.toFixed(2);
        if (!params.get("amount")) setAmount(target.balance.toFixed(2));
      } else if (Number(amount) > 0) {
        Object.assign(start, distribute(list, Number(amount)));
      }
      setApplied(start);
    }).catch((e: Error) => toast.error(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  const appliedTotal = r2(Object.values(applied).reduce((s, v) => s + (Number(v) || 0), 0));
  const received = Number(amount) || 0;

  useEffect(() => {
    if (!accountId || !(received > 0) || !date) { setCandidates([]); return; }
    const t = window.setTimeout(() => {
      api.depositCandidates(accountId, r2(received), date).then((c) => {
        setCandidates(c);
        setMatch((cur) => (c.some((x) => x.id === cur) ? cur : c.length === 1 && c[0] ? c[0].id : ""));
      }).catch(() => setCandidates([]));
    }, 250);
    return () => window.clearTimeout(t);
  }, [accountId, received, date]);

  function distribute(list: InvoiceListItem[], total: number): Record<string, string> {
    const out: Record<string, string> = {};
    let left = r2(total);
    for (const inv of list) {
      if (left <= 0) break;
      const a = r2(Math.min(inv.balance, left));
      out[inv.id] = a.toFixed(2);
      left = r2(left - a);
    }
    return out;
  }

  function onAmount(v: string) {
    setAmount(v);
    if (open) setApplied(distribute(open, Number(v) || 0));
  }

  function setApply(inv: InvoiceListItem, v: string) {
    const next = { ...applied, [inv.id]: v };
    if (!v) delete next[inv.id];
    setApplied(next);
    setAmount(r2(Object.values(next).reduce((s, x) => s + (Number(x) || 0), 0)).toFixed(2));
  }

  const problems = useMemo(() => {
    const p: string[] = [];
    if (!customerId) p.push("Choose the customer.");
    if (!accountId) p.push("Choose the account the money went into.");
    if (!(received > 0)) p.push("Enter the amount received.");
    if (open && open.some((i) => (Number(applied[i.id]) || 0) > i.balance + 0.001)) p.push("An invoice is getting more than its balance.");
    if (received > 0 && Math.abs(appliedTotal - received) > 0.001) {
      p.push(appliedTotal < received
        ? `Apply all of it: ${money(received - appliedTotal)} isn't applied to an invoice yet.`
        : `You've applied ${money(appliedTotal - received)} more than was received.`);
    }
    return p;
  }, [customerId, accountId, received, appliedTotal, applied, open]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (problems.length) { toast.error(problems[0] ?? "Check the payment"); return; }
    setBusy(true);
    try {
      const p = await api.receivePayment({
        customer_id: customerId, payment_date: date, account_id: accountId, amount: r2(received), method: method || null,
        reference: reference.trim() || null, memo: memo.trim() || null, transaction_id: match || null,
        applications: Object.entries(applied).filter(([, v]) => Number(v) > 0).map(([invoice_id, v]) => ({ invoice_id, amount: r2(Number(v)) })),
      });
      toast.success(`Payment of ${money(p.amount)} recorded`);
      const only = p.applications.length === 1 ? p.applications[0] : undefined;
      navigate(fromTxn ? "/banking" : only ? `/invoices/${only.invoice_id}` : "/invoices");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not record the payment");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <Link to={fromInvoice ? `/invoices/${fromInvoice}` : "/invoices"} className="back">{fromInvoice ? "Invoice" : "Invoices"}</Link>
          <h1>Receive payment</h1>
          <p className="muted">Record money a customer paid you and which invoices it covers.</p>
        </div>
        <div className="head-status"><span className="head-amount">{money(received)} <span className="muted small">received</span></span></div>
      </header>

      <ModuleNotice module="invoicing" />
      <form className="panel form" onSubmit={save} noValidate>
        <div className="grid-3">
          <label className="field"><span>Customer</span>
            <select value={customerId} onChange={(e) => { setCustomerId(e.target.value); }}>
              <option value="">Choose a customer</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}{c.open_balance ? ` (${money(c.open_balance)} open)` : ""}</option>)}
            </select></label>
          <label className="field"><span>Payment date</span>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
          <label className="field"><span>Amount received</span>
            <div className="money-input"><span>{currencySymbol().trim()}</span>
              <input inputMode="decimal" value={amount} placeholder="0.00"
                onChange={(e) => onAmount(e.target.value.replace(/[^0-9.]/g, ""))}
                onBlur={() => received > 0 && setAmount(received.toFixed(2))} /></div></label>
        </div>
        <div className="grid-3">
          <label className="field"><span>Payment method</span>
            <select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethodIn | "")}>
              <option value="">Not specified</option>
              {methodOptions("received", method).map((m) => <option key={m.code} value={m.code}>{m.label}</option>)}
            </select></label>
          <label className="field"><span>Reference no.</span>
            <input value={reference} maxLength={100} placeholder="Check or confirmation number" onChange={(e) => setReference(e.target.value)} /></label>
          <label className="field"><span>Deposit to</span>
            <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">Choose the account</option>
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select></label>
        </div>

        <div className="field"><span>Outstanding invoices</span>
          {!customerId ? <p className="muted">Choose a customer to see their open invoices.</p>
            : open === null ? <p className="muted">Loading…</p>
            : open.length === 0 ? <p className="muted">This customer has no open invoices. <Link to={`/invoices/new?customer=${customerId}`}>Create one</Link> first.</p>
            : (
              <table className="ledger apply-table">
                <thead><tr><th className="center"><span className="sr-only">Apply</span></th><th>Invoice</th><th>Date</th><th>Due</th>
                  <th className="num">Original amount</th><th className="num">Open balance</th><th className="num">Payment</th></tr></thead>
                <tbody>
                  {open.map((i) => {
                    const v = applied[i.id] ?? "";
                    return (
                      <tr key={i.id} className={Number(v) > 0 ? "selected-row" : ""}>
                        <td className="center"><input type="checkbox" checked={Number(v) > 0} aria-label={`Apply to invoice ${i.invoice_number}`}
                          onChange={(e) => setApply(i, e.target.checked ? i.balance.toFixed(2) : "")} /></td>
                        <td>Invoice #{i.invoice_number}</td>
                        <td className="nowrap">{formatDate(i.invoice_date)}</td>
                        <td className={i.status === "overdue" ? "nowrap overdue-text" : "nowrap"}>{formatDate(i.due_date)}</td>
                        <td className="num">{money(i.total)}</td>
                        <td className="num">{money(i.balance)}</td>
                        <td className="num"><div className="money-input small-money"><span aria-hidden="true">{currencySymbol().trim()}</span>
                          <input inputMode="decimal" value={v} aria-label={`Payment for invoice ${i.invoice_number}`}
                            onChange={(e) => setApply(i, e.target.value.replace(/[^0-9.]/g, ""))} /></div></td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot><tr><td colSpan={6} className="num">Amount to apply</td><td className="num">{money(appliedTotal)}</td></tr></tfoot>
              </table>
            )}
        </div>

        <div className="field"><span>Match to the bank deposit</span>
          {!accountId || !(received > 0) ? <p className="muted">Enter the amount and account to look for the deposit in Banking.</p>
            : candidates.length === 0 ? (
              <p className="muted">No imported deposit of {money(received)} in this account near {formatDate(date)}. That's fine: the payment is
                recorded now, and when the statement is imported you can match it from Banking.</p>
            ) : (
              <ul className="cand-list match-list">
                {candidates.map((c) => (
                  <li key={c.id}><label className="check">
                    <input type="radio" name="match" checked={match === c.id} onChange={() => setMatch(c.id)} />
                    <span>{formatDate(c.txn_date)} · {c.description} · <strong>{money(c.amount)}</strong>
                      {c.review_status === "approved" && <span className="tag">already in your books</span>}</span>
                  </label></li>
                ))}
                <li><label className="check"><input type="radio" name="match" checked={match === ""} onChange={() => setMatch("")} />
                  <span>Don't match (this payment isn't in the imported statements)</span></label></li>
              </ul>
            )}
          {match && <p className="hint">The matched deposit is approved in Banking and counted once, through this payment.</p>}
        </div>

        <label className="field"><span>Memo</span>
          <input value={memo} maxLength={500} onChange={(e) => setMemo(e.target.value)} /></label>

        {problems.length > 0 && customerId && received > 0 && <p className="hint">{problems[0]}</p>}
        <div className="form-actions">
          <span className="spacer" />
          <Link className="btn" to={fromInvoice ? `/invoices/${fromInvoice}` : "/invoices"}>Cancel</Link>
          <button type="submit" className="btn btn-primary" disabled={!on || busy || problems.length > 0}>{busy ? "Saving…" : "Save payment"}</button>
        </div>
      </form>
    </div>
  );
}
