import { useCallback, useEffect, useState, type FormEvent } from "react";
import TempPassword from "../components/TempPassword";
import { api } from "../api";
import { useToast } from "../context";
import type { Reseller } from "../types";

export default function ResellersPage() {
  const toast = useToast();
  const [resellers, setResellers] = useState<Reseller[]>([]);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);

  const load = useCallback(() => {
    api.resellers().then(setResellers).catch((e: Error) => toast.error(e.message));
  }, [toast]);
  useEffect(load, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api.createReseller(name.trim());
      toast.success(`${r.name} added. Now add its administrator.`);
      setName("");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add the reseller");
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Resellers</h1>
          <p className="muted">Partners, such as an accounting firm, who offer F&amp;M Finance to their own clients.
            Their administrators add and open their client companies; you can't open those books unless they add you.</p>
        </div>
      </header>

      {created && <TempPassword email={created.email} password={created.password} onDone={() => setCreated(null)} />}

      {resellers.map((r) => <ResellerCard key={r.id} reseller={r} onChanged={load} onCreatedUser={setCreated} />)}

      <section className="panel">
        <h2>Add a reseller</h2>
        <form className="inline-form flat" onSubmit={add}>
          <label className="field grow"><span>Reseller name</span>
            <input value={name} maxLength={255} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Garcia Tax & Accounting" /></label>
          <button type="submit" className="btn btn-primary" disabled={!name.trim()}>Add reseller</button>
        </form>
      </section>
    </div>
  );
}

function ResellerCard({ reseller: r, onChanged, onCreatedUser }: {
  reseller: Reseller; onChanged: () => void; onCreatedUser: (v: { email: string; password: string }) => void;
}) {
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");

  async function addAdmin(e: FormEvent) {
    e.preventDefault();
    try {
      const res = await api.addResellerAdmin(r.id, email.trim(), name.trim() || null);
      if (res.temporary_password) onCreatedUser({ email: res.admin.email, password: res.temporary_password });
      else toast.success(`${res.admin.name} now manages ${r.name}`);
      setEmail(""); setName("");
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add the administrator");
    }
  }

  async function removeAdmin(userId: string, who: string) {
    if (!window.confirm(`Remove ${who} as an administrator of ${r.name}? They lose access to its client companies.`)) return;
    try {
      await api.removeResellerAdmin(r.id, userId);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not remove the administrator");
    }
  }

  async function toggleActive() {
    try {
      await api.updateReseller(r.id, r.name, !r.is_active);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update the reseller");
    }
  }

  return (
    <section className={r.is_active ? "panel" : "panel inactive"}>
      <div className="panel-head">
        <h2>{r.name}{!r.is_active && <span className="tag">Paused</span>}</h2>
        <span className="muted">{r.company_count} client compan{r.company_count === 1 ? "y" : "ies"}</span>
      </div>
      {r.admins.length === 0 ? <p className="muted">No administrator yet.</p> : (
        <ul className="admin-list">
          {r.admins.map((a) => (
            <li key={a.user_id}><span>{a.name} <span className="muted">{a.email}</span></span>
              <button type="button" className="link-button" onClick={() => void removeAdmin(a.user_id, a.name)}>Remove</button></li>
          ))}
        </ul>
      )}
      <form className="inline-form" onSubmit={addAdmin}>
        <label className="field grow"><span>Administrator email</span>
          <input type="email" value={email} maxLength={255} required onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="field grow"><span>Name</span>
          <input value={name} maxLength={255} onChange={(e) => setName(e.target.value)} /></label>
        <button type="submit" className="btn" disabled={!email.trim()}>Add administrator</button>
      </form>
      <button type="button" className="link-button" onClick={() => void toggleActive()}>
        {r.is_active ? "Pause this reseller (its administrators lose access until resumed)" : "Resume this reseller"}
      </button>
    </section>
  );
}
