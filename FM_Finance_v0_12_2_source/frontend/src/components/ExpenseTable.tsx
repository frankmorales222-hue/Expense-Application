import { useNavigate } from "react-router-dom";
import { formatDate, money } from "../format";
import type { ExpenseListItem } from "../types";
import StatusBadge from "./StatusBadge";

export default function ExpenseTable({ items, footerTotal, currency = "USD" }: {
  items: ExpenseListItem[]; footerTotal?: { label: string; amount: number }; currency?: string;
}) {
  const navigate = useNavigate();
  return (
    <div className="table-wrap">
      <table className="ledger">
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Vendor</th>
            <th scope="col">Description</th>
            <th scope="col">Category</th>
            <th scope="col">Paid from</th>
            <th scope="col" className="num">Amount</th>
            <th scope="col">Status</th>
            <th scope="col"><span className="sr-only">Receipts</span></th>
          </tr>
        </thead>
        <tbody>
          {items.map((e) => (
            <tr
              key={e.id}
              tabIndex={0}
              onClick={() => navigate(`/expenses/${e.id}`)}
              onKeyDown={(ev) => { if (ev.key === "Enter") navigate(`/expenses/${e.id}`); }}
            >
              <td className="nowrap">{formatDate(e.expense_date)}</td>
              <td>{e.vendor_name ?? <span className="muted">—</span>}</td>
              <td className="desc">
                {e.description}
                {e.is_reimbursable && <span className="tag">Reimbursable</span>}
              </td>
              <td className="muted">{e.line_count > 1 ? `Split (${e.line_count} lines)` : e.category_name}</td>
              <td className="muted">{e.is_reimbursable ? "Paid personally" : e.payment_account_name ?? <span className="overdue-text">Not set</span>}</td>
              <td className="num">{money(e.amount, e.currency)}</td>
              <td><StatusBadge status={e.status} /></td>
              <td className="receipt-cell" title={e.receipt_count ? `${e.receipt_count} receipt(s)` : "No receipt"}>
                {e.receipt_count > 0 ? <PaperclipIcon /> : null}
              </td>
            </tr>
          ))}
        </tbody>
        {footerTotal && (
          <tfoot>
            <tr>
              <td colSpan={5}>{footerTotal.label}</td>
              <td className="num">{money(footerTotal.amount, currency)}</td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

function PaperclipIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-label="Has receipt">
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}
