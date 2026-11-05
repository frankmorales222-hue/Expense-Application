import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ModuleNotice, useModule } from "../modules";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import { useAuth, useToast } from "../context";
import { defaultTerm, dueDateFor, formatDate, formatDateTime, money, termOptions, today } from "../format";
import CustomFields from "../components/CustomFields";
import type { Billable, Category, Customer, CustomValues, InvoiceDetail, InvoiceInput, Item, Terms } from "../types";
import { InvoiceBadge } from "./InvoicesPage";

interface LineDraft {
  key: number;
  service_date: string;
  product: string; // "item:<id>" | "cat:<id>" | "" ; billable lines keep ""
  description: string;
  quantity: string;
  rate: string;
  expense_line_id: string | null;
  bill_line_id: string | null;
  source_label: string | null;
}

let nextKey = 1;
const blank = (): LineDraft => ({ key: nextKey++, service_date: "", product: "", description: "", quantity: "1", rate: "",
  expense_line_id: null, bill_line_id: null, source_label: null });
const num = (s: string) => Number(s) || 0;
const lineAmount = (l: LineDraft) => Math.round(num(l.quantity) * num(l.rate) * 100) / 100;
const used = (l: LineDraft) => Boolean(l.product || l.description.trim() || l.rate || l.expense_line_id || l.bill_line_id);

interface FormState {
  customer_id: string;
  bill_email: string;
  invoice_number: string;
  invoice_date: string;
  terms: Terms | "";
  due_date: string;
  message: string;
  memo: string;
  lines: LineDraft[];
  custom: CustomValues;
}

// The company's default terms (v0.10.0), worked out the same way as on the server.
const empty = (): FormState => {
  const terms = defaultTerm("invoice");
  return { customer_id: "", bill_email: "", invoice_number: "", invoice_date: today(), terms,
    due_date: dueDateFor(terms, today()), message: "", memo: "", lines: [blank(), blank()], custom: {} };
};

