import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth, useToast } from "../context";
import { formatDate, money } from "../format";
import type { AccountType, LedgerAccount, LedgerAccountInput, Register } from "../types";

export const TYPE_LABEL: Record<AccountType, string> = {
  asset: "Asset", liability: "Liability", equity: "Equity", income: "Income", expense: "Expense",
};
export const DETAIL_LABEL: Record<string, string> = {
  bank: "Bank", accounts_receivable: "Accounts receivable (A/R)", other_current_asset: "Other current asset",
  fixed_asset: "Fixed asset", other_asset: "Other asset", credit_card: "Credit card",
  accounts_payable: "Accounts payable (A/P)", other_current_liability: "Other current liability",
  long_term_liability: "Long-term liability", equity: "Equity", income: "Income", other_income: "Other income",
  expense: "Expense", cost_of_goods_sold: "Cost of goods sold", other_expense: "Other expense",
};
// Types people can add here. Bank/card accounts come from Accounts, A/R and A/P are built in.
const ADDABLE: Record<AccountType, string[]> = {
  asset: ["other_current_asset", "fixed_asset", "other_asset"],
  liability: ["other_current_liability", "long_term_liability"],
  equity: ["equity"],
  income: ["income", "other_income"],
  expense: ["expense", "cost_of_goods_sold", "other_expense"],
};
const ORDER: AccountType[] = ["asset", "liability", "equity", "income", "expense"];
const SOURCE_LABEL: Record<string, string> = {
  expense: "Expense", reimbursement: "Reimbursement", transaction: "Bank", opening_balance: "Opening balance",
  bill: "Bill", bill_payment: "Bill payment", journal: "Journal", invoice: "Invoice", customer_payment: "Payment",
  owner_funds: "Owner funds",
};

export function sourceLink(source_type: string, source_id: string | null, entry_id: string): string | null {
  if (source_type === "journal") return `/journal/${entry_id}`;
  if (!source_id) return null;
  if (source_type === "expense" || source_type === "reimbursement") return `/expenses/${source_id}`;
  if (source_type === "bill") return `/bills/${source_id}`;
  if (source_type === "invoice") return `/invoices/${source_id}`;
  if (source_type === "transaction") return "/banking";
  if (source_type === "opening_balance") return "/accounts";
  if (source_type === "owner_funds") return "/owner-funds";
  return null;
}
export const sourceLabel = (s: string) => SOURCE_LABEL[s] ?? s;

export default function ChartOfAccountsPage() {
  const { id } = useParams();
  return id ? <RegisterView id={id} /> : <ChartList />;
}

