import { useEffect, useState } from "react";
import { useModule } from "../../modules";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useToast } from "../../context";
import { formatDate, money } from "../../format";
import type { Candidates, Customer, Txn } from "../../types";

interface Props {
  txn: Txn;
  customers: Customer[];
  onChanged: (t?: Txn) => void;
}

export default function TxnDetail({ txn, customers, onChanged }: Props) {
  const toast = useToast();
  const navigate = useNavigate();
  const [vendor, setVendor] = useState(txn.vendor_name ?? txn.suggested_vendor_name ?? "");
  const [customerId, setCustomerId] = useState(txn.customer_id ?? "");
  const [memo, setMemo] = useState(txn.memo ?? "");
  const [cands, setCands] = useState<Candidates | null>(null);
  const [busy, setBusy] = useState(false);
  const inflow = txn.amount > 0;
  const { on: invoicingOn } = useModule("invoicing");

  useEffect(() => {
    setVendor(txn.vendor_name ?? txn.suggested_vendor_name ?? "");
    setCustomerId(txn.customer_id ?? "");
    setMemo(txn.memo ?? "");
  }, [txn]);

  useEffect(() => {
    let live = true;
    api.candidates(txn.id).then((c) => { if (live) setCands(c); }).catch(() => setCands(null));
    return () => { live = false; };
  }, [txn.id, txn.is_transfer, txn.expense_id]);

  async function run<T>(fn: () => Promise<T>, success?: string): Promise<T | undefined> {
    setBusy(true);
    try {
      const out = await fn();
      if (success) toast.success(success);
      return out;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Something went wrong");
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function saveDetails() {
    const body: Record<string, string | null> = {};
    const currentVendor = txn.vendor_name ?? txn.suggested_vendor_name ?? "";
    if (vendor.trim() !== currentVendor) body.vendor_name = vendor.trim() || null;
    if ((customerId || null) !== txn.customer_id) body.customer_id = customerId || null;
    if ((memo.trim() || null) !== txn.memo) body.memo = memo.trim() || null;
    if (Object.keys(body).length === 0) return;
    const t = await run(() => api.updateTransaction(txn.id, body), "Saved");
    if (t) onChanged(t);
  }

  async function createExpense() {
    const e = await run(() => api.createExpenseFromTxn(txn.id));
    if (e) {
      toast.success("Expense created. Attach the receipt here.");
      navigate(`/expenses/${e.id}`);
    }
  }

  const locked = txn.review_status !== "unreviewed";

  return (
    <div className="txn-detail">
      <div className="txn-detail-grid">
        <section className="detail-block">
          <h3>Details</h3>
          <p className="raw-desc">{txn.description}</p>
          {txn.suggestion_reason && !txn.is_transfer && <p className="hint">Suggestion: {txn.suggestion_reason}</p>}
          <div className="grid-2">
            <label className="field"><span>{inflow ? "Payer" : "Vendor"}</span>
              <input value={vendor} maxLength={255} onChange={(e) => setVendor(e.target.value)} placeholder="Who was this?" /></label>
            {inflow ? (
              <label className="field"><span>Customer</span>
                <select value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                  <option value="">No customer</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select></label>
            ) : <span />}
          </div>
          <label className="field"><span>Memo</span>
            <input value={memo} maxLength={5000} onChange={(e) => setMemo(e.target.value)} placeholder="Optional note" /></label>
          <div className="form-actions">
            <button type="button" className="btn" disabled={busy} onClick={() => void saveDetails()}>Save details</button>
            <span className="spacer" />
            {txn.review_status === "excluded" || txn.review_status === "approved" ? (
              <button type="button" className="btn" disabled={busy}
                onClick={async () => { const t = await run(() => api.restoreTransaction(txn.id), "Moved back to review"); if (t) onChanged(t); }}>
                Move back to review
              </button>
            ) : (
              <button type="button" className="btn btn-danger-quiet" disabled={busy}
                onClick={async () => { const t = await run(() => api.excludeTransaction(txn.id), "Excluded"); if (t) onChanged(t); }}>
                Exclude
              </button>
            )}
          </div>
        </section>

        <section className="detail-block">
          {txn.allocation_account_name && (
            <div className="callout callout-ok"><strong>Owner funds</strong>
              <p>This is posted to {txn.allocation_account_name}, not to income or expenses. Manage it on the{" "}
                <Link to="/owner-funds">Owner funds</Link> page.</p></div>
          )}
          {txn.duplicate_of && (
            <div className="callout callout-warn">
              <strong>Possible duplicate</strong>
              <p>Same amount on {formatDate(txn.duplicate_of.txn_date)}: {txn.duplicate_of.description}</p>
              <div className="callout-actions">
                <button type="button" className="btn btn-danger-quiet" disabled={busy}
                  onClick={async () => { const t = await run(() => api.excludeTransaction(txn.id), "Excluded as duplicate"); if (t) onChanged(t); }}>
                  Exclude this one
                </button>
                <button type="button" className="btn" disabled={busy}
                  onClick={async () => { const t = await run(() => api.notDuplicate(txn.id)); if (t) onChanged(t); }}>
                  Not a duplicate
                </button>
              </div>
            </div>
          )}

          <h3>Transfer</h3>
          {txn.is_transfer && txn.transfer_peer ? (
            <div className="peer">
              <p>Paired with <strong>{money(txn.transfer_peer.amount)}</strong> in {txn.transfer_peer.account_name} on{" "}
                {formatDate(txn.transfer_peer.txn_date)}. Transfers move money between your own accounts and are not income or expense.</p>
              {!locked && (
                <button type="button" className="link-button" disabled={busy}
                  onClick={async () => { const t = await run(() => api.unlinkTransfer(txn.id), "Transfer unlinked"); if (t) onChanged(t); }}>
                  Not a transfer
                </button>
              )}
            </div>
          ) : cands && cands.transfers.length > 0 && !locked ? (
            <ul className="cand-list">
              {cands.transfers.map((c) => (
                <li key={c.id}>
                  <span>{formatDate(c.txn_date)} <span className="muted">{c.account_name}</span> {money(c.amount)}</span>
                  <button type="button" className="link-button" disabled={busy}
                    onClick={async () => { const t = await run(() => api.linkTransfer(txn.id, c.id), "Linked as transfer"); if (t) onChanged(t); }}>
                    Link as transfer
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="hint">No matching amount in your other accounts.</p>}

          {inflow && !txn.is_transfer && (invoicingOn || txn.customer_payment_id) && (
            <>
              <h3>Invoice payment</h3>
              {txn.customer_payment_id ? (
                <p>
                  This deposit is a customer payment on{" "}
                  {(txn.invoice_ids ?? []).map((iid, n) => (
                    <span key={iid}>{n > 0 ? ", " : ""}<Link to={`/invoices/${iid}`}>{(txn.invoice_ids ?? []).length > 1 ? `invoice ${n + 1}` : "this invoice"}</Link></span>
                  ))}. To undo it, remove the payment on the invoice.
                </p>
              ) : (
                <>
                  <Link className="btn" to={`/payments/new?transaction=${txn.id}&account=${txn.account_id}&amount=${txn.amount.toFixed(2)}&date=${txn.txn_date}${txn.customer_id ? `&customer=${txn.customer_id}` : ""}`}>
                    Receive payment
                  </Link>
                  <p className="hint">If a customer paid an invoice with this deposit, record it as their payment so the invoice is marked paid and the money isn't counted twice.</p>
                </>
              )}
            </>
          )}

          {!inflow && !txn.is_transfer && !txn.allocation_account_id && (
            <>
              <h3>Receipt</h3>
              {txn.bill_id ? (
                <p>
                  This is the payment of <Link to={`/bills/${txn.bill_id}`}>a bill</Link>
                  {txn.receipt_status === "attached" ? ", which has the bill attached" : ""}.
                  To undo it, remove the payment on the bill.
                </p>
              ) : txn.expense_id ? (
                <p>
                  {txn.receipt_status === "attached" ? "Receipt attached on " : "Linked to "}
                  <Link to={`/expenses/${txn.expense_id}`}>this expense</Link>
                  {txn.receipt_status !== "attached" && " (no receipt yet)"}.{" "}
                  {!locked && (
                    <button type="button" className="link-button" disabled={busy}
                      onClick={async () => { const t = await run(() => api.updateTransaction(txn.id, { expense_id: null })); if (t) onChanged(t); }}>
                      Unlink
                    </button>
                  )}
                </p>
              ) : (
                <>
                  {cands && cands.expenses.length > 0 && (
                    <ul className="cand-list">
                      {cands.expenses.map((e) => (
                        <li key={e.id}>
                          <span>{formatDate(e.expense_date)} {e.vendor_name ?? e.description} {money(e.amount)}
                            {e.receipt_count > 0 && <span className="tag">receipt</span>}</span>
                          <button type="button" className="link-button" disabled={busy}
                            onClick={async () => { const t = await run(() => api.updateTransaction(txn.id, { expense_id: e.id }), "Linked to expense"); if (t) onChanged(t); }}>
                            Link
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <button type="button" className="btn" disabled={busy} onClick={() => void createExpense()}>
                    Add receipt
                  </button>
                  <p className="hint">Creates an expense for this charge so you can attach the receipt.</p>
                </>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
