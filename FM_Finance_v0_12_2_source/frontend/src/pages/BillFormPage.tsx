import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ModuleNotice, useModule } from "../modules";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import BillDrop from "../components/BillDrop";
import ConfirmDialog from "../components/ConfirmDialog";
import LinesEditor, { blankLine, lineTotal, linesForApi, validateLines, type LineDraft } from "../components/LinesEditor";
import { useAuth, useToast } from "../context";
import { currencySymbol, defaultTerm, dueDateFor, fileSize, formatDate, money, termOptions, today } from "../format";
import CustomFields from "../components/CustomFields";
import type { Account, BillDetail, BillExtract, BillTerms, Category, Customer, CustomValues, PeerTxn, Vendor } from "../types";

const STATUS_LABEL = { open: "Open", partial: "Partly paid", paid: "Paid", overdue: "Overdue" } as const;

interface FormState {
  vendor_name: string;
  bill_date: string;
  terms: BillTerms | "";
  due_date: string;
  bill_number: string;
  memo: string;
  lines: LineDraft[];
  custom: CustomValues;
}

const empty = (): FormState => {
  const terms = defaultTerm("bill");
  return { vendor_name: "", bill_date: today(), terms, due_date: dueDateFor(terms, today()),
    bill_number: "", memo: "", lines: [blankLine()], custom: {} };
};

function fromBill(b: BillDetail): FormState {
  return {
    vendor_name: b.vendor_name, bill_date: b.bill_date, terms: b.terms ?? "", due_date: b.due_date,
    bill_number: b.bill_number ?? "", memo: b.memo ?? "", custom: b.custom ?? {},
    lines: b.lines.map((l) => ({ ...blankLine(l.category_id), description: l.description ?? "", amount: l.amount.toFixed(2),
      billable: l.billable, customer_id: l.customer_id ?? "" })),
  };
}

