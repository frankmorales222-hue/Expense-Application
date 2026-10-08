import { useEffect, useState } from "react";
import { STATUS_LABEL } from "../format";
import type { Category, ExpenseFilters, ExpenseStatus } from "../types";

const STATUSES = Object.keys(STATUS_LABEL) as ExpenseStatus[];

export default function Filters({ value, categories, onChange }: {
  value: ExpenseFilters; categories: Category[]; onChange: (f: ExpenseFilters) => void;
}) {
  const [search, setSearch] = useState(value.search ?? "");

  // Debounce typing in the search box.
  useEffect(() => {
    if (search === (value.search ?? "")) return;
    const t = window.setTimeout(() => onChange({ ...value, search }), 300);
    return () => window.clearTimeout(t);
  }, [search, value, onChange]);

  const hasFilters = Boolean(value.search || value.status || value.category_id || value.date_from || value.date_to);

  return (
    <div className="filters">
      <label className="field grow">
        <span>Search</span>
        <input type="search" placeholder="Vendor, description or notes" value={search} onChange={(e) => setSearch(e.target.value)} />
      </label>
      <label className="field">
        <span>Status</span>
        <select value={value.status ?? ""} onChange={(e) => onChange({ ...value, status: e.target.value as ExpenseStatus | "" })}>
          <option value="">Any status</option>
          {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
      </label>
      <label className="field">
        <span>Category</span>
        <select value={value.category_id ?? ""} onChange={(e) => onChange({ ...value, category_id: e.target.value })}>
          <option value="">Any category</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>
      <label className="field">
        <span>From</span>
        <input type="date" value={value.date_from ?? ""} onChange={(e) => onChange({ ...value, date_from: e.target.value })} />
      </label>
      <label className="field">
        <span>To</span>
        <input type="date" value={value.date_to ?? ""} onChange={(e) => onChange({ ...value, date_to: e.target.value })} />
      </label>
      {hasFilters && (
        <button type="button" className="link-button clear" onClick={() => { setSearch(""); onChange({ sort: value.sort }); }}>
          Clear filters
        </button>
      )}
    </div>
  );
}