export default function InvoiceFormPage() {
  const { id } = useParams();
  const isNew = !id;
  const { user } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const { on: moduleOn } = useModule("invoicing");
  const canEdit = (user?.role === "admin" || user?.role === "approver") && moduleOn;
  const [inv, setInv] = useState<InvoiceDetail | null>(null);
  const [form, setForm] = useState<FormState>(empty);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [incomeCats, setIncomeCats] = useState<Category[]>([]);
  const [billable, setBillable] = useState<Billable[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [sendOpen, setSendOpen] = useState(Boolean((location.state as { send?: boolean } | null)?.send));
  const [confirm, setConfirm] = useState<"" | "void" | "delete">("");
  const [addingCustomer, setAddingCustomer] = useState(false);
  const readOnly = !canEdit || inv?.status === "void";

  // "Save and send" on a new invoice lands here with { send: true }; the page is reused, so watch for it.
  useEffect(() => {
    if ((location.state as { send?: boolean } | null)?.send && id) setSendOpen(true);
  }, [location.key, location.state, id]);

  const reloadCustomers = useCallback(() => api.customers().then(setCustomers).catch(() => setCustomers([])), []);
  useEffect(() => {
    void reloadCustomers();
    api.items().then(setItems).catch(() => setItems([]));
    api.categories().then((cs) => setIncomeCats(cs.filter((c) => c.kind === "income"))).catch(() => setIncomeCats([]));
  }, [reloadCustomers]);

  const fill = useCallback((d: InvoiceDetail) => {
    setInv(d);
    setForm({
      customer_id: d.customer_id, bill_email: d.bill_email ?? d.customer_email ?? "", invoice_number: d.invoice_number,
      invoice_date: d.invoice_date, terms: d.terms ?? "", due_date: d.due_date, message: d.message ?? "", memo: d.memo ?? "",
      lines: d.lines.map((l) => ({
        key: nextKey++, service_date: l.service_date ?? "",
        product: l.item_id ? `item:${l.item_id}` : l.category_id && !(l.expense_line_id || l.bill_line_id) ? `cat:${l.category_id}` : "",
        description: l.description ?? "", quantity: String(l.quantity), rate: l.rate.toFixed(2),
        expense_line_id: l.expense_line_id, bill_line_id: l.bill_line_id,
        source_label: l.expense_line_id || l.bill_line_id ? "Billable expense" : null,
      })),
      custom: d.custom ?? {},
    });
  }, []);

  useEffect(() => {
    if (isNew) {
      setInv(null);
      setForm(empty());
      api.nextInvoiceNumber().then((n) => setForm((f) => ({ ...f, invoice_number: n.invoice_number }))).catch(() => undefined);
      return;
    }
    api.getInvoice(id).then(fill).catch((e: Error) => toast.error(e.message));
  }, [id, isNew, fill, toast]);

  // A customer chosen from a link (?customer=) on a new invoice.
  useEffect(() => {
    const c = params.get("customer");
    if (isNew && c && customers.some((x) => x.id === c) && !form.customer_id) chooseCustomer(c);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customers, isNew]);

  useEffect(() => {
    if (!form.customer_id || readOnly) { setBillable([]); return; }
    api.billable(form.customer_id, inv?.id).then(setBillable).catch(() => setBillable([]));
  }, [form.customer_id, inv?.id, readOnly]);

  function chooseCustomer(customerId: string) {
    const c = customers.find((x) => x.id === customerId);
    setForm((f) => {
      const terms = (c?.default_terms ?? f.terms) as Terms | "";
      return { ...f, customer_id: customerId, bill_email: c?.email ?? "", terms,
        due_date: terms ? dueDateFor(terms, f.invoice_date) : f.due_date,
        // Billable lines belong to one customer.
        lines: f.lines.filter((l) => !(l.expense_line_id || l.bill_line_id)).length
          ? f.lines.filter((l) => !(l.expense_line_id || l.bill_line_id)) : [blank()] };
    });
    setErrors({});
  }

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => {
      const next = { ...f, [key]: value };
      if ((key === "terms" || key === "invoice_date") && next.terms) {
        next.due_date = dueDateFor(next.terms, next.invoice_date);
      }
      if (key === "due_date") next.terms = "";
      return next;
    });
    setErrors((e) => ({ ...e, [key]: "" }));
  }

  function setLine(i: number, patch: Partial<LineDraft>) {
    setForm((f) => ({ ...f, lines: f.lines.map((l, idx) => (idx === i ? { ...l, ...patch } : l)) }));
    setErrors({});
  }

  function chooseProduct(i: number, value: string) {
    const line = form.lines[i];
    if (!line) return;
    const patch: Partial<LineDraft> = { product: value };
    if (value.startsWith("item:")) {
      const it = items.find((x) => `item:${x.id}` === value);
      if (it) {
        if (!line.description.trim() && it.description) patch.description = it.description;
        if (it.rate !== null && (!line.rate || num(line.rate) === 0)) patch.rate = it.rate.toFixed(2);
      }
    }
    setLine(i, patch);
  }

  function addBillable(b: Billable) {
    setForm((f) => {
      const line: LineDraft = { key: nextKey++, service_date: b.date, product: "",
        description: [b.vendor_name, b.description].filter(Boolean).join(": "), quantity: "1", rate: b.amount.toFixed(2),
        expense_line_id: b.source === "expense" ? b.line_id : null, bill_line_id: b.source === "bill" ? b.line_id : null,
        source_label: "Billable expense" };
      const kept = f.lines.filter(used);
      return { ...f, lines: [...kept, line] };
    });
  }

  const onInvoice = useMemo(() => new Set(form.lines.flatMap((l) => [l.expense_line_id, l.bill_line_id]).filter(Boolean)),
    [form.lines]);
  const available = billable.filter((b) => !onInvoice.has(b.line_id));
  const total = Math.round(form.lines.filter(used).reduce((s, l) => s + lineAmount(l), 0) * 100) / 100;
  const paid = inv?.paid ?? 0;

  function validate(): InvoiceInput | null {
    const e: Record<string, string> = {};
    if (!form.customer_id) e.customer_id = "Choose the customer";
    if (form.bill_email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.bill_email)) e.bill_email = "Enter a valid email";
    if (!form.invoice_date) e.invoice_date = "Enter the invoice date";
    if (form.due_date && form.due_date < form.invoice_date) e.due_date = "Can't be before the invoice date";
    const lines = form.lines.filter(used);
    if (lines.length === 0) e.lines = "Add at least one line";
    form.lines.forEach((l, i) => {
      if (!used(l)) return;
      if (!l.product && !l.expense_line_id && !l.bill_line_id) e[`${i}.product`] = "Choose";
      if (!(num(l.quantity) > 0)) e[`${i}.quantity`] = "Qty";
      if (!(num(l.rate) > 0)) e[`${i}.rate`] = "Rate";
    });
    setErrors(e);
    if (Object.values(e).some(Boolean)) return null;
    return {
      customer_id: form.customer_id, invoice_number: form.invoice_number.trim() || null, invoice_date: form.invoice_date,
      terms: form.terms || null, due_date: form.due_date || null, bill_email: form.bill_email.trim() || null,
      message: form.message.trim() || null, memo: form.memo.trim() || null, custom: form.custom,
      lines: lines.map((l) => ({
        service_date: l.service_date || null,
        item_id: l.product.startsWith("item:") ? l.product.slice(5) : null,
        category_id: l.product.startsWith("cat:") ? l.product.slice(4) : null,
        description: l.description.trim() || null, quantity: Number(num(l.quantity).toFixed(2)),
        rate: Number(num(l.rate).toFixed(2)), expense_line_id: l.expense_line_id, bill_line_id: l.bill_line_id,
      })),
    };
  }

  async function save(e: FormEvent | null, andSend = false) {
    e?.preventDefault();
    const body = validate();
    if (!body) { toast.error("Check the highlighted fields"); return; }
    setSaving(true);
    try {
      if (isNew) {
        const created = await api.createInvoice(body);
        toast.success(`Invoice ${created.invoice_number} saved`);
        navigate(`/invoices/${created.id}`, { replace: true, state: { send: andSend } });
      } else {
        fill(await api.updateInvoice(id, body));
        toast.success("Invoice saved");
        if (andSend) setSendOpen(true);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the invoice");
    } finally {
      setSaving(false);
    }
  }

  async function run(action: () => Promise<InvoiceDetail | void>, message: string) {
    try {
      const d = await action();
      if (d) fill(d);
      toast.success(message);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "That didn't work");
    }
  }

  const customer = customers.find((c) => c.id === form.customer_id);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <Link to="/invoices" className="back">Invoices</Link>
          <h1>{isNew ? "New invoice" : `Invoice ${inv?.invoice_number ?? ""}`}</h1>
          {inv && <p className="muted">{inv.customer_name}</p>}
        </div>
        {inv && (
          <div className="head-status">
            <InvoiceBadge status={inv.status} due={inv.due_date} />
            <span className="head-amount">{money(inv.balance)} <span className="muted small">balance due</span></span>
          </div>
        )}
      </header>

      <ModuleNotice module="invoicing" />
      <div className="form-layout invoice-layout">
        <form className="panel form" onSubmit={(e) => void save(e)} noValidate>
          <div className="grid-2">
            <div className={errors.customer_id ? "field has-error" : "field"}>
              <span>Customer</span>
              <select value={form.customer_id} disabled={readOnly || paid > 0} aria-label="Customer"
                onChange={(e) => (e.target.value === "__new" ? setAddingCustomer(true) : chooseCustomer(e.target.value))}>
                <option value="">Choose a customer</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                {!readOnly && <option value="__new">+ Add a new customer</option>}
              </select>
              {errors.customer_id && <small className="field-error">{errors.customer_id}</small>}
            </div>
            <label className={errors.bill_email ? "field has-error" : "field"}><span>Customer email</span>
              <input type="email" value={form.bill_email} maxLength={255} disabled={readOnly} placeholder="Where the invoice goes"
                onChange={(e) => set("bill_email", e.target.value)} />
              {errors.bill_email && <small className="field-error">{errors.bill_email}</small>}</label>
          </div>
          {addingCustomer && (
            <QuickCustomer onCancel={() => setAddingCustomer(false)} onAdded={async (c) => {
              await reloadCustomers();
              setAddingCustomer(false);
              setCustomers((list) => (list.some((x) => x.id === c.id) ? list : [...list, c]));
              setForm((f) => ({ ...f, customer_id: c.id, bill_email: c.email ?? "" }));
            }} />
          )}
          {customer?.billing_address && <p className="small muted bill-to">Bill to: {customer.billing_address.split("\n").join(", ")}</p>}

          <div className="grid-4">
            <label className="field"><span>Invoice no.</span>
              <input value={form.invoice_number} maxLength={30} disabled={readOnly} onChange={(e) => set("invoice_number", e.target.value)} /></label>
            <label className={errors.invoice_date ? "field has-error" : "field"}><span>Invoice date</span>
              <input type="date" value={form.invoice_date} disabled={readOnly} onChange={(e) => set("invoice_date", e.target.value)} /></label>
            <label className="field"><span>Terms</span>
              <select value={form.terms} disabled={readOnly} onChange={(e) => set("terms", e.target.value as Terms | "")}>
                <option value="">Custom due date</option>
                {termOptions(form.terms).map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
              </select></label>
            <label className={errors.due_date ? "field has-error" : "field"}><span>Due date</span>
              <input type="date" value={form.due_date} disabled={readOnly} onChange={(e) => set("due_date", e.target.value)} />
              {errors.due_date && <small className="field-error">{errors.due_date}</small>}</label>
          </div>

          <div className="field"><span>Products and services</span>
            <div className="lines">
              <table className="lines-table inv-lines">
                <thead><tr>
                  <th className="ln-num">#</th><th className="ln-date">Service date</th><th className="ln-cat">Product/service</th>
                  <th>Description</th><th className="num ln-qty">Qty</th><th className="num ln-rate">Rate</th>
                  <th className="num ln-amt">Amount</th><th><span className="sr-only">Remove</span></th>
                </tr></thead>
                <tbody>
                  {form.lines.map((l, i) => (
                    <tr key={l.key}>
                      <td className="ln-num muted">{i + 1}</td>
                      <td><input type="date" value={l.service_date} disabled={readOnly} aria-label={`Line ${i + 1} service date`}
                        onChange={(e) => setLine(i, { service_date: e.target.value })} /></td>
                      <td className={errors[`${i}.product`] ? "has-error" : ""}>
                        {l.source_label ? <span className="static-field small">{l.source_label}</span> : (
                          <select value={l.product} disabled={readOnly} aria-label={`Line ${i + 1} product or service`}
                            onChange={(e) => chooseProduct(i, e.target.value)}>
                            <option value="">Choose</option>
                            {items.length > 0 && <optgroup label="Products and services">
                              {items.map((it) => <option key={it.id} value={`item:${it.id}`}>{it.name}</option>)}
                            </optgroup>}
                            <optgroup label="Income categories">
                              {incomeCats.filter((c) => c.is_active || `cat:${c.id}` === l.product)
                                .map((c) => <option key={c.id} value={`cat:${c.id}`}>{c.name}</option>)}
                            </optgroup>
                          </select>
                        )}
                      </td>
                      <td><textarea rows={2} className="grow-text" value={l.description} maxLength={1000} disabled={readOnly}
                        aria-label={`Line ${i + 1} description`} onChange={(e) => setLine(i, { description: e.target.value })} /></td>
                      <td className={errors[`${i}.quantity`] ? "num has-error" : "num"}>
                        <input inputMode="decimal" className="num-input" value={l.quantity} disabled={readOnly} aria-label={`Line ${i + 1} quantity`}
                          onChange={(e) => setLine(i, { quantity: e.target.value.replace(/[^0-9.]/g, "") })} /></td>
                      <td className={errors[`${i}.rate`] ? "num has-error" : "num"}>
                        <input inputMode="decimal" className="num-input" value={l.rate} disabled={readOnly} aria-label={`Line ${i + 1} rate`}
                          placeholder="0.00" onChange={(e) => setLine(i, { rate: e.target.value.replace(/[^0-9.]/g, "") })}
                          onBlur={() => num(l.rate) > 0 && setLine(i, { rate: num(l.rate).toFixed(2) })} /></td>
                      <td className="num ln-amt-cell">{used(l) ? money(lineAmount(l)) : ""}</td>
                      <td className="row-actions">
                        {!readOnly && <button type="button" className="icon-btn" aria-label={`Remove line ${i + 1}`}
                          onClick={() => setForm((f) => ({ ...f, lines: f.lines.length > 1 ? f.lines.filter((_, idx) => idx !== i) : [blank()] }))}>×</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={3}>{!readOnly && <button type="button" className="link-button"
                      onClick={() => setForm((f) => ({ ...f, lines: [...f.lines, blank()] }))}>Add line</button>}</td>
                    <td colSpan={3} className="num muted">Total</td>
                    <td className="num lines-total">{money(total)}</td>
                    <td />
                  </tr>
                </tfoot>
              </table>
              {errors.lines && <p className="field-error">{errors.lines}</p>}
              {Object.keys(errors).some((k) => /^\d+\./.test(k) && errors[k]) && <p className="field-error">Check the highlighted lines.</p>}
              {!readOnly && items.length === 0 && (
                <p className="hint">Tip: add what you sell in <Link to="/products">Products and services</Link> so the rate and description fill in.</p>
              )}
            </div>
          </div>

          <div className="grid-2">
            <label className="field"><span>Message on invoice</span>
              <textarea rows={3} value={form.message} maxLength={4000} disabled={readOnly} placeholder="Thank you for your business!"
                onChange={(e) => set("message", e.target.value)} /></label>
            <label className="field"><span>Internal memo <span className="muted">(not on the invoice)</span></span>
              <textarea rows={3} value={form.memo} maxLength={4000} disabled={readOnly} onChange={(e) => set("memo", e.target.value)} /></label>
          </div>

          <CustomFields entity="invoice" value={form.custom} disabled={readOnly} onChange={(v) => set("custom", v)} />

          <div className="inv-totals">
            <div><span>Total</span><strong>{money(total)}</strong></div>
            {paid > 0 && <div><span>Payments received</span><span>{money(-paid)}</span></div>}
            <div className="inv-balance"><span>Balance due</span><strong>{money(Math.max(total - paid, 0))}</strong></div>
          </div>

          {!readOnly && (
            <div className="form-actions">
              {inv && paid === 0 && (
                <button type="button" className="btn btn-danger-quiet" onClick={() => setConfirm("delete")}>Delete</button>
              )}
              <span className="spacer" />
              <Link className="btn" to="/invoices">Cancel</Link>
              <button type="submit" className="btn" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void save(null, true)}>
                Save and send
              </button>
            </div>
          )}
        </form>

        <aside className="side">
          {inv && (
            <section className="panel">
              <h2>Send and share</h2>
              <div className="stack">
                {inv.status !== "void" && canEdit && (
                  <button type="button" className="btn btn-primary" onClick={() => setSendOpen(true)}>Email invoice</button>
                )}
                <a className="btn" href={api.invoicePdfUrl(inv.id)} target="_blank" rel="noreferrer">Preview PDF</a>
                <a className="btn" href={api.invoicePdfUrl(inv.id, true)}>Download PDF</a>
              </div>
              <p className="small muted">
                {inv.sent_at ? `Sent ${formatDateTime(inv.sent_at)}.` : "Not sent yet."}{" "}
                {canEdit && inv.status !== "void" && (
                  <button type="button" className="link-button" onClick={() => void run(() => api.markSent(inv.id, !inv.sent_at),
                    inv.sent_at ? "Marked as not sent" : "Marked as sent")}>
                    {inv.sent_at ? "Mark as not sent" : "Mark as sent"}
                  </button>
                )}
              </p>
              {inv.emails.length > 0 && (
                <ul className="email-log">
                  {inv.emails.map((m) => (
                    <li key={m.id} className={m.status === "failed" ? "failed" : ""}>
                      <strong>{m.status === "sent" ? "Emailed" : "Failed"}</strong> {formatDateTime(m.sent_at)}
                      <div className="muted small">to {m.sent_to}</div>
                      {m.error && <div className="small overdue-text">{m.error}</div>}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {inv && (
            <section className="panel">
              <h2>Payments</h2>
              {inv.payments.length === 0 ? <p className="muted">No payments yet.</p> : (
                <ul className="pay-list">
                  {inv.payments.map((p) => (
                    <li key={p.payment_id}>
                      <div><strong>{money(p.amount)}</strong> on {formatDate(p.payment_date)}
                        <div className="muted small">into {p.account_name}{p.reference ? ` · #${p.reference}` : ""}
                          {p.payment_total !== p.amount ? ` · part of ${money(p.payment_total)}` : ""}
                          {p.transaction_id ? " · matched to the bank deposit" : ""}</div></div>
                      {canEdit && (
                        <button type="button" className="link-button danger" onClick={async () => {
                          if (!window.confirm(p.payment_total !== p.amount
                            ? `This payment of ${money(p.payment_total)} also paid other invoices. Remove the whole payment?`
                            : "Remove this payment? The invoice goes back to unpaid for this amount.")) return;
                          await run(async () => { await api.deletePayment(p.payment_id); return api.getInvoice(inv.id); }, "Payment removed");
                        }}>Remove</button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {canEdit && inv.balance > 0 && inv.status !== "void" && (
                <Link className="btn btn-primary" to={`/payments/new?customer=${inv.customer_id}&invoice=${inv.id}`}>Receive payment</Link>
              )}
              <p className="small muted">Received {money(paid)} of {money(inv.total)}</p>
            </section>
          )}

          {!readOnly && form.customer_id && (
            <section className="panel">
              <h2>Billable expenses</h2>
              {available.length === 0 ? (
                <p className="muted">Nothing waiting to be billed to {customer?.name ?? "this customer"}.
                  Mark expense or bill lines "Billable" for them and they show up here.</p>
              ) : (
                <>
                  <ul className="billable-list">
                    {available.map((b) => (
                      <li key={b.line_id}>
                        <div>
                          <strong>{money(b.amount)}</strong> <span className="muted small">{formatDate(b.date)}</span>
                          <div className="small">{b.vendor_name ? `${b.vendor_name}: ` : ""}{b.description}</div>
                          <div className="muted small">{b.source === "bill" ? "Bill" : "Expense"} · {b.category_name}</div>
                        </div>
                        <button type="button" className="link-button" onClick={() => addBillable(b)}>Add</button>
                      </li>
                    ))}
                  </ul>
                  {available.length > 1 && (
                    <button type="button" className="btn" onClick={() => available.forEach(addBillable)}>Add all</button>
                  )}
                </>
              )}
            </section>
          )}

          {inv && canEdit && inv.status !== "void" && (
            <section className="panel">
              <h2>More</h2>
              <button type="button" className="btn btn-danger-quiet" disabled={paid > 0} onClick={() => setConfirm("void")}>Void invoice</button>
              <p className="small muted">{paid > 0 ? "Remove the payments first to void it." :
                "Voiding keeps the invoice and its number but makes it worth zero."}</p>
            </section>
          )}
          {inv?.status === "void" && (
            <section className="panel"><h2>Void</h2><p className="muted">Voided {inv.voided_at ? formatDateTime(inv.voided_at) : ""}. It no longer counts in your books.</p></section>
          )}
        </aside>
      </div>

      {inv && sendOpen && (
        <SendDialog invoice={inv} onClose={() => setSendOpen(false)} onSent={(d) => { fill(d); setSendOpen(false); }} />
      )}

      <ConfirmDialog open={confirm === "void"} title={`Void invoice ${inv?.invoice_number ?? ""}?`} danger confirmLabel="Void invoice"
        message="It stays in your list with its number, but is worth zero and comes off Accounts Receivable and income."
        onConfirm={() => { setConfirm(""); if (inv) void run(() => api.voidInvoice(inv.id), "Invoice voided"); }}
        onCancel={() => setConfirm("")} />
      <ConfirmDialog open={confirm === "delete"} title={`Delete invoice ${inv?.invoice_number ?? ""}?`} danger confirmLabel="Delete"
        message="It comes off your books and the invoice list. The history is kept. To keep the number on record, void it instead."
        onConfirm={async () => {
          if (!inv) return;
          try { await api.deleteInvoice(inv.id); navigate("/invoices", { replace: true }); } catch (err) {
            toast.error(err instanceof Error ? err.message : "Could not delete"); setConfirm("");
          }
        }} onCancel={() => setConfirm("")} />
    </div>
  );
}

function QuickCustomer({ onAdded, onCancel }: { onAdded: (c: Customer) => void; onCancel: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="quick-add">
      <label className="field grow"><span>New customer name</span>
        <input value={name} maxLength={255} autoFocus onChange={(e) => setName(e.target.value)} /></label>
      <label className="field grow"><span>Email</span>
        <input type="email" value={email} maxLength={255} onChange={(e) => setEmail(e.target.value)} /></label>
      <button type="button" className="btn btn-primary" disabled={busy || !name.trim()} onClick={async () => {
        setBusy(true);
        try {
          const c = await api.createCustomer({ name: name.trim(), email: email.trim() || null, notes: null, is_active: true });
          toast.success(`Added ${c.name}`);
          onAdded(c);
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Could not add the customer");
        } finally { setBusy(false); }
      }}>Add</button>
      <button type="button" className="link-button" onClick={onCancel}>Cancel</button>
    </div>
  );
}

function SendDialog({ invoice, onClose, onSent }: { invoice: InvoiceDetail; onClose: () => void; onSent: (d: InvoiceDetail) => void }) {
  const toast = useToast();
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [from, setFrom] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.emailDraft(invoice.id).then((d) => {
      setTo(d.to.join(", ")); setCc(d.cc.join(", ")); setSubject(d.subject); setBody(d.body);
      setConfigured(d.configured); setFrom(d.from_label);
    }).catch((e: Error) => toast.error(e.message));
  }, [invoice.id, toast]);

  const split = (s: string) => s.split(/[,;]/).map((x) => x.trim()).filter(Boolean);

  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const d = await api.sendInvoice(invoice.id, { to: split(to), cc: split(cc), subject, body });
      toast.success(`Invoice ${invoice.invoice_number} sent`);
      onSent(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="send-title">
      <form className="dialog send-dialog" onSubmit={send}>
        <h2 id="send-title">Email invoice {invoice.invoice_number}</h2>
        {configured === false ? (
          <>
            <p>Email isn't set up yet. An owner can add the mail server in <Link to="/settings#email">Settings › Email</Link>
              {" "}(Microsoft 365, Gmail or any SMTP server).</p>
            <p className="muted">Meanwhile you can download the PDF and attach it to an email yourself, then mark the invoice as sent.</p>
            <div className="form-actions">
              <span className="spacer" />
              <a className="btn" href={api.invoicePdfUrl(invoice.id, true)}>Download PDF</a>
              <button type="button" className="btn btn-primary" onClick={onClose}>Close</button>
            </div>
          </>
        ) : (
          <>
            {from && <p className="small muted">From {from}</p>}
            <label className="field"><span>To</span>
              <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="name@company.com" required /></label>
            <label className="field"><span>Cc</span>
              <input value={cc} onChange={(e) => setCc(e.target.value)} placeholder="Optional; separate with commas" /></label>
            <label className="field"><span>Subject</span>
              <input value={subject} maxLength={255} onChange={(e) => setSubject(e.target.value)} required /></label>
            <label className="field"><span>Message</span>
              <textarea rows={10} value={body} maxLength={10000} onChange={(e) => setBody(e.target.value)} required /></label>
            <p className="small muted attach-note">📎 Invoice-{invoice.invoice_number}.pdf is attached ·{" "}
              <a href={api.invoicePdfUrl(invoice.id)} target="_blank" rel="noreferrer">preview</a></p>
            {error && <p className="form-error">{error}</p>}
            <div className="form-actions">
              <span className="spacer" />
              <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={busy || configured === null || !split(to).length}>
                {busy ? "Sending…" : "Send"}
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}