export default function BillFormPage() {
  const { id } = useParams();
  const isNew = !id;
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const { user } = useAuth();
  const { on: billsOn } = useModule("bills");
  const { on: captureOn } = useModule("smart_capture");
  const readOnly = user?.role === "viewer" || !billsOn;
  const [bill, setBill] = useState<BillDetail | null>(null);
  const [form, setForm] = useState<FormState>(empty);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [categories, setCategories] = useState<Category[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [filledFromBill, setFilledFromBill] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.categories(true).then(setCategories).catch(() => setCategories([]));
    api.customers().then(setCustomers).catch(() => setCustomers([]));
    api.accounts().then(setAccounts).catch(() => setAccounts([]));
  }, []);

  const load = useCallback(() => {
    if (!id) return;
    api.getBill(id).then((b) => { setBill(b); setForm(fromBill(b)); }).catch((e: Error) => toast.error(e.message));
  }, [id, toast]);

  const apply = useCallback((r: BillExtract, file: File) => {
    setForm((f) => {
      const bill_date = r.expense_date ?? f.bill_date;
      const due_date = r.due_date ?? (f.terms ? dueDateFor(f.terms, bill_date) : f.due_date);
      return {
        ...f, vendor_name: r.vendor_name ?? f.vendor_name, bill_date, due_date, terms: r.due_date ? "" : f.terms,
        bill_number: r.invoice_number ?? f.bill_number, memo: r.description ?? f.memo,
        lines: [{ ...blankLine(r.category_id ?? ""), amount: r.amount !== null ? r.amount.toFixed(2) : "" }],
      };
    });
    setPendingFile(file);
    setFilledFromBill(true);
  }, []);

  useEffect(() => {
    if (id) { load(); return; }
    setBill(null);
    setForm(empty());
    // Arrived from the expense form with a bill that was already read.
    const state = location.state as { extract?: BillExtract; file?: File } | null;
    if (state?.extract && state.file) apply(state.extract, state.file);
  }, [id, load, location.state, apply]);

  useEffect(() => {
    const t = window.setTimeout(() => api.vendors(form.vendor_name.trim()).then(setVendors).catch(() => setVendors([])), 200);
    return () => window.clearTimeout(t);
  }, [form.vendor_name]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((f) => {
      const next = { ...f, [key]: value };
      if ((key === "terms" || key === "bill_date") && next.terms) {
        next.due_date = dueDateFor(next.terms, next.bill_date);
      }
      if (key === "due_date") next.terms = "";
      return next;
    });
    setErrors(({ [key]: _gone, ...rest }) => rest);
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!form.vendor_name.trim()) errs.vendor_name = "Enter the vendor.";
    if (!form.bill_date) errs.bill_date = "Enter the bill date.";
    if (!form.due_date) errs.due_date = "Enter the due date.";
    for (const [k, v] of Object.entries(validateLines(form.lines))) errs[`line:${k}`] = v;
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const body = {
      vendor_name: form.vendor_name.trim(), bill_date: form.bill_date, terms: form.terms || null,
      due_date: form.due_date, bill_number: form.bill_number.trim() || null, memo: form.memo.trim() || null,
      lines: linesForApi(form.lines), custom: form.custom,
    };
    setSaving(true);
    try {
      if (isNew) {
        const created = await api.createBill(body);
        if (pendingFile) {
          try { await api.uploadBillAttachment(created.id, pendingFile); } catch (err) {
            toast.error(`Bill saved, but the file didn't attach: ${err instanceof Error ? err.message : "upload failed"}`);
          }
        }
        toast.success("Bill saved");
        navigate(`/bills/${created.id}`, { replace: true });
      } else if (id) {
        setBill(await api.updateBill(id, body));
        toast.success("Changes saved");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the bill");
    } finally {
      setSaving(false);
    }
  }

  async function attach(file: File | undefined) {
    if (!file || !id) return;
    try {
      await api.uploadBillAttachment(id, file);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not attach the file");
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const lineErrors = Object.fromEntries(Object.entries(errors).filter(([k]) => k.startsWith("line:")).map(([k, v]) => [k.slice(5), v]));
  const paid = bill?.paid ?? 0;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <Link to="/bills" className="back">Bills</Link>
          <h1>{isNew ? "Enter a bill" : `Bill from ${bill?.vendor_name ?? ""}`}</h1>
        </div>
        {bill && (
          <div className="head-status">
            <span className={`badge badge-bill-${bill.status}`}>{STATUS_LABEL[bill.status]}</span>
            <span className="head-amount">{money(bill.balance)} <span className="muted small">open</span></span>
          </div>
        )}
      </header>

      <ModuleNotice module="bills" />
      <div className="form-layout">
        <form className="panel form" onSubmit={submit} noValidate>
          {isNew && captureOn && !readOnly && <BillDrop onFilled={apply} />}
          {filledFromBill && <p className="hint ok-text">Filled from {pendingFile?.name}. Check the fields; the file is attached when you save.</p>}
          <div className="grid-2">
            <label className={errors.vendor_name ? "field has-error" : "field"}><span>Vendor</span>
              <input list="bill-vendors" value={form.vendor_name} maxLength={255} disabled={readOnly}
                onChange={(e) => set("vendor_name", e.target.value)} autoComplete="off" />
              <datalist id="bill-vendors">{vendors.map((v) => <option key={v.id} value={v.name} />)}</datalist>
              {errors.vendor_name && <small className="field-error">{errors.vendor_name}</small>}</label>
            <label className="field"><span>Bill no.</span>
              <input value={form.bill_number} maxLength={100} disabled={readOnly} onChange={(e) => set("bill_number", e.target.value)} /></label>
          </div>
          <div className="grid-3">
            <label className="field"><span>Bill date</span>
              <input type="date" value={form.bill_date} disabled={readOnly} onChange={(e) => set("bill_date", e.target.value)} /></label>
            <label className="field"><span>Terms</span>
              <select value={form.terms} disabled={readOnly} onChange={(e) => set("terms", e.target.value as BillTerms | "")}>
                <option value="">Custom due date</option>
                {termOptions(form.terms).map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
              </select></label>
            <label className={errors.due_date ? "field has-error" : "field"}><span>Due date</span>
              <input type="date" value={form.due_date} disabled={readOnly} onChange={(e) => set("due_date", e.target.value)} /></label>
          </div>
          <div className="field"><span>Category details</span>
            <LinesEditor lines={form.lines} categories={categories} customers={customers} errors={lineErrors}
              disabled={readOnly} highlight={filledFromBill}
              onChange={(lines) => { setForm((f) => ({ ...f, lines })); setErrors({}); }} />
          </div>
          <label className="field"><span>Memo</span>
            <textarea rows={2} value={form.memo} maxLength={5000} disabled={readOnly} onChange={(e) => set("memo", e.target.value)} /></label>
          <CustomFields entity="bill" value={form.custom} disabled={readOnly} onChange={(v) => set("custom", v)} />
          {!readOnly && (
            <div className="form-actions">
              {bill && bill.payments.length === 0 && (
                <button type="button" className="btn btn-danger-quiet" onClick={() => setConfirmDelete(true)}>Delete bill</button>
              )}
              <span className="spacer" />
              <span className="form-total">Total <strong>{money(lineTotal(form.lines))}</strong></span>
              <Link className="btn" to="/bills">Cancel</Link>
              <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? "Saving…" : isNew ? "Save bill" : "Save changes"}</button>
            </div>
          )}
        </form>

        <aside className="side">
          {bill && (
            <section className="panel">
              <h2>Payments</h2>
              {bill.payments.length === 0 ? <p className="muted">Nothing paid yet.</p> : (
                <ul className="pay-list">
                  {bill.payments.map((p) => (
                    <li key={p.id}>
                      <div><strong>{money(p.amount)}</strong> on {formatDate(p.payment_date)}
                        <div className="muted small">from {p.account_name}{p.transaction_id ? " · matched to the bank charge" : ""}</div></div>
                      {!readOnly && (
                        <button type="button" className="link-button danger" onClick={async () => {
                          if (!window.confirm("Remove this payment? The bill goes back to unpaid for this amount.")) return;
                          try { setBill(await api.deleteBillPayment(bill.id, p.id)); } catch (err) {
                            toast.error(err instanceof Error ? err.message : "Could not remove the payment");
                          }
                        }}>Remove</button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {!readOnly && bill.balance > 0 && (
                <PayBill bill={bill} accounts={accounts} onPaid={(b) => { setBill(b); toast.success("Payment recorded"); }} />
              )}
              <p className="small muted">Paid {money(paid)} of {money(bill.total)}</p>
            </section>
          )}
          {bill && (
            <section className="panel">
              <h2>Attachments</h2>
              {bill.attachments.length === 0 ? <p className="muted">No file attached.</p> : (
                <ul className="receipt-list">
                  {bill.attachments.map((a) => (
                    <li key={a.id}>
                      <a href={api.billAttachmentUrl(bill.id, a.id)} target="_blank" rel="noreferrer">{a.original_filename}</a>
                      <span className="muted">{fileSize(a.size_bytes)}</span>
                      {!readOnly && <button type="button" className="link-button danger" onClick={async () => {
                        await api.deleteBillAttachment(bill.id, a.id); load();
                      }}>Remove</button>}
                    </li>
                  ))}
                </ul>
              )}
              {!readOnly && <>
                <button type="button" className="btn" onClick={() => fileInput.current?.click()}>Attach a file</button>
                <input ref={fileInput} type="file" hidden accept=".pdf,.jpg,.jpeg,.png,.heic,.webp,.docx,.eml,.msg"
                  onChange={(e) => void attach(e.target.files?.[0])} />
              </>}
            </section>
          )}
          {isNew && pendingFile && (
            <section className="panel"><h2>Attachment</h2><p>{pendingFile.name} <span className="muted">attaches when you save</span></p></section>
          )}
        </aside>
      </div>

      <ConfirmDialog open={confirmDelete} title="Delete this bill?" danger confirmLabel="Delete bill"
        message="It comes off Accounts Payable and the reports. The history is kept."
        onConfirm={async () => {
          if (!id) return;
          try { await api.deleteBill(id); navigate("/bills", { replace: true }); } catch (err) {
            toast.error(err instanceof Error ? err.message : "Could not delete the bill"); setConfirmDelete(false);
          }
        }} onCancel={() => setConfirmDelete(false)} />
    </div>
  );
}

function PayBill({ bill, accounts, onPaid }: { bill: BillDetail; accounts: Account[]; onPaid: (b: BillDetail) => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [accountId, setAccountId] = useState("");
  const [date, setDate] = useState(today());
  const [amount, setAmount] = useState(bill.balance.toFixed(2));
  const [candidates, setCandidates] = useState<PeerTxn[]>([]);
  const [match, setMatch] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { setAmount(bill.balance.toFixed(2)); }, [bill.balance]);
  useEffect(() => {
    setMatch("");
    if (!open || !accountId || !(Number(amount) > 0) || !date) { setCandidates([]); return; }
    api.billPaymentCandidates(bill.id, accountId, Number(amount), date).then((c) => {
      setCandidates(c);
      if (c.length === 1 && c[0]) setMatch(c[0].id);
    }).catch(() => setCandidates([]));
  }, [open, accountId, amount, date, bill.id]);

  if (!open) return <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>Pay bill</button>;

  async function pay(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const b = await api.payBill(bill.id, { payment_date: date, account_id: accountId, amount: Number(Number(amount).toFixed(2)),
        memo: null, transaction_id: match || null });
      onPaid(b);
      setOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not record the payment");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form pay-form" onSubmit={pay}>
      <label className="field"><span>Paid from</span>
        <select value={accountId} onChange={(e) => setAccountId(e.target.value)} required>
          <option value="">Choose the account</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select></label>
      <div className="grid-2">
        <label className="field"><span>Payment date</span>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required /></label>
        <label className="field"><span>Amount</span>
          <div className="money-input"><span>{currencySymbol().trim()}</span>
            <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))} /></div></label>
      </div>
      {candidates.length > 0 && (
        <div className="field"><span>Matching bank charge</span>
          {candidates.map((c) => (
            <label key={c.id} className="check small">
              <input type="radio" name="match" checked={match === c.id} onChange={() => setMatch(c.id)} />
              <span>{formatDate(c.txn_date)} {c.description} {money(c.amount)}</span>
            </label>
          ))}
          <label className="check small"><input type="radio" name="match" checked={match === ""} onChange={() => setMatch("")} />
            <span>Not in the bank feed yet</span></label>
          <p className="hint">Matching marks that charge as reviewed, so it isn't counted twice.</p>
        </div>
      )}
      <div className="form-actions">
        <button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={busy || !accountId}>{busy ? "Saving…" : "Record payment"}</button>
      </div>
    </form>
  );
}
