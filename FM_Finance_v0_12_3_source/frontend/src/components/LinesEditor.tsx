import { currencySymbol, money } from "../format";
import type { Category, Customer } from "../types";

/** One editable row of "category details" (QuickBooks-style split). Amount is kept as typed text. */
export interface LineDraft {
  key: number;
  category_id: string;
  description: string;
  amount: string;
  billable: boolean;
  customer_id: string;
}

let nextKey = 1;
export const blankLine = (category_id = ""): LineDraft =>
  ({ key: nextKey++, category_id, description: "", amount: "", billable: false, customer_id: "" });

export function lineTotal(lines: LineDraft[]): number {
  return Math.round(lines.reduce((s, l) => s + (Number(l.amount) || 0), 0) * 100) / 100;
}

/** Problems keyed "rowIndex.field", plus "_" for the whole table. */
export function validateLines(lines: LineDraft[]): Record<string, string> {
  const out: Record<string, string> = {};
  const used = lines.filter((l) => l.category_id || l.amount.trim() || l.description.trim());
  if (used.length === 0) out._ = "Add at least one line with a category and amount.";
  lines.forEach((l, i) => {
    if (!(l.category_id || l.amount.trim() || l.description.trim())) return;
    if (!l.category_id) out[`${i}.category`] = "Choose a category";
    if (!/^\d+(\.\d{1,2})?$/.test(l.amount.trim()) || Number(l.amount) <= 0) out[`${i}.amount`] = "Enter an amount";
    if (l.billable && !l.customer_id) out[`${i}.customer`] = "Choose the customer";
  });
  return out;
}

export function linesForApi(lines: LineDraft[]) {
  return lines
    .filter((l) => l.category_id || l.amount.trim() || l.description.trim())
    .map((l) => ({
      category_id: l.category_id, description: l.description.trim() || null, amount: Number(Number(l.amount).toFixed(2)),
      billable: l.billable, customer_id: l.customer_id || null,
    }));
}

interface Props {
  lines: LineDraft[];
  categories: Category[];
  customers: Customer[];
  errors: Record<string, string>;
  disabled?: boolean;
  highlight?: boolean;
  onChange: (lines: LineDraft[]) => void;
}

export default function LinesEditor({ lines, categories, customers, errors, disabled, highlight, onChange }: Props) {
  const update = (i: number, patch: Partial<LineDraft>) =>
    onChange(lines.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  const remove = (i: number) => onChange(lines.length > 1 ? lines.filter((_, idx) => idx !== i) : [blankLine()]);
  const anyBillable = lines.some((l) => l.billable);
  // Expense categories first; income/owner categories stay available for refunds and owner draws.
  const options = (current: string) => [
    ...categories.filter((c) => (c.is_active || c.id === current) && c.kind === "expense"),
    ...categories.filter((c) => (c.is_active || c.id === current) && c.kind !== "expense"),
  ];

  return (
    <div className={highlight ? "lines lines-filled" : "lines"}>
      <table className="lines-table">
        <thead>
          <tr>
            <th className="ln-num">#</th>
            <th className="ln-cat">Category</th>
            <th>Description</th>
            <th className="num">Amount</th>
            <th className="center ln-bill" title="Charge this to a customer later">Billable</th>
            {anyBillable && <th className="ln-cust">Customer</th>}
            <th><span className="sr-only">Remove</span></th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={l.key}>
              <td className="ln-num muted">{i + 1}</td>
              <td className={errors[`${i}.category`] ? "has-error" : ""}>
                <select value={l.category_id} disabled={disabled} aria-label={`Line ${i + 1} category`}
                  onChange={(e) => update(i, { category_id: e.target.value })}>
                  <option value="">Choose a category</option>
                  {options(l.category_id).map((c) => (
                    <option key={c.id} value={c.id}>{c.name}{c.kind !== "expense" ? ` (${c.kind})` : ""}</option>
                  ))}
                </select>
              </td>
              <td>
                <input value={l.description} maxLength={500} disabled={disabled} aria-label={`Line ${i + 1} description`}
                  placeholder="What it was for" onChange={(e) => update(i, { description: e.target.value })} />
              </td>
              <td className={errors[`${i}.amount`] ? "num has-error" : "num"}>
                <div className="money-input small-money"><span aria-hidden="true">{currencySymbol().trim()}</span>
                  <input inputMode="decimal" value={l.amount} disabled={disabled} aria-label={`Line ${i + 1} amount`}
                    placeholder="0.00"
                    onChange={(e) => update(i, { amount: e.target.value.replace(/[^0-9.]/g, "") })}
                    onBlur={() => { const n = Number(l.amount); if (l.amount && n > 0) update(i, { amount: n.toFixed(2) }); }} />
                </div>
              </td>
              <td className="center">
                <input type="checkbox" checked={l.billable} disabled={disabled} aria-label={`Line ${i + 1} billable`}
                  onChange={(e) => update(i, { billable: e.target.checked, customer_id: e.target.checked ? l.customer_id : "" })} />
              </td>
              {anyBillable && (
                <td className={errors[`${i}.customer`] ? "has-error" : ""}>
                  {l.billable && (
                    <select value={l.customer_id} disabled={disabled} aria-label={`Line ${i + 1} customer`}
                      onChange={(e) => update(i, { customer_id: e.target.value })}>
                      <option value="">Choose customer</option>
                      {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                  )}
                </td>
              )}
              <td className="row-actions">
                {!disabled && (
                  <button type="button" className="icon-btn" aria-label={`Remove line ${i + 1}`} onClick={() => remove(i)}>×</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={2}>
              {!disabled && <button type="button" className="link-button" onClick={() => onChange([...lines, blankLine()])}>Add line</button>}
            </td>
            <td className="num muted">Total</td>
            <td className="num lines-total">{money(lineTotal(lines))}</td>
            <td colSpan={anyBillable ? 3 : 2} />
          </tr>
        </tfoot>
      </table>
      {errors._ && <p className="field-error">{errors._}</p>}
      {Object.keys(errors).some((k) => k !== "_") && <p className="field-error">Check the highlighted lines.</p>}
      {anyBillable && customers.length === 0 && (
        <p className="hint">Add customers in Settings to mark lines billable.</p>
      )}
    </div>
  );
}
