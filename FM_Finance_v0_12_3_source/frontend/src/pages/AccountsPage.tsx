import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth, useToast } from "../context";
import { ACCOUNT_KIND_LABEL, money, currencySymbol } from "../format";
import type { Account, AccountInput, AccountKind } from "../types";

const KINDS: AccountKind[] = ["checking", "savings", "credit_card", "cash", "other"];
const blank: AccountInput = { name: "", kind: "checking", institution: null, last4: null, opening_balance: 0, opening_date: null, is_active: true };

export default function AccountsPage() {
  const toast = useToast();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<Account | "new" | null>(null);

  const load = useCallback(() => {
    api.accounts(showInactive).then(setAccounts).catch((e: Error) => toast.error(e.message));
  }, [showInactive, toast]);
  useEffect(load, [load]);

  return (
    <div className="page">
      <header className="page-head">
        <h1>Accounts</h1>
        <div className="actions">
          <label className="switch"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /><span>Show closed</span></label>
          {isAdmin && <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>Add account</button>}
        </div>
      </header>

      {editing && (
        <AccountForm key={editing === "new" ? "new" : editing.id} account={editing === "new" ? null : editing}
          onDone={(saved) => { setEditing(null); if (saved) load(); }} />
      )}

      {accounts.length === 0 && !editing ? (
        <div className="empty">
          <p>Add the bank accounts and credit cards F&amp;M IT Services uses. Each one gets its own statement imports and balance.</p>
          {isAdmin && <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>Add account</button>}
        </div>
      ) : (
        <section className="panel flush">
          <div className="table-wrap">
            <table className="ledger settings-table">
              <thead><tr><th>Account</th><th>Type</th><th>Bank</th><th className="num">Transactions</th><th className="num">Balance</th><th /></tr></thead>
              <tbody>
                {accounts.map((a) => (
                  <tr key={a.id} className={a.is_active ? "" : "inactive"}>
                    <td><Link to={`/banking?account=${a.id}`} className="strong-link">{a.name}</Link>{a.last4 && <span className="muted"> ending {a.last4}</span>}</td>
                    <td>{ACCOUNT_KIND_LABEL[a.kind]}</td>
                    <td>{a.institution ?? <span className="muted">Not set</span>}</td>
                    <td className="num">{a.transaction_count}{a.unreviewed_count > 0 && <span className="tag">{a.unreviewed_count} to review</span>}</td>
                    <td className="num">{a.kind === "credit_card" && a.balance < 0 ? `${money(-a.balance)} owed` : money(a.balance)}</td>
                    <td className="row-actions">{isAdmin && <button type="button" className="btn btn-small" onClick={() => setEditing(a)}>Edit</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <p className="hint">Balance is the opening balance plus every transaction that isn't excluded. Credit card balances show what you owe.</p>
    </div>
  );
}

function AccountForm({ account, onDone }: { account: Account | null; onDone: (saved: boolean) => void }) {
  const toast = useToast();
  const [f, setF] = useState<AccountInput>(account ? {
    name: account.name, kind: account.kind, institution: account.institution, last4: account.last4,
    opening_balance: account.opening_balance, opening_date: account.opening_date, is_active: account.is_active,
  } : blank);
  const [opening, setOpening] = useState(account
    ? String(account.kind === "credit_card" ? Math.abs(account.opening_balance) : account.opening_balance) : "0");
  const [owed, setOwed] = useState(account ? account.kind === "credit_card" && account.opening_balance < 0 : true);
  const [busy, setBusy] = useState(false);
  const card = f.kind === "credit_card";

  async function submit(e: FormEvent) {
    e.preventDefault();
    const value = Number(opening || 0);
    if (Number.isNaN(value)) { toast.error("Opening balance must be a number"); return; }
    const signed = card ? (owed ? -Math.abs(value) : Math.abs(value)) : value;
    const body = { ...f, name: f.name.trim(), opening_balance: Number(signed.toFixed(2)) };
    setBusy(true);
    try {
      if (account) await api.updateAccount(account.id, body);
      else await api.createAccount(body);
      toast.success(account ? "Account saved" : "Account added");
      onDone(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>{account ? `Edit ${account.name}` : "Add account"}</h2>
      <form className="form" onSubmit={submit}>
        <div className="grid-2">
          <label className="field"><span>Name</span>
            <input value={f.name} maxLength={120} required placeholder="e.g. Chase Business Checking" onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <label className="field"><span>Type</span>
            <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as AccountKind })}>
              {KINDS.map((k) => <option key={k} value={k}>{ACCOUNT_KIND_LABEL[k]}</option>)}
            </select></label>
          <label className="field"><span>Bank or card issuer</span>
            <input value={f.institution ?? ""} maxLength={120} onChange={(e) => setF({ ...f, institution: e.target.value || null })} /></label>
          <label className="field"><span>Last 4 digits</span>
            <input value={f.last4 ?? ""} maxLength={4} inputMode="numeric" pattern="[0-9]{4}" onChange={(e) => setF({ ...f, last4: e.target.value || null })} /></label>
          <label className="field"><span>{card ? "Opening balance owed" : "Opening balance"}</span>
            <div className="money-input"><span>{currencySymbol().trim()}</span><input inputMode="decimal" value={opening} onChange={(e) => setOpening(e.target.value)} /></div>
            {card && <label className="check small"><input type="checkbox" checked={owed} onChange={(e) => setOwed(e.target.checked)} /><span>This is money owed on the card</span></label>}</label>
          <label className="field"><span>Opening balance date</span>
            <input type="date" value={f.opening_date ?? ""} onChange={(e) => setF({ ...f, opening_date: e.target.value || null })} /></label>
        </div>
        {account && (
          <label className="check"><input type="checkbox" checked={!f.is_active} onChange={(e) => setF({ ...f, is_active: !e.target.checked })} />
            <span>Account is closed (hide it from Banking and imports)</span></label>
        )}
        <div className="form-actions">
          {account?.has_csv_profile && (
            <button type="button" className="link-button" onClick={async () => { await api.forgetCsvProfile(account.id); toast.success("Saved CSV columns cleared"); }}>
              Forget saved CSV columns
            </button>
          )}
          <span className="spacer" />
          <button type="button" className="btn" onClick={() => onDone(false)}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !f.name.trim()}>{busy ? "Saving…" : account ? "Save account" : "Add account"}</button>
        </div>
      </form>
    </section>
  );
}
