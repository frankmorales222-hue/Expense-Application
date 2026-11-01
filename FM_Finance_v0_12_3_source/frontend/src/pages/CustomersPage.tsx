import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useModule } from "../modules";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth, useToast } from "../context";
import { formatDate, money, termOptions } from "../format";
import CustomFields from "../components/CustomFields";
import type { Customer, CustomerDetail, CustomerInput, CustomValues, Terms } from "../types";
import { InvoiceBadge } from "./InvoicesPage";

export default function CustomersPage() {
  const { id } = useParams();
  return id ? <CustomerView id={id} /> : <CustomerList />;
}

function CustomerList() {
  const { on: invoicing } = useModule("invoicing");
  const toast = useToast();
  const navigate = useNavigate();
  const [rows, setRows] = useState<Customer[] | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    api.customers(showInactive).then(setRows).catch((e: Error) => toast.error(e.message));
  }, [showInactive, toast]);
  useEffect(load, [load]);

  const q = search.trim().toLowerCase();
  const list = (rows ?? []).filter((c) => !q || c.name.toLowerCase().includes(q) || (c.email ?? "").toLowerCase().includes(q));
  const open = (rows ?? []).reduce((s, c) => s + (c.open_balance ?? 0), 0);
  const overdue = (rows ?? []).reduce((s, c) => s + (c.overdue_balance ?? 0), 0);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Customers</h1>
          <p className="muted">Who you bill, what they owe, and how quickly they pay.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>New customer</button>
      </header>

      {rows && rows.length > 0 && (
        <div className="figures">
          <div className="figure figure-lead"><span className="figure-label">Open balance</span><span className="figure-value">{money(open)}</span></div>
          <div className="figure"><span className="figure-label">Overdue</span>
            <span className={overdue > 0 ? "figure-value overdue-text" : "figure-value"}>{money(overdue)}</span></div>
        </div>
      )}

      {adding && <CustomerForm onClose={() => setAdding(false)} onSaved={(c) => { setAdding(false); navigate(`/customers/${c.id}`); }} />}

      <div className="toolbar">
        <label className="field grow"><span className="sr-only">Search</span>
          <input type="search" placeholder="Search name or email" value={search} onChange={(e) => setSearch(e.target.value)} /></label>
        <label className="switch"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          <span>Include inactive</span></label>
      </div>

      <section className="panel flush">
        {rows && list.length === 0 ? (
          <div className="empty inner"><p>{rows.length === 0 ? "No customers yet." : "No customers match."}</p></div>
        ) : (
          <div className="table-wrap">
            <table className="ledger">
              <thead><tr><th>Name</th><th>Email</th><th>Phone</th><th className="num">Open balance</th><th className="num">Overdue</th>
                <th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {list.map((c) => (
                  <tr key={c.id} className={c.is_active ? "" : "inactive"} onClick={() => navigate(`/customers/${c.id}`)}>
                    <td><strong>{c.name}</strong></td>
                    <td className="muted">{c.email ?? ""}</td>
                    <td className="muted nowrap">{c.phone ?? ""}</td>
                    <td className="num">{money(c.open_balance ?? 0)}</td>
                    <td className={(c.overdue_balance ?? 0) > 0 ? "num overdue-text" : "num muted"}>{money(c.overdue_balance ?? 0)}</td>
                    <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                      {invoicing && <Link className="link-button" to={`/invoices/new?customer=${c.id}`}>Create invoice</Link>}
                      {invoicing && (c.open_balance ?? 0) > 0 && <Link className="link-button" to={`/payments/new?customer=${c.id}`}>Receive payment</Link>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export function CustomerForm({ customer, onClose, onSaved }: {
  customer?: Customer; onClose: () => void; onSaved: (c: Customer) => void;
}) {
  const toast = useToast();
  const [f, setF] = useState({
    name: customer?.name ?? "", email: customer?.email ?? "", cc_emails: customer?.cc_emails ?? "", phone: customer?.phone ?? "",
    billing_address: customer?.billing_address ?? "", default_terms: (customer?.default_terms ?? "") as Terms | "",
    notes: customer?.notes ?? "", is_active: customer?.is_active ?? true,
  });
  const [custom, setCustom] = useState<CustomValues>(customer?.custom ?? {});
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f, v: string | boolean) => setF((x) => ({ ...x, [k]: v }));

  async function save(e: FormEvent) {
    e.preventDefault();
    const body: CustomerInput = {
      name: f.name.trim(), email: f.email.trim() || null, cc_emails: f.cc_emails.trim() || null, phone: f.phone.trim() || null,
      billing_address: f.billing_address.trim() || null, default_terms: f.default_terms || null, notes: f.notes.trim() || null,
      is_active: f.is_active, custom,
    };
    setBusy(true);
    try {
      const c = customer ? await api.updateCustomer(customer.id, body) : await api.createCustomer(body);
      toast.success(customer ? "Customer saved" : `Added ${c.name}`);
      onSaved(c);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the customer");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>{customer ? "Edit customer" : "New customer"}</h2>
      <form className="form-grid" onSubmit={save}>
        <label className="field"><span>Name</span>
          <input value={f.name} maxLength={255} required onChange={(e) => set("name", e.target.value)} placeholder="e.g. Acme Dental Group" /></label>
        <label className="field"><span>Email (invoices go here)</span>
          <input type="email" value={f.email} maxLength={255} onChange={(e) => set("email", e.target.value)} /></label>
        <label className="field"><span>Cc on invoices</span>
          <input value={f.cc_emails} maxLength={500} placeholder="ap@client.com, owner@client.com" onChange={(e) => set("cc_emails", e.target.value)} /></label>
        <label className="field"><span>Phone</span>
          <input value={f.phone} maxLength={50} onChange={(e) => set("phone", e.target.value)} /></label>
        <label className="field"><span>Billing address</span>
          <textarea rows={3} value={f.billing_address} maxLength={1000} onChange={(e) => set("billing_address", e.target.value)} /></label>
        <div className="form-col">
          <label className="field"><span>Default terms</span>
            <select value={f.default_terms} onChange={(e) => set("default_terms", e.target.value)}>
              <option value="">Use the invoice's terms</option>
              {termOptions(f.default_terms).map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
            </select></label>
          {customer && <label className="switch"><input type="checkbox" checked={f.is_active} onChange={(e) => set("is_active", e.target.checked)} />
            <span>{f.is_active ? "Active" : "Inactive (hidden from lists)"}</span></label>}
        </div>
        <label className="field span-2"><span>Notes</span>
          <input value={f.notes} maxLength={5000} onChange={(e) => set("notes", e.target.value)} /></label>
        <div className="span-2"><CustomFields entity="customer" value={custom} onChange={setCustom} /></div>
        <div className="form-actions span-2">
          <span className="spacer" />
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !f.name.trim()}>{busy ? "Saving…" : "Save customer"}</button>
        </div>
      </form>
    </section>
  );
}

function CustomerView({ id }: { id: string }) {
  const toast = useToast();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "approver";
  const { on: invoicing } = useModule("invoicing");
  const [d, setD] = useState<CustomerDetail | null>(null);
  const [editing, setEditing] = useState(false);

  const load = useCallback(() => { api.customerDetail(id).then(setD).catch((e: Error) => toast.error(e.message)); }, [id, toast]);
  useEffect(load, [load]);

  if (!d) return <div className="page"><p className="muted">Loading…</p></div>;
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <Link to="/customers" className="back">Customers</Link>
          <h1>{d.name}{!d.is_active && <span className="tag">inactive</span>}</h1>
          <p className="muted">{[d.email, d.phone].filter(Boolean).join(" · ") || "No contact details yet"}</p>
        </div>
        {canEdit && (
          <div className="head-actions">
            <button type="button" className="btn" onClick={() => setEditing(true)}>Edit</button>
            {invoicing && d.open_balance > 0 && <Link className="btn" to={`/payments/new?customer=${d.id}`}>Receive payment</Link>}
            {invoicing && <Link className="btn btn-primary" to={`/invoices/new?customer=${d.id}`}>Create invoice</Link>}
          </div>
        )}
      </header>

      {editing && <CustomerForm customer={d} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); load(); }} />}

      <div className="figures">
        <div className="figure figure-lead"><span className="figure-label">Open balance</span><span className="figure-value">{money(d.open_balance)}</span></div>
        <div className="figure"><span className="figure-label">Overdue</span>
          <span className={d.overdue_balance > 0 ? "figure-value overdue-text" : "figure-value"}>{money(d.overdue_balance)}</span></div>
        <div className="figure"><span className="figure-label">Average days to pay</span>
          <span className="figure-value">{d.avg_days_to_pay ?? "—"}</span>
          <span className="figure-note">{d.on_time_percent !== null ? `${d.on_time_percent}% paid on time` : "No paid invoices yet"}</span></div>
        <div className="figure"><span className="figure-label">Unbilled expenses</span>
          <span className="figure-value">{money(d.unbilled_amount)}</span>
          <span className="figure-note">{d.unbilled_count} waiting to go on an invoice</span></div>
      </div>

      <div className="two-col wide-left">
        <section className="panel flush">
          <h2 className="panel-title">Invoices</h2>
          {d.invoices.length === 0 ? <div className="empty inner"><p>No invoices yet.</p></div> : (
            <div className="table-wrap">
              <table className="ledger">
                <thead><tr><th>Date</th><th>No.</th><th>Due</th><th>Status</th><th className="num">Amount</th><th className="num">Open</th></tr></thead>
                <tbody>
                  {d.invoices.map((i) => (
                    <tr key={i.id} onClick={() => navigate(`/invoices/${i.id}`)}>
                      <td className="nowrap">{formatDate(i.invoice_date)}</td><td>{i.invoice_number}</td>
                      <td className="nowrap">{formatDate(i.due_date)}</td><td><InvoiceBadge status={i.status} due={i.due_date} /></td>
                      <td className="num">{money(i.total)}</td><td className="num"><strong>{money(i.balance)}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="panel">
          <h2>Payments received</h2>
          {d.payments.length === 0 ? <p className="muted">None yet.</p> : (
            <ul className="pay-list">
              {d.payments.map((p) => (
                <li key={p.id}><div><strong>{money(p.amount)}</strong> on {formatDate(p.payment_date)}
                  <div className="muted small">into {p.account_name} · for {p.applications.map((a) => `#${a.invoice_number}`).join(", ")}
                    {p.transaction_id ? " · matched in Banking" : ""}</div></div></li>
              ))}
            </ul>
          )}
          {d.billing_address && <><h3>Billing address</h3><p className="pre">{d.billing_address}</p></>}
          {d.cc_emails && <><h3>Cc on invoices</h3><p>{d.cc_emails}</p></>}
          {d.notes && <><h3>Notes</h3><p>{d.notes}</p></>}
        </section>
      </div>
    </div>
  );
}
