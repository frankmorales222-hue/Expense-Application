import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { hasModule } from "../modules";
import Icon from "../components/Icon";
import { api } from "../api";
import { BRANDING_CHANGED } from "../components/BrandMark";
import AppearancePanel from "../components/AppearancePanel";
import { useAuth, useToast } from "../context";
import { CATEGORY_KIND_LABEL, MONTH_NAMES, formatDate, money } from "../format";
import type { BillCapabilities, BooksStatus, Category, CategoryKind, Company, EmailSettings, MicrosoftStart, PlansCatalog } from "../types";

export default function SettingsPage() {
  const { settings, user } = useAuth();
  const toast = useToast();
  const isAdmin = user?.role === "admin";
  const [categories, setCategories] = useState<Category[]>([]);
  const [newName, setNewName] = useState("");
  const [newThreshold, setNewThreshold] = useState("");
  const [newKind, setNewKind] = useState<CategoryKind>("expense");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(() => {
    api.categories(true).then(setCategories).catch((e: Error) => toast.error(e.message));
  }, [toast]);
  useEffect(load, [load]);

  async function update(c: Category, body: Parameters<typeof api.updateCategory>[1], message?: string) {
    setBusyId(c.id);
    try {
      await api.updateCategory(c.id, body);
      if (message) toast.success(message);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not update the category");
    } finally {
      setBusyId(null);
    }
  }

  async function move(index: number, dir: -1 | 1) {
    const a = categories[index];
    const b = categories[index + dir];
    if (!a || !b) return;
    setBusyId(a.id);
    try {
      // Give distinct values even if two categories share a sort order.
      const aOrder = b.sort_order === a.sort_order ? a.sort_order + dir : b.sort_order;
      await api.updateCategory(a.id, { sort_order: aOrder });
      await api.updateCategory(b.id, { sort_order: a.sort_order });
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not reorder");
    } finally {
      setBusyId(null);
    }
  }

  async function addCategory(e: FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    const t = newThreshold.trim();
    if (t && !(Number(t) >= 0)) { toast.error("Approval threshold must be a number"); return; }
    try {
      await api.createCategory(newName.trim(), t ? Number(t) : null, newKind);
      toast.success(`Added ${newName.trim()}`);
      setNewName("");
      setNewThreshold("");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add the category");
    }
  }

  return (
    <div className="page">
      <header className="page-head"><h1>Settings</h1></header>

      {user?.role !== "none" && (
        <Link to="/settings/rules" className="panel rules-entry">
          <span className="rules-entry-icon" aria-hidden="true"><Icon name="sliders" /></span>
          <span className="rules-entry-text"><strong>Company rules</strong>
            <span className="muted">Payment terms, payment methods, approvals, currency and date formats, custom fields,
              invoice numbering, PDF wording and the invoice email. {user?.company_role === "owner" ? "Set them your way." : "See how this company works."}</span></span>
          <span className="rules-entry-go" aria-hidden="true">›</span>
        </Link>
      )}

      <AppearancePanel />

      <CompanyPanel isAdmin={isAdmin} />

      <PlanPanel />

      {(isAdmin || user?.role === "approver") && <BooksPanel isOwner={isAdmin} />}

      <section className="panel">
        <h2>Categories</h2>
        <p className="muted">
          {settings?.approval_required
            ? `Approval is on. Expenses at or above a category's threshold (default ${money(settings.default_approval_threshold)}) wait for approval.`
            : "Approval is off, so every expense is saved as approved. Thresholds only apply when approvals are turned on in "}
          {!settings?.approval_required && <Link to="/settings/rules?tab=approvals">Company rules › Approvals</Link>}
          {!settings?.approval_required && "."}
        </p>
        <div className="table-wrap">
          <table className="ledger settings-table">
            <thead>
              <tr><th>Name</th><th>Type</th><th>Tax line (optional)</th><th className="num">Approval threshold</th><th>Active</th><th><span className="sr-only">Order</span></th></tr>
            </thead>
            <tbody>
              {categories.map((c, i) => (
                <CategoryRow key={c.id} category={c} disabled={!isAdmin || busyId !== null}
                  first={i === 0} last={i === categories.length - 1}
                  defaultThreshold={settings?.default_approval_threshold ?? 500}
                  onRename={(name) => void update(c, { name }, "Category renamed")}
                  onKind={(kind) => void update(c, { kind }, "Type changed")}
                  onTaxLine={(tax_line) => void update(c, { tax_line }, "Tax line saved")}
                  onThreshold={(value) => void update(c, value === null ? { clear_threshold: true } : { approval_threshold: value }, "Threshold saved")}
                  onToggle={() => void update(c, { is_active: !c.is_active })}
                  onMove={(dir) => void move(i, dir)} />
              ))}
            </tbody>
          </table>
        </div>
        {isAdmin && (
          <form className="inline-form" onSubmit={addCategory}>
            <label className="field grow"><span>New category</span>
              <input value={newName} maxLength={100} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Domain names" /></label>
            <label className="field"><span>Type</span>
              <select value={newKind} onChange={(e) => setNewKind(e.target.value as CategoryKind)}>
                {Object.entries(CATEGORY_KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select></label>
            <label className="field"><span>Threshold (optional)</span>
              <input inputMode="decimal" value={newThreshold} onChange={(e) => setNewThreshold(e.target.value)} placeholder="Default" /></label>
            <button type="submit" className="btn btn-primary" disabled={!newName.trim()}>Add category</button>
          </form>
        )}
      </section>

      <BillReadingPanel />

      {(isAdmin || user?.role === "approver") && <EmailPanel isOwner={isAdmin} />}

      <ChangePassword />
    </div>
  );
}

function CategoryRow({ category: c, disabled, first, last, defaultThreshold, onRename, onKind, onTaxLine, onThreshold, onToggle, onMove }: {
  category: Category; disabled: boolean; first: boolean; last: boolean; defaultThreshold: number;
  onRename: (name: string) => void; onKind: (k: CategoryKind) => void; onTaxLine: (t: string | null) => void;
  onThreshold: (v: number | null) => void; onToggle: () => void; onMove: (dir: -1 | 1) => void;
}) {
  const [name, setName] = useState(c.name);
  const [taxLine, setTaxLine] = useState(c.tax_line ?? "");
  const [threshold, setThreshold] = useState(c.approval_threshold?.toFixed(2) ?? "");
  useEffect(() => { setName(c.name); setTaxLine(c.tax_line ?? ""); setThreshold(c.approval_threshold?.toFixed(2) ?? ""); }, [c]);

  return (
    <tr className={c.is_active ? "" : "inactive"}>
      <td>
        <input className="cell-input" value={name} disabled={disabled} maxLength={100} aria-label="Category name"
          onChange={(e) => setName(e.target.value)}
          onBlur={() => { if (name.trim() && name.trim() !== c.name) onRename(name.trim()); else setName(c.name); }} />
      </td>
      <td>
        <select className="cell-input" value={c.kind} disabled={disabled} aria-label="Category type"
          onChange={(e) => onKind(e.target.value as CategoryKind)}>
          {Object.entries(CATEGORY_KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </td>
      <td>
        <input className="cell-input" value={taxLine} disabled={disabled} maxLength={100} aria-label="Tax line"
          placeholder="e.g. Schedule C line 18"
          onChange={(e) => setTaxLine(e.target.value)}
          onBlur={() => { const t = taxLine.trim(); if (t !== (c.tax_line ?? "")) onTaxLine(t || null); }} />
      </td>
      <td className="num">
        <input className="cell-input num" value={threshold} disabled={disabled} inputMode="decimal" aria-label="Approval threshold"
          placeholder={`${money(defaultThreshold)} (default)`}
          onChange={(e) => setThreshold(e.target.value)}
          onBlur={() => {
            const t = threshold.trim();
            const current = c.approval_threshold?.toFixed(2) ?? "";
            if (t === current) return;
            if (t === "") onThreshold(null);
            else if (Number(t) >= 0) onThreshold(Number(Number(t).toFixed(2)));
            else setThreshold(current);
          }} />
      </td>
      <td>
        <label className="switch">
          <input type="checkbox" checked={c.is_active} disabled={disabled} onChange={onToggle} />
          <span>{c.is_active ? "Active" : "Hidden"}</span>
        </label>
      </td>
      <td className="order">
        <button type="button" className="icon-btn" disabled={disabled || first} onClick={() => onMove(-1)} aria-label={`Move ${c.name} up`}>↑</button>
        <button type="button" className="icon-btn" disabled={disabled || last} onClick={() => onMove(1)} aria-label={`Move ${c.name} down`}>↓</button>
      </td>
    </tr>
  );
}

function ChangePassword() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const mismatch = confirm.length > 0 && next !== confirm;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (next.length < 10) { toast.error("New password must be at least 10 characters"); return; }
    if (next !== confirm) return;
    setBusy(true);
    try {
      await api.changePassword(current, next);
      toast.success("Password changed");
      setCurrent(""); setNext(""); setConfirm("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not change the password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel narrow">
      <h2>Change password</h2>
      <form className="form" onSubmit={submit}>
        <label className="field"><span>Current password</span>
          <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required /></label>
        <label className="field"><span>New password (10+ characters)</span>
          <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={10} /></label>
        <label className={mismatch ? "field has-error" : "field"}><span>Confirm new password</span>
          <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
          {mismatch && <small className="field-error">Passwords don't match.</small>}</label>
        <div className="form-actions">
          <span className="spacer" />
          <button type="submit" className="btn btn-primary" disabled={busy || !current || !next || mismatch}>
            {busy ? "Saving…" : "Change password"}
          </button>
        </div>
      </form>
    </section>
  );
}

function BooksPanel({ isOwner }: { isOwner: boolean }) {
  const toast = useToast();
  const [status, setStatus] = useState<BooksStatus | null>(null);
  const [closing, setClosing] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.booksStatus().then((s) => { setStatus(s); setClosing(s.closing_date ?? ""); }).catch((e: Error) => toast.error(e.message));
  }, [toast]);

  async function save(value: string | null) {
    setBusy(true);
    try {
      const s = await api.setClosingDate(value);
      setStatus(s);
      setClosing(s.closing_date ?? "");
      toast.success(s.closing_date ? `Books closed through ${formatDate(s.closing_date)}` : "Closing date removed");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the closing date");
    } finally {
      setBusy(false);
    }
  }

  if (!status) return null;
  return (
    <section className="panel">
      <h2>Books</h2>
      <div className="books-health">
        <div className={status.balanced ? "health ok" : "health bad"}>
          <strong>{status.balanced ? "Your books are in balance." : "Your books are out of balance."}</strong>
          <span className="muted"> Total debits {money(status.total_debit)} · total credits {money(status.total_credit)}</span>
        </div>
        {status.unbalanced_entries > 0 && (
          <p className="field-error">{status.unbalanced_entries} entr{status.unbalanced_entries === 1 ? "y doesn't" : "ies don't"} balance.</p>
        )}
        {status.payment_account_not_set > 0 && (
          <p className="hint">
            {status.payment_account_not_set} expense{status.payment_account_not_set === 1 ? " has" : "s have"} no payment account,
            so {status.payment_account_not_set === 1 ? "it sits" : "they sit"} in "Payment Account Not Set".
            Open {status.payment_account_not_set === 1 ? "it" : "them"} from Expenses and choose the bank or card that paid.
          </p>
        )}
      </div>
      <h3>Closing date</h3>
      <p className="muted">
        Closing the books stops anyone from adding, changing or deleting anything dated on or before this date,
        so filed numbers stay put. Set it after your accountant finishes a year or quarter.
      </p>
      <form className="inline-form flat" onSubmit={(e) => { e.preventDefault(); void save(closing || null); }}>
        <label className="field"><span>Closed through</span>
          <input type="date" value={closing} disabled={!isOwner || busy} onChange={(e) => setClosing(e.target.value)} /></label>
        {isOwner && <button type="submit" className="btn" disabled={busy || closing === (status.closing_date ?? "")}>Save closing date</button>}
        {isOwner && status.closing_date && (
          <button type="button" className="link-button" disabled={busy} onClick={() => void save(null)}>Remove closing date</button>
        )}
      </form>
      {!isOwner && <p className="hint">Only an owner can change the closing date.</p>}
    </section>
  );
}

function CompanyPanel({ isAdmin }: { isAdmin: boolean }) {
  const toast = useToast();
  const [company, setCompany] = useState<Company | null>(null);
  const [name, setName] = useState("");
  const [legal, setLegal] = useState("");
  const [fy, setFy] = useState(1);
  const [inv, setInv] = useState({ address: "", phone: "", email: "", website: "", invoice_footer: "" });

  useEffect(() => {
    api.company().then((c) => {
      setCompany(c); setName(c.name); setLegal(c.legal_name ?? ""); setFy(c.fiscal_year_start_month);
      setInv({ address: c.address ?? "", phone: c.phone ?? "", email: c.email ?? "", website: c.website ?? "",
        invoice_footer: c.invoice_footer ?? "" });
    }).catch((e: Error) => toast.error(e.message));
  }, [toast]);

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      const c = await api.updateCompany({ name: name.trim(), legal_name: legal.trim() || null, fiscal_year_start_month: fy,
        address: inv.address.trim() || null, phone: inv.phone.trim() || null, email: inv.email.trim() || null,
        website: inv.website.trim() || null, invoice_footer: inv.invoice_footer.trim() || null });
      setCompany(c);
      toast.success("Company saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save");
    }
  }

  if (!company) return null;
  return (
    <section className="panel">
      <h2>Company</h2>
      <form className="inline-form flat" onSubmit={save}>
        <label className="field grow"><span>Name</span>
          <input value={name} maxLength={255} disabled={!isAdmin} onChange={(e) => setName(e.target.value)} required /></label>
        <label className="field grow"><span>Legal name</span>
          <input value={legal} maxLength={255} disabled={!isAdmin} placeholder="e.g. F&M IT Services LLC" onChange={(e) => setLegal(e.target.value)} /></label>
        <label className="field"><span>Fiscal year starts</span>
          <select value={fy} disabled={!isAdmin} onChange={(e) => setFy(Number(e.target.value))}>
            {MONTH_NAMES.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
          </select></label>
        {isAdmin && <button type="submit" className="btn">Save</button>}
      </form>
      <form className="invoice-details" onSubmit={save}>
        <h3>On your invoices</h3>
        <p className="muted small">Printed at the top of every invoice PDF, under your logo.</p>
        <div className="form-grid">
          <label className="field"><span>Address</span>
            <textarea rows={3} value={inv.address} maxLength={1000} disabled={!isAdmin} placeholder={"1234 Main St, Suite 200\nPembroke Pines, FL 33023"}
              onChange={(e) => setInv({ ...inv, address: e.target.value })} /></label>
          <div className="form-col">
            <label className="field"><span>Phone</span>
              <input value={inv.phone} maxLength={50} disabled={!isAdmin} onChange={(e) => setInv({ ...inv, phone: e.target.value })} /></label>
            <label className="field"><span>Email</span>
              <input type="email" value={inv.email} maxLength={255} disabled={!isAdmin} placeholder="billing@yourcompany.com"
                onChange={(e) => setInv({ ...inv, email: e.target.value })} /></label>
            <label className="field"><span>Website</span>
              <input value={inv.website} maxLength={255} disabled={!isAdmin} onChange={(e) => setInv({ ...inv, website: e.target.value })} /></label>
          </div>
          <label className="field span-2"><span>Payment instructions (bottom of every invoice)</span>
            <textarea rows={3} value={inv.invoice_footer} maxLength={2000} disabled={!isAdmin}
              placeholder={"Pay by ACH: Bank name, routing and account number\nOr mail a check to the address above."}
              onChange={(e) => setInv({ ...inv, invoice_footer: e.target.value })} /></label>
        </div>
        {isAdmin && <div className="form-actions"><button type="submit" className="btn">Save invoice details</button></div>}
      </form>
      <LogoEditor company={company} isAdmin={isAdmin} onChange={setCompany} />
    </section>
  );
}

function BillReadingPanel() {
  const [caps, setCaps] = useState<BillCapabilities | null>(null);
  useEffect(() => { api.billCapabilities().then(setCaps).catch(() => setCaps(null)); }, []);
  if (!caps) return null;
  const aiState = caps.ai_mode === "fallback" ? "On, only when offline reading isn't sure"
    : caps.ai_mode === "always" ? "On for every bill"
    : caps.ai_requested !== "off" && !caps.ai_key_set ? "Turned on, but ANTHROPIC_API_KEY is empty" : "Off";
  return (
    <section className="panel">
      <h2>Bill reading</h2>
      <dl className="facts">
        <dt>Offline reading</dt><dd>PDF, Word and email text{caps.ocr ? ", plus OCR for scans and photos" : " (OCR unavailable)"}</dd>
        <dt>AI reading</dt><dd>{aiState}{caps.ai_mode !== "off" && <span className="muted"> ({caps.ai_model})</span>}</dd>
      </dl>
      <p className="hint">
        To turn AI reading on, add these lines to the .env file next to FMFinance.exe and restart the app:
        AI_EXTRACTION=fallback and ANTHROPIC_API_KEY=your key. When AI is used, the bill is sent to Anthropic to be read.
      </p>
    </section>
  );
}

function LogoEditor({ company, isAdmin, onChange }: { company: Company; isAdmin: boolean; onChange: (c: Company) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function upload(file: File | undefined) {
    if (!file) return;
    if (file.size > 1024 * 1024) { toast.error("The logo must be 1 MB or smaller."); return; }
    setBusy(true);
    try {
      onChange(await api.uploadLogo(file));
      window.dispatchEvent(new Event(BRANDING_CHANGED));
      toast.success("Logo updated");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not upload the logo");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function remove() {
    setBusy(true);
    try {
      onChange(await api.removeLogo());
      window.dispatchEvent(new Event(BRANDING_CHANGED));
      toast.success("Logo removed");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not remove the logo");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="logo-editor">
      <div className={company.has_logo ? "logo-preview" : "logo-preview empty"}>
        {company.has_logo
          ? <img src={`/api/company/logo?v=${company.logo_version}`} alt={`${company.name} logo`} />
          : <span>Your logo here</span>}
      </div>
      <div className="logo-actions">
        <strong>Company logo</strong>
        <p className="hint">PNG, JPG or WEBP up to 1 MB. A wide logo on a transparent or white background works best
          (about 4 to 1). It appears in the sidebar and on the sign-in page, and later on invoices.</p>
        {isAdmin && (
          <div className="form-actions">
            <button type="button" className="btn" disabled={busy} onClick={() => input.current?.click()}>
              {company.has_logo ? "Replace logo" : "Upload logo"}
            </button>
            {company.has_logo && <button type="button" className="link-button" disabled={busy} onClick={() => void remove()}>Remove</button>}
            <input ref={input} type="file" hidden accept=".png,.jpg,.jpeg,.webp" onChange={(e) => void upload(e.target.files?.[0])} />
          </div>
        )}
      </div>
    </div>
  );
}

const SMTP_PRESETS = {
  gmail: { label: "Gmail / Google Workspace", host: "smtp.gmail.com", port: 587, security: "starttls" as const,
    help: "Use your Gmail address and an app password (Google Account › Security › 2-Step Verification › App passwords), not your normal password." },
  other: { label: "Other mail server", host: "", port: 587, security: "starttls" as const,
    help: "Ask your email provider for the SMTP server name and port. Port 587 normally uses STARTTLS; port 465 uses SSL." },
};
type Choice = "microsoft" | keyof typeof SMTP_PRESETS;
const GUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

function EmailPanel({ isOwner }: { isOwner: boolean }) {
  const toast = useToast();
  const { user } = useAuth();
  const [saved, setSaved] = useState<EmailSettings | null>(null);
  const [choice, setChoice] = useState<Choice>("microsoft");
  const [testTo, setTestTo] = useState(user?.email ?? "");
  const [busy, setBusy] = useState(false);

  const apply = useCallback((s: EmailSettings) => {
    setSaved(s);
    if (s.configured) {
      setChoice(s.provider === "microsoft" ? "microsoft" : s.smtp_host === SMTP_PRESETS.gmail.host ? "gmail" : "other");
    }
  }, []);
  useEffect(() => { api.emailSettings().then(apply).catch(() => setSaved(null)); }, [apply]);

  async function test() {
    setBusy(true);
    try {
      await api.testEmail(testTo.trim());
      toast.success(`Test email sent to ${testTo.trim()}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "The test email failed");
    } finally {
      setBusy(false);
    }
  }

  const connectedHere = saved?.configured && (saved.provider === "microsoft") === (choice === "microsoft");
  return (
    <section className="panel" id="email">
      <h2>Email</h2>
      <p className="muted">Invoices are emailed from your own mailbox with the PDF attached, so replies come back to you.
        {saved?.configured ? "" : " Not set up yet: you can still download invoice PDFs and send them yourself."}</p>
      <div className="preset-row" role="radiogroup" aria-label="Email provider">
        <label className={choice === "microsoft" ? "preset active" : "preset"}>
          <input type="radio" name="preset" checked={choice === "microsoft"} disabled={!isOwner} onChange={() => setChoice("microsoft")} />
          Microsoft 365 / Outlook <span className="tag">works with MFA</span>
        </label>
        {(Object.keys(SMTP_PRESETS) as (keyof typeof SMTP_PRESETS)[]).map((k) => (
          <label key={k} className={choice === k ? "preset active" : "preset"}>
            <input type="radio" name="preset" checked={choice === k} disabled={!isOwner} onChange={() => setChoice(k)} />
            {SMTP_PRESETS[k].label}
          </label>
        ))}
      </div>

      {saved && choice === "microsoft" && (
        <MicrosoftConnect saved={saved} isOwner={isOwner} onChange={apply} />
      )}
      {saved && choice !== "microsoft" && (
        <SmtpForm preset={choice} saved={saved} isOwner={isOwner} onSaved={apply} />
      )}

      {connectedHere && isOwner && (
        <div className="inline-form">
          <label className="field grow"><span>Send a test email to</span>
            <input type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} /></label>
          <button type="button" className="btn" disabled={busy || !testTo.trim()} onClick={() => void test()}>{busy ? "Sending…" : "Send test"}</button>
        </div>
      )}
      {!isOwner && <p className="hint">Only an owner can change the email settings.</p>}
    </section>
  );
}

function MicrosoftConnect({ saved, isOwner, onChange }: { saved: EmailSettings; isOwner: boolean; onChange: (s: EmailSettings) => void }) {
  const toast = useToast();
  const connected = saved.configured && saved.provider === "microsoft";
  const [clientId, setClientId] = useState(saved.ms_client_id ?? "");
  const [tenantId, setTenantId] = useState(saved.ms_tenant ?? "");
  const [editingId, setEditingId] = useState(!saved.microsoft_ready);
  const [flow, setFlow] = useState<MicrosoftStart | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [replyTo, setReplyTo] = useState(saved.reply_to ?? "");
  const [copyMe, setCopyMe] = useState(saved.copy_me);
  const [showHelp, setShowHelp] = useState(!saved.microsoft_ready);

  useEffect(() => {
    setReplyTo(saved.reply_to ?? ""); setCopyMe(saved.copy_me);
    if (saved.configured && saved.provider === "microsoft") { setEditingId(false); setShowHelp(false); }
  }, [saved]);

  // Poll until the person finishes signing in on Microsoft's page.
  useEffect(() => {
    if (!flow) return;
    let stop = false;
    const tick = async () => {
      if (stop) return;
      try {
        const r = await api.msPoll(flow.flow_id);
        if (stop) return;
        if (r.status === "connected" && r.settings) {
          setFlow(null);
          onChange(r.settings);
          toast.success(`Connected to Microsoft 365 as ${r.settings.oauth_account}`);
          return;
        }
        window.setTimeout(() => void tick(), Math.max(flow.interval, 2) * 1000);
      } catch (err) {
        if (stop) return;
        setFlow(null);
        setError(err instanceof Error ? err.message : "The sign-in didn't finish");
      }
    };
    const first = window.setTimeout(() => void tick(), Math.max(flow.interval, 2) * 1000);
    return () => { stop = true; window.clearTimeout(first); };
  }, [flow, onChange, toast]);

  async function start() {
    setError("");
    const id = clientId.trim();
    if (editingId && id && !GUID.test(id)) { setError("The Application (client) ID looks like 00000000-0000-0000-0000-000000000000."); return; }
    setBusy(true);
    try {
      const tenant = tenantId.trim();
      setFlow(await api.msStart(editingId && id ? id : null, editingId ? (tenant || "organizations") : null));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't start the Microsoft sign-in");
    } finally {
      setBusy(false);
    }
  }

  async function saveOptions(e: FormEvent) {
    e.preventDefault();
    try {
      onChange(await api.saveEmailOptions({ reply_to: replyTo.trim() || null, copy_me: copyMe }));
      toast.success("Saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save");
    }
  }

  return (
    <div className="ms-connect">
      {connected && !flow && (
        <div className="health ok">
          <strong>Connected to Microsoft 365 as {saved.oauth_account}.</strong>
          <span className="muted"> Invoices are sent from this mailbox and saved in its Sent Items. Your password and MFA stay with Microsoft.</span>
        </div>
      )}
      {!connected && !flow && (
        <p className="hint">You'll sign in on Microsoft's own page, with your password and MFA as usual. F&amp;M Finance never sees your
          password; it keeps only a sign-in token, encrypted.</p>
      )}

      {flow ? (
        <div className="device-code">
          <ol>
            <li>Copy this code:
              <div className="code-row">
                <code className="user-code">{flow.user_code}</code>
                <button type="button" className="btn" onClick={() => { void navigator.clipboard?.writeText(flow.user_code); toast.success("Code copied"); }}>Copy</button>
              </div>
            </li>
            <li>Open <a href={flow.verification_uri} target="_blank" rel="noreferrer">{flow.verification_uri.replace("https://", "")}</a>,
              paste the code and sign in with the mailbox that should send invoices (for example billing@yourcompany.com).</li>
            <li>Approve F&amp;M Finance sending mail for you. This page updates by itself when you're done.</li>
          </ol>
          <p className="muted small"><span className="spinner" aria-hidden="true" /> Waiting for you to finish signing in…</p>
          <button type="button" className="link-button" onClick={() => setFlow(null)}>Cancel</button>
        </div>
      ) : isOwner && (
        <>
          {editingId ? (
            <div className="client-id">
              <div className="grid-2">
                <label className="field"><span>Application (client) ID</span>
                  <input value={clientId} maxLength={64} placeholder="00000000-0000-0000-0000-000000000000" spellCheck={false}
                    onChange={(e) => setClientId(e.target.value)} /></label>
                <label className="field"><span>Directory (tenant) ID</span>
                  <input value={tenantId} maxLength={64} placeholder="00000000-0000-0000-0000-000000000000" spellCheck={false}
                    onChange={(e) => setTenantId(e.target.value)} /></label>
              </div>
              <p className="small muted">Both are on the app registration's Overview page. The tenant ID is needed for a single-tenant app
                (one app per company, recommended); leave it empty only for a multitenant app.
                {saved.ms_client_id_in_env ? " Leave the app ID empty to use the one in the app's .env file." : ""}</p>
            </div>
          ) : (
            <p className="small muted">Microsoft app ID: {saved.ms_client_id ?? "from the .env file"}
              {saved.ms_tenant ? ` · tenant ${saved.ms_tenant}` : ""} ·{" "}
              <button type="button" className="link-button" onClick={() => setEditingId(true)}>change</button></p>
          )}
          <div className="form-actions">
            <button type="button" className="btn btn-primary" disabled={busy || (editingId && !clientId.trim() && !saved.ms_client_id_in_env)}
              onClick={() => void start()}>{busy ? "Starting…" : connected ? "Reconnect Microsoft 365" : "Connect Microsoft 365"}</button>
            {connected && (
              <button type="button" className="btn btn-danger-quiet" onClick={async () => {
                if (!window.confirm("Disconnect Microsoft 365? Invoices can't be emailed until you connect again.")) return;
                onChange(await api.msDisconnect());
                toast.success("Disconnected");
              }}>Disconnect</button>
            )}
            <span className="spacer" />
            <button type="button" className="link-button" onClick={() => setShowHelp(!showHelp)}>
              {showHelp ? "Hide setup steps" : "How do I get these IDs?"}</button>
          </div>
        </>
      )}
      {error && <p className="form-error">{error}</p>}

      {showHelp && !flow && (
        <div className="setup-steps">
          <h3>One-time setup in Microsoft Entra (about 5 minutes, by a Microsoft 365 admin)</h3>
          <ol>
            <li>Go to <a href="https://entra.microsoft.com" target="_blank" rel="noreferrer">entra.microsoft.com</a> › Applications › App registrations › <strong>New registration</strong>.</li>
            <li>Name: <strong>F&amp;M Finance</strong>. Supported account types: <strong>Accounts in this organizational directory only (single tenant)</strong>. Leave Redirect URI empty. Register.</li>
            <li>Open <strong>Authentication</strong> and set <strong>Allow public client flows</strong> to <strong>Yes</strong>. Save.</li>
            <li>Open <strong>API permissions</strong> › Add a permission › Microsoft Graph › Delegated › tick <strong>Mail.Send</strong> and <strong>offline_access</strong> (User.Read is already there). Then click <strong>Grant admin consent</strong> for your organization.</li>
            <li>On <strong>Overview</strong>, copy the <strong>Application (client) ID</strong> and the <strong>Directory (tenant) ID</strong>,
              paste them above, then click Connect Microsoft 365.</li>
          </ol>
          <p className="small muted">No client secret is needed. Each company uses an app in its own Microsoft 365, and the IDs are saved
            only in that company's settings.</p>
        </div>
      )}

      {connected && !flow && isOwner && (
        <form className="inline-form" onSubmit={saveOptions}>
          <label className="field grow"><span>Replies go to (optional)</span>
            <input type="email" value={replyTo} maxLength={255} placeholder={saved.oauth_account ?? ""} onChange={(e) => setReplyTo(e.target.value)} /></label>
          <label className="check"><input type="checkbox" checked={copyMe} onChange={(e) => setCopyMe(e.target.checked)} /> Send me a copy (Bcc)</label>
          <button type="submit" className="btn">Save</button>
        </form>
      )}
    </div>
  );
}

function SmtpForm({ preset, saved, isOwner, onSaved }: {
  preset: keyof typeof SMTP_PRESETS; saved: EmailSettings; isOwner: boolean; onSaved: (s: EmailSettings) => void;
}) {
  const toast = useToast();
  const p = SMTP_PRESETS[preset];
  const smtpSaved = saved.configured && saved.provider === "smtp";
  const [f, setF] = useState({
    smtp_host: smtpSaved ? saved.smtp_host ?? "" : p.host, smtp_port: String(smtpSaved ? saved.smtp_port ?? 587 : p.port),
    security: (smtpSaved ? saved.security ?? "starttls" : p.security) as "starttls" | "ssl" | "none",
    username: smtpSaved ? saved.username ?? "" : "", password: "", from_email: smtpSaved ? saved.from_email ?? "" : "",
    from_name: smtpSaved ? saved.from_name ?? "" : "", reply_to: smtpSaved ? saved.reply_to ?? "" : "", copy_me: smtpSaved ? saved.copy_me : true,
  });
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (preset === "gmail") setF((x) => ({ ...x, smtp_host: p.host, smtp_port: String(p.port), security: p.security }));
  }, [preset, p.host, p.port, p.security]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (saved.configured && saved.provider === "microsoft"
      && !window.confirm("Switch from Microsoft 365 sign-in to this mail server? The Microsoft connection is removed.")) return;
    setBusy(true);
    try {
      const s = await api.saveEmailSettings({
        smtp_host: f.smtp_host.trim(), smtp_port: Number(f.smtp_port) || 587, security: f.security,
        username: f.username.trim() || null, password: f.password ? f.password : null, from_email: f.from_email.trim(),
        from_name: f.from_name.trim() || null, reply_to: f.reply_to.trim() || null, copy_me: f.copy_me,
      });
      onSaved(s);
      setF((x) => ({ ...x, password: "" }));
      toast.success("Email settings saved. Send a test to check them.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  const disabled = !isOwner || busy;
  return (
    <>
      <p className="hint">{p.help}</p>
      <form className="form-grid" onSubmit={save}>
        <label className="field"><span>Your email address (sends the invoices)</span>
          <input type="email" value={f.from_email} required maxLength={255} disabled={disabled} placeholder="billing@yourcompany.com"
            onChange={(e) => setF({ ...f, from_email: e.target.value })}
            onBlur={() => !f.username && setF((x) => ({ ...x, username: x.from_email }))} /></label>
        <label className="field"><span>Name shown to customers</span>
          <input value={f.from_name} maxLength={255} disabled={disabled} onChange={(e) => setF({ ...f, from_name: e.target.value })} /></label>
        <label className="field"><span>Sign-in name</span>
          <input value={f.username} maxLength={255} disabled={disabled} autoComplete="off" placeholder="Usually the same email address"
            onChange={(e) => setF({ ...f, username: e.target.value })} /></label>
        <label className="field"><span>Password {preset === "gmail" ? "(app password)" : ""}</span>
          <input type="password" value={f.password} maxLength={500} disabled={disabled} autoComplete="new-password"
            placeholder={smtpSaved && saved.has_password ? "Saved. Leave blank to keep it." : ""} onChange={(e) => setF({ ...f, password: e.target.value })} /></label>
        <label className="field"><span>Mail server (SMTP)</span>
          <input value={f.smtp_host} required maxLength={255} disabled={disabled || preset !== "other"}
            onChange={(e) => setF({ ...f, smtp_host: e.target.value })} /></label>
        <div className="grid-2">
          <label className="field"><span>Port</span>
            <input inputMode="numeric" value={f.smtp_port} disabled={disabled || preset !== "other"}
              onChange={(e) => setF({ ...f, smtp_port: e.target.value.replace(/[^0-9]/g, "") })} /></label>
          <label className="field"><span>Security</span>
            <select value={f.security} disabled={disabled || preset !== "other"}
              onChange={(e) => setF({ ...f, security: e.target.value as "starttls" | "ssl" | "none" })}>
              <option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option><option value="none">None (not recommended)</option>
            </select></label>
        </div>
        <label className="field"><span>Replies go to (optional)</span>
          <input type="email" value={f.reply_to} maxLength={255} disabled={disabled} onChange={(e) => setF({ ...f, reply_to: e.target.value })} /></label>
        <label className="check"><input type="checkbox" checked={f.copy_me} disabled={disabled}
          onChange={(e) => setF({ ...f, copy_me: e.target.checked })} /> Send me a copy of every invoice email (Bcc)</label>
        {isOwner && (
          <div className="form-actions span-2">
            {smtpSaved && <button type="button" className="btn btn-danger-quiet" disabled={busy} onClick={async () => {
              if (!window.confirm("Remove the email settings? Invoices can still be downloaded as PDFs.")) return;
              await api.removeEmailSettings(); onSaved({ ...saved, configured: false, has_password: false }); toast.success("Email settings removed");
            }}>Remove</button>}
            <span className="spacer" />
            <button type="submit" className="btn btn-primary" disabled={busy || !f.from_email.trim() || !f.smtp_host.trim()}>Save email settings</button>
          </div>
        )}
      </form>
    </>
  );
}

function PlanPanel() {
  const { user } = useAuth();
  const [catalog, setCatalog] = useState<PlansCatalog | null>(null);
  useEffect(() => { api.plansCatalog().then(setCatalog).catch(() => setCatalog(null)); }, []);
  if (!user?.company_id) return null;
  return (
    <section className="panel" id="plan">
      <h2>Your plan: {user.plan_label ?? "All modules"}</h2>
      <p className="muted">Core is always included: dashboard, expenses, accounts and banking, chart of accounts, profit and loss,
        balance sheet, closing date, history and export. Your administrator manages the plan.</p>
      <ul className="plan-modules">
        {(catalog?.modules ?? []).map((m) => {
          const on = hasModule(user, m.key);
          return (
            <li key={m.key} className={on ? "on" : "off"}>
              <span aria-hidden="true">{on ? "✓" : "–"}</span>
              <div><strong>{m.label}</strong>{!on && user.module_data?.includes(m.key) ? <span className="tag">view only</span> : null}
                <div className="muted small">{m.description}</div></div>
            </li>
          );
        })}
      </ul>
      <p className="small muted">Users: {user.seats_used ?? 0} of {user.user_limit ?? "unlimited"} (the Accountant doesn't count).</p>
    </section>
  );
}
