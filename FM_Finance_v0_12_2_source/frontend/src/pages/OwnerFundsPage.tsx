import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useToast } from "../context";
import { formatDate, money, today } from "../format";
import type { Account, OwnerFunds, OwnerFundsAction, Txn } from "../types";

export default function OwnerFundsPage() {
  const toast = useToast();
  const [data, setData] = useState<OwnerFunds | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [transactions, setTransactions] = useState<Txn[]>([]);
  const [action, setAction] = useState<OwnerFundsAction>("repayment");
  const [entryDate, setEntryDate] = useState(today());
  const [amount, setAmount] = useState("");
  const [accountId, setAccountId] = useState("");
  const [transactionId, setTransactionId] = useState("");
  const [memo, setMemo] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    Promise.all([api.ownerFunds(), api.accounts(), api.transactions({ tab: "review", sort: "date_desc" }, 1, 200)])
      .then(([owner, accts, txns]) => {
        setData(owner);
        setAccounts(accts.filter((a) => a.is_active && a.kind !== "credit_card"));
        setTransactions(txns.items.filter((t) => !t.is_transfer && !t.expense_id && !t.duplicate_of));
        if (!accountId) setAccountId(accts.find((a) => a.is_active && a.kind !== "credit_card")?.id ?? "");
      }).catch((e: Error) => toast.error(e.message));
  }
  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const candidates = useMemo(() => transactions.filter((t) => action === "loan" ? t.amount > 0 : t.amount < 0),
    [transactions, action]);

  function chooseTransaction(id: string) {
    setTransactionId(id);
    const t = transactions.find((x) => x.id === id);
    if (t) {
      setAmount(Math.abs(t.amount).toFixed(2));
      setEntryDate(t.txn_date);
      setAccountId(t.account_id);
    }
  }

  function changeAction(next: OwnerFundsAction) {
    setAction(next);
    setTransactionId("");
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const value = Number(amount);
    if (!(value > 0)) { toast.error("Enter an amount greater than zero"); return; }
    if (action !== "opening_balance" && !transactionId && !accountId) {
      toast.error("Choose the business bank account"); return;
    }
    setBusy(true);
    try {
      const out = await api.recordOwnerFunds({
        action, entry_date: entryDate, amount: value,
        account_id: action === "opening_balance" ? null : accountId || null,
        transaction_id: transactionId || null, memo: memo.trim() || null,
      });
      setData(out); setAmount(""); setMemo(""); setTransactionId("");
      toast.success(action === "repayment" ? "Owner repayment recorded" : "Owner funds recorded");
      const txns = await api.transactions({ tab: "review", sort: "date_desc" }, 1, 200);
      setTransactions(txns.items.filter((t) => !t.is_transfer && !t.expense_id && !t.duplicate_of));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not record the owner funds");
    } finally { setBusy(false); }
  }

  return (
    <div className="page">
      <header className="page-head"><div><h1>Owner funds</h1>
        <p className="page-sub">Money the owner put into the business, repayments, and personally paid expenses.</p></div></header>

      <section className="summary-grid owner-summary">
        <div className="summary-card"><span>Owner loans still owed</span><strong>{money(data?.loan_balance ?? 0)}</strong>
          <small>Loan principal; not an expense</small></div>
        <div className="summary-card"><span>Expense reimbursements owed</span><strong>{money(data?.reimbursement_balance ?? 0)}</strong>
          <small>Approved expenses paid personally</small></div>
        <div className="summary-card accent"><span>Total owed to owner</span><strong>{money(data?.total_owed ?? 0)}</strong>
          <small>Shown on the Balance Sheet</small></div>
      </section>

      <div className="two-col owner-grid">
        <form className="panel form" onSubmit={save}>
          <h2>Record owner money</h2>
          <label className="field"><span>What happened?</span>
            <select value={action} onChange={(e) => changeAction(e.target.value as OwnerFundsAction)}>
              <option value="repayment">The business repaid the owner</option>
              <option value="loan">The owner loaned money to the business</option>
              <option value="opening_balance">An existing opening balance was owner money</option>
            </select></label>

          {action !== "opening_balance" && (
            <label className="field"><span>Use an imported bank transaction (recommended)</span>
              <select value={transactionId} onChange={(e) => chooseTransaction(e.target.value)}>
                <option value="">No—record it manually</option>
                {candidates.map((t) => <option key={t.id} value={t.id}>
                  {formatDate(t.txn_date)} · {t.account_name} · {money(Math.abs(t.amount))} · {t.description}
                </option>)}
              </select>
              <small>Selecting the bank transaction records it once and removes it from “For review.”</small>
            </label>
          )}

          <div className="grid-2">
            <label className="field"><span>Date</span><input type="date" required value={entryDate}
              disabled={Boolean(transactionId)} onChange={(e) => setEntryDate(e.target.value)} /></label>
            <label className="field"><span>Amount</span><input inputMode="decimal" required value={amount}
              disabled={Boolean(transactionId)} onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))} /></label>
          </div>
          {action !== "opening_balance" && (
            <label className="field"><span>Business bank account</span>
              <select value={accountId} disabled={Boolean(transactionId)} onChange={(e) => setAccountId(e.target.value)}>
                <option value="">Choose an account</option>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}{a.last4 ? ` ··${a.last4}` : ""}</option>)}
              </select></label>
          )}
          <label className="field"><span>Memo (optional)</span><input value={memo} maxLength={500}
            placeholder={action === "repayment" ? "Partial repayment to owner" : "Owner funds"}
            onChange={(e) => setMemo(e.target.value)} /></label>
          {action === "opening_balance" && <div className="callout">Use this only when the bank account's opening balance already
            includes the owner's money. It reclassifies Opening Balance Equity and does not change cash.</div>}
          <div className="form-actions"><span className="spacer" />
            <button className="btn btn-primary" disabled={busy} type="submit">{busy ? "Saving…" : "Record it"}</button></div>
        </form>

        <section className="panel">
          <h2>Personally paid business expense?</h2>
          <p>Enter it as an expense and choose <strong>Paid personally</strong>. The amount appears here under expense
            reimbursements. When the business pays you back, mark that expense reimbursed and select the bank account.</p>
          <Link className="btn" to="/expenses/new">Add personally paid expense</Link>
          <hr />
          <h2>What your accountant sees</h2>
          <p>Owner loans and reimbursements stay on the Balance Sheet. Repaying loan principal lowers cash and the liability;
            it does not lower profit.</p>
          <Link to="/reports">Open financial reports</Link>
        </section>
      </div>

      <section className="panel flush">
        <div className="panel-head"><h2>Owner-funds activity</h2>
          {data && <Link to={`/chart-of-accounts/${data.due_to_owner_account_id}`}>Open Due to Owner register</Link>}</div>
        {!data ? <div className="empty inner"><p className="muted">Loading…</p></div>
          : data.activity.length === 0 ? <div className="empty inner"><p>No owner-funds activity yet.</p></div>
          : <div className="table-wrap"><table className="ledger"><thead><tr><th>Date</th><th>Type</th><th>Description</th>
              <th className="num">Increase</th><th className="num">Decrease</th></tr></thead><tbody>
            {data.activity.map((a, i) => <tr key={`${a.entry_id}-${i}`}><td>{formatDate(a.entry_date)}</td>
              <td>{a.account === "loan" ? "Owner loan" : "Expense reimbursement"}</td><td>{a.description}</td>
              <td className="num">{a.change > 0 ? money(a.change) : ""}</td>
              <td className="num">{a.change < 0 ? money(-a.change) : ""}</td></tr>)}
          </tbody></table></div>}
      </section>
    </div>
  );
}
