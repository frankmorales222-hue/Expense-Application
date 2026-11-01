import { Fragment, useCallback, useEffect, useState, type FormEvent } from "react";
import TempPassword from "../components/TempPassword";
import { useAuth, useToast } from "../context";
import { api } from "../api";
import { ROLE_HELP, ROLE_LABEL } from "../format";
import type { AreaLevel, CompanyRole, CustomRole, Member, RoleAreas, RoleInput } from "../types";
import ConfirmDialog from "../components/ConfirmDialog";

const ROLES: CompanyRole[] = ["owner", "accountant", "bookkeeper", "employee", "viewer"];
const LEVEL_LABEL: Record<AreaLevel, string> = { full: "Full", view: "View only", none: "No access" };
const ORDER: Record<AreaLevel, number> = { none: 0, view: 1, full: 2 };

/** Role choices are "base:owner" or "custom:<id>" (a company role always sits on a base role). */
function roleValue(m: { role: CompanyRole; custom_role_id?: string | null }): string {
  return m.custom_role_id ? `custom:${m.custom_role_id}` : `base:${m.role}`;
}
function parseRole(v: string, roles: CustomRole[]): { role: CompanyRole; custom_role_id: string | null } {
  if (v.startsWith("custom:")) {
    const r = roles.find((x) => x.id === v.slice(7));
    return { role: r?.base_role ?? "viewer", custom_role_id: r?.id ?? null };
  }
  return { role: v.slice(5) as CompanyRole, custom_role_id: null };
}

function RoleOptions({ roles }: { roles: CustomRole[] }) {
  return (
    <>
      <optgroup label="Built in">{ROLES.map((r) => <option key={r} value={`base:${r}`}>{ROLE_LABEL[r]}</option>)}</optgroup>
      {roles.length > 0 && <optgroup label="Your company's roles">
        {roles.map((r) => <option key={r.id} value={`custom:${r.id}`}>{r.name}</option>)}</optgroup>}
    </>
  );
}

