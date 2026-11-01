import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type RefObject } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import AccountStrip from "../components/banking/AccountStrip";
import ConfidencePill from "../components/banking/ConfidencePill";
import TxnDetail from "../components/banking/TxnDetail";
import Icon from "../components/Icon";
import { useAuth, useToast } from "../context";
import { formatDate, money, today, currencySymbol } from "../format";
import type { Account, Category, Customer, Tab, Txn, TxnFilters, TxnFlag, TxnPage } from "../types";

const FLAGS: { value: TxnFlag | ""; label: string }[] = [
  { value: "", label: "Everything" },
  { value: "duplicate", label: "Possible duplicates" },
  { value: "transfer", label: "Transfers" },
  { value: "uncategorized", label: "Needs a category" },
  { value: "missing_receipt", label: "Missing receipt" },
  { value: "money_in", label: "Money in" },
  { value: "money_out", label: "Money out" },
];
const TABS: { key: Tab; label: string; count: keyof TxnPage["counts"] }[] = [
  { key: "review", label: "For review", count: "review" },
  { key: "approved", label: "Approved", count: "approved" },
  { key: "excluded", label: "Excluded", count: "excluded" },
];
const PAGE_SIZE = 50;

export default function BankingPage() {
  const toast = useToast();
  const { rules, user } = useAuth();
  // v0.10.0: each company sets how sure "Approve all" must be.
  const confident = rules?.rules.auto_approve_confidence ?? 90;
  const [params, setParams] = useSearchParams();
  const accountId = params.get("account") ?? "";
  const tab = (params.get("tab") as Tab) || "review";
  const [flag, setFlag] = useState<TxnFlag | "">("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<TxnPage | null>(null);
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const addDialog = useRef<HTMLDialogElement>(null);

  useEffect(() => { const t = window.setTimeout(() => setDebounced(search), 300); return () => window.clearTimeout(t); }, [search]);
  useEffect(() => { setPage(1); setSelected(new Set()); setExpanded(null); }, [accountId, tab, flag, debounced]);

  useEffect(() => {
    api.categories().then(setCategories).catch((e: Error) => toast.error(e.message));
    api.customers().then(setCustomers).catch(() => setCustomers([]));
  }, [toast]);

  const filters: TxnFilters = useMemo(() => ({ account_id: accountId || undefined, tab, flag, search: debounced }),
    [accountId, tab, flag, debounced]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [page_, accts] = await Promise.all([api.transactions(filters, page, PAGE_SIZE), api.accounts()]);
      setData(page_);
      setAccounts(accts);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not load transactions");
    } finally {
      setLoading(false);
    }
  }, [filters, page, toast]);
  useEffect(() => { void load(); }, [load]);

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  }

  function replaceRow(t: Txn) {
    setData((d) => d && { ...d, items: d.items.map((x) => (x.id === t.id ? t : x)) });
  }

  async function act(id: string, fn: () => Promise<unknown>, message?: string, reload = true) {
    setBusy(id);
    try {
      await fn();
      if (message) toast.success(message);
      if (reload) await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  async function changeCategory(t: Txn, categoryId: string) {
    setBusy(t.id);
    try {
      replaceRow(await api.updateTransaction(t.id, { category_id: categoryId || null }));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not change the category");
    } finally {
      setBusy(null);
    }
  }

  const items = data?.items ?? [];
  const reviewable = items.filter((t) => t.review_status === "unreviewed");
  const allSelected = reviewable.length > 0 && reviewable.every((t) => selected.has(t.id));
  const confidentCount = reviewable.filter((t) => t.confidence >= confident && !t.duplicate_of
    && (t.is_transfer || t.allocation_account_id || t.category_id || t.suggested_category_id)).length;
  const expenseCats = categories.filter((c) => c.kind === "expense");
  const incomeCats = categories.filter((c) => c.kind !== "expense");

  // v0.9.0 keyboard shortcuts on the review list: J/K or arrows move, A approves, E opens details, X excludes.
  const [focusIdx, setFocusIdx] = useState<number | null>(null);
  useEffect(() => { setFocusIdx(null); }, [accountId, tab, flag, debounced, page]);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(el.tagName))) return;
      if (document.querySelector("dialog[open]")) return;
      if (items.length === 0) return;
      const key = e.key.toLowerCase();
      const cur = focusIdx ?? -1;
      if (key === "j" || key === "arrowdown") { e.preventDefault(); setFocusIdx(Math.min(cur + 1, items.length - 1)); return; }
      if (key === "k" || key === "arrowup") { e.preventDefault(); setFocusIdx(Math.max(cur - 1, 0)); return; }
      const txn = focusIdx !== null ? items[focusIdx] : undefined;
      if (!txn) return;
      if (key === "e" || key === "enter") { e.preventDefault(); setExpanded(expanded === txn.id ? null : txn.id); return; }
      if (key === "escape") { setExpanded(null); return; }
      if (txn.review_status !== "unreviewed" || busy !== null) return;
      if (key === "a") {
        e.preventDefault();
        if (!txn.is_transfer && !txn.allocation_account_id && !txn.category_id && !txn.suggested_category_id && !txn.bill_id && !txn.customer_payment_id) {
          toast.error("Choose a category first (press E to open it)");
          return;
        }
        void act(txn.id, () => api.approveTransaction(txn.id), `Approved: ${txn.vendor_name ?? txn.suggested_vendor_name ?? txn.description}`);
      } else if (key === "x") {
        e.preventDefault();
        void act(txn.id, () => api.excludeTransaction(txn.id), "Excluded");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  useEffect(() => {
    if (focusIdx === null) return;
    document.querySelector(`[data-row="${focusIdx}"]`)?.scrollIntoView({ block: "nearest" });
  }, [focusIdx]);
  useEffect(() => {
    if (focusIdx !== null && focusIdx >= items.length) setFocusIdx(items.length ? items.length - 1 : null);
  }, [items.length, focusIdx]);

  function toggle(id: string) {
    setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }

  async function bulkApprove() {
    await act("bulk", async () => {
      const r = await api.bulkApprove([...selected]);
      toast.success(`Approved ${r.approved}${r.skipped ? `, ${r.skipped} need a category` : ""}`);
      setSelected(new Set());
    });
  }

  async function approveConfident() {
    await act("bulk", async () => {
      const r = await api.approveConfident(confident, accountId || undefined);
      toast.success(r.approved ? `Approved ${r.approved} high-confidence transaction${r.approved === 1 ? "" : "s"}` : "Nothing to approve");
    });
  }

  if (accounts && accounts.length === 0) {
    return (
      <div className="page">
        <header className="page-head"><h1>Banking</h1></header>
        <div className="empty">
          <h2>Add a bank account to get started</h2>
          <p>Add your business checking and credit card accounts, then import a CSV, OFX or QFX statement from your bank.</p>
          <Link className="btn btn-primary" to="/accounts">Add an account</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="page page-wide">
      <header className="page-head">
        <h1>Banking</h1>
        <div className="actions">
          {(user?.role === "admin" || user?.role === "approver") && <Link className="btn" to="/banking/rules">Bank rules</Link>}
          <button type="button" className="btn" onClick={() => addDialog.current?.showModal()}>Add transaction</button>
          <Link className="btn btn-primary" to={`/banking/import${accountId ? `?account=${accountId}` : ""}`}>Import statement</Link>
        </div>
      </header>

      {accounts && <AccountStrip accounts={accounts} selected={accountId} onSelect={(id) => setParam("account", id)} />}

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key}
            className={tab === t.key ? "tab active" : "tab"} onClick={() => setParam("tab", t.key === "review" ? "" : t.key)}>
            {t.label}<span className="tab-count">{data?.counts[t.count] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="toolbar">
        <label className="field grow"><span className="sr-only">Search</span>
          <input type="search" placeholder="Search description, vendor or memo" value={search} onChange={(e) => setSearch(e.target.value)} /></label>
        <label className="field"><span className="sr-only">Show</span>
          <select value={flag} onChange={(e) => setFlag(e.target.value as TxnFlag | "")}>
            {FLAGS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
          </select></label>
        {tab === "review" && (
          <div className="toolbar-actions">
            {selected.size > 0 && (
              <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={() => void bulkApprove()}>
                Approve {selected.size} selected
              </button>
            )}
            <button type="button" className="btn" disabled={busy !== null || confidentCount === 0} onClick={() => void approveConfident()}
              title={`Approves every transaction in review with ${confident}% confidence or more`}>
              Approve all {confident}%+
            </button>
          </div>
        )}
      </div>

      {tab === "review" && items.length > 0 && (
        <div className="keys" aria-label="Keyboard shortcuts">
          <span><kbd>J</kbd><kbd>K</kbd> move</span><span><kbd>A</kbd> approve</span><span><kbd>E</kbd> open details</span>
          <span><kbd>X</kbd> exclude</span><span><kbd>Esc</kbd> close</span>
        </div>
      )}

      <section className={loading ? "panel flush is-loading" : "panel flush"}>
        {items.length === 0 ? (
          <div className="empty inner">
            <p>{loading ? "Loading…" : tab === "review" ? "Nothing waiting for review. Import a statement to bring in new transactions." : "No transactions here."}</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="ledger bank-table">
              <thead>
                <tr>
                  {tab === "review" && (
                    <th className="check-col">
                      <input type="checkbox" aria-label="Select all" checked={allSelected}
                        onChange={() => setSelected(allSelected ? new Set() : new Set(reviewable.map((t) => t.id)))} />
                    </th>
                  )}
                  <th>Date</th>
                  <th>Description</th>
                  <th>Category</th>
                  <th className="center">Receipt</th>
                  <th className="num">Amount</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {items.map((t, idx) => {
                  const open = expanded === t.id;
                  const chosen = t.category_id ?? (t.review_status === "unreviewed" ? t.suggested_category_id : null) ?? "";
                  const isSuggestion = !t.category_id && !!t.suggested_category_id;
                  const cats = t.amount > 0 ? [...incomeCats, ...expenseCats] : [...expenseCats, ...incomeCats];
                  return (
                    <Fragment key={t.id}>
                      <tr data-row={idx} className={[open ? "open" : "", focusIdx === idx ? "kb-focus" : ""].join(" ").trim()}
                        onClick={() => { setFocusIdx(idx); setExpanded(open ? null : t.id); }}>
                        {tab === "review" && (
                          <td className="check-col" onClick={(e) => e.stopPropagation()}>
                            <input type="checkbox" aria-label="Select" checked={selected.has(t.id)} onChange={() => toggle(t.id)} />
                          </td>
                        )}
                        <td className="nowrap">{formatDate(t.txn_date)}</td>
                        <td className="desc-cell">
                          <div className="payee">{t.vendor_name ?? t.suggested_vendor_name ?? t.description}</div>
                          <div className="raw">
                            {!accountId && <span className="acct-chip">{t.account_name}</span>}
                            {t.description}
                          </div>
                          {(t.is_transfer || t.duplicate_of || t.customer_name || t.memo) && (
                            <div className="chips">
                              {t.is_transfer && t.transfer_peer && <span className="chip chip-transfer">Transfer {t.amount < 0 ? "to" : "from"} {t.transfer_peer.account_name}</span>}
                              {t.duplicate_of && <span className="chip chip-warn">Possible duplicate</span>}
                              {t.customer_name && <span className="chip">{t.customer_name}</span>}
                              {t.memo && <span className="chip chip-quiet" title={t.memo}>Memo</span>}
                            </div>
                          )}
                        </td>
                        <td className="cat-cell" onClick={(e) => e.stopPropagation()}>
                          {t.is_transfer ? (
                            <span className="muted">Transfer</span>
                          ) : t.allocation_account_name ? (
                            <span className="sugg match"><Icon name="wallet" size={14} />{t.allocation_account_name}</span>
                          ) : (
                            <>
                              <select className={isSuggestion ? "cat-select suggested" : "cat-select"} value={chosen}
                                disabled={busy === t.id || t.review_status !== "unreviewed"}
                                aria-label="Category" onChange={(e) => void changeCategory(t, e.target.value)}>
                                <option value="">Choose a category</option>
                                {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                              </select>
                              {isSuggestion && t.review_status === "unreviewed" && <ConfidencePill value={t.confidence} reason={t.suggestion_reason} />}
                            </>
                          )}
                          {t.is_transfer && t.review_status === "unreviewed" && <ConfidencePill value={t.confidence} reason={t.suggestion_reason} />}
                        </td>
                        <td className="center">
                          <ReceiptIcon status={t.receipt_status} />
                        </td>
                        <td className={t.amount > 0 ? "num amount-in" : "num"}>{t.amount > 0 ? "+" : ""}{money(t.amount)}</td>
                        <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                          {t.review_status === "unreviewed" && (
                            <button type="button" className="btn btn-small btn-primary" disabled={busy !== null || (!chosen && !t.is_transfer)}
                              onClick={() => void act(t.id, () => api.approveTransaction(t.id))}>
                              Approve
                            </button>
                          )}
                          {t.review_status !== "unreviewed" && (
                            <button type="button" className="btn btn-small" disabled={busy !== null}
                              onClick={() => void act(t.id, () => api.restoreTransaction(t.id), "Moved back to review")}>
                              {t.review_status === "approved" ? "Undo" : "Restore"}
                            </button>
                          )}
                        </td>
                      </tr>
                      {open && (
                        <tr className="detail-row">
                          <td colSpan={tab === "review" ? 7 : 6}>
                            <TxnDetail txn={t} customers={customers} onChanged={() => void load()} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {data && data.total > 0 && (
        <div className="list-meta">
          <span className="muted">
            {data.total} transaction{data.total === 1 ? "" : "s"}. In {money(data.total_in)}, out {money(data.total_out)}.
          </span>
          {data.total > PAGE_SIZE && (
            <div className="pager">
              <button type="button" className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span className="muted">Page {page} of {Math.ceil(data.total / PAGE_SIZE)}</span>
              <button type="button" className="btn" disabled={page * PAGE_SIZE >= data.total} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
        </div>
      )}

      <AddTransactionDialog dialogRef={addDialog} accounts={accounts ?? []} categories={categories}
        customers={customers} defaultAccount={accountId} onCreated={() => void load()} />
    </div>
  );
}

function ReceiptIcon({ status }: { status: Txn["receipt_status"] }) {
  if (status === "not_needed") return <span className="receipt-none" aria-label="Receipt not needed">–</span>;
  if (status === "attached") return <span className="receipt-ok" title="Receipt attached" aria-label="Receipt attached">✓</span>;
  return <span className="receipt-missing" title="No receipt yet" aria-label="No receipt">○</span>;
}

function AddTransactionDialog({ dialogRef, accounts, categories, customers, defaultAccount, onCreated }: {
  dialogRef: RefObject<HTMLDialogElement>; accounts: Account[]; categories: Category[]; customers: Customer[];
  defaultAccount: string; onCreated: () => void;
}) {
  const toast = useToast();
  const blank = () => ({ account_id: defaultAccount || accounts[0]?.id || "", txn_date: today(), description: "",
    amount: "", direction: "out" as "out" | "in", category_id: "", vendor_name: "", customer_id: "" });
  const [f, setF] = useState(blank);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setF((x) => ({ ...x, account_id: defaultAccount || x.account_id || accounts[0]?.id || "" })); }, [defaultAccount, accounts]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const amount = Number(f.amount);
    if (!(amount > 0)) { toast.error("Enter an amount greater than zero"); return; }
    setBusy(true);
    try {
      await api.createTransaction({
        account_id: f.account_id, txn_date: f.txn_date, description: f.description.trim(),
        amount: Number((f.direction === "out" ? -amount : amount).toFixed(2)), category_id: f.category_id || null,
        vendor_name: f.vendor_name.trim() || null, customer_id: f.customer_id || null, memo: null,
      });
      toast.success("Transaction added");
      setF(blank());
      dialogRef.current?.close();
      onCreated();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add the transaction");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog ref={dialogRef} className="dialog dialog-wide" aria-labelledby="add-txn-title">
      <form className="form" onSubmit={submit}>
        <h2 id="add-txn-title">Add transaction</h2>
        <p className="hint">For cash spending or anything your bank file won't include.</p>
        <div className="grid-2">
          <label className="field"><span>Account</span>
            <select value={f.account_id} onChange={(e) => setF({ ...f, account_id: e.target.value })} required>
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select></label>
          <label className="field"><span>Date</span>
            <input type="date" value={f.txn_date} onChange={(e) => setF({ ...f, txn_date: e.target.value })} required /></label>
        </div>
        <label className="field"><span>Description</span>
          <input value={f.description} maxLength={500} onChange={(e) => setF({ ...f, description: e.target.value })} required /></label>
        <div className="grid-2">
          <div className="field"><span>Direction</span>
            <div className="segmented">
              <button type="button" className={f.direction === "out" ? "active" : ""} onClick={() => setF({ ...f, direction: "out" })}>Money out</button>
              <button type="button" className={f.direction === "in" ? "active" : ""} onClick={() => setF({ ...f, direction: "in" })}>Money in</button>
            </div></div>
          <label className="field"><span>Amount</span>
            <div className="money-input"><span>{currencySymbol().trim()}</span>
              <input inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} required /></div></label>
        </div>
        <div className="grid-2">
          <label className="field"><span>Category</span>
            <select value={f.category_id} onChange={(e) => setF({ ...f, category_id: e.target.value })}>
              <option value="">Suggest one for me</option>
              {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select></label>
          {f.direction === "in" ? (
            <label className="field"><span>Customer</span>
              <select value={f.customer_id} onChange={(e) => setF({ ...f, customer_id: e.target.value })}>
                <option value="">No customer</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select></label>
          ) : (
            <label className="field"><span>Vendor</span>
              <input value={f.vendor_name} maxLength={255} onChange={(e) => setF({ ...f, vendor_name: e.target.value })} /></label>
          )}
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={() => dialogRef.current?.close()}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !f.account_id}>{busy ? "Adding…" : "Add transaction"}</button>
        </div>
      </form>
    </dialog>
  );
}
