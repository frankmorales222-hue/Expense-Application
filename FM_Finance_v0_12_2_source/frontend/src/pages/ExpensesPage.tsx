import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import ExpenseTable from "../components/ExpenseTable";
import Filters from "../components/Filters";
import { useAuth, useToast } from "../context";
import type { Category, ExpenseFilters, ExpensePage, ExpenseStatus } from "../types";

const PAGE_SIZE = 25;
type SortKey = NonNullable<ExpenseFilters["sort"]>;

export default function ExpensesPage() {
  const { settings } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [categories, setCategories] = useState<Category[]>([]);
  const [data, setData] = useState<ExpensePage | null>(null);
  const [loading, setLoading] = useState(true);

  // Filters live in the URL so they survive refresh and can be bookmarked.
  const filters = useMemo<ExpenseFilters>(() => ({
    search: params.get("search") ?? "",
    status: (params.get("status") ?? "") as ExpenseStatus | "",
    category_id: params.get("category_id") ?? "",
    date_from: params.get("date_from") ?? "",
    date_to: params.get("date_to") ?? "",
    sort: (params.get("sort") as SortKey | null) ?? "date_desc",
  }), [params]);
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);

  const setFilters = useCallback((f: ExpenseFilters) => {
    const next = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v && !(k === "sort" && v === "date_desc")) next.set(k, String(v));
    setParams(next, { replace: true });
  }, [setParams]);

  useEffect(() => {
    api.categories(true).then((cs) => setCategories(cs.filter((c) => c.kind === "expense"))).catch((e: Error) => toast.error(e.message));
  }, [toast]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.listExpenses(filters, page, PAGE_SIZE)
      .then((d) => { if (alive) setData(d); })
      .catch((e: Error) => toast.error(e.message))
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [filters, page, toast]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const goPage = (p: number) => {
    const next = new URLSearchParams(params);
    if (p > 1) next.set("page", String(p)); else next.delete("page");
    setParams(next);
  };

  return (
    <div className="page">
      <header className="page-head">
        <h1>Expenses</h1>
        <div className="actions">
          <a className="btn" href={api.exportUrl(filters)}>Export CSV</a>
          <Link className="btn btn-primary" to="/expenses/new">Add expense</Link>
        </div>
      </header>

      <Filters value={filters} categories={categories} onChange={setFilters} />

      <div className="list-meta">
        <span className="muted">{data ? `${data.total} ${data.total === 1 ? "expense" : "expenses"}` : " "}</span>
        <label className="field inline">
          <span>Sort</span>
          <select value={filters.sort} onChange={(e) => setFilters({ ...filters, sort: e.target.value as SortKey })}>
            <option value="date_desc">Newest first</option>
            <option value="date_asc">Oldest first</option>
            <option value="amount_desc">Largest amount</option>
            <option value="amount_asc">Smallest amount</option>
          </select>
        </label>
      </div>

      <section className={loading ? "panel flush is-loading" : "panel flush"}>
        {data && data.items.length > 0 ? (
          <ExpenseTable
            items={data.items}
            currency={settings?.currency}
            footerTotal={{ label: data.total > data.items.length ? `Total of all ${data.total} matching` : "Total", amount: data.total_amount }}
          />
        ) : data ? (
          <div className="empty inner">
            <h2>No expenses match</h2>
            <p>Change the filters, or add a new expense.</p>
          </div>
        ) : null}
      </section>

      {pages > 1 && (
        <nav className="pager" aria-label="Pagination">
          <button type="button" className="btn" disabled={page <= 1} onClick={() => goPage(page - 1)}>Previous</button>
          <span>Page {page} of {pages}</span>
          <button type="button" className="btn" disabled={page >= pages} onClick={() => goPage(page + 1)}>Next</button>
        </nav>
      )}
    </div>
  );
}
