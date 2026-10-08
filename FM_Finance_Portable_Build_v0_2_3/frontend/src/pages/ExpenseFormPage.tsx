import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import ReceiptUpload, { validateReceipt } from "../components/ReceiptUpload";
import StatusBadge from "../components/StatusBadge";
import { useAuth, useToast } from "../context";
import { PAYMENT_LABEL, STATUS_ACTION, STATUS_LABEL, formatDateTime, money, today } from "../format";
import type { AuditEntry, Category, ExpenseDetail, ExpenseInput, ExpenseStatus, PaymentMethod, Receipt, Vendor } from "../types";

interface FormState {
  expense_date: string;
  vendor_name: string;
  category_id: string;
  description: string;
  amount: string;
  payment_method: PaymentMethod | "";
  is_reimbursable: boolean;
  notes: string;
}

const EMPTY: FormState = {
  expense_date: today(), vendor_name: "", category_id: "", description: "", amount: "",
  payment_method: "", is_reimbursable: false, notes: "",
};

function fromExpense(e: ExpenseDetail): FormState {
  return {
    expense_date: e.expense_date, vendor_name: e.vendor_name ?? "", category_id: e.category_id,
    description: e.description, amount: e.amount.toFixed(2), payment_method: e.payment_method ?? "",
    is_reimbursable: e.is_reimbursable, notes: e.notes ?? "",
  };
}

function validate(f: FormState): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!f.expense_date) errors.expense_date = "Enter the date of the expense.";
  if (!f.category_id) errors.category_id = "Choose a category.";
  if (!f.description.trim()) errors.description = "Describe what this expense was for.";
  if (!/^\d+(\.\d{1,2})?$/.test(f.amount.trim()) || Number(f.amount) <= 0) {
    errors.amount = "Enter an amount greater than 0, with up to 2 decimal places.";
  } else if (Number(f.amount) >= 1e10) {
    errors.amount = "Amount is too large.";
  }
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
  const [form, setForm] = useState<FormState>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [pending, setPending] = useState<File[]>([]);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [statusBusy, setStatusBusy] = useState<ExpenseStatus | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [receiptToRemove, setReceiptToRemove] = useState<Receipt | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    api.categories(true).then(setCategories).catch((e: Error) => toast.error(e.message));
  }, [toast]);

  useEffect(() => {
    setErrors({});
    setPending([]);
    setLoadError(null);
    if (!id) {
      setExpense(null);
      setForm(EMPTY);
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
    if (errors[key]) setErrors(({ [key]: _removed, ...rest }) => rest);
  };

  // Active categories, plus the current one even if it was deactivated later.
  const categoryOptions = categories.filter((c) => c.is_active || c.id === form.category_id);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const v = validate(form);
    setErrors(v);
    if (Object.keys(v).length) return;
    const body: ExpenseInput = {
      expense_date: form.expense_date,
      vendor_name: form.vendor_name.trim() || null,
      category_id: form.category_id,
      description: form.description.trim(),
      amount: Number(form.amount),
      payment_method: form.payment_method || null,
      is_reimbursable: form.is_reimbursable,
      notes: form.notes.trim() || null,
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
    setStatusBusy(status);
    try {
      const updated = await api.setStatus(id, status);
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
          <div className="grid-2">
            <Field label="Date" error={errors.expense_date}>
              <input type="date" value={form.expense_date} max="2100-12-31" onChange={(e) => set("expense_date", e.target.value)} />
            </Field>
            <Field label="Amount" error={errors.amount}>
              <div className="money-input">
                <span aria-hidden="true">$</span>
                <input inputMode="decimal" placeholder="0.00" value={form.amount}
                  onChange={(e) => set("amount", e.target.value.replace(/[^0-9.]/g, ""))}
                  onBlur={() => { const n = Number(form.amount); if (form.amount && n > 0) set("amount", n.toFixed(2)); }} />
              </div>
            </Field>
          </div>

          <Field label="Vendor">
            <input list="vendor-options" placeholder="Who you paid" value={form.vendor_name} maxLength={255}
              onChange={(e) => set("vendor_name", e.target.value)} autoComplete="off" />
            <datalist id="vendor-options">
              {vendors.map((v) => <option key={v.id} value={v.name} />)}
            </datalist>
          </Field>

          <Field label="Description" error={errors.description}>
            <input placeholder="What was this for?" value={form.description} maxLength={500}
              onChange={(e) => set("description", e.target.value)} />
          </Field>

          <div className="grid-2">
            <Field label="Category" error={errors.category_id}>
              <select value={form.category_id} onChange={(e) => set("category_id", e.target.value)}>
                <option value="">Choose a category</option>
                {categoryOptions.map((c) => <option key={c.id} value={c.id}>{c.name}{c.is_active ? "" : " (inactive)"}</option>)}
              </select>
            </Field>
            <Field label="Paid with">
              <select value={form.payment_method} onChange={(e) => set("payment_method", e.target.value as PaymentMethod | "")}>
                <option value="">Not specified</option>
                {(Object.keys(PAYMENT_LABEL) as PaymentMethod[]).map((p) => <option key={p} value={p}>{PAYMENT_LABEL[p]}</option>)}
              </select>
            </Field>
          </div>

          <label className="check">
            <input type="checkbox" checked={form.is_reimbursable} onChange={(e) => set("is_reimbursable", e.target.checked)} />
            <span>I paid this personally and the business owes me back</span>
          </label>

          <Field label="Notes">
            <textarea rows={3} value={form.notes} maxLength={5000} onChange={(e) => set("notes", e.target.value)} />
          </Field>

          <div className="form-actions">
            {!isNew && (
              <button type="button" className="btn btn-danger-quiet" onClick={() => setConfirmDelete(true)}>Delete expense</button>
            )}
            <span className="spacer" />
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

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className={error ? "field has-error" : "field"}>
      <span>{label}</span>
      {children}
      {error && <small className="field-error">{error}</small>}
    </label>
  );
}

const FIELD_NAMES: Record<string, string> = {
  expense_date: "date", vendor: "vendor", category: "category", description: "description",
  amount: "amount", payment_method: "payment method", is_reimbursable: "reimbursable", notes: "notes",
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
