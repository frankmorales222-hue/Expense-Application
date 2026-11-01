import { useEffect, useState, type FormEvent } from "react";
import { useModule } from "../modules";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import BillDrop from "../components/BillDrop";
import ConfirmDialog from "../components/ConfirmDialog";
import LinesEditor, { blankLine, lineTotal, linesForApi, validateLines, type LineDraft } from "../components/LinesEditor";
import ReceiptUpload, { validateReceipt } from "../components/ReceiptUpload";
import StatusBadge from "../components/StatusBadge";
import { useAuth, useToast } from "../context";
import { ACCOUNT_KIND_LABEL, STATUS_ACTION, STATUS_LABEL, formatDateTime, methodOptions, money, today } from "../format";
import CustomFields from "../components/CustomFields";
import type { CustomValues,
  Account, AuditEntry, BillExtract, Category, Customer, ExpenseDetail, ExpenseInput, ExpenseStatus, PaymentMethod, Receipt,
  Vendor,
} from "../types";

interface FormState {
  expense_date: string;
  vendor_name: string;
  description: string;
  payment_account_id: string;
  lines: LineDraft[];
  payment_method: PaymentMethod | "";
  is_reimbursable: boolean;
  notes: string;
  invoice_number: string;
  custom: CustomValues;
}

const empty = (): FormState => ({
  expense_date: today(), vendor_name: "", description: "", payment_account_id: "", lines: [blankLine()],
  payment_method: "", is_reimbursable: false, notes: "", invoice_number: "", custom: {},
});

function fromExpense(e: ExpenseDetail): FormState {
  const lines = e.lines.length ? e.lines.map((l) => ({
    ...blankLine(l.category_id), description: l.description ?? "", amount: l.amount.toFixed(2), billable: l.billable,
    customer_id: l.customer_id ?? "",
  })) : [{ ...blankLine(e.category_id), amount: e.amount.toFixed(2) }];
  return {
    expense_date: e.expense_date, vendor_name: e.vendor_name ?? "", description: e.description,
    payment_account_id: e.is_reimbursable ? "" : e.payment_account_id ?? "", lines,
    payment_method: e.payment_method ?? "", is_reimbursable: e.is_reimbursable, notes: e.notes ?? "",
    invoice_number: e.invoice_number ?? "", custom: e.custom ?? {},
  };
}

function validate(f: FormState): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!f.expense_date) errors.expense_date = "Enter the date of the expense.";
  if (!f.description.trim()) errors.description = "Describe what this expense was for.";
  const lineErrors = validateLines(f.lines);
  for (const [k, v] of Object.entries(lineErrors)) errors[`line:${k}`] = v;
  if (lineTotal(f.lines) >= 1e10) errors["line:_"] = "The total is too large.";
  return errors;
}