function ChartList() {
  const { user } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const isOwner = user?.role === "admin";
  const [accounts, setAccounts] = useState<LedgerAccount[]>([]);
  const [showInactive, setShowInactive] = useState(false);
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<LedgerAccount | null>(null);

  const load = useCallback(() => {
    api.ledgerAccounts(showInactive).then(setAccounts).catch((e: Error) => toast.error(e.message));
  }, [showInactive, toast]);
  useEffect(load, [load]);

  const grouped = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = accounts.filter((a) => !q || a.name.toLowerCase().includes(q) || (a.code ?? "").toLowerCase().includes(q));
    return ORDER.map((t) => ({ type: t, rows: list.filter((a) => a.type === t) })).filter((g) => g.rows.length > 0);
  }, [accounts, search]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Chart of accounts</h1>
          <p className="muted">Every account in your books. Categories and bank accounts appear here automatically.</p>
        </div>
        {isOwner && <button type="button" className="btn btn-primary" onClick={() => { setEditing(null); setAdding(true); }}>New account</button>}
      </header>

      {(adding || editing) && (
        <AccountForm account={editing} onClose={() => { setAdding(false); setEditing(null); }}
          onSaved={() => { setAdding(false); setEditing(null); load(); }} />
      )}

      <div className="toolbar">
        <label className="field grow"><span className="sr-only">Search</span>
          <input type="search" placeholder="Search by name or number" value={search} onChange={(e) => setSearch(e.target.value)} /></label>
        <label className="switch"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          <span>Include inactive</span></label>
      </div>

      <section className="panel flush">
        <div className="table-wrap">
          <table className="ledger coa-table">
            <thead><tr><th>Number</th><th>Name</th><th>Detail type</th><th>Comes from</th>
              <th className="num">Balance</th><th><span className="sr-only">Actions</span></th></tr></thead>
            {grouped.map((g) => (
              <tbody key={g.type}>
                <tr className="group-row"><th colSpan={6}>{TYPE_LABEL[g.type]}</th></tr>
                {g.rows.map((a) => (
                  <tr key={a.id} className={a.is_active ? "" : "inactive"} onClick={() => navigate(`/chart-of-accounts/${a.id}`)}>
                    <td className="muted">{a.code ?? ""}</td>
                    <td><strong>{a.name}</strong>{a.system_key && <span className="tag">built in</span>}</td>
                    <td>{DETAIL_LABEL[a.detail_type] ?? a.detail_type}</td>
                    <td className="muted">{a.linked_to === "category" ? "Category" : a.linked_to === "bank" ? "Accounts page"
                      : a.linked_to === "system" ? "F&M Finance" : "Added here"}</td>
                    <td className="num">{money(a.balance)}</td>
                    <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                      <Link className="link-button" to={`/chart-of-accounts/${a.id}`}>View register</Link>
                      {isOwner && !a.system_key && (
                        <button type="button" className="link-button" onClick={() => { setAdding(false); setEditing(a); }}>Edit</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      </section>
      <p className="hint">Balances are as of today. Assets and expenses show their debit balance; liabilities, equity and income their credit balance.</p>
    </div>
  );
}

function AccountForm({ account, onClose, onSaved }: { account: LedgerAccount | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const linked = account !== null && account.linked_to !== "none";
  const [type, setType] = useState<AccountType>(account?.type ?? "expense");
  const [detail, setDetail] = useState(account?.detail_type ?? "expense");
  const [name, setName] = useState(account?.name ?? "");
  const [code, setCode] = useState(account?.code ?? "");
  const [description, setDescription] = useState(account?.description ?? "");
  const [active, setActive] = useState(account?.is_active ?? true);
  const [busy, setBusy] = useState(false);

  const fixedDetail = account !== null && (account.linked_to === "bank" || account.linked_to === "system");
  const detailOptions = fixedDetail || (account && !ADDABLE[type].includes(account.detail_type))
    ? [account!.detail_type] : ADDABLE[type];

  async function save(e: FormEvent) {
    e.preventDefault();
    const body: LedgerAccountInput = {
      code: code.trim() || null, name: name.trim(), type, detail_type: detail,
      description: description.trim() || null, is_active: active,
    };
    setBusy(true);
    try {
      if (account) await api.updateLedgerAccount(account.id, body);
      else await api.createLedgerAccount(body);
      toast.success(account ? "Account saved" : `Added ${body.name}`);
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>{account ? `Edit ${account.name}` : "New account"}</h2>
      {!account && (type === "income" || type === "expense") && (
        <p className="hint">Income and expense accounts also show up as categories, so you can pick them on expenses and in Banking.</p>
      )}
      {linked && <p className="hint">This account is linked to a {account?.linked_to === "bank" ? "bank or card account" : "category"}, so its type is fixed.</p>}
      <form className="form-grid" onSubmit={save}>
        <label className="field"><span>Account type</span>
          <select value={type} disabled={!!account} onChange={(e) => { const t = e.target.value as AccountType; setType(t); setDetail(ADDABLE[t][0] ?? ""); }}>
            {ORDER.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
          </select></label>
        <label className="field"><span>Detail type</span>
          <select value={detail} disabled={fixedDetail} onChange={(e) => setDetail(e.target.value)}>
            {detailOptions.map((d) => <option key={d} value={d}>{DETAIL_LABEL[d] ?? d}</option>)}
          </select></label>
        <label className="field"><span>Name</span>
          <input value={name} maxLength={150} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Computer equipment" /></label>
        <label className="field"><span>Number (optional)</span>
          <input value={code} maxLength={20} onChange={(e) => setCode(e.target.value)} placeholder="e.g. 1500" /></label>
        <label className="field span-2"><span>Description (optional)</span>
          <input value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} /></label>
        {account && (
          <label className="switch"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            <span>{active ? "Active" : "Inactive (hidden from lists)"}</span></label>
        )}
        <div className="form-actions span-2">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>{busy ? "Saving…" : "Save account"}</button>
        </div>
      </form>
    </section>
  );
}

function RegisterView({ id }: { id: string }) {
  const toast = useToast();
  const navigate = useNavigate();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [data, setData] = useState<Register | null>(null);

  useEffect(() => {
    api.register(id, from || undefined, to || undefined).then(setData).catch((e: Error) => toast.error(e.message));
  }, [id, from, to, toast]);

  if (!data) return <div className="page"><p className="muted">Loading…</p></div>;
  const a = data.account;
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="crumbs"><Link to="/chart-of-accounts">Chart of accounts</Link></p>
          <h1>{a.code ? `${a.code} · ` : ""}{a.name}</h1>
          <p className="muted">{TYPE_LABEL[a.type]} · {DETAIL_LABEL[a.detail_type] ?? a.detail_type}</p>
        </div>
        <div className="figure figure-lead"><span className="figure-label">{to ? `Balance at ${formatDate(to)}` : "Balance"}</span>
          <span className="figure-value">{money(a.balance)}</span></div>
      </header>

      <div className="toolbar">
        <label className="field"><span>From</span><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="field"><span>To</span><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        {(from || to) && <button type="button" className="link-button" onClick={() => { setFrom(""); setTo(""); }}>All dates</button>}
      </div>

      <section className="panel flush">
        {data.lines.length === 0 ? (
          <div className="empty inner"><p>Nothing has been recorded in this account{from || to ? " for these dates" : " yet"}.</p></div>
        ) : (
          <div className="table-wrap">
            <table className="ledger">
              <thead><tr><th>Date</th><th>Type</th><th>Description</th><th>Other account</th>
                <th className="num">Debit</th><th className="num">Credit</th><th className="num">Balance</th></tr></thead>
              <tbody>
                {from && (
                  <tr className="muted-row"><td colSpan={6}>Balance before {formatDate(from)}</td>
                    <td className="num">{money(data.opening_balance)}</td></tr>
                )}
                {data.lines.map((l, i) => {
                  const link = sourceLink(l.source_type, l.source_id, l.entry_id);
                  return (
                    <tr key={`${l.entry_id}-${i}`} className={link ? "" : "no-link"} onClick={() => link && navigate(link)}>
                      <td className="nowrap">{formatDate(l.entry_date)}</td>
                      <td><span className="tag tag-plain">{sourceLabel(l.source_type)}</span>{l.number && <span className="muted"> #{l.number}</span>}</td>
                      <td>{l.description || l.memo || <span className="muted">No description</span>}</td>
                      <td className="muted">{l.other_accounts}</td>
                      <td className="num">{l.debit ? money(l.debit) : ""}</td>
                      <td className="num">{l.credit ? money(l.credit) : ""}</td>
                      <td className="num"><strong>{money(l.balance)}</strong></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