export default function TeamPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("base:bookkeeper");
  const [roles, setRoles] = useState<CustomRole[]>([]);
  const [areas, setAreas] = useState<RoleAreas | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);

  const load = useCallback(() => {
    api.members().then(setMembers).catch((e: Error) => toast.error(e.message));
    api.roles().then(setRoles).catch(() => setRoles([]));
  }, [toast]);
  useEffect(() => { api.roleAreas().then(setAreas).catch(() => setAreas(null)); }, []);
  useEffect(load, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.addMember({ email: email.trim(), name: name.trim() || null, ...parseRole(role, roles) });
      if (r.temporary_password) setCreated({ email: r.member.email, password: r.temporary_password });
      else toast.success(`${r.member.name} can now open ${user?.company_name}`);
      setEmail(""); setName("");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add the person");
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(m: Member, value: string) {
    const next = parseRole(value, roles);
    try {
      await api.changeMemberRole(m.user_id, next.role, next.custom_role_id);
      const label = next.custom_role_id ? roles.find((r) => r.id === next.custom_role_id)?.name ?? "" : ROLE_LABEL[next.role] ?? next.role;
      toast.success(`${m.name} is now ${label.toLowerCase()}`);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not change the role");
    }
  }

  async function remove(m: Member) {
    if (!window.confirm(`Remove ${m.name}'s access to ${user?.company_name}? Their past entries stay.`)) return;
    try {
      await api.removeMember(m.user_id);
      toast.success(`${m.name} no longer has access`);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not remove the person");
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Team</h1>
          <p className="muted">Who can open {user?.company_name}, and what they can do there.
            {user?.user_limit ? ` Your plan includes ${user.user_limit} user${user.user_limit === 1 ? "" : "s"}; ${user.seats_used ?? 0} in use. The Accountant doesn't count.` : ""}</p>
        </div>
      </header>

      {created && <TempPassword email={created.email} password={created.password} onDone={() => setCreated(null)} />}

      <section className="panel flush">
        <div className="table-wrap">
          <table className="ledger settings-table">
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th /></tr></thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.user_id}>
                  <td>{m.name}{m.is_you && <span className="tag">You</span>}</td>
                  <td>{m.email}</td>
                  <td>
                    {m.via_reseller ? <span>Owner <span className="muted">(reseller administrator)</span></span> : (
                      <select className="cell-input" value={roleValue(m)} aria-label={`Role for ${m.name}`}
                        onChange={(e) => void changeRole(m, e.target.value)}>
                        <RoleOptions roles={roles} />
                      </select>
                    )}
                  </td>
                  <td className="row-actions">
                    {!m.via_reseller && !m.is_you && (
                      <button type="button" className="btn btn-small btn-danger-quiet" onClick={() => void remove(m)}>Remove</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h2>Give someone access</h2>
        <form className="inline-form flat" onSubmit={add}>
          <label className="field grow"><span>Email</span>
            <input type="email" value={email} maxLength={255} required onChange={(e) => setEmail(e.target.value)} /></label>
          <label className="field grow"><span>Name (for new sign-ins)</span>
            <input value={name} maxLength={255} onChange={(e) => setName(e.target.value)} /></label>
          <label className="field"><span>Role</span>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <RoleOptions roles={roles} />
            </select></label>
          <button type="submit" className="btn btn-primary" disabled={busy || !email.trim()}>{busy ? "Adding…" : "Add"}</button>
        </form>
        <dl className="facts role-help">
          {ROLES.map((r) => <Fragment key={r}><dt>{ROLE_LABEL[r]}</dt><dd>{ROLE_HELP[r]}</dd></Fragment>)}
        </dl>
        <p className="hint">Someone who already signs in to F&amp;M Finance (for another company) keeps their password.
          New people get a temporary password shown once here.</p>
      </section>

      {areas && <RolesPanel roles={roles} areas={areas} onChanged={load} />}
    </div>
  );
}

// ---------------------------------------------------------------- v0.10.0 the company's own roles
function RolesPanel({ roles, areas, onChanged }: { roles: CustomRole[]; areas: RoleAreas; onChanged: () => void }) {
  const toast = useToast();
  const [editing, setEditing] = useState<CustomRole | "new" | null>(null);
  const [removing, setRemoving] = useState<CustomRole | null>(null);
  return (
    <section className="panel team-roles">
      <div className="panel-head">
        <div>
          <h2>Your company's roles</h2>
          <p className="muted">Start from a built-in role and take away what this job doesn't need, for example a front desk
            person who sends invoices but never sees the bank. A role can limit access, never add to it.</p>
        </div>
        {editing === null && <button type="button" className="btn" onClick={() => setEditing("new")}>New role</button>}
      </div>
      {editing !== null && (
        <RoleEditor role={editing === "new" ? null : editing} areas={areas}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onChanged(); }} />
      )}
      {roles.length > 0 && (
        <div className="table-wrap">
          <table className="ledger">
            <thead><tr><th>Role</th><th>Starts from</th><th>Limits</th><th className="num">People</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {roles.map((r) => {
                const limits = Object.entries(r.effective).filter(([a, l]) => l !== (areas.base[r.base_role]?.[a] ?? "full"));
                return (
                  <tr key={r.id}>
                    <td><strong>{r.name}</strong>{r.description && <div className="small muted">{r.description}</div>}</td>
                    <td>{ROLE_LABEL[r.base_role]}</td>
                    <td><div className="chips">{limits.length === 0 ? <span className="muted small">Same as {ROLE_LABEL[r.base_role]}</span>
                      : limits.map(([a, l]) => <span key={a} className={`chip level-${l}`}>{areaName(areas, a)}: {LEVEL_LABEL[l]}</span>)}</div></td>
                    <td className="num">{r.member_count}</td>
                    <td className="row-actions">
                      <button type="button" className="link-button" onClick={() => setEditing(r)}>Edit</button>
                      <button type="button" className="link-button danger" onClick={() => setRemoving(r)}>Delete</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <ConfirmDialog open={removing !== null} danger title={`Delete the role "${removing?.name ?? ""}"?`} confirmLabel="Delete role"
        message={removing?.member_count ? `${removing.member_count} ${removing.member_count === 1 ? "person goes" : "people go"} back to ${ROLE_LABEL[removing.base_role]}.` : "Nobody has this role."}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          if (!removing) return;
          api.deleteRole(removing.id).then(() => { toast.success("Role deleted"); onChanged(); })
            .catch((e: Error) => toast.error(e.message)).finally(() => setRemoving(null));
        }} />
    </section>
  );
}

function areaName(areas: RoleAreas, key: string): string {
  return (areas.areas[key] ?? key).split(":")[0] ?? key;
}

function RoleEditor({ role, areas, onClose, onSaved }: { role: CustomRole | null; areas: RoleAreas; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState<RoleInput>(() => role
    ? { name: role.name, description: role.description, base_role: role.base_role, permissions: { ...role.permissions } }
    : { name: "", description: null, base_role: "bookkeeper", permissions: {} });
  const [busy, setBusy] = useState(false);
  const base = areas.base[f.base_role] ?? {};

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      if (role) await api.updateRole(role.id, f); else await api.createRole(f);
      toast.success(role ? "Role saved" : `Added ${f.name}`);
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the role");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="role-editor" onSubmit={save}>
      <div className="grid-3">
        <label className="field"><span>Name</span>
          <input value={f.name} maxLength={60} required placeholder="e.g. Front desk" onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label className="field"><span>Starts from</span>
          <select value={f.base_role} onChange={(e) => setF({ ...f, base_role: e.target.value as CompanyRole })}>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select></label>
        <label className="field"><span>Description (optional)</span>
          <input value={f.description ?? ""} maxLength={300} onChange={(e) => setF({ ...f, description: e.target.value || null })} /></label>
      </div>
      <div className="table-wrap">
        <table className="ledger area-table">
          <thead><tr><th>Area</th><th>{ROLE_LABEL[f.base_role]} has</th><th>This role gets</th></tr></thead>
          <tbody>
            {Object.entries(areas.areas).map(([key, label]) => {
              const max = base[key] ?? "full";
              const wanted = f.permissions[key] ?? "full";
              const value = ORDER[wanted] < ORDER[max] ? wanted : max;
              return (
                <tr key={key}>
                  <td>{label}</td>
                  <td><span className={`chip level-${max}`}>{LEVEL_LABEL[max]}</span></td>
                  <td>
                    <select className="cell-input" value={value} disabled={max === "none"} aria-label={`Access to ${key}`}
                      onChange={(e) => {
                        const p = { ...f.permissions };
                        if (e.target.value === max) delete p[key]; else p[key] = e.target.value as AreaLevel;
                        setF({ ...f, permissions: p });
                      }}>
                      {(["full", "view", "none"] as AreaLevel[]).filter((l) => ORDER[l] <= ORDER[max]).map((l) =>
                        <option key={l} value={l}>{LEVEL_LABEL[l]}</option>)}
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="hint">Lists that forms need (categories, customers, accounts) stay readable so people can still fill in what they're allowed to.</p>
      <div className="form-actions">
        <span className="spacer" />
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={busy || !f.name.trim()}>{busy ? "Saving…" : "Save role"}</button>
      </div>
    </form>
  );
}