export default function ExpenseFormPage() {
  const { id } = useParams();
  const isNew = !id;
  const navigate = useNavigate();
  const toast = useToast();
  const { settings } = useAuth();
  const maxMb = settings?.max_receipt_mb ?? 10;

  const [categories, setCategories] = useState<Category[]>([]);
  const [expense, setExpense] = useState<ExpenseDetail | null>(null);
  const [form, setForm] = useState<FormState>(empty);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [looksLikeBill, setLooksLikeBill] = useState<{ result: BillExtract; file: File } | null>(null);
  const { on: captureOn } = useModule("smart_capture");
  const { on: billsOn } = useModule("bills");
  const [repayAccount, setRepayAccount] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [pending, setPending] = useState<File[]>([]);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [statusBusy, setStatusBusy] = useState<ExpenseStatus | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [receiptToRemove, setReceiptToRemove] = useState<Receipt | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Fields filled from a bill: key -> "ok" (confident) or "check" (please verify).
  const [filled, setFilled] = useState<Record<string, "ok" | "check">>({});
  const [billFile, setBillFile] = useState<File | null>(null);

  useEffect(() => {
    api.categories(true).then(setCategories).catch((e: Error) => toast.error(e.message));
    // Employees can't list bank accounts or customers; their expenses are claims an approver completes.
    api.accounts().then(setAccounts).catch(() => setAccounts([]));
    api.customers().then(setCustomers).catch(() => setCustomers([]));
  }, [toast]);

  useEffect(() => {
    setErrors({});
    setPending([]);
    setFilled({});
    setBillFile(null);
    setLooksLikeBill(null);
    setLoadError(null);
    if (!id) {
      setExpense(null);
      setForm(empty());
      return;
    }
    api.getExpense(id)
      .then((e) => { setExpense(e); setForm(fromExpense(e)); })
      .catch((e: Error) => setLoadError(e.message));
  }, [id]);

  // Vendor autocomplete (debounced).
  useEffect(() => {
    const q = form.vendor_name.trim();
    const t = window.setTimeout(() => {
      api.vendors(q).then(setVendors).catch(() => setVendors([]));
    }, 200);
    return () => window.clearTimeout(t);
  }, [form.vendor_name]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    if (filled[key]) setFilled(({ [key]: _gone, ...rest }) => rest);
    if (errors[key]) setErrors(({ [key]: _removed, ...rest }) => rest);
  };

  const setLines = (lines: LineDraft[]) => {
    setForm((f) => ({ ...f, lines }));
    if (filled.lines) setFilled(({ lines: _gone, ...rest }) => rest);
    setErrors((e) => Object.fromEntries(Object.entries(e).filter(([k]) => !k.startsWith("line:"))));
  };
  const lineErrors = Object.fromEntries(Object.entries(errors).filter(([k]) => k.startsWith("line:"))
    .map(([k, v]) => [k.slice(5), v]));
  const canPickAccount = accounts.length > 0;

  function applyBill(r: BillExtract, file: File) {
    const mark: Record<string, "ok" | "check"> = {};
    const level = (k: string) => ((r.confidence[k] ?? 0) >= 0.75 ? "ok" : "check");
    setForm((f) => {
      const next = { ...f };
      if (r.expense_date) { next.expense_date = r.expense_date; mark.expense_date = level("expense_date"); }
      if (r.amount !== null || r.category_id) {
        next.lines = [{ ...blankLine(r.category_id ?? ""), amount: r.amount !== null ? r.amount.toFixed(2) : "" }];
        mark.lines = r.category_id && level("amount") === "ok" ? "ok" : "check";
      }
      if (r.vendor_name) { next.vendor_name = r.vendor_name; mark.vendor_name = level("vendor"); }
      if (r.description) { next.description = r.description; mark.description = "check"; }
      if (r.invoice_number) { next.invoice_number = r.invoice_number; mark.invoice_number = level("invoice_number"); }
      if (r.bank_match) next.payment_account_id = accounts.find((a) => a.name === r.bank_match?.account_name)?.id ?? "";
      return next;
    });
    setFilled(mark);
    setErrors({});
    // The bill becomes the receipt; replace a previously read bill rather than stacking copies.
    setPending((p) => [...p.filter((x) => x !== billFile), file]);
    setBillFile(file);
    // A bill that's still to be paid belongs in Bills (Accounts Payable), not Expenses.
    setLooksLikeBill(r.due_date && canPickAccount ? { result: r, file } : null);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const v = validate(form);
    setErrors(v);
    if (Object.keys(v).length) return;
    const body: ExpenseInput = {
      expense_date: form.expense_date,
      vendor_name: form.vendor_name.trim() || null,
      description: form.description.trim(),
      lines: linesForApi(form.lines),
      payment_account_id: form.is_reimbursable ? null : form.payment_account_id || null,
      payment_method: form.payment_method || null,
      is_reimbursable: form.is_reimbursable,
      notes: form.notes.trim() || null,
      invoice_number: form.invoice_number.trim() || null,
      due_date: null,
      custom: form.custom,
    };
    setSaving(true);
    try {
      if (isNew) {
        const created = await api.createExpense(body);
        const failed: string[] = [];
        for (const file of pending) {
          try {
            await api.uploadReceipt(created.id, file);
          } catch (err) {
            failed.push(`${file.name} (${err instanceof Error ? err.message : "upload failed"})`);
          }
        }
        if (failed.length) toast.error(`Expense saved, but these receipts did not upload: ${failed.join(", ")}`);
        else toast.success(created.status === "pending" ? "Expense saved and sent for approval" : "Expense saved");
        navigate(`/expenses/${created.id}`, { replace: true });
      } else if (id) {
        const updated = await api.updateExpense(id, body);
        setExpense(updated);
        setForm(fromExpense(updated));
        toast.success("Changes saved");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the expense");
    } finally {
      setSaving(false);
    }
  }

  async function addFiles(files: File[]) {
    const good: File[] = [];
    for (const f of files) {
      const problem = validateReceipt(f, maxMb);
      if (problem) toast.error(problem); else good.push(f);
    }
    if (!good.length) return;
    if (isNew || !id) {
      setPending((p) => [...p, ...good]);
      return;
    }
    setUploading(true);
    try {
      for (const f of good) {
        try {
          await api.uploadReceipt(id, f);
          toast.success(`Attached ${f.name}`);
        } catch (err) {
          toast.error(`${f.name}: ${err instanceof Error ? err.message : "upload failed"}`);
        }
      }
      setExpense(await api.getExpense(id));
    } finally {
      setUploading(false);
    }
  }

  async function removeReceipt() {
    if (!receiptToRemove || !id) return;
    try {
      await api.deleteReceipt(receiptToRemove.id);
      setExpense(await api.getExpense(id));
      toast.success("Receipt removed");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not remove the receipt");
    } finally {
      setReceiptToRemove(null);
    }
  }

  async function changeStatus(status: ExpenseStatus) {
    if (!id) return;
    if (status === "paid" && expense?.is_reimbursable && canPickAccount && !repayAccount) {
      toast.error("Choose the account the reimbursement was paid from");
      return;
    }
    setStatusBusy(status);
    try {
      const updated = await api.setStatus(id, status, undefined,
        status === "paid" && expense?.is_reimbursable ? repayAccount || undefined : undefined);
      setExpense(updated);
      toast.success(`Status changed to ${STATUS_LABEL[status].toLowerCase()}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not change the status");
    } finally {
      setStatusBusy(null);
    }
  }

  async function deleteExpense() {
    if (!id) return;
    try {
      await api.deleteExpense(id);
      toast.success("Expense deleted");
      navigate("/expenses", { replace: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete the expense");
      setConfirmDelete(false);
    }
  }

  if (loadError) {
    return (
      <div className="page">
        <section className="empty">
          <h2>This expense can't be opened</h2>
          <p>{loadError}</p>
          <Link className="btn" to="/expenses">Back to expenses</Link>
        </section>
      </div>
    );
  }
  if (!isNew && !expense) return <div className="page"><p className="muted">Loading…</p></div>;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <Link to="/expenses" className="back">Expenses</Link>
          <h1>{isNew ? "Add expense" : expense?.description}</h1>
        </div>
        {expense && (
          <div className="head-status">
            <StatusBadge status={expense.status} />
            <span className="head-amount">{money(expense.amount, expense.currency)}</span>
          </div>
        )}
      </header>

      <div className="form-layout">
        <form className="panel form" onSubmit={submit} noValidate>
          {isNew && captureOn && <BillDrop onFilled={applyBill} />}
          {looksLikeBill && billsOn && (
            <div className="callout callout-warn">
              <strong>This looks like a bill you still have to pay</strong>
              <p>It has a due date ({looksLikeBill.result.due_date}). Bills track what you owe until you pay them.
                An expense is for something already paid.</p>
              <div className="callout-actions">
                <button type="button" className="btn btn-primary"
                  onClick={() => navigate("/bills/new", { state: { extract: looksLikeBill.result, file: looksLikeBill.file } })}>
                  Enter it as a bill
                </button>
                <button type="button" className="btn" onClick={() => setLooksLikeBill(null)}>It's already paid</button>
              </div>
            </div>
          )}

          <div className="grid-2">
            <Field label="Payee" filled={filled.vendor_name}>
              <input list="vendor-options" placeholder="Who you paid" value={form.vendor_name} maxLength={255}
                onChange={(e) => set("vendor_name", e.target.value)} autoComplete="off" />
              <datalist id="vendor-options">
                {vendors.map((v) => <option key={v.id} value={v.name} />)}
              </datalist>
            </Field>
            {form.is_reimbursable ? (
              <Field label="Payment account">
                <div className="static-field">Paid personally (owed back)</div>
              </Field>
            ) : canPickAccount ? (
              <Field label="Payment account" error={errors.payment_account_id}>
                <select value={form.payment_account_id} onChange={(e) => set("payment_account_id", e.target.value)}>
                  <option value="">Choose the account that paid</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.name} ({ACCOUNT_KIND_LABEL[a.kind]}{a.last4 ? ` ${a.last4}` : ""})</option>
                  ))}
                </select>
              </Field>
            ) : <span />}
          </div>

          <div className="grid-3">
            <Field label="Payment date" error={errors.expense_date} filled={filled.expense_date}>
              <input type="date" value={form.expense_date} max="2100-12-31" onChange={(e) => set("expense_date", e.target.value)} />
            </Field>
            <Field label="Payment method">
              <select value={form.payment_method} onChange={(e) => set("payment_method", e.target.value as PaymentMethod | "")}>
                <option value="">Not specified</option>
                {methodOptions("expense", form.payment_method).map((p) => <option key={p.code} value={p.code}>{p.label}</option>)}
              </select>
            </Field>
            <Field label="Ref no." filled={filled.invoice_number}>
              <input value={form.invoice_number} maxLength={100} placeholder="Receipt or invoice #"
                onChange={(e) => set("invoice_number", e.target.value)} />
            </Field>
          </div>

          <Field label="Description" error={errors.description} filled={filled.description}>
            <input placeholder="What was this for?" value={form.description} maxLength={500}
              onChange={(e) => set("description", e.target.value)} />
          </Field>

          <div className={filled.lines ? `field filled filled-${filled.lines}` : "field"}>
            <span>Category details{filled.lines && <em className="filled-tag">{filled.lines === "ok" ? "From bill" : "Check this"}</em>}</span>
            <LinesEditor lines={form.lines} categories={categories} customers={customers} errors={lineErrors}
              highlight={!!filled.lines} onChange={setLines} />
          </div>

          <label className="check">
            <input type="checkbox" checked={form.is_reimbursable} onChange={(e) => set("is_reimbursable", e.target.checked)} />
            <span>I paid this personally and the business owes me back</span>
          </label>
          {!form.is_reimbursable && canPickAccount && !form.payment_account_id && (
            <p className="hint warn-text">Without a payment account the expense is held in "Payment Account Not Set" until you choose one.</p>
          )}

          <Field label="Memo">
            <textarea rows={2} value={form.notes} maxLength={5000} onChange={(e) => set("notes", e.target.value)} />
          </Field>

          <CustomFields entity="expense" value={form.custom} onChange={(v) => set("custom", v)} />

          <div className="form-actions">
            {!isNew && (
              <button type="button" className="btn btn-danger-quiet" onClick={() => setConfirmDelete(true)}>Delete expense</button>
            )}
            <span className="spacer" />
            <span className="form-total">Total <strong>{money(lineTotal(form.lines))}</strong></span>
            <Link className="btn" to="/expenses">Cancel</Link>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Saving…" : isNew ? "Save expense" : "Save changes"}
            </button>
          </div>
        </form>

        <aside className="side">
          <section className="panel">
            <h2>Receipts</h2>
            <ReceiptUpload
              receipts={expense?.receipts ?? []}
              pending={pending}
              maxMb={maxMb}
              busy={uploading}
              onAdd={(files) => void addFiles(files)}
              onRemovePending={(i) => setPending((p) => p.filter((_, idx) => idx !== i))}
              onDelete={isNew ? undefined : setReceiptToRemove}
            />
          </section>

          {expense && expense.allowed_transitions.length > 0 && (
            <section className="panel">
              <h2>Status</h2>
              {expense.is_reimbursable && expense.allowed_transitions.includes("paid") && canPickAccount && (
                <label className="field"><span>Repaid from</span>
                  <select value={repayAccount} onChange={(e) => setRepayAccount(e.target.value)}>
                    <option value="">Choose the account</option>
                    {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                  </select></label>
              )}
              {expense.is_reimbursable && expense.status === "paid" && expense.payment_account_name && (
                <p className="hint">Repaid from {expense.payment_account_name}.</p>
              )}
              <div className="status-actions">
                {expense.allowed_transitions.map((s) => (
                  <button key={s} type="button" className={s === "rejected" ? "btn btn-danger-quiet" : "btn"}
                    disabled={statusBusy !== null} onClick={() => void changeStatus(s)}>
                    {statusBusy === s ? "Updating…" : expense.status === "paid" && s === "approved" ? "Undo paid" : STATUS_ACTION[s]}
                  </button>
                ))}
              </div>
            </section>
          )}

          {expense && (
            <section className="panel">
              <h2>History</h2>
              <ol className="history">
                {expense.history.map((h) => (
                  <li key={h.id}>
                    <div>{describe(h)}</div>
                    <div className="muted small">{h.user_name ?? "System"}, {formatDateTime(h.created_at)}</div>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </aside>
      </div>

      <ConfirmDialog open={confirmDelete} title="Delete this expense?" danger confirmLabel="Delete expense"
        message="It will be removed from lists and reports. The audit history is kept."
        onConfirm={() => void deleteExpense()} onCancel={() => setConfirmDelete(false)} />
      <ConfirmDialog open={receiptToRemove !== null} title="Remove this receipt?" danger confirmLabel="Remove receipt"
        message={receiptToRemove ? `${receiptToRemove.original_filename} will be permanently deleted.` : ""}
        onConfirm={() => void removeReceipt()} onCancel={() => setReceiptToRemove(null)} />
    </div>
  );
}

function Field({ label, error, filled, children }: {
  label: string; error?: string; filled?: "ok" | "check"; children: React.ReactNode;
}) {
  const cls = ["field", error ? "has-error" : "", filled ? `filled filled-${filled}` : ""].filter(Boolean).join(" ");
  return (
    <label className={cls}>
      <span>{label}{filled && <em className="filled-tag">{filled === "ok" ? "From bill" : "Check this"}</em>}</span>
      {children}
      {error && <small className="field-error">{error}</small>}
    </label>
  );
}

const FIELD_NAMES: Record<string, string> = {
  expense_date: "date", vendor: "vendor", category: "category", description: "description",
  amount: "amount", payment_method: "payment method", is_reimbursable: "reimbursable", notes: "memo",
  invoice_number: "ref no.", due_date: "due date", payment_account: "payment account", lines: "category details",
  custom: "more details",
};

function describe(h: AuditEntry): string {
  const c = h.changes ?? {};
  switch (h.action) {
    case "created": return "Created";
    case "deleted": return "Deleted";
    case "receipt_added": return `Attached ${String(c.filename ?? "a receipt")}`;
    case "receipt_removed": return `Removed ${String(c.filename ?? "a receipt")}`;
    case "status_changed": {
      const [from, to] = (c.status as [ExpenseStatus, ExpenseStatus] | undefined) ?? [];
      return from && to ? `Status: ${STATUS_LABEL[from]} to ${STATUS_LABEL[to]}` : "Status changed";
    }
    case "updated": {
      const fields = Object.keys(c).map((k) => FIELD_NAMES[k] ?? k);
      return fields.length ? `Changed ${fields.join(", ")}` : "Updated";
    }
    default: return h.action.replace(/_/g, " ");
  }
}
