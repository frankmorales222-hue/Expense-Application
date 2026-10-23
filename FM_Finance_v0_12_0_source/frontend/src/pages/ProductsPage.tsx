import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ModuleNotice, useModule } from "../modules";
import { api } from "../api";
import { useToast } from "../context";
import { money, currencySymbol } from "../format";
import CustomFields from "../components/CustomFields";
import type { Category, CustomValues, Item } from "../types";

export default function ProductsPage() {
  const toast = useToast();
  const [items, setItems] = useState<Item[] | null>(null);
  const [cats, setCats] = useState<Category[]>([]);
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<Item | "new" | null>(null);
  const { on } = useModule("invoicing");

  const load = useCallback(() => {
    api.items(showInactive).then(setItems).catch((e: Error) => toast.error(e.message));
  }, [showInactive, toast]);
  useEffect(load, [load]);
  useEffect(() => { api.categories(true).then((c) => setCats(c.filter((x) => x.kind === "income"))).catch(() => setCats([])); }, []);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Products and services</h1>
          <p className="muted">What you sell, with a default rate and description, so invoices fill in quickly.
            Each one goes to an income category on your Profit and loss.</p>
        </div>
        {on && <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>New product or service</button>}
      </header>

      <ModuleNotice module="invoicing" />
      {editing && <ItemForm item={editing === "new" ? null : editing} cats={cats}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}

      <div className="toolbar">
        <label className="switch"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          <span>Include inactive</span></label>
      </div>

      <section className="panel flush">
        {items && items.length === 0 ? (
          <div className="empty inner">
            <p>Nothing here yet. Add the services you bill, such as "Managed IT – per user", "vCIO hour" or "Onsite visit".</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="ledger">
              <thead><tr><th>Name</th><th>Description</th><th>Income category</th><th className="num">Rate</th></tr></thead>
              <tbody>
                {(items ?? []).map((it) => (
                  <tr key={it.id} className={it.is_active ? "" : "inactive"} onClick={() => on && setEditing(it)}>
                    <td><strong>{it.name}</strong>{!it.is_active && <span className="tag">inactive</span>}</td>
                    <td className="muted desc">{it.description ?? ""}</td>
                    <td>{it.category_name}</td>
                    <td className="num">{it.rate !== null ? money(it.rate) : <span className="muted">—</span>}</td>
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

function ItemForm({ item, cats, onClose, onSaved }: { item: Item | null; cats: Category[]; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(item?.name ?? "");
  const [description, setDescription] = useState(item?.description ?? "");
  const [rate, setRate] = useState(item?.rate !== null && item?.rate !== undefined ? item.rate.toFixed(2) : "");
  const [categoryId, setCategoryId] = useState(item?.category_id ?? cats.find((c) => c.code === "client_services_revenue")?.id ?? cats[0]?.id ?? "");
  const [active, setActive] = useState(item?.is_active ?? true);
  const [custom, setCustom] = useState<CustomValues>(item?.custom ?? {});
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (!categoryId && cats[0]) setCategoryId(cats.find((c) => c.code === "client_services_revenue")?.id ?? cats[0].id); }, [cats, categoryId]);

  async function save(e: FormEvent) {
    e.preventDefault();
    const body = { name: name.trim(), description: description.trim() || null, rate: rate ? Number(Number(rate).toFixed(2)) : null,
      category_id: categoryId, is_active: active, custom };
    setBusy(true);
    try {
      if (item) await api.updateItem(item.id, body); else await api.createItem(body);
      toast.success(item ? "Saved" : `Added ${body.name}`);
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>{item ? `Edit ${item.name}` : "New product or service"}</h2>
      <form className="form-grid" onSubmit={save}>
        <label className="field"><span>Name</span>
          <input value={name} maxLength={150} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Managed IT – per user" /></label>
        <label className="field"><span>Rate (optional)</span>
          <div className="money-input"><span>{currencySymbol().trim()}</span>
            <input inputMode="decimal" value={rate} placeholder="0.00" onChange={(e) => setRate(e.target.value.replace(/[^0-9.]/g, ""))} /></div></label>
        <label className="field span-2"><span>Description on invoices (optional)</span>
          <input value={description} maxLength={1000} onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. Help desk, patching, monitoring and backups for one user, per month" /></label>
        <label className="field"><span>Income category</span>
          <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} required>
            {cats.filter((c) => c.is_active || c.id === categoryId).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select></label>
        {item && <label className="switch"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          <span>{active ? "Active" : "Inactive (hidden on new invoices)"}</span></label>}
        <div className="span-2"><CustomFields entity="item" value={custom} onChange={setCustom} /></div>
        <div className="form-actions span-2">
          <span className="spacer" />
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !name.trim() || !categoryId}>{busy ? "Saving…" : "Save"}</button>
        </div>
      </form>
    </section>
  );
}
