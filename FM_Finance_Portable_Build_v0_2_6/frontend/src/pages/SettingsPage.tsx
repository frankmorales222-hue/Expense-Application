import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth, useToast } from "../context";
import { money } from "../format";
import type { Category } from "../types";

export default function SettingsPage() {
  const { settings, user } = useAuth();
  const toast = useToast();
  const isAdmin = user?.role === "admin";
  const [categories, setCategories] = useState<Category[]>([]);
  const [newName, setNewName] = useState("");
  const [newThreshold, setNewThreshold] = useState("");
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
      await api.createCategory(newName.trim(), t ? Number(t) : null);
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

      <section className="panel">
        <h2>Expense categories</h2>
        <p className="muted">
          {settings?.approval_required
            ? `Approval is on. Expenses at or above a category's threshold (default ${money(settings.default_approval_threshold)}) wait for approval.`
            : "Approval is off, so every expense is saved as approved. Thresholds only apply if APPROVAL_REQUIRED is turned on in the server's .env file."}
        </p>
        <div className="table-wrap">
          <table className="ledger settings-table">
            <thead>
              <tr><th>Name</th><th className="num">Approval threshold</th><th>Active</th><th><span className="sr-only">Order</span></th></tr>
            </thead>
            <tbody>
              {categories.map((c, i) => (
                <CategoryRow key={c.id} category={c} disabled={!isAdmin || busyId !== null}
                  first={i === 0} last={i === categories.length - 1}
                  defaultThreshold={settings?.default_approval_threshold ?? 500}
                  onRename={(name) => void update(c, { name }, "Category renamed")}
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
            <label className="field"><span>Threshold (optional)</span>
              <input inputMode="decimal" value={newThreshold} onChange={(e) => setNewThreshold(e.target.value)} placeholder="Default" /></label>
            <button type="submit" className="btn btn-primary" disabled={!newName.trim()}>Add category</button>
          </form>
        )}
      </section>

      <ChangePassword />
    </div>
  );
}

function CategoryRow({ category: c, disabled, first, last, defaultThreshold, onRename, onThreshold, onToggle, onMove }: {
  category: Category; disabled: boolean; first: boolean; last: boolean; defaultThreshold: number;
  onRename: (name: string) => void; onThreshold: (v: number | null) => void; onToggle: () => void; onMove: (dir: -1 | 1) => void;
}) {
  const [name, setName] = useState(c.name);
  const [threshold, setThreshold] = useState(c.approval_threshold?.toFixed(2) ?? "");
  useEffect(() => { setName(c.name); setThreshold(c.approval_threshold?.toFixed(2) ?? ""); }, [c]);

  return (
    <tr className={c.is_active ? "" : "inactive"}>
      <td>
        <input className="cell-input" value={name} disabled={disabled} maxLength={100} aria-label="Category name"
          onChange={(e) => setName(e.target.value)}
          onBlur={() => { if (name.trim() && name.trim() !== c.name) onRename(name.trim()); else setName(c.name); }} />
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
